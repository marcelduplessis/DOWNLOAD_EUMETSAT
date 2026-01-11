from pathlib import Path
import re
from datetime import datetime
import matplotlib.pyplot as plt

# -----------------------------
# PATH SETUP (cross-platform)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parents[1]  # GOFLOW_LR root
data_dir = BASE_DIR / "data" / "raw"

# -----------------------------
# UTILITY FUNCTION
# -----------------------------
def extract_start_time(filename: str) -> datetime:
    """
    Extract the start datetime from an MTG FCI filename.
    """
    match = re.search(r"OPE_(\d{14})_\d{14}", filename)
    if not match:
        raise ValueError(f"Could not parse start time from {filename}")
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")


# -----------------------------
# COLLECT FILES & TIMES
# -----------------------------
files_with_time = []

for f in data_dir.iterdir():
    if f.is_file():
        try:
            start_time = extract_start_time(f.name)
            files_with_time.append((start_time, f))
        except ValueError:
            pass  # skip files that don't match the pattern

# Sort by time
files_with_time.sort(key=lambda x: x[0])

start_times = [t for t, _ in files_with_time]

time_deltas_minutes = [
    (start_times[i + 1] - start_times[i]).total_seconds() / 60
    for i in range(len(start_times) - 1)
]

# -----------------------------
# PLOT
# -----------------------------
plt.figure(figsize=(10, 4))
plt.plot(time_deltas_minutes, marker="o", linestyle="-")

plt.axhline(10, color="red", linestyle="--", label="10 minutes")
plt.axhline(7 / 60, color="green", linestyle="--", label="7 seconds")

plt.xlabel("File index")
plt.ylabel("Δt between consecutive files [minutes]")
plt.title("Time difference between consecutive MTG FCI files")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()
