"""
Read the regridded FCI radiance and cloud-mask time-series files and,
for a given IR channel, produce a single NetCDF with four variables:

    BT              – {channel} brightness temperature (K), float32
    loggrad_T       – log10 of horizontal gradient magnitude of BT, float32
    mask            – cloud/clear/nodata flag, float32
                        CLM 0 or 1 (clear water / clear land) → 1
                        CLM 2      (cloud)                    → 0
                        CLM 3      (no data)                  → NaN
    loggrad_T_masked – loggrad_T set to NaN where mask == 0 (cloudy)

Output file: <t_start>-<t_end>_FCI-{channel}_0p02deg.nc

Coded by Lucie Reymondet (Scripps-UCSD)
"""

import datetime
import os
import re
import glob
import numpy as np
import xarray as xr

from params import regridded_data_dir_rrad_hr, \
    regridded_data_dir_clm, processed_goflow_inputs, \
    lon_min, lon_max, lat_min, lat_max, resolution 

# ─────────────────────────────────────────────────────────────────────────────
# CHANNEL CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
channel = "ir_105"
# channel = "ir_123"

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORIES
# ─────────────────────────────────────────────────────────────────────────────
def fmt_lon(v):
    return f"{abs(v):.0f}{'E' if v >= 0 else 'W'}"

def fmt_lat(v):
    return f"{abs(v):.0f}{'N' if v >= 0 else 'S'}"

area_label = f"{fmt_lon(lon_min)}-{fmt_lon(lon_max)}_{fmt_lat(lat_min)}-{fmt_lat(lat_max)}"

DIR_RRAD = os.path.join(regridded_data_dir_rrad_hr, area_label) # or regridded_data_dir_rrad_nr
DIR_CLM  = os.path.join(regridded_data_dir_clm,     area_label)
DIR_OUT  = os.path.join(processed_goflow_inputs,    area_label)

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


def parse_timespan(path: str) -> tuple[datetime.datetime, datetime.datetime]:
    """Extract the start and end datetimes from a concatenated NetCDF filename."""
    basename = os.path.basename(path)
    match = re.match(r"(?P<start>\d{12})-(?P<end>\d{12})_", basename)
    if not match:
        raise ValueError(f"Cannot parse time span from filename: {basename}")

    start = datetime.datetime.strptime(match.group("start"), "%Y%m%d%H%M")
    end = datetime.datetime.strptime(match.group("end"), "%Y%m%d%H%M")
    return start, end


def find_timeseries_last_48h(directory: str, pattern: str) -> str:
    """Return the most recent concatenated NetCDF overlapping the last 48 hours."""
    window_end = datetime.datetime.now()
    window_start = window_end - datetime.timedelta(hours=48)

    hits = glob.glob(os.path.join(directory, pattern))
    hits = [h for h in hits if re.match(r"\d{12}-\d{12}_", os.path.basename(h))]

    matching_hits = []
    for hit in hits:
        start, end = parse_timespan(hit)
        if end >= window_start and start <= window_end:
            matching_hits.append((start, end, hit))

    if not matching_hits:
        raise FileNotFoundError(
            f"No concatenated NetCDF matching '{pattern}' in the last 48 hours found in {directory}"
        )

    matching_hits.sort(key=lambda item: (item[1], item[0]))
    if len(matching_hits) > 1:
        print(
            f"WARNING: multiple matches for '{pattern}' in the last 48 hours, using the most recent:\n  " +
            "\n  ".join(hit[2] for hit in matching_hits)
        )

    return matching_hits[-1][2]


