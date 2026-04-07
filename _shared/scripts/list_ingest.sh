#!/usr/bin/env bash
set -euo pipefail

# list_ingest.sh — Query the DIL knowledge registry
# Delegates to lib/list_ingest.py (vanilla Python, no venv needed)
#
# Usage:
#   list_ingest.sh --state pending_tooling
#   list_ingest.sh --state failed --domain personal
#   list_ingest.sh --domain work --format json
#   list_ingest.sh --summary

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/lib/resolve_base.sh"
export BASE_DIL="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

# Resolve Python interpreter
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "ERR | 4 | Python 3 not found in PATH"
  exit 4
fi

exec "$PYTHON" "$SCRIPT_DIR/lib/list_ingest.py" "$@"
