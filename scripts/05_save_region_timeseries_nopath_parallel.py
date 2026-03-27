from zipfile import ZipFile
import re
import os
from datetime import datetime
from satpy.scene import Scene
from satpy import find_files_and_readers
from pyresample import create_area_def
import xarray as xr
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
DIR_OUT_RRAD = processed_data_dir_rrad_nr
DIR_OUT_CLM = processed_data_dir_clm



for d in [DIR_OUT_RRAD, DIR_OUT_CLM]:
    os.makedirs(d, exist_ok=True)

# -----------------------------
# TIME WINDOW
# -----------------------------
t0 = datetime.strptime("20250126000000", "%Y%m%d%H%M%S")
t1 = datetime.strptime("20250127000000", "%Y%m%d%H%M%S")

# -----------------------------
# AREA OF INTEREST
# -----------------------------
lon_min, lon_max = 10.0, 21.0
lat_min, lat_max = -45.0, -30.0

area_def = create_area_def(
    area_id="geo_area",
    projection={"proj": "latlong", "datum": "WGS84"},
    resolution=(0.02, 0.02),
    area_extent=(lon_min, lat_min, lon_max, lat_max),
)

# -----------------------------
# UTILITY FUNCTIONS
# -----------------------------
def unzip_file(zip_path, out_dir):
    """Unzip a single zip file."""
    os.makedirs(out_dir, exist_ok=True)
    with ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)

def process_zip(zip_file):
    """Process a single zip file: unzip, load, crop, resample, save NetCDF."""
    try:
        # Create a unique temp folder per worker
        temp_dir = tempfile.mkdtemp(prefix="unzip_")

        RAW_DIR = RAW_DIR_RRAD if 'RRAD' in zip_file else RAW_DIR_CLM
        full_zip_path = os.path.join(RAW_DIR, zip_file)

        match = re.search(r"OPE_(\d{14})_", zip_file)
        if not match:
            print(f"Skipping {zip_file}: timestamp not found")
            return

        sensing_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        if not (t0 <= sensing_time < t1):
            return

        # Unzip
        unzip_file(full_zip_path, temp_dir)

        # Load, crop, resample
        if "1C-RRAD" in zip_file:
            files = find_files_and_readers(base_dir=temp_dir, reader='fci_l1c_nc')
            scn = Scene(filenames=files)
            channels = ['ir_105','ir_123']#,'ir_133','ir_38','ir_87','ir_97','nir_13','nir_16','nir_22',
                        # 'vis_04','vis_05','vis_06','vis_08','vis_09','wv_63','wv_73']
            outfile = os.path.join(DIR_OUT_RRAD, f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD.nc")
        elif "CLM" in zip_file:
            filenames = [f for f in os.listdir(temp_dir) if 'CLM' in f]
            files = [os.path.join(temp_dir, f) for f in filenames]
            scn = Scene(filenames=files, reader='fci_l2_grib')
            channels = ['cloud_mask']
            outfile = os.path.join(DIR_OUT_CLM, f"{sensing_time:%Y%m%d%H%M}_FCI-2-CLM.nc")

        scn.load(channels, upper_right_corner='NE')
        scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
        scn_resampled = scn.resample(area_def)

        ds = scn_resampled.to_xarray().compute()
        time_coord = sensing_time.replace(second=0, microsecond=0)
        ds = ds.assign_coords(time=("time",[time_coord]))
        ds["time"].attrs.update(standard_name="time", long_name="time")
        ds.to_netcdf(outfile)

        # Cleanup
        del scn, ds, scn_resampled
        gc.collect()
        shutil.rmtree(temp_dir)

        print(f"Saved {outfile}")

    except Exception as e:
        print(f"Error processing {zip_file}: {e}")

# -----------------------------
# MAIN EXECUTION
# -----------------------------
if __name__ == "__main__":
    # Detect available cores
    num_cores = os.cpu_count()
    max_workers = 60
    print(f"Detected {num_cores} CPU cores, using {max_workers} workers")

    # List zip files
    zip_files_rrad = [f for f in os.listdir(RAW_DIR_RRAD) if f.endswith(".zip")]
    zip_files_clm  = [f for f in os.listdir(RAW_DIR_CLM)  if f.endswith(".zip")]
    zip_files = zip_files_rrad + zip_files_clm

    start_time_perf = time.perf_counter()

    # Parallel processing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_zip, zf) for zf in zip_files]
        for future in as_completed(futures):
            # Raise exceptions if any
            future.result()

    end_time_perf = time.perf_counter()
    elapsed_minutes = (end_time_perf - start_time_perf)/60
    print(f"Processing completed in {elapsed_minutes:.2f} minutes")
