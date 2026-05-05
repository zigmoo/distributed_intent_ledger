#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# Walk upward to find the DIL root (directory containing _shared/_meta)
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

LOG_DIR="$BASE_DIL/_shared/logs/signal_tool"
mkdir -p "$LOG_DIR"
HOSTNAME_SHORT=$(hostname -s | tr '[:upper:]' '[:lower:]')
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/${HOSTNAME_SHORT}.signal_tool.${1:-help}.${TIMESTAMP}.log"

exec > >(tee -a "$LOG_FILE") 2>&1

exec python3 "$SCRIPT_DIR/../lib/signal_tool/signal_tool.py" "$@"
