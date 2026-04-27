#!/usr/bin/env bash
# file path: _shared/scripts/research_tool.sh (canonical)
#
# research_tool — thin bash wrapper for the unified Python research artifact tool.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
ARTIFACT_REGISTRY_FILE="$BASE/_shared/_meta/research_artifact_registry.json"
if [[ -z "${RESEARCH_TOOL_ARTIFACT_TYPES_FILE:-}" && -f "$ARTIFACT_REGISTRY_FILE" ]]; then
  export RESEARCH_TOOL_ARTIFACT_TYPES_FILE="$ARTIFACT_REGISTRY_FILE"
fi

PYTHON_BIN="$SCRIPT_DIR/../findLatestPy.sh"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERR | 4 | findLatestPy helper not found: $PYTHON_BIN" >&2
  exit 4
fi

PYTHON_PATH="$($PYTHON_BIN)"
if [[ -z "$PYTHON_PATH" ]]; then
  echo "ERR | 4 | Could not resolve Python binary via findLatestPy" >&2
  exit 4
fi

exec "$PYTHON_PATH" "$SCRIPT_DIR/research_tool.py" --base "$BASE" "$@"
