# MTG FCI Download & Processing Pipeline
*Lucie Reymondet — Scripps Institution of Oceanography, UCSD*

Downloads, reprojects, and visualises MTG FCI full-disk products (radiances and cloud mask) from EUMETSAT over a user-defined region of interest.

---

## Repository structure

```
├── scripts/
│   ├── 00_download_eumdac.py               # Download raw zips from EUMETSAT
│   ├── 01_check_raw_products_time_deltas.py# Diagnose temporal gaps in raw data
│   ├── 02_build_land_mask.py               # Build land mask (run once per domain)
│   ├── 031_regrid_RRAD_CLM_to_timeseries.py# Regrid raw zips → per-channel NetCDF time series
│   ├── 032_process_timeseries_for_goflow.py# Compute BT, loggrad, cloud mask → final NetCDF
│   ├── 041_plot_fci.py                     # Static snapshot figure
│   ├── 042_animate_fci.py                  # MP4 animation
│   ├── plot_utils.py                       # Shared matplotlib rcParams
│   ├── params.py                           # Local config — NOT tracked (see below)
│   └── params_template.py                  # Template to create your params.py
├── env/
│   └── satpy-env.yml                       # Conda environment
├── figures/                                # Output figures (NOT tracked)
└── README.md
```

---

## Setup

### 1. Conda environment
```bash
conda env create -f env/satpy-env.yml
conda activate satpy-env
```

### 2. Local configuration
`params.py` is intentionally **not tracked** (it contains your EUMETSAT credentials and local data paths). Copy the template and fill it in:
```bash
cp params_template.py params.py
```
Edit `params.py` to set:
- `consumer_key` / `consumer_secret` — from your [EUMETSAT API credentials](https://api.eumetsat.int/api-key/)
- data directories (`raw_*`, `regridded_*`, `processed_*`) — wherever you want data stored on your machine

---

## Pipeline

Run scripts in order:

| Step | Script | Description |
|------|--------|-------------|
| 0 | `00_download_eumdac.py` | Download raw `.zip` files from EUMETSAT for a chosen collection and time window. |
| 1 | `01_check_raw_products_time_deltas.py` | Plot Δt between consecutive files to detect gaps or duplicates (sanity check). |
| 2 | `02_build_land_mask.py` | Build and save a land mask for the domain — **run once**, or when changing domain |
| 3 | `031_regrid_RRAD_CLM_to_timeseries.py` | Unzip, crop, resample, and concatenate raw products into regional NetCDF time series |
| 4 | `032_process_timeseries_for_goflow.py` | Combine radiance and CLM time series into a single file with BT, loggrad_T, mask, loggrad_T_masked |
| 5 | `041_plot_fci.py` / `042_animate_fci.py` | Static snapshot or MP4 animation of the processed variables |

---

## Supported collections

| EUMETSAT collection ID | Product | Variable |
|------------------------|---------|----------|
| `EO:EUM:DAT:0662` | FCI L1C RRAD FDHSI (normal resolution, 16 channels) | Brightness temperature / reflectance |
| `EO:EUM:DAT:0665` | FCI L1C RRAD HRFI (high resolution, 4 channels) | Brightness temperature / reflectance |
| `EO:EUM:DAT:0800` | FCI L2 CLM (cloud mask, GRIB2) | Cloud mask (0=clear water, 1=clear land, 2=cloud, 3=no data) |

---

## Output file naming

| File | Description |
|------|-------------|
| `land_mask_<area>_0p02deg.nc` | Boolean land mask on the 0.02° grid |
| `<t0>-<t1>_FCI-1C-RRAD_<resolution>>deg.nc` | Regridded radiance time series |
| `<t0>-<t1>_FCI-2-CLM_<resolution>deg.nc` | Regridded cloud mask time series |
| `<t0>-<t1>_FCI-<channel>_<resolution>deg.nc` | Final dataset: BT, loggrad_T, mask, loggrad_T_masked |

Timestamps follow `YYYYMMDDhhmm` format. Area labels follow `<lon0>-<lon1>_<lat0>-<lat1>` convention.

---

## Notes
- The RRAD `.nc` files use fci_l1c_nc reader to decode.
- The CLM `.bin` files use GRIB2 `grid_second_order` packing that eccodes cannot reconstruct natively. The pipeline decodes the raw residuals directly via `clm = raw % 4`.
- Land pixels are set to `NaN` in all output files using a Natural Earth 1:50m land mask.
- 1 full disk time step of normal resolution level 1C radiances (1 `.zip` file) can be anywhere between 2MB and 1GB and they are produced every 10min, so this can become quite large and downloading can take a while.
- Resources about MTG products can be found in the user guides at https://user.eumetsat.int/data/satellites/meteosat-third-generation/resources
- EUMETVIEW (https://view.eumetsat.int/productviewer?v=default) can be useful to scan which time span is of interest.
