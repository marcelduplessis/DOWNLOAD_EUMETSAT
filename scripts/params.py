"""
params_template.py
──────────────────
Copy this file to params.py and fill in your own values.
params.py is gitignored — never commit credentials or local paths.

    cp params_template.py params.py
"""
from pathlib import Path

# ── EUMETSAT API credentials ──────────────────────────────────────────────────
# Obtain from https://api.eumetsat.int/api-key/
consumer_key    = "_cMS2mlBfwrKSCFqLN9M7i5DB_Ua"
consumer_secret = "86Wz26QfQYb5ugSFJzAKwx_Ksd4a"

# ── Project root (do not change) ─────────────────────────────────────────────
base_dir = Path(__file__).resolve().parent

# ── Data storage root ─────────────────────────────────────────────────────────
# Set this to wherever you want raw and processed data stored.
# Can be outside the repo (e.g. an external drive).
DATA_DIR = Path("/home/mduplessis/share/EUMETSAT/")

# ── Raw data directories ──────────────────────────────────────────────────────
raw_data_dir_clm     = DATA_DIR / "raw_CLM"
raw_data_dir_rrad_nr = DATA_DIR / "raw_RRAD_NR"
raw_data_dir_rrad_hr = DATA_DIR / "raw_RRAD_HR"

# ── Processed data directories ────────────────────────────────────────────────
processed_data_dir_rrad_nr = DATA_DIR / "processed_RRAD_NR"
processed_data_dir_rrad_hr = DATA_DIR / "processed_RRAD_HR"
processed_data_dir_clm     = DATA_DIR / "processed_CLM"

processed_goflow_inputs    = DATA_DIR / "processed_goflow_inputs"

# ── Regridded data directories ────────────────────────────────────────────────
regridded_data_dir_rrad_nr = DATA_DIR / "regridded_RRAD_NR"
regridded_data_dir_rrad_hr = DATA_DIR / "regridded_RRAD_HR"
regridded_data_dir_clm     = DATA_DIR / "regridded_CLM"

# ── Domain of interest ────────────────────────────────────────────────────────
lon_min, lon_max =  10.0,  35.0
lat_min, lat_max = -45.0, -30.0
resolution       =   0.02          # degrees