def list_timeseries_in_window(
    directory: str,
    pattern: str,
    window_hours: int = 48,
) -> list[tuple[datetime.datetime, datetime.datetime, str]]:
    """Return all concatenated NetCDF paths overlapping the trailing window."""
    window_end = datetime.datetime.now()
    window_start = window_end - datetime.timedelta(hours=window_hours)

    hits = glob.glob(os.path.join(directory, pattern))
    hits = [h for h in hits if re.match(r"\d{12}-\d{12}_", os.path.basename(h))]

    matching_hits = []
    for hit in hits:
        start, end = parse_timespan(hit)
        if end >= window_start and start <= window_end:
            matching_hits.append((start, end, hit))

    matching_hits.sort(key=lambda item: (item[0], item[1]))
    return matching_hits


def time_prefix_from_path(path: str) -> str:
    """Return YYYYMMDDHHMM-YYYYMMDDHHMM from a concatenated NetCDF path."""
    basename = os.path.basename(path)
    match = re.match(r"(?P<prefix>\d{12}-\d{12})_", basename)
    if not match:
        raise ValueError(f"Cannot extract time prefix from filename: {basename}")
    return match.group("prefix")


def output_path_from_prefix(time_prefix: str) -> str:
    return os.path.join(
        DIR_OUT,
        f"{time_prefix}_FCI-{channel}_{str(resolution).replace('.', 'p')}deg.nc",
    )


