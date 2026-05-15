from zipfile import ZipFile
import re
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1] #DOWNLOAD_EUMETSAT directory

dirin = BASE_DIR / "data" / "raw"
dirout_fci = BASE_DIR / "data" / "unzipped" / "1C-RRAD"
dirout_clm = BASE_DIR / "data" / "unzipped" / "2-CLM"

dirout_fci.mkdir(parents=True, exist_ok=True)
dirout_clm.mkdir(parents=True, exist_ok=True)

fci_file = "W_XX-EUMETSAT-Darmstadt,IMG+SAT,MTI1+FCI-1C-RRAD-FDHSI-FD--x-x---x_C_EUMT_20250202001320_IDPFI_OPE_20250202001007_20250202001928_N__O_0002_0000.zip"
clm_file = "W_XX-EUMETSAT-Darmstadt,IMG+SAT,MTI1+FCI-2-CLM--FD------GRIB2_C_EUMT_20250202002519_L2PF_OPE_20250202001000_20250202002000_N__C_0002_0000.zip"

match = re.search(r'OPE_(\d{14})_',fci_file)
if match:
    timestamp = match.group(1)
    print(timestamp)
else:
    print(RuntimeError(f"No valid time step in {fci_file}"))

with ZipFile(dirin / fci_file, "r") as z:
    z.extractall(dirout_fci)

with ZipFile(dirin / clm_file, "r") as z:
    z.extractall(dirout_clm)
