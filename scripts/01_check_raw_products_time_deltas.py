# Coded by Lucie Reymondet (Scripps-UCSD)

from pathlib import Path
import re
from datetime import datetime
import matplotlib.pyplot as plt
from params import raw_data_dir_rrad_nr, raw_data_dir_rrad_hr, raw_data_dir_clm

# -----------------------------
# PATH SETUP
# -----------------------------
RAW_DIRS = {
    "RRAD_NR": Path(raw_data_dir_rrad_nr).expanduser().resolve(),
    "RRAD_HR": Path(raw_data_dir_rrad_hr).expanduser().resolve(),
    "CLM":     Path(raw_data_dir_clm).expanduser().resolve(),
}

BASE_DIR = Path(__file__).resolve().parents[1]
DIR_OUT  = BASE_DIR / "figures"
DIR_OUT.mkdir(parents=True, exist_ok=True)

# Compile once — reused across all directories
_PATTERN = re.compile(r"OPE_(\d{14})_\d{14}")

# -----------------------------
# UTILITY FUNCTIONS
# -----------------------------

def collect_times(raw_dir: Path) -> list[datetime]:
    """
    Scan a directory and return a sorted list of start datetimes parsed
    from MTG FCI filenames.  Uses a pre-compiled regex and avoids
    exception-based control flow for speed on large directories.
    """
    times = []
    for f in raw_dir.iterdir():
        if not f.is_file():
            continue
        m = _PATTERN.search(f.name)
        if m:
            times.append(datetime.strptime(m.group(1), "%Y%m%d%H%M%S"))
    times.sort()
    return times


def plot_time_deltas(raw_dir: Path, label: str) -> None:
    """
    Compute Δt between consecutive files in raw_dir and save a figure.
    """
    times = collect_times(raw_dir)

    if len(times) < 2:
        print(f"[{label}] Not enough valid files found in {raw_dir} — skipping.")
        return

    deltas = [
        (times[i + 1] - times[i]).total_seconds() / 60
        for i in range(len(times) - 1)
    ]

    print(f"[{label}] {len(times)} files — "
          f"Δt min={min(deltas):.2f} max={max(deltas):.2f} "
          f"mean={sum(deltas)/len(deltas):.2f} min")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(deltas, marker="o", markersize=2, linewidth=0.8, linestyle="-")
    ax.axhline(10,      color="red",   linestyle="--", linewidth=0.8, label="10 min")
    ax.axhline(7 / 60,  color="green", linestyle="--", linewidth=0.8, label="7 s")
    ax.set_xlabel("File index")
    ax.set_ylabel("Δt between consecutive files [minutes]")
    ax.set_title(f"Time difference between consecutive MTG FCI files — {label}")
    ax.legend()
    ax.grid(True, which="both", linewidth=0.4)
    ax.set_yscale("log")
    fig.tight_layout()

    outfile = DIR_OUT / f"time_deltas_{label.lower()}.png"
    fig.savefig(outfile, dpi=150)
    plt.close(fig)
    print(f"[{label}] Saved → {outfile}")


# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    for label, raw_dir in RAW_DIRS.items():
        plot_time_deltas(raw_dir, label)