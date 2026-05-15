# run_once_build_mask.py
import numpy as np
import xarray as xr
import regionmask
import os
from params import base_dir

lon_min, lon_max = 10.0, 35.0
lat_min, lat_max = -45.0, -30.0
area_label = "10E-35E_45S-30S"

_lat_vals = np.arange(lat_min, lat_max, 0.02)
_lon_vals = np.arange(lon_min, lon_max, 0.02)

land = regionmask.defined_regions.natural_earth_v5_0_0.land_110
mask = land.mask(_lon_vals, _lat_vals)
LAND_MASK = ~np.isnan(mask.values)

MASK_PATH = os.path.join(base_dir, f"land_mask_{area_label}.nc")
xr.Dataset(
    {"land_mask": (["lat", "lon"], LAND_MASK)},
    coords={"lat": _lat_vals, "lon": _lon_vals},
).to_netcdf(MASK_PATH)
print(f"Saved {MASK_PATH} — {LAND_MASK.sum()} land pixels")