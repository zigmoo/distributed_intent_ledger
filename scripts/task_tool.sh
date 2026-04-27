#!/usr/bin/env bash
# file path: _shared/scripts/task_tool.sh (canonical)
#
# task_tool — thin bash wrapper for the unified Python task tool.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

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

exec "$PYTHON_BIN" "$SCRIPT_DIR/task_tool.py" --base "$BASE" "$@"
