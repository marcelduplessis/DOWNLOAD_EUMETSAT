import numpy as np
import xarray as xr
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.ticker import MultipleLocator
import cartopy.crs as ccrs
import cartopy.mpl.ticker as cticker

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
# PATHS (cross-platform)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parents[1]  # GOFLOW_LR root

dirin = BASE_DIR / "data" / "processed"
dirout = BASE_DIR / "plots"
dirout.mkdir(parents=True, exist_ok=True)

# -----------------------------
# TIME RANGE
# -----------------------------
start, end = "202501250000", "202501250100"

dates = pd.date_range(
    start=pd.to_datetime(start, format="%Y%m%d%H%M"),
    end=pd.to_datetime(end, format="%Y%m%d%H%M"),
    freq="10min",
    inclusive="left",
)

dates_str = dates.strftime("%Y%m%d%H%M").tolist()

# -----------------------------
# DATA SELECTION
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

files = [
    fname
    for d in dates_str
    for fname in (dirin / product).glob(f"{d}*.nc")
]
print(files)
ds = xr.open_mfdataset(
    [str(f) for f in files],
    combine="nested",
    concat_dim="time",
)[channel]

ds = ds.assign_coords(time=("time", dates))

files_clm = [
    fname
    for d in dates_str
    for fname in (dirin / "2-CLM_nc").glob(f"{d}*.nc")
]

ds_clm = xr.open_mfdataset(
    [str(f) for f in files_clm],
    combine="nested",
    concat_dim="time",
)["cloud_mask"]

ds_clm = ds_clm.assign_coords(time=("time", dates))

lon_min, lon_max = ds.x.min().item(), ds.x.max().item()
lat_min, lat_max = ds.y.min().item(), ds.y.max().item()

# -----------------------------
# PLOT SETUP
# -----------------------------
da0 = ds.isel(time=0)
cld = ds_clm.isel(time=0)

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
    da_clear = xr.where(
        ds_clm.isel(time=frame) == 0,
        ds.isel(time=frame),
        np.nan,
    )
    im.set_array(da_clear)
    ax.set_title(dates[frame].strftime("%Y-%m-%d %H:%M"))
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
outfile = dirout / f"{start}_{end}_{channel}.mp4"

ani.save(
    outfile,
    writer="ffmpeg",
    fps=6,
    bitrate=10000,
)

print(f"Saved animation: {outfile}")
