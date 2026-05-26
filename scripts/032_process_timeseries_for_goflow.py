"""
build_ir105_dataset.py
──────────────────────
Reads the pre-processed FCI radiance and cloud-mask time-series files and
produces a single NetCDF with four variables:

    BT              – ir_105 brightness temperature (K), float32
    loggrad_T       – log10 of horizontal gradient magnitude of BT, float32
    mask            – cloud/clear/nodata flag, float32
                        CLM 0 or 1 (clear water / clear land) → 1
                        CLM 2      (cloud)                    → 0
                        CLM 3      (no data)                  → NaN
    loggrad_T_masked – loggrad_T set to NaN where mask == 0 (cloudy)

Output file: <t_start>-<t_end>_FCI-ir_105_0p02deg.nc
"""

import os
import re
import glob
import numpy as np
import xarray as xr

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION  –  adjust these two directories to match your setup
# ─────────────────────────────────────────────────────────────────────────────
DIR_RRAD = r"D:\EUMETSAT_data\processed_RRAD_NR\10E-35E_45S-30S"
DIR_CLM  = r"D:\EUMETSAT_data\processed_CLM\10E-35E_45S-30S"
DIR_OUT  = DIR_RRAD   # write the output alongside the radiance data

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def find_timeseries(directory: str, pattern: str) -> str:
    """Return the path of the concatenated NetCDF (pattern = e.g. '*FCI-1C-RRAD*')."""
    hits = glob.glob(os.path.join(directory, pattern))
    # The concatenated file has a name like YYYYMMDDHHMM-YYYYMMDDHHMM_*.nc
    hits = [h for h in hits if re.match(r"\d{12}-\d{12}_", os.path.basename(h))]
    if not hits:
        raise FileNotFoundError(
            f"No concatenated NetCDF matching '{pattern}' found in {directory}"
        )
    if len(hits) > 1:
        print(f"WARNING: multiple matches for '{pattern}', using the first:\n  " +
              "\n  ".join(hits))
    return hits[0]


def compute_loggrad(bt_2d: xr.DataArray, eps: float = 1e-12) -> xr.DataArray:
    """
    Log10 of the horizontal gradient magnitude of a 2-D BT field (lat × lon).

    Uses central differences via xarray.differentiate with a spherical-metric
    correction so units are K m⁻¹ before taking log10.
    """
    Rt  = 6_378_000.0   # Earth radius in metres

    # cos-correction converts degrees → metres in the zonal direction
    Rlat = xr.DataArray(
        Rt * np.cos(np.deg2rad(bt_2d["lat"])),
        dims="lat",
        coords={"lat": bt_2d["lat"].values},
    )

    # Derivatives in K/m
    dTdx = bt_2d.differentiate("lon") * (180.0 / (np.pi * Rlat))
    dTdy = bt_2d.differentiate("lat") * (180.0 / (np.pi * Rt))

    gradT    = np.sqrt(dTdx ** 2 + dTdy ** 2)
    log_grad = np.log10(gradT + eps).astype(np.float32)

    log_grad.attrs.update(
        long_name  = "Log10 horizontal gradient magnitude of ir_105 brightness temperature",
        units      = "log10(K/m)",
        source_channel      = "ir_105",
        source_calibration  = "brightness_temperature",
        gradient_method     = ("central differences via xarray.differentiate, "
                               "spherical metric correction"),
        eps = str(eps),
    )
    return log_grad


