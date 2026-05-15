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

# -----------------------------
# PATH SETUP
# -----------------------------
RAW_DIR_RRAD = raw_data_dir_rrad_nr
RAW_DIR_CLM = raw_data_dir_clm
BASE_DIR = base_dir
# DIR_OUT_RRAD = processed_data_dir_rrad_nr
# DIR_OUT_CLM = processed_data_dir_clm

# -----------------------------
# TIME WINDOW
# -----------------------------
t0 = datetime.strptime("20250126000000", "%Y%m%d%H%M%S")
t1 = datetime.strptime("20250126010000", "%Y%m%d%H%M%S")

# -----------------------------
# AREA OF INTEREST
# -----------------------------
lon_min, lon_max = 10.0, 35.0
lat_min, lat_max = -45.0, -30.0

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
# e.g. "10E-21E_45S-30S"

DIR_OUT_RRAD = os.path.join(processed_data_dir_rrad_nr, area_label)
DIR_OUT_CLM  = os.path.join(processed_data_dir_clm,     area_label)

# -----------------------------
# UTILITY FUNCTIONS
# -----------------------------
def unzip_file(zip_path, out_dir):
    """Unzip a single zip file."""
    os.makedirs(out_dir, exist_ok=True)
    with ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)

def restructure_ds(ds, sensing_time):
    """
    Convert satpy output (dims: y, x, time) to CF-style (dims: time, lat, lon).

    After resampling to a latlong AreaDefinition the y-axis maps 1-to-1 to
    latitude and the x-axis to longitude, so we can safely promote those 1-D
    coordinate arrays to dimension coordinates and rename accordingly.
    """
    # 1. Extract the 1-D lat/lon values from the 2-D auxiliary coordinates.
    #    After latlong resampling each row has the same lon and each column
    #    the same lat, so taking the first row / first column is exact.
    lat_vals = ds["latitude"].values[:, 0]   # shape (y,)
    lon_vals = ds["longitude"].values[0, :]  # shape (x,)

    # 2. Build the scalar time value (already set as a length-1 coord).
    time_val = np.datetime64(sensing_time.replace(second=0, microsecond=0), "ns")

    # 3. Identify the data variables we actually want to keep.
    skip = {"geo_area", "latitude", "longitude"}
    data_vars = [v for v in ds.data_vars if v not in skip]

    # 4. Re-assemble each variable with (time, lat, lon) layout.
    new_vars = {}
    for var in data_vars:
        arr = ds[var].values  # (y, x)  — time dim was squeezed by satpy/xr
        # Insert a leading time axis → (1, y, x)
        arr = arr[np.newaxis, ...]
        new_vars[var] = xr.DataArray(
            arr,
            dims=["time", "lat", "lon"],
            attrs=ds[var].attrs,
        )

    # 5. Build the new dataset with clean 1-D coordinates.
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

    # Carry over global attributes
    new_ds.attrs = ds.attrs
    return new_ds

