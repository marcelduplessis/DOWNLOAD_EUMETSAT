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
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np
import xarray as xr
import cmocean.cm as cmo

from params import processed_goflow_inputs, lon_min, lon_max, lat_min, lat_max, resolution


def fmt_lon(v):
    return f"{abs(v):.0f}{'E' if v >= 0 else 'W'}"


def fmt_lat(v):
    return f"{abs(v):.0f}{'N' if v >= 0 else 'S'}"


def area_label_from_params():
    return f"{fmt_lon(lon_min)}-{fmt_lon(lon_max)}_{fmt_lat(lat_min)}-{fmt_lat(lat_max)}"


def cold_bt_overlay_cmap(n=256):
    grey = np.linspace(0.9, 0.35, n)
    rgba = np.column_stack([grey, grey, grey, np.ones(n)])
    return ListedColormap(rgba)


def show_legend(
    ax,
    *,
    show_glider=True,
    show_waveglider=True,
    loc="lower left",
    fontsize=11,
    frameon=True,
):
    """Add legend proxies for enabled Seaglider and Wave Glider tracks."""
    legend_elements = []
    if show_glider:
        legend_elements.append(
            Line2D(
                [0], [0], marker="o", linestyle="", markerfacecolor="gold",
                markeredgecolor="k", label="SG Koeksister"
            )
        )
    if show_waveglider:
        legend_elements.append(
            Line2D(
                [0], [0], marker="s", linestyle="", markerfacecolor="#B87333",
                markeredgecolor="k", label="WG Melktert"
            )
        )

    if legend_elements:
        ax.legend(handles=legend_elements, loc=loc, frameon=frameon, fontsize=fontsize)
    return ax


def parse_timespan_from_name(path):
    name = os.path.basename(path)
    match = re.match(r"(\d{12})-(\d{12})_", name)
    if not match:
        return None
    start = dt.datetime.strptime(match.group(1), "%Y%m%d%H%M")
    end = dt.datetime.strptime(match.group(2), "%Y%m%d%H%M")
    return start, end


def files_in_window(directory, pattern, hours=36):
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


def load_dataset(channel, hours=36, input_dir=None):
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


def load_glider_track(csv_path, lon_bounds=None, lat_bounds=None):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Glider track CSV not found: {csv_path}")

    track = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    track = np.atleast_1d(track)
    if track.size == 0:
        raise ValueError(f"Glider track CSV is empty: {csv_path}")

    times = np.array([np.datetime64(t, "ns") for t in track["time"]], dtype="datetime64[ns]")
    lons = np.asarray(track["longitude"], dtype=float)
    lats = np.asarray(track["latitude"], dtype=float)

    valid = np.isfinite(lons) & np.isfinite(lats)
    if lon_bounds is not None:
        lon_lo, lon_hi = sorted(lon_bounds)
        valid &= (lons >= lon_lo) & (lons <= lon_hi)
    if lat_bounds is not None:
        lat_lo, lat_hi = sorted(lat_bounds)
        valid &= (lats >= lat_lo) & (lats <= lat_hi)

    times = times[valid]
    lons = lons[valid]
    lats = lats[valid]
    if times.size == 0:
        raise ValueError("No valid glider points remain after filtering.")

    order = np.argsort(times)
    return {
        "time": times[order],
        "lon": lons[order],
        "lat": lats[order],
    }


def _extract_datetime64_from_dataarray(time_da):
    values = np.asarray(time_da.values)
    if np.issubdtype(values.dtype, np.datetime64):
        return values.astype("datetime64[ns]")

    units = str(time_da.attrs.get("units", "")).lower()
    match = re.match(r"^(seconds|minutes|hours|days) since (.+)$", units)
    if not match:
        raise ValueError(
            "Unsupported NetCDF time format. Expected datetime64 values or CF units like 'seconds since ...'."
        )

    unit_key = match.group(1)
    base_time = np.datetime64(match.group(2).strip(), "ns")
    values = np.asarray(values, dtype=float)
    if unit_key == "seconds":
        delta = (values * 1e9).astype("timedelta64[ns]")
    elif unit_key == "minutes":
        delta = (values * 60 * 1e9).astype("timedelta64[ns]")
    elif unit_key == "hours":
        delta = (values * 3600 * 1e9).astype("timedelta64[ns]")
    else:
        delta = (values * 86400 * 1e9).astype("timedelta64[ns]")
    return base_time + delta


