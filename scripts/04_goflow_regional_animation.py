#!/usr/bin/env python3
"""
Animate a regional time series for a given IR channel, showing brightness
temperature and its log-gradient overlaid with cloud mask.

Original code by Lucie Reymondet (Scripps-UCSD), adapted by M. du Plessis
(University of Gothenburg), and refactored into a terminal-runnable script.
"""

from pathlib import Path
import argparse
import datetime as dt
import glob
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import xarray as xr

from params import processed_goflow_inputs, lon_min, lon_max, lat_min, lat_max, resolution


def fmt_lon(v):
    return f"{abs(v):.0f}{'E' if v >= 0 else 'W'}"


def fmt_lat(v):
    return f"{abs(v):.0f}{'N' if v >= 0 else 'S'}"


def area_label_from_params():
    return f"{fmt_lon(lon_min)}-{fmt_lon(lon_max)}_{fmt_lat(lat_min)}-{fmt_lat(lat_max)}"


def parse_timespan_from_name(path):
    name = os.path.basename(path)
    match = re.match(r"(\d{12})-(\d{12})_", name)
    if not match:
        return None
    start = dt.datetime.strptime(match.group(1), "%Y%m%d%H%M")
    end = dt.datetime.strptime(match.group(2), "%Y%m%d%H%M")
    return start, end


def files_in_window(directory, pattern, hours=48):
    now = dt.datetime.now()
    window_start = now - dt.timedelta(hours=hours)
    candidates = glob.glob(os.path.join(directory, pattern))
    selected = []
    for path in candidates:
        span = parse_timespan_from_name(path)
        if span is None:
            continue
        start, end = span
        if end >= window_start and start <= now:
            selected.append((start, path))
    selected.sort(key=lambda item: item[0])
    return [item[1] for item in selected]


def load_dataset(channel, hours=48, input_dir=None):
    if input_dir is None:
        input_dir = os.path.join(processed_goflow_inputs, area_label_from_params())

    pattern = f"*_FCI-{channel}_{str(resolution).replace('.', 'p')}deg.nc"
    selected_files = files_in_window(input_dir, pattern, hours=hours)

    if not selected_files:
        raise FileNotFoundError(
            f"No files found in the last {hours}h for pattern {pattern} in {input_dir}"
        )

    print("Using files:")
    for p in selected_files:
        print(f"  {os.path.basename(p)}")

    datasets = [xr.open_dataset(p) for p in selected_files]
    ds = xr.concat(datasets, dim="time").sortby("time")

    time_index = ds.get_index("time")
    if time_index.has_duplicates:
        ds = ds.isel(time=~time_index.duplicated())

    return ds


def make_animation(ds, var, output_path, lon_bounds=(10, 20), lat_bounds=(-38, -30),
                   cmap="magma", vmin=-4.5, vmax=-3.5, fps=4, interval=300, dpi=200):
    ds_subset = ds.sel(lat=slice(lat_bounds[0], lat_bounds[1]), lon=slice(lon_bounds[0], lon_bounds[1]))

    if ds_subset.sizes.get("time", 0) == 0:
        raise ValueError("Subset contains no time steps.")

    proj = ccrs.PlateCarree()
    fig = plt.figure(figsize=(7, 4), constrained_layout=True)
    ax = plt.axes(projection=proj)

    ax.set_extent([
        float(ds_subset.lon.min()),
        float(ds_subset.lon.max()),
        float(ds_subset.lat.min()),
        float(ds_subset.lat.max()),
    ], crs=ccrs.PlateCarree())

    ax.coastlines(resolution="10m", linewidth=0.8)
    ax.add_feature(cfeature.LAND, facecolor="0.85", zorder=0)
    gl = ax.gridlines(draw_labels=True, linewidth=0.4, color="gray", alpha=0.5, linestyle="--")
    gl.top_labels = False
    gl.right_labels = False

    data0 = ds_subset[var].isel(time=0)
    pcm = ax.pcolormesh(
        ds_subset.lon,
        ds_subset.lat,
        data0,
        transform=ccrs.PlateCarree(),
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="auto",
    )

    cbar = plt.colorbar(pcm, ax=ax, pad=0.02)
    cbar.set_label(var)
    title = ax.set_title(np.datetime_as_string(ds_subset.time.values[0], unit="m"))

    def update(frame):
        data = ds_subset[var].isel(time=frame).values
        pcm.set_array(data.ravel())
        title.set_text(np.datetime_as_string(ds_subset.time.values[frame], unit="m"))
        return pcm, title

    ani = FuncAnimation(
        fig,
        update,
        frames=ds_subset.sizes["time"],
        interval=interval,
        blit=False,
        repeat=True,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ani.save(output_path, writer="pillow", fps=fps, dpi=dpi)
    plt.close(fig)
    print(f"Saved animation to {output_path}")


def build_default_output(channel, var, outdir):
    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M")
    return Path(outdir) / f"goflow_{channel}_{var}_{timestamp}.gif"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a GIF animation from GOFLOW regional satellite data."
    )
    parser.add_argument("--channel", default="ir_105", help="IR channel, e.g. ir_105 or ir_123")
    parser.add_argument("--var", default="loggrad_T_masked", help="Variable to animate")
    parser.add_argument("--hours", type=int, default=48, help="Time window in hours")
    parser.add_argument("--lon-min", type=float, default=10)
    parser.add_argument("--lon-max", type=float, default=20)
    parser.add_argument("--lat-min", type=float, default=-38)
    parser.add_argument("--lat-max", type=float, default=-30)
    parser.add_argument("--cmap", default="magma")
    parser.add_argument("--vmin", type=float, default=-4.5)
    parser.add_argument("--vmax", type=float, default=-3.5)
    parser.add_argument("--fps", type=int, default=4)
    parser.add_argument("--interval", type=int, default=300, help="Animation interval in ms")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--input-dir", default=None, help="Override input directory")
    parser.add_argument("--outdir", default="./figures", help="Output directory")
    parser.add_argument("--output", default=None, help="Full output GIF path")
    return parser.parse_args()


def main():
    args = parse_args()
    ds = load_dataset(args.channel, hours=args.hours, input_dir=args.input_dir)
    output = args.output or build_default_output(args.channel, args.var, args.outdir)
    make_animation(
        ds=ds,
        var=args.var,
        output_path=output,
        lon_bounds=(args.lon_min, args.lon_max),
        lat_bounds=(args.lat_min, args.lat_max),
        cmap=args.cmap,
        vmin=args.vmin,
        vmax=args.vmax,
        fps=args.fps,
        interval=args.interval,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    main()
