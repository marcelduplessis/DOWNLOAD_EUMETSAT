import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import re
import shutil
import time
import requests
from urllib3.exceptions import ProtocolError, IncompleteRead

import eumdac
from params import consumer_key, consumer_secret,\
    raw_data_dir_rrad_nr, raw_data_dir_rrad_hr, raw_data_dir_clm

# -----------------------------
# TIME ZONE
# -----------------------------
PACIFIC = ZoneInfo("America/Los_Angeles")

# -----------------------------
# PATHS
# -----------------------------
RAW_DIR_RRAD_NR = Path(raw_data_dir_rrad_nr).expanduser().resolve()
RAW_DIR_RRAD_HR = Path(raw_data_dir_rrad_hr).expanduser().resolve()
RAW_DIR_CLM  = Path(raw_data_dir_clm).expanduser().resolve()

RAW_DIR_RRAD_NR.mkdir(parents=True, exist_ok=True)
RAW_DIR_RRAD_HR.mkdir(parents=True, exist_ok=True)
RAW_DIR_CLM.mkdir(parents=True, exist_ok=True)

# -----------------------------
# HELPERS
# -----------------------------
def extract_first_datetime(filename: str) -> str:
    match = re.search(r"\d{14}", filename)
    return match.group(0) if match else filename


def check_local_file(target: Path, expected_size: int) -> str:
    """
    Returns:
      - 'missing'
      - 'complete'
      - 'incomplete'
    """
    if not target.exists():
        return "missing"

    if expected_size <= 0:
        return "incomplete"  # can't verify → force re-download

    if target.stat().st_size == expected_size:
        return "complete"
    else:
        return "incomplete"


def get_token():
    """Generate token (valid ~24h)."""
    credentials = (consumer_key, consumer_secret)
    token = eumdac.AccessToken(credentials)
    try:
        print(f"This token '{token}' expires {token.expiration}")
    except requests.exceptions.HTTPError as error:
        print(f"Error requesting token: {error}")
    return token


# -----------------------------
# AUTH
# -----------------------------
token = get_token()
token_expiration = token.expiration.replace(tzinfo=PACIFIC)

datastore = eumdac.DataStore(token)
datatailor = eumdac.DataTailor(token)

# -----------------------------
# COLLECTION : UNCOMMENT DESIRED COLLECTION
# -----------------------------
# coll = 'EO:EUM:DAT:0662'    # MTG FCI NR
coll = "EO:EUM:DAT:0665"    # MTG FCI HR
# coll = 'EO:EUM:DAT:0800'    # MTG FCI CLM, cloud_mask, grib 
# coll = 'EO:EUM:DAT:0678'    # MTG FCI CLS, cloud_state, netcdf, pipeline not coded yet

if coll == 'EO:EUM:DAT:0662':
    RAW_DIR = RAW_DIR_RRAD_NR
elif coll == 'EO:EUM:DAT:0800':
    RAW_DIR = RAW_DIR_CLM
elif coll == "EO:EUM:DAT:0665":
    RAW_DIR = RAW_DIR_RRAD_HR
else:
    raise ValueError("Invalid collection name")

try:
    selected_collection = datastore.get_collection(coll)
except Exception as error:
    raise RuntimeError(f"Failed to load collection {coll}: {error}")

# -----------------------------
# SEARCH: SET DESIRED TIME SPAN
# -----------------------------
start = datetime.datetime(2026, 1, 1, 0, 0)
end   = datetime.datetime(2026, 3, 20, 18, 13) # when stoped, resume from the last downloaded file before server error

products = selected_collection.search(dtstart=start, dtend=end)

# -----------------------------
# DOWNLOAD LOOP
# -----------------------------
t0 = time.time()
MAX_RETRIES = 3

for product in products:

    # Get filename, expected size, and download status
    with product.open() as fsrc:
        filename = Path(fsrc.name).name
        expected_size = int(fsrc.headers.get("Content-Length", 0))

    dt = extract_first_datetime(filename)
    target = RAW_DIR / filename
    status = check_local_file(target, expected_size)

    if status == "complete":
        print(f"Skipping already downloaded timestamp: {dt}")
        continue

    if status == "incomplete":
        print(f"Incomplete file for timestamp {dt}, re-downloading")
        target.unlink(missing_ok=True)

    # Refresh token if needed
    now_pt = datetime.datetime.now(PACIFIC)
    if now_pt + datetime.timedelta(minutes=10) > token_expiration:
        print("Refreshing token")
        token = get_token()
        token_expiration = token.expiration.replace(tzinfo=PACIFIC)
        datastore = eumdac.DataStore(token)
        datatailor = eumdac.DataTailor(token)

    # Retry loop
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tmp_target = target.with_suffix(target.suffix + ".part")

            with product.open() as fsrc, open(tmp_target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)

            tmp_target.replace(target)
            print(f"Download of timestamp {dt} finished.")
            break

        except (ProtocolError, IncompleteRead) as error:
            print(f"Attempt {attempt}/{MAX_RETRIES} failed for {filename}: {error}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
            else:
                print("Giving up on this product")

        except eumdac.product.ProductError as error:
            print(f"Product error for {filename}: {error}")
            break

        except requests.exceptions.ConnectionError as error:
            print(f"Connection error on attempt {attempt}: {error}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
            else:
                print("Giving up on this product")

        except requests.exceptions.RequestException as error:
            print(f"Request error for {filename}: {error}")
            break

        except Exception as error:
            print(f"Fatal unexpected error for {filename}: {error}")
            break

print(f"All downloads finished. Time elapsed: {(time.time() - t0) / 60:.1f} min")
