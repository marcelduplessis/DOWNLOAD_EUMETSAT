import datetime
from zoneinfo import ZoneInfo
PACIFIC = ZoneInfo("America/Los_Angeles")
import eumdac
import shutil
import time
import requests
import time
import os
from urllib3.exceptions import ProtocolError, IncompleteRead
import re
from params import consumer_key, consumer_secret, raw_data_dir 

def extract_first_datetime(filename):
    match = re.search(r"\d{14}", filename)
    return match.group(0) if match else filename

def check_local_file(target, expected_size):
    """
    Returns:
      - 'missing'
      - 'complete'
      - 'incomplete'
    """
    if not os.path.exists(target):
        return "missing"

    if expected_size <= 0:
        return "incomplete"  # can't verify → force re-download

    local_size = os.path.getsize(target)

    if local_size == expected_size:
        return "complete"
    else:
        return "incomplete"


def get_token():
    """Generate token, by default validity = 24h"""
    credentials = (consumer_key, consumer_secret)
    token = eumdac.AccessToken(credentials)
    try:
        print(f"This token '{token}' expires {token.expiration}")
    except requests.exceptions.HTTPError as error:
        print(f"Error when tryng the request to the server: '{error}'")
    return token

token = get_token()
token_expiration = token.expiration.replace(tzinfo=PACIFIC)

# Initialize DataStore and DataTailor instances
datastore = eumdac.DataStore(token)
datatailor = eumdac.DataTailor(token)

# Desired collection
# coll = 'EO:EUM:DAT:0662' # MTG FCI NR
coll = 'EO:EUM:DAT:0800' # MTG FCI CLM

# Display search options for the selected collection
try:
    selected_collection = datastore.get_collection(coll) 
    # print(f"{selected_collection} - {selected_collection.title}")
    # print(f"Description: {selected_collection.abstract}")
    # print(f"Metadata: {selected_collection.metadata}")
    # print(f"Search options: {selected_collection.search_options} \n")
except eumdac.datastore.DataStoreError as error:
    print(f"Error related to the data store: '{error}'")
except eumdac.collection.CollectionError as error:
    print(f"Error related to the collection: '{error}'")
except requests.exceptions.ConnectionError as error:
    print(f"Error related to the connection: '{error}'")
except requests.exceptions.RequestException as error:
    print(f"Unexpected error: {error}")

# Option 1 : Download all products resulting from a search
start = datetime.datetime(2025, 1, 1, 0, 0)
end = datetime.datetime(2026, 1, 1, 0, 0)
products = selected_collection.search(
    dtstart=start, dtend=end
    )

dirout = raw_data_dir
t0 = time.time()
MAX_RETRIES = 3

for product in products:

    # Open once to get filename + expected size
    with product.open() as fsrc:
        filename = os.path.basename(fsrc.name)
        expected_size = int(fsrc.headers.get("Content-Length", 0))
    
    dt = extract_first_datetime(filename)
    target = os.path.join(dirout, filename)
    status = check_local_file(target, expected_size)

    if status == "complete":
        print(f"Skipping already downloaded timestamp : {dt}")
        continue

    if status == "incomplete":
        print(f"Incomplete file for timestamp {dt}, re-downloading")
        if os.path.exists(target):
            os.remove(target)

    # refresh token if needed
    now_pt = datetime.datetime.now(PACIFIC)
    if now_pt + datetime.timedelta(minutes=10) > token_expiration:
        print("refreshing token")
        token = get_token()
        token_expiration = token.expiration.replace(tzinfo=PACIFIC)
        datastore = eumdac.DataStore(token)
        datatailor = eumdac.DataTailor(token)

    # retry loop
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            tmp_target = target + ".part"

            with product.open() as fsrc:
                with open(tmp_target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)

            os.replace(tmp_target, target)
            print(f"Download of timestamp {dt} finished.")
            break

        except (ProtocolError, IncompleteRead) as error:
            print(f"Attempt {attempt}/{MAX_RETRIES} failed for {filename}: {error}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
            else:
                print("Giving up on this product")

        except eumdac.product.ProductError as error:
            print(f"Product error for {filename}: {error.msg}")
            break

        except requests.exceptions.ConnectionError as error:
            print(f"Connection error on attempt {attempt}: {error}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
            else:
                print("Giving up on this product.")

        except requests.exceptions.RequestException as error:
            print(f"Request error for {filename}: {error}")
            break

        except Exception as error:
            print(f"Fatal unexpected error for {filename}: {error}")
            break
   
print(f'All downloads are finished. Time elapsed : {(time.time()-t0)/60:.1f} min')

