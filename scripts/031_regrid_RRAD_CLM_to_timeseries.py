from zipfile import ZipFile
import re
import os
from datetime import datetime
from satpy.scene import Scene
from satpy import find_files_and_readers
from pyresample import create_area_def
import xarray as xr
import numpy as np
import shutil
import gc
from params import raw_data_dir_rrad_nr, raw_data_dir_clm, \
    base_dir, processed_data_dir_rrad_nr, processed_data_dir_clm
import time
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import eccodes as ec
import dask.array as da

import warnings
from pyproj.exceptions import ProjError
warnings.filterwarnings(
    "ignore",
    message="You will likely lose important projection information",
    category=UserWarning,
    module="pyproj",
)

# -----------------------------
# PATH SETUP
# -----------------------------
RAW_DIR_RRAD = raw_data_dir_rrad_nr # raw_data_dir_rrad_hr #
RAW_DIR_CLM = raw_data_dir_clm
BASE_DIR = base_dir

# -----------------------------
# TIME WINDOW
# -----------------------------
YYYY0, MM0, DD0, HH0, MN0 = 2025, 2, 1, 0, 0
YYYY1, MM1, DD1, HH1, MN1 = 2025, 2, 1, 1, 0
t0 = datetime(YYYY0, MM0, DD0, HH0, MN0)
t1 = datetime(YYYY1, MM1, DD1, HH1, MN1)

# -----------------------------
# AREA OF INTEREST
# -----------------------------
lon_min, lon_max = 10.0, 35.0
lat_min, lat_max = -45.0, -30.0 # 30.0, 45.0

area_def = create_area_def(
    area_id="geo_area",
    projection={"proj": "latlong", "datum": "WGS84"},
    resolution=(0.02, 0.02),
    area_extent=(lon_min, lat_min, lon_max, lat_max),
)

# -----------------------------
# AREA-DERIVED OUTPUT DIRS
# -----------------------------
def fmt_lon(v):
    return f"{abs(v):.0f}{'E' if v >= 0 else 'W'}"

def fmt_lat(v):
    return f"{abs(v):.0f}{'N' if v >= 0 else 'S'}"

area_label = f"{fmt_lon(lon_min)}-{fmt_lon(lon_max)}_{fmt_lat(lat_min)}-{fmt_lat(lat_max)}"

DIR_OUT_RRAD = os.path.join(processed_data_dir_rrad_nr, area_label)
DIR_OUT_CLM  = os.path.join(processed_data_dir_clm,     area_label)

# -----------------------------
# CLM DECODE
# Satpy's fci_l2_grib reader calls eccodes' codes_get_values() internally.
# FCI CLM .bin files use grid_second_order packing (ECMWF local template 50002),
# which the eccodes Python bindings cannot reconstruct: codes_get_values() returns
# raw spatial-differencing residuals instead of the final 0–3 integers.
# The true 2-bit CLM flag is always recoverable from the bottom 2 bits of each
# residual:  clm = raw % 4  (verified: yields exactly {0,1,2,3}).
# We decode the .bin directly, then patch the value array back into the Satpy
# scene so that all geolocation / projection metadata is preserved for resampling.
# -----------------------------
def decode_clm_bin(bin_path: str) -> np.ndarray:
    """
    Read a FCI CLM .bin (GRIB2, grid_second_order) and return a 2D float32
    array shaped (ny, nx) with values in {0,1,2,3} and NaN for missing pixels.
    """
    with open(bin_path, "rb") as fh:
        gid = ec.codes_grib_new_from_file(fh)
        if gid is None:
            raise RuntimeError(f"No GRIB message found in {bin_path}")
        nx   = ec.codes_get(gid, "Nx")
        ny   = ec.codes_get(gid, "Ny")
        miss = ec.codes_get(gid, "missingValue")
        vals = ec.codes_get_values(gid)   # raw second-order residuals
        ec.codes_release(gid)

    missing_mask = (vals == miss)
    # Extract true CLM flag from the bottom 2 bits of the integer residuals.
    # np.mod handles negatives correctly: e.g. np.mod(-5, 4) == 3.
    clm = np.mod(vals.astype(np.int32), 4).astype(np.float32)
    clm[missing_mask] = np.nan
    arr = clm.reshape(ny, nx)
    clm.reshape(ny, nx)
    return np.flipud(arr)


# -----------------------------
# UTILITY FUNCTIONS
# -----------------------------
def unzip_file(zip_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)