def build_mask(clm: xr.DataArray) -> xr.DataArray:
    """
    Map CLM integer values to a float32 mask:
        0 (clear water) → 1
        1 (clear land)  → 1
        2 (cloud)       → 0
        3 (no data)     → NaN
    NaN pixels in the input (land-masked) are preserved as NaN.
    """
    clm_vals = clm.values           # (time, lat, lon) float32

    mask = np.where(clm_vals <= 1.0,   1.0,
           np.where(clm_vals == 2.0,   0.0,
           np.where(clm_vals == 3.0,   np.nan,
                                       np.nan)))   # any other value → NaN
    mask = mask.astype(np.float32)

    result = xr.DataArray(
        mask,
        dims   = clm.dims,
        coords = clm.coords,
        attrs  = {
            "long_name"  : "Cloud/clear/nodata mask derived from FCI CLM",
            "flag_values": "1, 0, NaN",
            "flag_meanings": "clear(water_or_land)=1  cloudy=0  no_data=NaN",
            "source"     : "FCI L2 Cloud Mask (CLM 0,1→1; CLM 2→0; CLM 3→NaN)",
        },
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # ── 1. Locate input files ─────────────────────────────────────────────
    rrad_path = find_timeseries(DIR_RRAD, "*FCI-1C-RRAD*.nc")
    clm_path  = find_timeseries(DIR_CLM,  "*FCI-2-CLM*.nc")

    print(f"RRAD file : {rrad_path}")
    print(f"CLM  file : {clm_path}")

    # Derive output filename from the RRAD file's time-span prefix
    basename    = os.path.basename(rrad_path)          # e.g. 202502010000-202502010050_FCI-1C-RRAD_0p02deg.nc
    time_prefix = basename.split("_")[0]               # "202502010000-202502010050"
    outfile     = os.path.join(DIR_OUT,
                               f"{time_prefix}_FCI-ir_105_0p02deg.nc")

    # ── 2. Load data ──────────────────────────────────────────────────────
    print("Loading datasets …")
    ds_rrad = xr.open_dataset(rrad_path)
    ds_clm  = xr.open_dataset(clm_path)

    bt  = ds_rrad["ir_105"]          # (time, lat, lon) float32, land=NaN
    clm = ds_clm["cloud_mask"]       # (time, lat, lon) float32, land=NaN

    # ── 3. BT ─────────────────────────────────────────────────────────────
    bt = bt.astype(np.float32)
    bt.attrs.update(
        long_name  = "ir_105 brightness temperature",
        units      = "K",
        source     = "FCI L1C RRAD FDHSI, channel ir_105, calibration=brightness_temperature",
    )

    # ── 4. loggrad_T (computed time-step by time-step to keep memory low) ─
    print("Computing loggrad_T …")
    loggrad_slices = []
    for t_idx in range(bt.sizes["time"]):
        bt_slice       = bt.isel(time=t_idx)   # 2-D (lat, lon)
        lg_slice       = compute_loggrad(bt_slice)
        loggrad_slices.append(lg_slice.expand_dims("time").assign_coords(
            time=[bt["time"].values[t_idx]]
        ))
    loggrad_T = xr.concat(loggrad_slices, dim="time")

    # ── 5. mask ──────────────────────────────────────────────────────────
    print("Building mask …")
    mask = build_mask(clm)

    # ── 6. loggrad_T_masked ──────────────────────────────────────────────
    # Blank only confirmed cloudy pixels (mask==0); leave NaN no-data pixels
    # untouched so they remain NaN rather than being double-assigned.
    loggrad_T_masked = loggrad_T.where(mask != 0.0)
    loggrad_T_masked = loggrad_T_masked.astype(np.float32)
    loggrad_T_masked.attrs.update(
        long_name = ("Log10 horizontal gradient magnitude of ir_105 BT, "
                     "masked to NaN where cloudy (mask=0); "
                     "no-data pixels (mask=NaN) left as NaN but not explicitly masked"),
        units     = "log10(K/m)",
        masking   = "NaN where mask==0 (CLM=2, cloudy) only",
    )

    # ── 7. Assemble output dataset ────────────────────────────────────────
    ds_out = xr.Dataset(
        {
            "BT"              : bt,
            "loggrad_T"       : loggrad_T,
            "mask"            : mask,
            "loggrad_T_masked": loggrad_T_masked,
        },
        coords={
            "time": bt["time"],
            "lat" : bt["lat"],
            "lon" : bt["lon"],
        },
    )

    # Clean up any inherited land-mask global attribute
    # ds_out.attrs.pop("land_mask", None)
    ds_out.attrs.update(
        title     = "FCI ir_105 brightness temperature, gradient, and cloud mask",
        source    = (f"RRAD: {os.path.basename(rrad_path)}; "
                     f"CLM: {os.path.basename(clm_path)}"),
        Conventions = "CF-1.8",
    )

    # ── 8. Save ───────────────────────────────────────────────────────────
    print(f"Saving → {outfile}")
    t_ref = str(ds_out["time"].values[0].astype("datetime64[D]"))
    ds_out.to_netcdf(
        outfile,
        encoding={
            "time"              : {"units": f"minutes since {t_ref}"},
            "BT"                : {"dtype": "float32", "zlib": True, "complevel": 4},
            "loggrad_T"         : {"dtype": "float32", "zlib": True, "complevel": 4},
            "mask"              : {"dtype": "float32", "zlib": True, "complevel": 4},
            "loggrad_T_masked"  : {"dtype": "float32", "zlib": True, "complevel": 4},
        },
    )
    print("Done.")
    print(ds_out)


if __name__ == "__main__":
    main()