#!/usr/bin/env bash
set -euo pipefail

# Rebuild the repository structure block in README.md from the current filesystem.
# Usage: ./scripts/update_readme_structure.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
README_PATH="$REPO_ROOT/README.md"

START_MARKER="<!-- structure:start -->"
END_MARKER="<!-- structure:end -->"

if [[ ! -f "$README_PATH" ]]; then
  echo "README not found at $README_PATH" >&2
  exit 1
fi

if ! grep -q "$START_MARKER" "$README_PATH"; then
  echo "Start marker not found in README: $START_MARKER" >&2
  exit 1
fi

if ! grep -q "$END_MARKER" "$README_PATH"; then
  echo "End marker not found in README: $END_MARKER" >&2
  exit 1
fi

is_ignored() {
  local name="$1"
  case "$name" in
    .git|__pycache__)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

render_tree() {
  echo '```text'
  echo 'DOWNLOAD_EUMETSAT/'

  mapfile -t level1 < <(find "$REPO_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)

  for entry in "${level1[@]}"; do
    if is_ignored "$entry"; then
      continue
    fi

    if [[ -d "$REPO_ROOT/$entry" ]]; then
      echo "|- $entry/"

      mapfile -t level2 < <(find "$REPO_ROOT/$entry" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
      for child in "${level2[@]}"; do
        if is_ignored "$child"; then
          continue
        fi

        if [[ -d "$REPO_ROOT/$entry/$child" ]]; then
          echo "|  |- $child/"
        else
          echo "|  |- $child"
        fi
      done
    else
      echo "|- $entry"
    fi
  done

  echo '```'
}

TMP_BLOCK="$(mktemp)"
render_tree > "$TMP_BLOCK"

TMP_README="$(mktemp)"
awk -v start="$START_MARKER" -v end="$END_MARKER" -v block_file="$TMP_BLOCK" '
  BEGIN {
    in_block = 0
    while ((getline line < block_file) > 0) {
      block = block line "\n"
    }
    close(block_file)
  }
  $0 == start {
    print
    printf "%s", block
    in_block = 1
    next
  }
  $0 == end {
    in_block = 0
    print
    next
  }
  in_block == 0 {
    print
  }
' "$README_PATH" > "$TMP_README"

mv "$TMP_README" "$README_PATH"
rm -f "$TMP_BLOCK"

echo "Updated repository structure block in $README_PATH"
