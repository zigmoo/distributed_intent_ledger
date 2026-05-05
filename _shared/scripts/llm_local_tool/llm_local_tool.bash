#!/usr/bin/env bash
# llm_local_tool — Discover, test, register, and manage locally hosted LLMs (LM Studio, Ollama, vLLM, etc.) with full integration to the DIL model registry
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

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
  echo "ERR | 4 | Python 3 not found in PATH" >&2
  exit 4
fi

if [[ $# -eq 0 ]]; then
    # Intelligent default: no arguments = full smart report + fastest model test
    exec "$PYTHON_PATH" "$SCRIPT_DIR/llm_local_tool.py" --base "$BASE" report
else
    exec "$PYTHON_PATH" "$SCRIPT_DIR/llm_local_tool.py" --base "$BASE" "$@"
fi
