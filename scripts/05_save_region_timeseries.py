## Save time series of FCI L1C-RRAD and L2-CLM products to netcdf format

# Input: raw zip files downloaded from EUMETSAT.

# Each zip file extracts to 40 body chunk .nc files + 1 trailer chunk .nc file + metadata.
# Each body chunk is a portion of the full disk scan at a given timestep.
# For each FD scan, this code reconstructs a region of interest (lon_min, lon_max, lat_min, lat_max) over a time span of interest (t0 -> t1). 
# FD scans are separated by 10 minutes. Note: the start time in the RRAD and CLM file names differ by a few seconds.

# Output: reconstructed snapshot saved as a dataset with the FCI channels as variables and x,y (lon,lat) as dimensions/coordinates.

"""
MTG FCI L1C (RRAD) & L2 (CLM) processing workflow (separate .nc per product)

1. Loop through time steps
2. Unzip FCI and CLM files into temp folder
3. Load only radiance channels
4. Crop and resample
5. Save .nc
6. Empty temp folder for next file
"""

"""
Save time series of FCI L1C-RRAD and L2-CLM products to NetCDF format
"""

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

# -----------------------------
# PATH SETUP (cross-platform)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parents[1]  # GOFLOW_LR root

dirin = BASE_DIR / "data" / "raw"
dirout_unzip = BASE_DIR / "data" / "tmp"
dirout_fci = BASE_DIR / "data" / "processed" / "1C-RRAD_nc"
dirout_clm = BASE_DIR / "data" / "processed" / "2-CLM_nc"

dirout_fci.mkdir(parents=True, exist_ok=True)
dirout_clm.mkdir(parents=True, exist_ok=True)
dirout_unzip.mkdir(parents=True, exist_ok=True)

# -----------------------------
# TIME WINDOW
# -----------------------------
t0 = datetime.strptime("20250202000000", "%Y%m%d%H%M%S")
t1 = datetime.strptime("20250203000000", "%Y%m%d%H%M%S")

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
        files = find_files_and_readers(
            base_dir=str(data_dir), reader="fci_l1c_nc"
        )
        return Scene(filenames=files)
    else:  # L2
        reader = "fci_l2_nc" if fmt == "nc" else "fci_l2_grib"
        filenames = list(data_dir.glob(f"*{product}*"))
        return Scene(filenames=[str(f) for f in filenames], reader=reader)


# -----------------------------
# MAIN LOOP
# -----------------------------
zip_files = [
    f for f in dirin.iterdir()
    if f.suffix == ".zip" and "FCI" in f.name
]

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
        channels = get_radiance_channels(scn.available_dataset_names())
        scn.load(channels)
        scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
        scn = scn.resample(area_def)
        ds = scn.to_xarray()

        outfile = dirout_fci / f"{sensing_time:%Y%m%d%H%M%S}_FCI-1C-RRAD.nc"
        ds.to_netcdf(outfile)
        print(f"Saved {outfile}")

        del scn, ds

    elif "CLM" in zip_file.name:
        scn = get_fci_scene(dirout_unzip, product="CLM", fmt="bin")
        channels = get_radiance_channels(scn.available_dataset_names())
        scn.load(channels)
        scn = scn.crop(ll_bbox=(lon_min, lat_min, lon_max, lat_max))
        scn = scn.resample(area_def)
        ds = scn.to_xarray()

        outfile = dirout_clm / f"{sensing_time:%Y%m%d%H%M%S}_FCI-2-CLM.nc"
        ds.to_netcdf(outfile)
        print(f"Saved {outfile}")

        del scn, ds

    # -----------------------------
    # CLEANUP
    # -----------------------------
    shutil.rmtree(dirout_unzip)
    dirout_unzip.mkdir(parents=True, exist_ok=True)
    gc.collect()
