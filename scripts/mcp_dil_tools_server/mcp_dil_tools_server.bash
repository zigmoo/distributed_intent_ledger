#!/usr/bin/env bash
# mcp_dil_tools_server - DIL-compliant launcher for the LM Studio MCP bridge.
#
# stdout is reserved for MCP Content-Length frames from the Python child.
# Operator-visible status is emitted on stderr and tee'd to a DIL log file.

set -euo pipefail

SCRIPT_NAME="mcp_dil_tools_server"
SCRIPT_VERSION="2026-04-14"
SCRIPT_AUTHOR="codex"
SCRIPT_MODEL="gpt-5.4"
SCRIPT_OWNER="moo"
IMPLEMENTATION_TASK_ID="DIL-1452"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_NAME"
PYTHON_SCRIPT_PATH="$SCRIPT_DIR/mcp_dil_tools_server.py"

# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/../lib/domains.sh"

BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
export BASE_DIL="$BASE"

resolve_domain personal

START_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
HOSTNAME_SHORT="$(hostname -s | tr '[:upper:]' '[:lower:]')"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
LOG_ROOT="$LOG_DIR/$SCRIPT_NAME"
mkdir -p "$LOG_ROOT"
LOG_FILE="$LOG_ROOT/${SCRIPT_NAME}.wrapper.${STAMP}.$$.log"

log_status() {
  local level="$1"
  shift
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  local line
  line="$(printf '[%s] [%s] [%s] %s' "$ts" "$SCRIPT_NAME" "$level" "$*")"
  printf '%s\n' "$line" >> "$LOG_FILE"
  if [[ "$level" == "ERROR" || "${MCP_DIL_TOOLS_VERBOSE_STDERR:-0}" == "1" ]]; then
    printf '%s\n' "$line" >&2
  fi
}

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  log_status ERROR "python runtime not found"
  exit 127
fi

if [[ ! -f "$PYTHON_SCRIPT_PATH" ]]; then
  log_status ERROR "python server not found: $PYTHON_SCRIPT_PATH"
  exit 2
fi

log_status INFO "wrapper_start script_version=$SCRIPT_VERSION task_id=$IMPLEMENTATION_TASK_ID"
log_status INFO "script_author=$SCRIPT_AUTHOR script_model=$SCRIPT_MODEL script_owner=$SCRIPT_OWNER"
log_status INFO "hostname_short=$HOSTNAME_SHORT pid=$$ start_ts_utc=$START_TS"
log_status INFO "base_dil=$BASE"
log_status INFO "script_path=$SCRIPT_PATH"
log_status INFO "python_script_path=$PYTHON_SCRIPT_PATH"
log_status INFO "wrapper_log_file=$LOG_FILE"
log_status INFO "exec=$PYTHON_BIN $PYTHON_SCRIPT_PATH"

exec "$PYTHON_BIN" "$PYTHON_SCRIPT_PATH" "$@"
