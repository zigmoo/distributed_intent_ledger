#!/usr/bin/env bash
# setting_tool — Read and update DIL global settings with defaults
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

PYTHON_BIN="$SCRIPTS_DIR/findLatestPy.sh"
if [[ -x "$PYTHON_BIN" ]]; then
  PYTHON_PATH="$($PYTHON_BIN)"
else
  PYTHON_PATH=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_PATH="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_PATH" ]]; then
  echo "ERR | 4 | Python 3 not found in PATH" >&2
  exit 4
fi

exec "$PYTHON_PATH" "$SCRIPT_DIR/setting_tool.py" --base "$BASE" "$@"
