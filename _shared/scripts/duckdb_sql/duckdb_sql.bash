#!/usr/bin/env bash
# DIL-native wrapper for duckdb_sql.py
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SN="$(basename "${SCRIPT_PATH%.*}")"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

VENV_TOOL="$SCRIPTS_DIR/bin/venv_tool"
if [[ -x "$VENV_TOOL" ]]; then
  "$VENV_TOOL" ensure "$SCRIPT_DIR" -q
fi

source "$VENV_DIR/bin/activate"
PYTHONUNBUFFERED=1 python "$SCRIPT_DIR/${SN}.py" "$@"
exit_code=$?
deactivate
exit "$exit_code"
