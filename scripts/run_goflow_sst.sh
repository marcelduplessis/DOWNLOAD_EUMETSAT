#!/bin/sh

# Run Python scripts in the scripts folder for GOFLOW SST processing.
# Uncomment script names in SELECTED_SCRIPTS to run only those files.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONDA_ENV_NAME="satpy_env"

resolve_conda_exe() {
    if [ -n "$CONDA_EXE" ] && [ -x "$CONDA_EXE" ]; then
        printf '%s\n' "$CONDA_EXE"
        return 0
    fi

    if [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/conda" ]; then
        printf '%s\n' "$CONDA_PREFIX/bin/conda"
        return 0
    fi

    if command -v conda >/dev/null 2>&1; then
        printf '%s\n' "$(command -v conda)"
        return 0
    fi

    if [ -x "/home/mduplessis/sw/miniconda3/bin/conda" ]; then
        printf '%s\n' "/home/mduplessis/sw/miniconda3/bin/conda"
        return 0
    fi

    return 1
}

SELECTED_SCRIPTS="
00_download_eumdac_CLM.py
00_download_eumdac_RRAD_HR.py
031_regrid_RRAD_CLM_to_timeseries.py
032_process_timeseries_for_goflow.py
04_goflow_regional_animation.py
# 01_check_raw_products_time_deltas.py
# 02_build_land_mask.py
"

list_scripts() {
    for py_file in "$SCRIPT_DIR"/*.py; do
        if [ -f "$py_file" ]; then
            basename "$py_file"
        fi
    done
}

run_script() {
    py_file="$1"
    conda_exe="$(resolve_conda_exe)"

    echo "Running: $(basename "$py_file")"
    if [ -n "$CONDA_ENV_NAME" ]; then
        if [ -z "$conda_exe" ]; then
            echo "conda was not found"
            exit 1
        fi

        "$conda_exe" run --no-capture-output -n "$CONDA_ENV_NAME" python "$py_file"
    else
        python3 "$py_file"
    fi

    if [ $? -ne 0 ]; then
        echo "Error running $(basename "$py_file")"
        exit 1
    fi
}

set -- $(printf '%s\n' "$SELECTED_SCRIPTS" | sed -e 's/[[:space:]]*#.*$//' -e '/^[[:space:]]*$/d')

if [ $# -gt 0 ]; then
    for requested_file in "$@"; do
        py_file="$SCRIPT_DIR/$requested_file"
        case "$requested_file" in
            *.py) ;;
            *) py_file="$py_file.py" ;;
        esac

        if [ ! -f "$py_file" ]; then
            echo "Script not found: $requested_file"
            echo "Available scripts:"
            list_scripts
            exit 1
        fi

        run_script "$py_file"
    done
else
    for py_file in "$SCRIPT_DIR"/*.py; do
        if [ -f "$py_file" ]; then
            run_script "$py_file"
        fi
    done
fi

echo "All GOFLOW SST processing complete!"
