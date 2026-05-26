import cmocean.cm as cmo
from matplotlib.ticker import MultipleLocator
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from matplotlib.patches import Rectangle
import cartopy.crs as ccrs

parameters = {
    # Axis label 
    'axes.labelsize': 5,
    'axes.labelpad': 2,

    # Tick label 
    'xtick.labelsize': 4,
    'ytick.labelsize': 4,

    # Tick 
    'xtick.major.size': 1,
    'ytick.major.size': 1,
    'xtick.minor.size': 0.5,
    'ytick.minor.size': 0.5,
    'xtick.major.width': 0.5,
    'ytick.major.width': 0.5,
    'xtick.minor.width': 0.3,
    'ytick.minor.width': 0.3,
    'xtick.major.pad': 1,
    'ytick.major.pad': 1,

    # Gridlines
    'grid.linewidth': 0.3,
    'grid.color': '0.7',
    'grid.linestyle': '-',

    # Miscellaneous
    'text.usetex': False,
    'figure.dpi': 300,
    'savefig.dpi': 300
}

def plt_args(VAR):
    """Return vmin, vmax, extend, units, title, cmap, scale, gridline_color"""
    args = {
        "BT":               [2, 22, 'both', r'$^{\circ}$C', 'BT',              cmo.thermal, 1, 'white'],
        "loggrad_T":        [-6,-3, 'both', '1',          r'log($\nabla$BT)',"viridis",    1, 'white'],
        "loggrad_T_masked": [-6,-3, 'both', '1',          r'log($\nabla$BT)',"viridis",    1, 'white'],
        "V":                [-1,1,  'both', r'm s$^{-1}$',  'V$_{10m}$',        cmo.balance, 1, 'darkgrey'],
        "U":                [-1,1,  'both', r'm s$^{-1}$',  'U$_{10m}$',        cmo.balance, 1, 'darkgrey'],
        "Eta":              [-2,2,  'both', r'm',           r'$\eta$',          cmo.balance, 1, 'darkgrey'],
        "vort":             [-1,1,  'both', r'1',           r'$\zeta$/f',       cmo.balance, 1, 'k'],
        "div":              [-1,1,  'both', r'1',           r'$\delta$/f',      cmo.balance, 1, 'k'],
    }
    if VAR not in args:
        raise ValueError("Invalid variable")
    return args[VAR]


def format_axes(axis, r, c):
    """Format axes, labels, gridlines, title..."""
    gl = axis.gridlines(crs=ccrs.PlateCarree(),
                    draw_labels=True,
                    linewidth=0.8, color='gray',
                    alpha=0.5, linestyle='--')
    gl.xformatter = LongitudeFormatter()
    gl.yformatter = LatitudeFormatter()
    gl.xlocator = MultipleLocator(5)
    gl.ylocator = MultipleLocator(5)
    gl.xpadding = 1
    gl.ypadding = 2
    gl.xlabel_style = {'size': 3}
    gl.ylabel_style = {'size': 3}
    gl.top_labels,gl.bottom_labels = True, True 

def add_box(ax, inds, lon, lat, color, label=None, lw=0.5):
    """inds = (y0, y1, x0, x1)"""
    y0, y1, x0, x1 = inds
    lon0, lon1 = lon[x0], lon[x1 - 1]
    lat0, lat1 = lat[y0], lat[y1 - 1]
    rect = Rectangle(
        (lon0, lat0), lon1 - lon0, lat1 - lat0,
        linewidth=lw, edgecolor=color, facecolor='none',
        linestyle='-', transform=ccrs.PlateCarree(),
        label=label, zorder=10
    )
    ax.add_patch(rect)