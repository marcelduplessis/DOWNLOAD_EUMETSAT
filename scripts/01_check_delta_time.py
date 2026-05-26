from pathlib import Path
import re
import os
from datetime import datetime
import matplotlib.pyplot as plt
from params import raw_data_dir_rrad_nr, raw_data_dir_rrad_hr, raw_data_dir_clm

# -----------------------------
# PATH SETUP
# -----------------------------
RAW_DIRS = {
    "RRAD_NR": Path(raw_data_dir_rrad_nr).expanduser().resolve(),
    "RRAD_HR": Path(raw_data_dir_rrad_hr).expanduser().resolve(),
    "CLM": Path(raw_data_dir_clm).expanduser().resolve()
}

BASE_DIR = Path(__file__).resolve().parents[1]  # GOFLOW_LR root
dirout = os.path.join(BASE_DIR, "figures")
dirout.mkdir(parents=True, exist_ok=True)

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


def plot_time_deltas(raw_dir: Path, label: str):
    """
    Collect files from a directory, compute Δt between consecutive files,
    and save a plot.
    """
    # Collect files & times
    files_with_time = []
    for f in raw_dir.iterdir():
        if f.is_file():
            try:
                start_time = extract_start_time(f.name)
                files_with_time.append((start_time, f))
            except ValueError:
                pass  # skip files that don't match the pattern

    if not files_with_time:
        print(f"No valid files found in {raw_dir}")
        return

    files_with_time.sort(key=lambda x: x[0])
    start_times = [t for t, _ in files_with_time]

    time_deltas_minutes = [
        (start_times[i + 1] - start_times[i]).total_seconds() / 60
        for i in range(len(start_times) - 1)
    ]

    # Plot
    plt.figure(figsize=(10, 4))
    plt.plot(time_deltas_minutes, marker="o", linestyle="-")
    plt.axhline(10, color="red", linestyle="--", label="10 minutes")
    plt.axhline(7 / 60, color="green", linestyle="--", label="7 seconds")
    plt.xlabel("File index")
    plt.ylabel("Δt between consecutive files [minutes]")
    plt.title(f"Time difference between consecutive MTG FCI files ({label})")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()

    # Save figure
    outfile =  os.path.join(dirout, f"time_deltas_{label.lower()}.png")
    plt.savefig(outfile, dpi=300)
    plt.close()
    print(f"Saved plot for {label} to {outfile}")


# -----------------------------
# GENERATE PLOTS
# -----------------------------
for label, raw_dir in RAW_DIRS.items():
    plot_time_deltas(raw_dir, label)