def load_waveglider_track(nc_path, lon_bounds=None, lat_bounds=None):
    nc_path = Path(nc_path)
    if not nc_path.exists():
        raise FileNotFoundError(f"Wave glider NetCDF not found: {nc_path}")

    ds = xr.open_dataset(nc_path)
    time_name = "time" if "time" in ds.variables else None
    lon_name = "longitude" if "longitude" in ds.variables else ("lon" if "lon" in ds.variables else None)
    lat_name = "latitude" if "latitude" in ds.variables else ("lat" if "lat" in ds.variables else None)

    if time_name is None or lon_name is None or lat_name is None:
        raise KeyError(
            "Could not find required variables in wave glider NetCDF. "
            "Expected time + (longitude or lon) + (latitude or lat)."
        )

    times = _extract_datetime64_from_dataarray(ds[time_name])
    lons = np.asarray(ds[lon_name].values, dtype=float)
    lats = np.asarray(ds[lat_name].values, dtype=float)

    if lons.ndim > 1:
        lons = np.ravel(lons)
    if lats.ndim > 1:
        lats = np.ravel(lats)
    if times.ndim > 1:
        times = np.ravel(times)

    valid = np.isfinite(lons) & np.isfinite(lats)
    if lon_bounds is not None:
        lon_lo, lon_hi = sorted(lon_bounds)
        valid &= (lons >= lon_lo) & (lons <= lon_hi)
    if lat_bounds is not None:
        lat_lo, lat_hi = sorted(lat_bounds)
        valid &= (lats >= lat_lo) & (lats <= lat_hi)

    times = times[valid]
    lons = lons[valid]
    lats = lats[valid]
    if times.size == 0:
        raise ValueError("No valid wave glider points remain after filtering.")

    order = np.argsort(times)
    return {
        "time": times[order],
        "lon": lons[order],
        "lat": lats[order],
    }


