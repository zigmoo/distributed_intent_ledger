#!/bin/bash
# file path: _shared/scripts/duckdb_sql/bin/duckdb_sql.bash
# DIL-native wrapper for duckdb_sql.py
# Self-contained venv management.

SCRIPT_PATH=$(readlink -f "$0")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
DRAWER_DIR=$(dirname "$SCRIPT_DIR")
VENV_DIR="$DRAWER_DIR/venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Creating venv at $VENV_DIR..." >&2
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --quiet -r "$REQUIREMENTS"
    deactivate
fi

source "$VENV_DIR/bin/activate"
PYTHONUNBUFFERED=1 python "$SCRIPT_DIR/duckdb_sql.py" "$@"
exit_code=$?
deactivate
exit "$exit_code"
