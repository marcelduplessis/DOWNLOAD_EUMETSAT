import numpy as np
import xarray as xr
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.ticker import MultipleLocator
import cartopy.crs as ccrs
from params import base_dir, processed_data_dir_rrad_nr, processed_data_dir_clm
import os
from datetime import datetime

# -----------------------------
# HELPER FUNCTION
# -----------------------------
def format_gl(ax):
    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=True,
        linewidth=0.6,
        color="gray",
        alpha=0.6,
        linestyle="--",
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xlocator = MultipleLocator(5.0)
    gl.ylocator = MultipleLocator(5.0)
    gl.xlabel_style = {"size": 10}
    gl.ylabel_style = {"size": 10}


# -----------------------------
# PATH SETUP
# -----------------------------
BASE_DIR = base_dir  # GOFLOW_LR root
dirin_rrad = processed_data_dir_rrad_nr
dirin_clm = processed_data_dir_clm

dirout = os.path.join(BASE_DIR, "plots")
os.makedirs(dirout, exist_ok=True)

# -----------------------------
# TIME RANGE
# -----------------------------
start, end = "202501250000", "202501270000"
start_dt = datetime.strptime(start, "%Y%m%d%H%M")
end_dt   = datetime.strptime(end, "%Y%m%d%H%M")

# dates = pd.date_range(
#     start=pd.to_datetime(start, format="%Y%m%d%H%M"),
#     end=pd.to_datetime(end, format="%Y%m%d%H%M"),
#     freq="10min",
#     inclusive="left",
# )

# dates_str = dates.strftime("%Y%m%d%H%M").tolist()

# -----------------------------
# CHANNEL SELECTION
# channels in 1C-RRAD are:
#   ['ir_105','ir_123','ir_133','ir_38','ir_87','ir_97',
#    'nir_13','nir_16','nir_22',
#    'vis_04','vis_05','vis_06','vis_08','vis_09',
#    'wv_63', 'wv_73']
# channels in 2-CLM are:
#   ['cloud_mask']
# -----------------------------
product = "1C-RRAD_nc"
channel = "ir_105"

# -----------------------------
# Helper to list files within start-end
# -----------------------------
def list_files_in_range(dir_path, suffix):
    files_in_range = []
    for fname in os.listdir(dir_path):
        if not fname.endswith(suffix):
            continue
        ts_str = fname.split("_")[0]  # YYYYMMDDhhmm
        try:
            ts = datetime.strptime(ts_str, "%Y%m%d%H%M")
        except ValueError:
            continue
        if start_dt <= ts < end_dt:
            files_in_range.append(os.path.join(dir_path, fname))
    return sorted(files_in_range)

# -----------------------------
# Open RRAD and CLM files between start and end
# -----------------------------
files_rrad = list_files_in_range(dirin_rrad, suffix="_FCI-1C-RRAD.nc")
files_clm  = list_files_in_range(dirin_clm, suffix="_FCI-2-CLM.nc")

da_rrad = xr.open_mfdataset(
    files_rrad, 
    combine="by_coords"
    )[channel]
da_clm  = xr.open_mfdataset(
    files_clm,  
    combine="by_coords"
    )["cloud_mask"]

# Add this temporarily after the open_mfdataset calls to inspect dims
ds_test = xr.open_dataset(files_rrad[0])
print(ds_test)

print(f"Before intersection, RRAD time steps: {len(da_rrad.time)}, CLM time steps: {len(da_clm.time)}")

# -----------------------------
# Keep only common time coordinates
# -----------------------------
common_times = da_rrad["time"].to_index().intersection(da_clm["time"].to_index())
da_rrad = da_rrad.sel(time=common_times)
da_clm  = da_clm.sel(time=common_times)

print(f"After intersection, RRAD time steps: {len(da_rrad.time)}, CLM time steps: {len(da_clm.time)}")

dates = da_rrad.time.values
lon_min, lon_max = da_rrad.x.min().item(), da_rrad.x.max().item()
lat_min, lat_max = da_rrad.y.min().item(), da_rrad.y.max().item()

# -----------------------------
# PLOT SETUP
# -----------------------------
da0 = da_rrad.isel(time=0)
cld = da_clm.isel(time=0)

# da_clear=da0
da_clear = xr.where(cld == 0, da0, np.nan)

extent = [lon_min, lon_max, lat_min, lat_max]

fig, ax = plt.subplots(
    figsize=(8, 8),
    subplot_kw={"projection": ccrs.PlateCarree()},
)

format_gl(ax)

im = ax.imshow(
    da_clear,
    extent=extent,
    origin="upper",
    cmap="gray",
    vmin=275,
    vmax=295,
    transform=ccrs.PlateCarree(),
)

ax.coastlines()
ax.set_extent(extent, crs=ccrs.PlateCarree())

cb = plt.colorbar(im, ax=ax, orientation="vertical", shrink=0.8)
cb.set_label(f"{channel} brightness temperature [K]")

# -----------------------------
# ANIMATION FUNCTION
# -----------------------------
def update(frame):
    # da_clear= da_rrad.isel(time=frame)
    da_clear = xr.where(
        da_clm.isel(time=frame) == 0,
        da_rrad.isel(time=frame),
        np.nan,
    )
    im.set_array(da_clear)
    ax.set_title(pd.to_datetime(dates[frame]).strftime("%Y-%m-%d %H:%M"))
    return im


ani = FuncAnimation(
    fig,
    update,
    frames=len(dates),
    blit=False,
)

# -----------------------------
# SAVE MOVIE
# -----------------------------
outfile =os.path.join(dirout, f"{start}_{end}_{channel}.mp4")

ani.save(
    outfile,
    writer="ffmpeg",
    fps=6,
    bitrate=4000,
)

print(f"Saved animation: {outfile}")
