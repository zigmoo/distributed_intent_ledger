#!/usr/bin/env bash
# DIL-native wrapper for duckdb_sql.py
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SN="$(basename "${SCRIPT_PATH%.*}")"
DRAWER_DIR="$(dirname "$SCRIPT_DIR")"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$DRAWER_DIR/venv"

VENV_TOOL="$SCRIPTS_DIR/bin/venv_tool"
if [[ -x "$VENV_TOOL" ]]; then
  "$VENV_TOOL" ensure "$DRAWER_DIR" -q
fi

source "$VENV_DIR/bin/activate"
PYTHONUNBUFFERED=1 python "$SCRIPT_DIR/${SN}.py" "$@"
exit_code=$?
deactivate
exit "$exit_code"
