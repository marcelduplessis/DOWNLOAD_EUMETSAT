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
from params import raw_data_dir_rrad, raw_data_dir_clm, base_dir, processed_data_dir_rrad, processed_data_dir_clm
import time



# -----------------------------
# PATH SETUP (cross-platform)
# -----------------------------
RAW_DIR_RRAD = raw_data_dir_rrad
RAW_DIR_CLM = raw_data_dir_clm
BASE_DIR = base_dir
DIR_OUT_RRAD = processed_data_dir_rrad
DIR_OUT_CLM =processed_data_dir_clm

DIR_OUT_UNZIP = os.path.join(BASE_DIR, "data", "tmp")

for d in [DIR_OUT_UNZIP, DIR_OUT_RRAD, DIR_OUT_CLM]:
    os.makedirs(d, exist_ok=True)

# -----------------------------
# TIME WINDOW
# -----------------------------
t0 = datetime.strptime("20250125000000", "%Y%m%d%H%M%S")
t1 = datetime.strptime("20250130000000", "%Y%m%d%H%M%S")

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

# def get_radiance_channels(all_channels):
#     """Keep only radiance channels (discard metadata)."""
#     return [
#         ch for ch in all_channels
#         if not re.search(
#             r"_(earth_sun_distance|index_map|pixel_quality|platform_altitude|"
#             r"subsatellite_latitude|subsatellite_longitude|subsolar_latitude|"
#             r"subsolar_longitude|sun_satellite_distance|swath_direction|"
#             r"swath_number|time)$",
#             ch,
#         )
#     ]

# def get_fci_scene(data_dir, product, fmt=None):
#     """Load FCI Scene using Satpy."""
#     if product == "L1C":
#         files = find_files_and_readers(base_dir=data_dir, reader='fci_l1c_nc')
#         return Scene(filenames=files)
#     else:  # L2
#         reader = "fci_l2_nc" if fmt == "nc" else "fci_l2_grib"
#         filenames = [f for f in os.listdir(data_dir) if product in f]
#         files = [os.path.join(data_dir, f) for f in filenames]
#         return Scene(filenames=files, reader=reader)

# -----------------------------
# MAIN LOOP
# -----------------------------
zip_files_rrad = [f for f in os.listdir(RAW_DIR_RRAD) if f.endswith(".zip")]
zip_files_clm  = [f for f in os.listdir(RAW_DIR_CLM) if f.endswith(".zip")]
zip_files = zip_files_rrad + zip_files_clm

start_time = time.perf_counter()

for zip_file in zip_files:
    RAW_DIR = RAW_DIR_RRAD if 'RRAD' in zip_file else RAW_DIR_CLM
    full_zip_path = os.path.join(RAW_DIR, zip_file)

    match = re.search(r"OPE_(\d{14})_", zip_file)
    if not match:
        continue

    sensing_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    if not (t0 <= sensing_time < t1):
        continue

    unzip_file(full_zip_path, DIR_OUT_UNZIP)

    # -----------------------------
    # LOAD, CROP, RESAMPLE
    # -----------------------------
    if "1C-RRAD" in zip_file:
        files = find_files_and_readers(base_dir=DIR_OUT_UNZIP, reader='fci_l1c_nc')
        scn = Scene(filenames=files)
        channels = ['ir_105', 'ir_123', 'ir_133', 'ir_38', 'ir_87', 'ir_97', 'nir_13', 'nir_16', 'nir_22', 'vis_04', 'vis_05', 'vis_06', 'vis_08', 'vis_09', 'wv_63', 'wv_73']
        outfile = os.path.join(DIR_OUT_RRAD, f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD.nc")
        # print("outfile = ", outfile)
    elif "CLM" in zip_file:
        filenames = [f for f in os.listdir(DIR_OUT_UNZIP) if 'CLM' in f]
        files = [os.path.join(DIR_OUT_UNZIP, f) for f in filenames]
        scn = Scene(filenames=files, reader='fci_l2_grib')
        channels = ['cloud_mask']
        outfile = os.path.join(DIR_OUT_CLM, f"{sensing_time:%Y%m%d%H%M}_FCI-2-CLM.nc")
        # print("outfile = ", outfile)
    
    scn.load(channels, upper_right_corner='NE')
    scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
    scn_resampled = scn.resample(area_def)

    ds = scn_resampled.to_xarray()
    ds = ds.compute()

    time_coord = sensing_time.replace(second=0, microsecond=0)
    ds = ds.assign_coords(time=("time",[time_coord]))
    ds["time"].attrs.update(standard_name="time",long_name="time")
    ds.to_netcdf(outfile)
    time.sleep(1)
    print(f"Saved {outfile}")

    # -----------------------------
    # CLEANUP
    # -----------------------------
    del scn, ds, scn_resampled
    gc.collect()

    # Clear temporary folder for next zip
    shutil.rmtree(DIR_OUT_UNZIP)
    os.makedirs(DIR_OUT_UNZIP, exist_ok=True)

end_time = time.perf_counter()
elapsed_seconds = end_time - start_time
elapsed_minutes = elapsed_seconds / 60

print(f"Downloads completed in {elapsed_minutes:.2f} minutes")