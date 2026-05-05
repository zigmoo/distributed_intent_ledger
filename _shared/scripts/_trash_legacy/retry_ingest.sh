#!/usr/bin/env bash
set -euo pipefail

# retry_ingest.sh — DIL Ingestion Pipeline Retry Tool (Bash Wrapper)
# Delegates to lib/retry_ingest.py (vanilla Python, no venv needed)
#
# Usage:
#   retry_ingest.sh <ingest_id>                          # retry single item
#   retry_ingest.sh --state pending_tooling              # retry all pending_tooling
#   retry_ingest.sh --state failed --domain personal     # retry failed in domain
#   retry_ingest.sh <ingest_id> --abandon                # mark as failed_terminal
#   retry_ingest.sh <ingest_id> --force-promote --yes    # skip validation, promote
#   retry_ingest.sh <ingest_id> --adapter txt_md         # retry with specific adapter
#
# Exit codes: 0=success, 2=input validation, 4=missing prereq
# Output: pipe-delimited (OK | ingest_id | action | new_state | path) or (ERR | code | message)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/lib/resolve_base.sh"
export BASE_DIL="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

# Resolve Python interpreter (prefer python3, fall back to python)
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

# Verify minimum Python version (3.8+)
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION#*.}"

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 8 ]]; }; then
  echo "ERR | 4 | Python 3.8+ required (found $PY_VERSION)"
  exit 4
fi

# Export machine identity for the Python core
export DIL_MACHINE="${DIL_MACHINE:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"

# Delegate to Python core
exec "$PYTHON" "$SCRIPT_DIR/lib/retry_ingest.py" "$@"
