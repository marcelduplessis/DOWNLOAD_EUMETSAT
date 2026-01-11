from zipfile import ZipFile
import re
from pathlib import Path
from datetime import datetime
from satpy.scene import Scene
from satpy import find_files_and_readers
from pyresample import create_area_def
import xarray as xr
import shutil
import gc
from params import raw_data_dir_rrad, raw_data_dir_clm

# -----------------------------
# PATH SETUP (cross-platform)
# -----------------------------
RAW_DIR_RRAD = Path(raw_data_dir_rrad).expanduser().resolve()
RAW_DIR_CLM  = Path(raw_data_dir_clm).expanduser().resolve()

BASE_DIR = Path(__file__).resolve().parents[1]  # GOFLOW_LR root
dirout_unzip = BASE_DIR / "data" / "tmp"
dirout_fci   = BASE_DIR / "data" / "processed" / "1C-RRAD_nc"
dirout_clm   = BASE_DIR / "data" / "processed" / "2-CLM_nc"

# Create directories if they do not exist
for d in [dirout_fci, dirout_clm, dirout_unzip]:
    d.mkdir(parents=True, exist_ok=True)

# -----------------------------
# RESTRICT THE TIME WINDOW TO READ
# -----------------------------
t0 = datetime.strptime("20250125000000", "%Y%m%d%H%M%S")
t1 = datetime.strptime("20250126000000", "%Y%m%d%H%M%S")

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
def get_radiance_channels(all_channels):
    """Keep only radiance channels (discard metadata)."""
    return [
        ch for ch in all_channels
        if not re.search(
            r"_(earth_sun_distance|index_map|pixel_quality|platform_altitude|"
            r"subsatellite_latitude|subsatellite_longitude|subsolar_latitude|"
            r"subsolar_longitude|sun_satellite_distance|swath_direction|"
            r"swath_number|time)$",
            ch,
        )
    ]


def unzip_file(zip_path: Path, out_dir: Path):
    """Unzip a single zip file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(zip_path, "r") as z:
        z.extractall(out_dir)


def get_fci_scene(data_dir: Path, product: str, fmt: str | None = None):
    """Load FCI Scene using Satpy."""
    if product == "L1C":
        reader="fci_l1c_nc"
        filenames = list(data_dir.glob("*.nc"))
        return Scene(filenames=[str(f) for f in filenames], reader=reader)
    else:  # L2
        reader = "fci_l2_nc" if fmt == "nc" else "fci_l2_grib"
        filenames = list(data_dir.glob(f"*{product}*"))
        return Scene(filenames=[str(f) for f in filenames], reader=reader)


# def get_fci_scene(data_dir: Path, product: str, fmt: str | None = None):
#     """Load FCI Scene using Satpy."""
#     if product == "L1C":
#         files = find_files_and_readers(str(data_dir), reader="fci_l1c_nc")
#         return Scene(filenames=files)
#     else:  # L2
#         reader = "fci_l2_nc" if fmt == "nc" else "fci_l2_grib"
#         filenames = list(data_dir.glob(f"*{product}*"))
#         return Scene(filenames=[str(f) for f in filenames], reader=reader)


# -----------------------------
# MAIN LOOP
# -----------------------------
# Collect zip files from both RRAD and CLM raw directories
zip_files_rrad = [f for f in RAW_DIR_RRAD.iterdir() if f.suffix == ".zip"]
zip_files_clm  = [f for f in RAW_DIR_CLM.iterdir()  if f.suffix == ".zip"]

zip_files = zip_files_rrad + zip_files_clm

for zip_file in zip_files:
    match = re.search(r"OPE_(\d{14})_", zip_file.name)
    if not match:
        continue

    sensing_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    if not (t0 <= sensing_time < t1):
        continue

    # Unzip
    unzip_file(zip_file, dirout_unzip)
    
    # -----------------------------
    # LOAD, CROP, RESAMPLE
    # -----------------------------
    if "1C-RRAD" in zip_file.name:
        scn = get_fci_scene(dirout_unzip, product="L1C")
        outfile = dirout_fci / f"{sensing_time:%Y%m%d%H%M}_FCI-1C-RRAD.nc"
        
    elif "CLM" in zip_file.name:
        scn = get_fci_scene(dirout_unzip, product="CLM", fmt="bin")
        outfile = dirout_clm / f"{sensing_time:%Y%m%d%H%M}_FCI-2-CLM.nc"

    channels = get_radiance_channels(scn.available_dataset_names())
    scn.load(channels)
    scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
    scn = scn.resample(area_def)
    ds = scn.to_xarray()
    
    ds.to_netcdf(outfile)
    print(f"Saved {outfile}")
    del scn, ds

    # -----------------------------
    # CLEANUP
    # -----------------------------
    shutil.rmtree(dirout_unzip)
    dirout_unzip.mkdir(parents=True, exist_ok=True)
    gc.collect()
