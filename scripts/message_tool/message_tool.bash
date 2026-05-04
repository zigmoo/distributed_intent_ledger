#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -z "${BASE_DIL:-}" ]]; then
  _cursor="$SCRIPT_DIR"
  while [[ -n "$_cursor" && "$_cursor" != "/" ]]; do
    if [[ -d "$_cursor/_shared/_meta" ]]; then
      BASE_DIL="$_cursor"
      break
    fi
    _cursor="$(dirname "$_cursor")"
  done
  unset _cursor
fi
BASE_DIL="${BASE_DIL:?Could not resolve DIL base. Set BASE_DIL.}"
export BASE_DIL

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
  echo "ERR | 4 | Python not found in PATH" >&2
  exit 4
fi

LOG_DIR="$BASE_DIL/_shared/logs/message_tool"
mkdir -p "$LOG_DIR"
HOSTNAME_SHORT=$(hostname -s | tr '[:upper:]' '[:lower:]')
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/${HOSTNAME_SHORT}.message_tool.${1:-help}.${TIMESTAMP}.log"

exec > >(tee -a "$LOG_FILE") 2>&1

exec "$PYTHON_PATH" "$SCRIPT_DIR/message_tool.py" "$@"
