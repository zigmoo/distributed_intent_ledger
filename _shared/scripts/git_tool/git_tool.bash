#!/usr/bin/env bash
# git_tool — DIL-compliant, agent-safe Git operations with deterministic commit templates
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SN="$(basename "${SCRIPT_PATH%.*}")"
DRAWER_DIR="$(dirname "$SCRIPT_DIR")"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"
if [[ "$(basename "$BASE")" == "scripts" && "$(basename "$(dirname "$BASE")")" == "_shared" ]]; then
  BASE="$(cd "$BASE/../.." && pwd)"
fi

# Bootstrap venv via venv_tool if requirements.txt exists
VENV_TOOL="$SCRIPTS_DIR/bin/venv_tool"
if [[ -x "$VENV_TOOL" ]]; then
  BASE_DIL="$BASE" "$VENV_TOOL" ensure "$DRAWER_DIR" -q
fi

VENV_DIR="$DRAWER_DIR/venv"
if [[ -f "$VENV_DIR/bin/activate" ]]; then
  source "$VENV_DIR/bin/activate"
  BASE_DIL="$BASE" PYTHONUNBUFFERED=1 python "$SCRIPT_DIR/${SN}.py" --base "$BASE" "$@"
  exit_code=$?
  deactivate
  exit "$exit_code"
fi

exec env BASE_DIL="$BASE" python3 "$SCRIPT_DIR/${SN}.py" --base "$BASE" "$@"
