import datetime
from zoneinfo import ZoneInfo
PACIFIC = ZoneInfo("America/Los_Angeles")
print(datetime.datetime.now(PACIFIC))