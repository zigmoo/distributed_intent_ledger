#!/usr/bin/env bash
# llm_tool — Wrapper for LM Studio model matrix with context ratchet + registry updates
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SN="$(basename "${SCRIPT_PATH%.*}")"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
source "$SCRIPTS_DIR/lib/tool_forge_log.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

PYTHON_PATH=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_PATH="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_PATH" ]]; then
  echo "ERR | 4 | Python 3 not found in PATH" >&2
  exit 4
fi

export BASE_DIL="$BASE"
export PYTHONUNBUFFERED=1

tool_forge_log_init "$SN" "run" "$BASE"
LOG_FILE="$(tool_forge_log_file)"
echo "LOG_FILE: $LOG_FILE"
tool_forge_log "starting python runner: $PYTHON_PATH $SCRIPT_DIR/${SN}.py"

set +e
if command -v stdbuf >/dev/null 2>&1; then
  stdbuf -oL -eL "$PYTHON_PATH" "$SCRIPT_DIR/${SN}.py" "$@" 2>&1 | tee -a "$LOG_FILE"
else
  "$PYTHON_PATH" "$SCRIPT_DIR/${SN}.py" "$@" 2>&1 | tee -a "$LOG_FILE"
fi
RC=${PIPESTATUS[0]}
set -e

tool_forge_log "runner exit_code=$RC"
tool_forge_log_close
echo "LOG_FILE: $LOG_FILE"
exit "$RC"