def process_zip(zip_file):
    """Process a single zip file: unzip, load, crop, resample, save NetCDF."""
    try:
        # 1. Create a unique temp folder per worker
        temp_dir = tempfile.mkdtemp(prefix="unzip_")

        # 2. Scan all raw files and select only valid ones
        RAW_DIR = RAW_DIR_RRAD if 'RRAD' in zip_file else RAW_DIR_CLM
        full_zip_path = os.path.join(RAW_DIR, zip_file)

        match = re.search(r"OPE_(\d{14})_", zip_file)
        if not match:
            print(f"Skipping {zip_file}: timestamp not found")
            return

        sensing_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        if not (t0 <= sensing_time < t1):
            return

        # 3. Unzip, load, crop, resample
        unzip_file(full_zip_path, temp_dir)

        if "1C-RRAD" in zip_file:
            files = find_files_and_readers(base_dir=temp_dir, reader='fci_l1c_nc')
            scn = Scene(filenames=files)
            ir_channels = ['ir_105','ir_123']#,'ir_133','ir_38','wv_63','wv_73','ir_87','ir_97']
            ref_channels = ['nir_13','nir_16']#,'nir_22','vis_04','vis_05','vis_06','vis_08','vis_09']
            outfile = os.path.join(DIR_OUT_RRAD, f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD.nc")
            scn.load(ir_channels, calibration='brightness_temperature', upper_right_corner='NE')
            scn.load(ref_channels, calibration='reflectance', upper_right_corner='NE')
        elif "CLM" in zip_file:
            filenames = [f for f in os.listdir(temp_dir) if 'CLM' in f]
            files = [os.path.join(temp_dir, f) for f in filenames]
            scn = Scene(filenames=files, reader='fci_l2_grib')
            channels = ['cloud_mask']
            outfile = os.path.join(DIR_OUT_CLM, f"{sensing_time:%Y%m%d%H%M}_FCI-2-CLM.nc")
            scn.load(channels, upper_right_corner='NE')

        # scn.load(channels, upper_right_corner='NE')
        scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
        scn_resampled = scn.resample(area_def)

        ds = scn_resampled.to_xarray().compute()
        
        # 4. restructure to (time, lat, lon) dimensions
        ds = restructure_ds(ds, sensing_time)
        if '1C-RRAD' in zip_file: 
            print(ds['ir_105'].attrs)  # should show calibration='BT' and units='K'
            print(ds['nir_13'].attrs)  # should showcaliration='reflectance' and units='%' or 'percent'
        else:
            print(ds['cloud_mask'].attrs)

        ds.to_netcdf(outfile)

        # Cleanup
        del scn, ds, scn_resampled
        gc.collect()
        shutil.rmtree(temp_dir)

        print(f"Saved {outfile}")

    except Exception as e:
        print(f"Error processing {zip_file}: {e}")

# -----------------------------
# MAIN PROCESS EXECUTION
# -----------------------------
if __name__ == "__main__":
    # Detect available cores
    num_cores = os.cpu_count()
    max_workers = 60
    print(f"Detected {num_cores} CPU cores, using {max_workers} workers")

    # Create output directories
    for d in [DIR_OUT_RRAD, DIR_OUT_CLM]:
        os.makedirs(d, exist_ok=True)

    # List zip files
    zip_files_rrad = [f for f in os.listdir(RAW_DIR_RRAD) if f.endswith(".zip")]
    zip_files_clm  = [f for f in os.listdir(RAW_DIR_CLM)  if f.endswith(".zip")]
    zip_files = zip_files_rrad + zip_files_clm

    # Parallel processing
    start_time_perf = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_zip, zf) for zf in zip_files]
        for future in as_completed(futures):
            # Raise exceptions if any
            future.result()

    # ── CONCATENATION ────────────────────────────────────────────────────

    for product, out_dir in [("FCI-1C-RRAD", DIR_OUT_RRAD), ("FCI-2-CLM", DIR_OUT_CLM)]:
        files = sorted(f for f in os.listdir(out_dir) if f.endswith(".nc"))
        if not files:
            continue

        # Extract timestamps from filenames for the output name
        timestamps = [f[:12] for f in files]  # "YYYYMMDDHHMM"
        t_start = timestamps[0]
        t_end   = timestamps[-1]
        outfile = os.path.join(out_dir, f"{t_start}-{t_end}_{product}.nc")

        print(f"Concatenating {len(files)} files → {outfile}")

        # open_mfdataset reads lazily — only writes to disk at to_netcdf time
        with xr.open_mfdataset(
            [os.path.join(out_dir, f) for f in files],
            concat_dim="time",
            combine="nested",
            parallel=True,
        ) as ds:
            # ds.to_netcdf(outfile)
            t_ref = str(ds.time.values[0].astype("datetime64[D]"))  # e.g. "2025-01-26"
            ds.to_netcdf(outfile, encoding={"time": {"units": f"minutes since {t_ref}"}})

        # # Remove the individual per-timestep files
        # for f in files:
        #     os.remove(os.path.join(out_dir, f))

        print(f"Saved {outfile}")

    # ─────────────────────────────────────────────────────────────────────

    end_time_perf = time.perf_counter()
    elapsed_minutes = (end_time_perf - start_time_perf)/60
    print(f"Processing completed in {elapsed_minutes:.2f} minutes")
