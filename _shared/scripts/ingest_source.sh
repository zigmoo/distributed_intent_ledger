#!/usr/bin/env bash
set -euo pipefail

# ingest_source.sh — DIL Universal Inbox Ingestion Pipeline (Bash Wrapper)
# Delegates to lib/ingest_source.py (vanilla Python, no venv needed)
#
# Usage:
#   ingest_source.sh /path/to/file.pdf
#   ingest_source.sh https://example.com/doc.html
#   cat file | ingest_source.sh -
#   ingest_source.sh --domain work --sensitivity internal /path/to/file
#
# Exit codes: 0=success, 2=input validation, 3=duplicate, 4=missing prereq, 5=post-validation failure
# Output: pipe-delimited (OK | ingest_id | domain | status | path) or (ERR | code | message)

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
exec "$PYTHON" "$SCRIPT_DIR/lib/ingest_source.py" "$@"
