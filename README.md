# MTG FCI Download and Processing Pipeline

Marcel du Plessis (University of Gothenburg), adapted from work by Lucie Reymondet (Scripps Institution of Oceanography, UCSD).

This repository downloads, reprojects, and visualizes MTG FCI full-disk products (radiances and cloud mask) over a user-defined region.

## Repository Structure

<!-- structure:start -->
```text
DOWNLOAD_EUMETSAT/
|- .gitignore
|- README.md
|- data/
|  |- .gitkeep
|- env/
|  |- satpy_env.yml
|- figures/
|  |- .gitkeep
|  |- ir_105_snapshot.png
|  |- ir_105_snapshot_animation.gif
|  |- time_deltas_clm.png
|  |- time_deltas_rrad_hr.png
|  |- time_deltas_rrad_nr.png
|- logs/
|  |- goflow_sst.log
|- notebooks/
|  |- .gitkeep
|- scripts/
|  |- 00_download_eumdac_CLM.py
|  |- 00_download_eumdac_RRAD_HR.py
|  |- 01_check_raw_products_time_deltas.py
|  |- 02_build_land_mask.py
|  |- 031_regrid_RRAD_CLM_to_timeseries.py
|  |- 032_process_timeseries_for_goflow.py
|  |- 04_goflow_regional_animation.py
|  |- figures/
|  |- land_mask_10E-35E_45S-30S_0p02deg.nc
|  |- land_mask_5E-25E_44S-33S_0p02deg.nc
|  |- params.py
|  |- params_template.py
|  |- plot_utils.py
|  |- run_goflow_sst.sh
|  |- update_readme_structure.sh
```
<!-- structure:end -->

To refresh this block after file changes:

```bash
./scripts/update_readme_structure.sh
```

### What Goes Where

- `scripts/`: all executable processing steps and shared utilities.
- `env/`: reproducible Python/Conda environment spec.
- `data/`: recommended location for downloaded and intermediate datasets.
- `figures/`: final or shared diagnostic figures.
- `logs/`: run logs and troubleshooting output.
- `notebooks/`: optional exploratory notebook work.

## Setup

1. Create and activate the Conda environment:

```bash
conda env create -f env/satpy_env.yml
conda activate satpy_env
```

2. Create local configuration inside `scripts/`:

```bash
cp scripts/params_template.py scripts/params.py
```

3. Edit `scripts/params.py` and set:

- `consumer_key` and `consumer_secret` from your EUMETSAT API credentials.
- local paths for raw, regridded, and processed outputs.
- region/time settings as needed for your workflow.

## Processing Pipeline

Run scripts in order:

| Step | Script | Purpose |
|---|---|---|
| 0 | `scripts/00_download_eumdac_CLM.py` | Download CLM zip products for a target period. |
| 0 | `scripts/00_download_eumdac_RRAD_HR.py` | Download RRAD zip products for a target period. |
| 1 | `scripts/01_check_raw_products_time_deltas.py` | Diagnose temporal gaps/duplicates in raw files. |
| 2 | `scripts/02_build_land_mask.py` | Build regional land mask (typically once per domain). |
| 3 | `scripts/031_regrid_RRAD_CLM_to_timeseries.py` | Regrid and concatenate regional RRAD/CLM time series. |
| 4 | `scripts/032_process_timeseries_for_goflow.py` | Derive BT/log-gradient/masks into final analysis files. |
| 5 | `scripts/04_goflow_regional_animation.py` | Build GOFLOW-ready GIF animations (BT and log-gradient), with optional glider-track overlays. |

## Supported EUMETSAT Collections

| Collection ID | Product | Main Variable |
|---|---|---|
| `EO:EUM:DAT:0662` | FCI L1C RRAD FDHSI (normal resolution) | Brightness temperature / reflectance |
| `EO:EUM:DAT:0665` | FCI L1C RRAD HRFI (high resolution) | Brightness temperature / reflectance |
| `EO:EUM:DAT:0800` | FCI L2 CLM (cloud mask, GRIB2) | Cloud mask classes |

## Notes

- RRAD products are decoded with Satpy's FCI reader workflow.
- CLM products use GRIB2 `grid_second_order` packing; cloud classes are reconstructed in processing.
- Land pixels are masked in final products using a precomputed land mask.
- Data volume can become large quickly (10-minute cadence, full-disk products), so plan storage accordingly.
- MTG user guides: https://user.eumetsat.int/data/satellites/meteosat-third-generation/resources
- EUMETView explorer: https://view.eumetsat.int/productviewer?v=default