def process_timeseries_pair(rrad_path: str, clm_path: str, outfile: str) -> None:
    print(f"RRAD file : {rrad_path}")
    print(f"CLM  file : {clm_path}")

    # ── 2. Load data ──────────────────────────────────────────────────────
    print("Loading datasets …")
    with xr.open_dataset(rrad_path) as ds_rrad, xr.open_dataset(clm_path) as ds_clm:
        bt = ds_rrad[channel]          # (time, lat, lon) float32, land=NaN
        clm = ds_clm["cloud_mask"]    # (time, lat, lon) float32, land=NaN

        # ── 3. BT ─────────────────────────────────────────────────────────────
        bt = bt.astype(np.float32)
        bt.attrs.update(
            long_name=f"{channel} brightness temperature",
            units="K",
            source=f"FCI L1C RRAD FDHSI, channel {channel}, calibration=brightness_temperature",
        )

        # ── 4. loggrad_T (computed time-step by time-step to keep memory low) ─
        print("Computing loggrad_T …")
        loggrad_slices = []
        for t_idx in range(bt.sizes["time"]):
            bt_slice = bt.isel(time=t_idx)   # 2-D (lat, lon)
            lg_slice = compute_loggrad(bt_slice)
            loggrad_slices.append(
                lg_slice.expand_dims("time").assign_coords(time=[bt["time"].values[t_idx]])
            )
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
            long_name=(f"Log10 horizontal gradient magnitude of {channel} BT, "
                       "masked to NaN where cloudy (mask=0); "
                       "no-data pixels (mask=NaN) left as NaN but not explicitly masked"),
            units="log10(K/m)",
            masking="NaN where mask==0 (CLM=2, cloudy) only",
        )

        # ── 7. Assemble output dataset ────────────────────────────────────────
        ds_out = xr.Dataset(
            {
                "BT": bt,
                "loggrad_T": loggrad_T,
                "mask": mask,
                "loggrad_T_masked": loggrad_T_masked,
            },
            coords={
                "time": bt["time"],
                "lat": bt["lat"],
                "lon": bt["lon"],
            },
        )

        # Clean up any inherited land-mask global attribute
        # ds_out.attrs.pop("land_mask", None)
        ds_out.attrs.update(
            title=f"FCI {channel} brightness temperature, gradient, and cloud mask",
            source=(f"RRAD: {os.path.basename(rrad_path)}; "
                    f"CLM: {os.path.basename(clm_path)}"),
            Conventions="CF-1.8",
        )

        # ── 8. Save ───────────────────────────────────────────────────────────
        print(f"Saving → {outfile}")
        t_ref = str(ds_out["time"].values[0].astype("datetime64[D]"))
        ds_out.to_netcdf(
            outfile,
            encoding={
                "time": {"units": f"minutes since {t_ref}"},
                "BT": {"dtype": "float32", "zlib": True, "complevel": 4},
                "loggrad_T": {"dtype": "float32", "zlib": True, "complevel": 4},
                "mask": {"dtype": "float32", "zlib": True, "complevel": 4},
                "loggrad_T_masked": {"dtype": "float32", "zlib": True, "complevel": 4},
            },
        )
        print("Done.")
        print(ds_out)


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
        long_name  = f"Log10 horizontal gradient magnitude of {channel} brightness temperature",
        units      = "log10(K/m)",
        source_channel      = f"{channel}",
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
    os.makedirs(DIR_OUT, exist_ok=True)

    # ── 1. Locate candidate files in the trailing 48-hour window ──────────
    rrad_hits = list_timeseries_in_window(DIR_RRAD, "*FCI-1C-RRAD*.nc", window_hours=48)
    clm_hits = list_timeseries_in_window(DIR_CLM, "*FCI-2-CLM*.nc", window_hours=48)

    if not rrad_hits:
        raise FileNotFoundError(
            f"No concatenated NetCDF matching '*FCI-1C-RRAD*.nc' in the last 48 hours found in {DIR_RRAD}"
        )
    if not clm_hits:
        raise FileNotFoundError(
            f"No concatenated NetCDF matching '*FCI-2-CLM*.nc' in the last 48 hours found in {DIR_CLM}"
        )

    # Keep one file per timespan prefix and prefer the latest end time.
    rrad_by_prefix = {}
    for start, end, path in rrad_hits:
        prefix = time_prefix_from_path(path)
        prev = rrad_by_prefix.get(prefix)
        if prev is None or (end, start) > (prev[0], prev[1]):
            rrad_by_prefix[prefix] = (end, start, path)

    clm_by_prefix = {}
    for start, end, path in clm_hits:
        prefix = time_prefix_from_path(path)
        prev = clm_by_prefix.get(prefix)
        if prev is None or (end, start) > (prev[0], prev[1]):
            clm_by_prefix[prefix] = (end, start, path)

    rrad_prefixes = set(rrad_by_prefix)
    clm_prefixes = set(clm_by_prefix)
    rrad_only_prefixes = sorted(rrad_prefixes - clm_prefixes)
    clm_only_prefixes = sorted(clm_prefixes - rrad_prefixes)

    if rrad_only_prefixes:
        print(
            f"WARNING: {len(rrad_only_prefixes)} RRAD prefix(es) in the last 48h "
            "have no matching CLM file:"
        )
        for prefix in rrad_only_prefixes:
            print(f"  {prefix}")

    if clm_only_prefixes:
        print(
            f"WARNING: {len(clm_only_prefixes)} CLM prefix(es) in the last 48h "
            "have no matching RRAD file:"
        )
        for prefix in clm_only_prefixes:
            print(f"  {prefix}")

    common_prefixes = sorted(
        set(rrad_by_prefix) & set(clm_by_prefix),
        key=lambda p: (rrad_by_prefix[p][0], rrad_by_prefix[p][1]),
    )
    if not common_prefixes:
        raise FileNotFoundError(
            "No matching RRAD/CLM timespan prefixes were found in the last 48 hours."
        )

    n_processed = 0
    n_skipped = 0
    for time_prefix in common_prefixes:
        outfile = output_path_from_prefix(time_prefix)
        if os.path.exists(outfile):
            print(f"Skipping existing output: {outfile}")
            n_skipped += 1
            continue

        rrad_path = rrad_by_prefix[time_prefix][2]
        clm_path = clm_by_prefix[time_prefix][2]
        process_timeseries_pair(rrad_path, clm_path, outfile)
        n_processed += 1

    print(
        f"Completed processing window: processed {n_processed}, skipped {n_skipped}, "
        f"total matched prefixes {len(common_prefixes)}"
    )


if __name__ == "__main__":
    main()