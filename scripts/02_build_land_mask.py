# run_once_build_mask.py
import numpy as np
import xarray as xr
import regionmask
import os
from params import base_dir

# -----------------------------
# DOMAIN
# -----------------------------
lon_min, lon_max = 10.0, 35.0
lat_min, lat_max = -45.0, -30.0

_lat_vals = np.arange(lat_min, lat_max, 0.02)
_lon_vals = np.arange(lon_min, lon_max, 0.02)

# -----------------------------
# AREA-DERIVED OUTPUT DIRS
# -----------------------------
def fmt_lon(v):
    return f"{abs(v):.0f}{'E' if v >= 0 else 'W'}"

def fmt_lat(v):
    return f"{abs(v):.0f}{'N' if v >= 0 else 'S'}"

area_label = f"{fmt_lon(lon_min)}-{fmt_lon(lon_max)}_{fmt_lat(lat_min)}-{fmt_lat(lat_max)}"

# -----------------------------
# MAIN PROCESS EXECUTION
# -----------------------------
land = regionmask.defined_regions.natural_earth_v5_0_0.land_50
mask = land.mask(_lon_vals, _lat_vals)
LAND_MASK = ~np.isnan(mask.values)

MASK_PATH = os.path.join(base_dir, f"land_mask_{area_label}_0p02deg.nc")
xr.Dataset(
    {"land_mask": (["lat", "lon"], LAND_MASK)},
    coords={"lat": _lat_vals, "lon": _lon_vals},
).to_netcdf(MASK_PATH)
print(f"Saved {MASK_PATH} — {LAND_MASK.sum()} land pixels")