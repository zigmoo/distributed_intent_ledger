#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE_DIL="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
export BASE_DIL

LOG_DIR="$BASE_DIL/_shared/logs/session_artifact_tool"
mkdir -p "$LOG_DIR"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' || printf 'unknown')"
ACTION="${1:-help}"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
LOG_FILE="$LOG_DIR/${HOSTNAME_SHORT}.session_artifact_tool.${ACTION}.${TIMESTAMP}.log"

PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERR | 4 | Python 3 not found in PATH" >&2
  exit 4
fi

exec > >(tee -a "$LOG_FILE") 2>&1
exec "$PYTHON_BIN" "$SCRIPT_DIR/../lib/session_artifact_tool/session_artifact_tool.py" "$@"