def restructure_ds(ds, sensing_time, ir_channels):
    """
    Convert satpy output (dims: y, x, time) to CF-style (dims: time, lat, lon).
    """
    # Extract coordinates
    lat_vals = ds["latitude"].values[:, 0]   # shape (y,)
    lon_vals = ds["longitude"].values[0, :]  # shape (x,)
    time_val = np.datetime64(sensing_time.replace(second=0, microsecond=0), "ns")

    # Skip data variables we don't want to keep.
    skip = {"geo_area", "latitude", "longitude"}
    data_vars = [v for v in ds.data_vars if v not in skip]

    # Flip lat to S→N so it matches the land mask orientation
    if lat_vals[0] > lat_vals[-1]:
        lat_vals = lat_vals[::-1]
        flip = True
    else:
        flip = False

    # Re-assemble each variable with (time, lat, lon) layout.
    new_vars = {}
    for var in data_vars:
        arr = ds[var].values.astype(np.float32)
        if flip:
            arr = arr[::-1, :]
        arr[LAND_MASK] = np.nan
        arr = arr[np.newaxis, ...]   # Insert a leading time axis → (1, y, x)
        new_vars[var] = xr.DataArray(arr, dims=["time", "lat", "lon"],
                                     attrs=ds[var].attrs)

    # Build the new dataset with clean 1-D coordinates.
    new_ds = xr.Dataset(
        new_vars,
        coords={
            "time": (["time"], [time_val]),
            "lat":  (["lat"],  lat_vals),
            "lon":  (["lon"],  lon_vals),
        },
    )
    new_ds["time"].attrs.update(standard_name="time", long_name="time")
    new_ds["lat"].attrs.update(standard_name="latitude",  long_name="latitude",  units="degrees_north")
    new_ds["lon"].attrs.update(standard_name="longitude", long_name="longitude", units="degrees_east")

    # Carry over global attributes: commented out for now because causes error and unnecessary
    # new_ds.attrs = ds.attrs
    return new_ds

def compute_loggrad(da, channel_name, eps=1e-12):
    """
    Compute log10 of the horizontal gradient magnitude of a 2D field.
    """
    Rt = 6378e3
    Rlat = xr.DataArray(
        Rt * np.cos(np.deg2rad(da["lat"])),
        dims="lat",
        coords={"lat": da["lat"].values},
    )
    dTdx = da.differentiate("lon") * 180 / (np.pi * Rlat)
    dTdy = da.differentiate("lat") * 180 / (np.pi * Rt)
    gradT = np.sqrt(dTdx**2 + dTdy**2)
    log_grad = np.log10(gradT + eps).astype(np.float32)
    log_grad.attrs.update(
        long_name=f"Log10 horizontal gradient magnitude of "
                  f"{channel_name} brightness temperature",
        units="log10(K/m)",
        source_channel=channel_name,
        source_calibration="brightness_temperature",
        gradient_method="central differences via xarray.differentiate, "
                        "spherical metric correction",
        eps=str(eps),
    )
    return log_grad


