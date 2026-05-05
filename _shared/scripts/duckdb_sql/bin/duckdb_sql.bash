#!/usr/bin/env bash
# file path: _shared/scripts/duckdb_sql/bin/duckdb_sql.bash
# DIL-native wrapper for duckdb_sql.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DRAWER_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$DRAWER_DIR/venv"

VENV_TOOL="$SCRIPTS_DIR/bin/venv_tool"
if [[ -x "$VENV_TOOL" ]]; then
  "$VENV_TOOL" ensure "$DRAWER_DIR" -q
fi

source "$VENV_DIR/bin/activate"
PYTHONUNBUFFERED=1 python "$SCRIPT_DIR/duckdb_sql.py" "$@"
exit_code=$?
deactivate
exit "$exit_code"