def make_animation(
    ds,
    var,
    output_path,
    lon_bounds=(7.5, 23),
    lat_bounds=(-40, -32),
    cmap="magma",
    vmin=-4.5,
    vmax=-3.5,
    fps=10,
    interval=50,
    dpi=200,
    mask_var=None,
    title=None,
    cbar_label=None,
    data_offset=0.0,
    overlay_var=None,
    overlay_offset=0.0,
    overlay_threshold_max=None,
    overlay_cmap=None,
    overlay_vmin=None,
    overlay_vmax=None,
    glider_track=None,
    waveglider_track=None,
):
    ds_subset = ds.sel(lat=slice(lat_bounds[0], lat_bounds[1]), lon=slice(lon_bounds[0], lon_bounds[1]))

    if ds_subset.sizes.get("time", 0) == 0:
        raise ValueError("Subset contains no time steps.")

    if mask_var is not None and mask_var not in ds_subset:
        raise KeyError(f"'{mask_var}' is missing from dataset.")

    proj = ccrs.PlateCarree()
    fig = plt.figure(figsize=(16, 8), constrained_layout=True)
    ax = plt.axes(projection=proj)

    ax.set_extent([
        float(ds_subset.lon.min()),
        float(ds_subset.lon.max()),
        float(ds_subset.lat.min()),
        float(ds_subset.lat.max()),
    ], crs=ccrs.PlateCarree())

    fig.patch.set_facecolor("#f8f9fa")
    ax.set_facecolor("#f8f9fa")
    ax.coastlines(resolution="10m", linewidth=0.8, zorder=10)
    ax.add_feature(cfeature.LAND, facecolor="0.85", zorder=0)
    ax.add_feature(cfeature.RIVERS, edgecolor="white", linewidth=0.6, zorder=11)
    show_legend(
        ax,
        show_glider=glider_track is not None,
        show_waveglider=waveglider_track is not None,
        loc="lower left",
        fontsize=11,
    )
    
    gl = ax.gridlines(draw_labels=True, linewidth=0.75, color="gray", alpha=1, linestyle="--", zorder=15)
    gl.top_labels = False
    gl.right_labels = False

    data0 = ds_subset[var].isel(time=0) + data_offset
    mask0 = None
    if mask_var is not None:
        mask0 = ds_subset[mask_var].isel(time=0)
        data0 = data0.where(mask0 != 0)

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

    pcm_mask = None
    if mask0 is not None:
        mask_overlay0 = np.where(mask0.values == 0, 1.0, np.nan)
        pcm_mask = ax.pcolormesh(
            ds_subset.lon,
            ds_subset.lat,
            mask_overlay0,
            transform=ccrs.PlateCarree(),
            cmap=ListedColormap(["0.8"]),
            vmin=0.5,
            vmax=1.5,
            shading="auto",
            zorder=2,
            alpha=0.5,
        )

    pcm_overlay = None
    if overlay_var is not None:
        overlay0 = ds_subset[overlay_var].isel(time=0) + overlay_offset
        if mask0 is not None:
            overlay0 = overlay0.where((mask0 == 0) | np.isnan(mask0))
        if overlay_threshold_max is not None:
            overlay0 = overlay0.where(overlay0 <= overlay_threshold_max)
        pcm_overlay = ax.pcolormesh(
            ds_subset.lon,
            ds_subset.lat,
            overlay0,
            transform=ccrs.PlateCarree(),
            cmap=overlay_cmap,
            vmin=overlay_vmin,
            vmax=overlay_vmax,
            shading="auto",
            zorder=3,
        )

    cbar = plt.colorbar(pcm, ax=ax, pad=0.02, aspect=30)
    cbar.set_label(cbar_label or var)
    title_text = title or var
    title = ax.set_title(
        f"{title_text} {np.datetime_as_string(ds_subset.time.values[0], unit='m')}",
        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 2},
    )

    glider_line = None
    glider_latest = None
    glider_time = None
    glider_lon = None
    glider_lat = None
    if glider_track is not None:
        glider_time = np.asarray(glider_track["time"], dtype="datetime64[ns]")
        glider_lon = np.asarray(glider_track["lon"], dtype=float)
        glider_lat = np.asarray(glider_track["lat"], dtype=float)

        glider_line, = ax.plot(
            [],
            [],
            color="gold",
            linewidth=2.0,
            transform=ccrs.PlateCarree(),
            zorder=20,
        )
        glider_latest, = ax.plot(
            [],
            [],
            marker="o",
            markersize=7,
            markerfacecolor="gold",
            markeredgecolor="black",
            markeredgewidth=1.0,
            linestyle="None",
            transform=ccrs.PlateCarree(),
            zorder=21,
        )

    waveglider_line = None
    waveglider_latest = None
    waveglider_time = None
    waveglider_lon = None
    waveglider_lat = None
    if waveglider_track is not None:
        waveglider_time = np.asarray(waveglider_track["time"], dtype="datetime64[ns]")
        waveglider_lon = np.asarray(waveglider_track["lon"], dtype=float)
        waveglider_lat = np.asarray(waveglider_track["lat"], dtype=float)

        waveglider_line, = ax.plot(
            [],
            [],
            color="#B87333",
            linewidth=2.0,
            transform=ccrs.PlateCarree(),
            zorder=22,
        )
        waveglider_latest, = ax.plot(
            [],
            [],
            marker="s",
            markersize=7,
            markerfacecolor="#B87333",
            markeredgecolor="black",
            markeredgewidth=1.0,
            linestyle="None",
            transform=ccrs.PlateCarree(),
            zorder=23,
        )

    def update(frame):
        nonlocal pcm, pcm_mask, pcm_overlay
        data = ds_subset[var].isel(time=frame) + data_offset
        mask_frame = None
        if mask_var is not None:
            mask_frame = ds_subset[mask_var].isel(time=frame)
            data = data.where(mask_frame != 0)

        pcm.remove()
        new_pcm = ax.pcolormesh(
            ds_subset.lon,
            ds_subset.lat,
            data.values,
            transform=ccrs.PlateCarree(),
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            shading="auto",
        )
        pcm = new_pcm

        if pcm_mask is not None and mask_frame is not None:
            pcm_mask.remove()
            mask_overlay = np.where(mask_frame.values == 0, 1.0, np.nan)
            pcm_mask = ax.pcolormesh(
                ds_subset.lon,
                ds_subset.lat,
                mask_overlay,
                transform=ccrs.PlateCarree(),
                cmap=ListedColormap(["0.9"]),
                vmin=0.5,
                vmax=1.5,
                shading="auto",
                zorder=2,
                alpha=0.5,
            )

        if pcm_overlay is not None and overlay_var is not None:
            pcm_overlay.remove()
            overlay = ds_subset[overlay_var].isel(time=frame) + overlay_offset
            if mask_frame is not None:
                overlay = overlay.where((mask_frame == 0) | np.isnan(mask_frame))
            if overlay_threshold_max is not None:
                overlay = overlay.where(overlay <= overlay_threshold_max)
            pcm_overlay = ax.pcolormesh(
                ds_subset.lon,
                ds_subset.lat,
                overlay,
                transform=ccrs.PlateCarree(),
                cmap=overlay_cmap,
                vmin=overlay_vmin,
                vmax=overlay_vmax,
                shading="auto",
                zorder=3,
            )

        if glider_time is not None:
            frame_time = np.datetime64(ds_subset.time.values[frame], "ns")
            n_track = np.searchsorted(glider_time, frame_time, side="right")

            if n_track > 0:
                glider_line.set_data(glider_lon[:n_track], glider_lat[:n_track])
                glider_latest.set_data([glider_lon[n_track - 1]], [glider_lat[n_track - 1]])
            else:
                glider_line.set_data([], [])
                glider_latest.set_data([], [])

        if waveglider_time is not None:
            frame_time = np.datetime64(ds_subset.time.values[frame], "ns")
            n_track = np.searchsorted(waveglider_time, frame_time, side="right")

            if n_track > 0:
                waveglider_line.set_data(waveglider_lon[:n_track], waveglider_lat[:n_track])
                waveglider_latest.set_data([waveglider_lon[n_track - 1]], [waveglider_lat[n_track - 1]])
            else:
                waveglider_line.set_data([], [])
                waveglider_latest.set_data([], [])

        title.set_text(f"{title_text} {np.datetime_as_string(ds_subset.time.values[frame], unit='m')}")
        artists = [pcm, title]
        if pcm_mask is not None:
            artists.append(pcm_mask)
        if pcm_overlay is not None:
            artists.append(pcm_overlay)
        if glider_line is not None and glider_latest is not None:
            artists.extend([glider_line, glider_latest])
        if waveglider_line is not None and waveglider_latest is not None:
            artists.extend([waveglider_line, waveglider_latest])
        return tuple(artists)

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
    ani.save(
        output_path,
        writer="pillow",
        fps=fps,
        dpi=dpi,
        savefig_kwargs={"transparent": False, "facecolor": "#f8f9fa", "edgecolor": "none"},
    )
    plt.close(fig)
    print(f"Saved animation to {output_path}")