# -----------------------------
# PER FILE PROCESSOR
# -----------------------------
def process_zip(zip_file):
    """Process a single zip file: unzip, load, crop, resample, save NetCDF."""
    try:
        # Create a unique temp folder per worker
        temp_dir = tempfile.mkdtemp(prefix="unzip_")

        RAW_DIR = RAW_DIR_RRAD if 'RRAD' in zip_file else RAW_DIR_CLM
        full_zip_path = os.path.join(RAW_DIR, zip_file)

        match = re.search(r"OPE_(\d{14})_", zip_file)
        sensing_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")

        unzip_file(full_zip_path, temp_dir)

        # ── RRAD (unchanged) ──────────────────────────────────────────────
        if "1C-RRAD-FDHSI" in zip_file:  # Normal resolution, all 16 channels available
            outfile         = os.path.join(DIR_OUT_RRAD, 
                                           f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD-FDHSI.nc")
            files           = find_files_and_readers(base_dir=temp_dir,
                                                      reader='fci_l1c_nc')
            scn             = Scene(filenames=files)
            ir_channels     = ['ir_105']#,'ir_123','ir_133','ir_38','wv_63','wv_73','ir_87','ir_97']
            # ref_channels  = ['nir_13','nir_16']#,'nir_22','vis_04','vis_05','vis_06','vis_08','vis_09']
            scn.load(ir_channels, calibration='brightness_temperature', 
                     upper_right_corner='NE')
            # scn.load(ref_channels, calibration='reflectance', upper_right_corner='NE')
        
        elif "1C-RRAD-HRFI" in zip_file:  # High resolution only 4 channels available
            outfile         = os.path.join(DIR_OUT_RRAD, 
                                           f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD-HRFI.nc")
            files           = find_files_and_readers(base_dir=temp_dir, 
                                                     reader='fci_l1c_nc')
            scn             = Scene(filenames=files)
            ir_channels     = ['ir_105'] # , 'ir_38']
            # ref_channels  = ['nir_22','vis_06']
            scn.load(ir_channels, calibration='brightness_temperature', 
                     upper_right_corner='NE')
            # scn.load(ref_channels, calibration='reflectance', upper_right_corner='NE')
        
        # ── CLM (fixed decoder) ───────────────────────────────────────────
        elif "CLM" in zip_file:
            outfile     = os.path.join(DIR_OUT_CLM,
                                       f"{sensing_time:%Y%m%d%H%M}_FCI-2-CLM.nc")
            bin_files = [f for f in os.listdir(temp_dir) if f.endswith(".bin")]
            if not bin_files:
                raise FileNotFoundError(
                    f"No .bin file found in {temp_dir} after unzipping {zip_file}"
                )
            bin_path = os.path.join(temp_dir, bin_files[0])
            arr_native = decode_clm_bin(bin_path)

            # Load Satpy scene for geolocation metadata only, then patch data
            filenames = [f for f in os.listdir(temp_dir) if 'CLM' in f]
            files     = [os.path.join(temp_dir, f) for f in filenames]
            scn       = Scene(filenames=files, reader='fci_l2_grib')
            scn.load(['cloud_mask'], upper_right_corner='NE')
            original = scn['cloud_mask']
            scn['cloud_mask'].data = da.from_array(
                arr_native.reshape(original.shape),
                chunks=original.data.chunks,
            )
            ir_channels = None
            

        # ── Crop → resample → restructure → save ─────────────────────────
        scn             = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
        resampler       = 'nearest' if 'CLM' in zip_file else 'bilinear'
        scn_resampled   = scn.resample(area_def, resampler=resampler)
        ds              = scn_resampled.to_xarray().compute()
        ds              = restructure_ds(ds, sensing_time, 
                                         ir_channels=ir_channels if "1C-RRAD" in zip_file else None)
        ds.to_netcdf(outfile)

        # ── Cleanup ───────────────────────────────────────────────────────
        del scn, ds, scn_resampled
        gc.collect()
        shutil.rmtree(temp_dir)

    except Exception as e:
        import traceback
        print(f"Error processing {zip_file}:\n{traceback.format_exc()}")

# -----------------------------
# MAIN PROCESS EXECUTION
# -----------------------------
LAND_MASK = None

def _worker_init(mask):
    global LAND_MASK
    LAND_MASK = mask


if __name__ == "__main__":

    num_cores = os.cpu_count()
    max_workers = 60
    # print(f"Detected {num_cores} CPU cores, using {max_workers} workers")

    for d in [DIR_OUT_RRAD, DIR_OUT_CLM]:
        os.makedirs(d, exist_ok=True)

    def in_window(filename):
        match = re.search(r"OPE_(\d{14})_", filename)
        if not match:
            return False
        return t0 <= datetime.strptime(match.group(1), "%Y%m%d%H%M%S") < t1
    
    zip_files_rrad = [f for f in os.listdir(RAW_DIR_RRAD) 
                      if f.endswith(".zip") and in_window(f)]
    zip_files_clm  = [f for f in os.listdir(RAW_DIR_CLM)  
                      if f.endswith(".zip") and in_window(f)]
    zip_files =  zip_files_clm + zip_files_rrad
    
    MASK_PATH = os.path.join(BASE_DIR,
                              f"land_mask_{area_label}_0p02deg.nc")
    if not os.path.exists(MASK_PATH):
        raise FileNotFoundError(
            f"Land mask not found: {MASK_PATH}\n"
            f"Run build_land_mask.py first."
        )
    LAND_MASK = xr.open_dataset(MASK_PATH)["land_mask"].values.astype(bool)
    print(f"Land mask loaded: {LAND_MASK.sum()} land pixels "
          f"of {LAND_MASK.size} total")

    start_time_perf = time.perf_counter()

    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_worker_init,
        initargs=(LAND_MASK,)
    ) as executor:
        futures = [executor.submit(process_zip, zf) for zf in zip_files]
        for future in tqdm(as_completed(futures), total=len(zip_files),
                            desc="Processing zips"):
            future.result()
    
    # ── CONCATENATION ────────────────────────────────────────────────────
    for product, out_dir in [("FCI-1C-RRAD", DIR_OUT_RRAD),
                             ("FCI-2-CLM", DIR_OUT_CLM)]:
        files = sorted(
            f for f in os.listdir(out_dir) 
            if f.endswith(".nc") and not re.match(r"\d{12}-\d{12}_", f)
        )
        if not files:
            continue

        timestamps = [f[:12] for f in files]  # "YYYYMMDDHHMM" for output
        t_start = timestamps[0]
        t_end   = timestamps[-1]
        outfile = os.path.join(out_dir, 
                               f"{t_start}-{t_end}_{product}_0p02deg.nc")

        print(f"Concatenating {len(files)} files → {outfile}")

        # open_mfdataset reads lazily — only writes to disk at to_netcdf time
        with xr.open_mfdataset(
            [os.path.join(out_dir, f) for f in files],
            concat_dim="time",
            combine="nested",
            parallel=True,
        ) as ds:
            t_ref = str(ds.time.values[0].astype("datetime64[D]"))  # e.g. "2025-01-26"
            ds.to_netcdf(outfile, 
                         encoding={"time": {"units": f"minutes since {t_ref}"}})

        # Remove the individual per-timestep files
        for f in files:
            os.remove(os.path.join(out_dir, f))

        print(f"Saved {outfile}")

    # ─────────────────────────────────────────────────────────────────────

    elapsed_minutes = (time.perf_counter() - start_time_perf)/60
    print(f"Processing completed in {elapsed_minutes:.2f} minutes")