def build_default_output(outdir, suffix):
    return Path(outdir) / f"sst_goflow_latest_{suffix}.gif"


def build_output_path(output, outdir, suffix):
    if output:
        output_path = Path(output)
        if output_path.suffix:
            return output_path.with_name(f"{output_path.stem}_{suffix}{output_path.suffix}")
        return output_path.with_name(f"{output_path.name}_{suffix}.gif")
    return build_default_output(outdir, suffix)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a GIF animation from GOFLOW regional satellite data."
    )
    parser.add_argument("--channel", default="ir_105", help="IR channel, e.g. ir_105 or ir_123")
    parser.add_argument("--var", default="loggrad_T_masked", help="Variable to animate")
    parser.add_argument("--hours", type=int, default=36, help="Time window in hours")
    parser.add_argument("--lon-min", type=float, default=7.5)
    parser.add_argument("--lon-max", type=float, default=23)
    parser.add_argument("--lat-min", type=float, default=-42)
    parser.add_argument("--lat-max", type=float, default=-33)
    parser.add_argument("--cmap", default="magma")
    parser.add_argument("--vmin", type=float, default=-4.5)
    parser.add_argument("--vmax", type=float, default=-3.5)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--interval", type=int, default=50, help="Animation interval in ms")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--input-dir", default=None, help="Override input directory")
    parser.add_argument("--outdir", default="/home/mduplessis/share/www/html/img/", help="Output directory")
    parser.add_argument("--output", default=None, help="Full output GIF path")
    parser.add_argument(
        "--single-var",
        action="store_true",
        help="Use the legacy single-variable animation mode.",
    )
    parser.add_argument("--bt-var", default="BT", help="BT variable name")
    parser.add_argument("--loggrad-var", default="loggrad_T_masked", help="Log-gradient variable name")
    parser.add_argument("--bt-cmap", default="cmo.thermal", help="Colormap for BT panel")
    parser.add_argument("--bt-vmin", type=float, default=12.0, help="Color min for BT panel")
    parser.add_argument("--bt-vmax", type=float, default=17.0, help="Color max for BT panel")
    parser.add_argument("--loggrad-cmap", default="magma", help="Colormap for log-gradient panel")
    parser.add_argument("--loggrad-vmin", type=float, default=-4.5, help="Color min for log-gradient panel")
    parser.add_argument("--loggrad-vmax", type=float, default=-3.5, help="Color max for log-gradient panel")
    parser.add_argument(
        "--glider-track-csv",
        default="/home/mduplessis/share/www/data/sg267_WHIRLS_Mission3_2026/sg267_mission3_track.csv",
        help="CSV with columns: time, longitude, latitude.",
    )
    parser.add_argument(
        "--glider-track",
        dest="glider_track",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable plotting Seaglider track overlay.",
    )
    parser.add_argument(
        "--waveglider-track-nc",
        default="/home/mduplessis/share/gliders/waveglider/wg1169/wg1169_WHIRLS_Mission3_L1.nc",
        help="NetCDF with wave glider track (time/longitude/latitude).",
    )
    parser.add_argument(
        "--waveglider-track",
        dest="waveglider_track",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable/disable plotting Wave Glider track overlay.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    ds = load_dataset(args.channel, hours=args.hours, input_dir=args.input_dir)
    glider_track = None
    waveglider_track = None
    if args.glider_track:
        glider_track = load_glider_track(
            args.glider_track_csv,
            lon_bounds=(args.lon_min, args.lon_max),
            lat_bounds=(args.lat_min, args.lat_max),
        )
    if args.waveglider_track:
        waveglider_track = load_waveglider_track(
            args.waveglider_track_nc,
            lon_bounds=(args.lon_min, args.lon_max),
            lat_bounds=(args.lat_min, args.lat_max),
        )

    if not args.single_var:
        bt_output = build_output_path(args.output, args.outdir, "bt")
        loggrad_output = build_output_path(args.output, args.outdir, "loggrad_T_masked")
        make_animation(
            ds=ds,
            var=args.bt_var,
            output_path=bt_output,
            lon_bounds=(args.lon_min, args.lon_max),
            lat_bounds=(args.lat_min, args.lat_max),
            cmap=args.bt_cmap,
            vmin=args.bt_vmin,
            vmax=args.bt_vmax,
            fps=args.fps,
            interval=args.interval,
            dpi=args.dpi,
            mask_var="mask",
            # mask_var=None,
            title="Brightness Temperature ($^{{\\circ}}$C)",
            # cbar_label=f"{args.bt_var} $^{{\\circ}}$C",
            cbar_label=None,
            data_offset=-273.15,
            overlay_var=args.bt_var,
            overlay_offset=-273.15,
            overlay_threshold_max=15.0,
            overlay_cmap=cold_bt_overlay_cmap(),
            overlay_vmin=-60.0,
            overlay_vmax=15.0,
            glider_track=glider_track,
            waveglider_track=waveglider_track,
        )
        make_animation(
            ds=ds,
            var=args.loggrad_var,
            output_path=loggrad_output,
            lon_bounds=(args.lon_min, args.lon_max),
            lat_bounds=(args.lat_min, args.lat_max),
            cmap=args.loggrad_cmap,
            vmin=args.loggrad_vmin,
            vmax=args.loggrad_vmax,
            fps=args.fps,
            interval=args.interval,
            dpi=args.dpi,
            mask_var="mask",
            title="Brightness Temperature Gradient ($^{\\circ}$C/km, log scale)",
            # cbar_label=f"{args.loggrad_var} $^{{\\circ}}$C/km",
            cbar_label=None,
            overlay_var=args.bt_var,
            overlay_offset=-273.15,
            overlay_threshold_max=15.0,
            overlay_cmap=cold_bt_overlay_cmap(),
            overlay_vmin=-60.0,
            overlay_vmax=15.0,
            glider_track=glider_track,
            waveglider_track=waveglider_track,
        )
    else:
        output = args.output or build_default_output(args.outdir, args.var)
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
            glider_track=glider_track,
            waveglider_track=waveglider_track,
        )


if __name__ == "__main__":
    main()
