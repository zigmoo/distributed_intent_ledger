#!/usr/bin/env bash
set -euo pipefail
# dil_search.sh
# Hybrid search across DIL memory, tasks, and preferences with ranked results.
# Delegates scoring to lib/dil_search.py (stdlib-only Python).

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

usage() {
  cat << 'USAGE'
Usage:
  dil_search.sh <query> [options]

Arguments:
  <query>              Search terms (required; multiple words treated as AND)

Options:
  --scope <scope>      Restrict search scope: all, memory, tasks, preferences (default: all)
  --recall             Preset for assistant recall: memory + tasks + preferences
  --domain <domain>    Restrict to domain: personal, work, triv (default: all)
  --limit <n>          Max results to display (default: 10)
  --context <n>        Lines of context around matches (default: 1)
  --status <status>    Filter tasks by status: active, done, all (default: active)
  --no-color           Disable colored output
  --json               Output results as JSON
  -h, --help           Show this help
  Env: BASE_DIL        Override DIL base path

Examples:
  dil_search.sh "jira token"
  dil_search.sh "oauth migration" --recall
  dil_search.sh "memory protocol" --scope preferences
  dil_search.sh "DMDI-11614" --domain work --context 3
USAGE
}

# --- Defaults ---
QUERY=""
SCOPE="all"
DOMAIN="all"
LIMIT=10
CONTEXT=1
STATUS="active"
NO_COLOR=0
JSON_OUTPUT=0
RECALL_MODE=0
SCOPE_SET=0
STATUS_SET=0

# --- Parse args ---
if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

# First positional arg is the query
if [[ "${1:0:1}" != "-" ]]; then
  QUERY="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)    SCOPE="${2:-}"; SCOPE_SET=1; shift 2 ;;
    --recall)   RECALL_MODE=1; shift ;;
    --domain)   DOMAIN="${2:-}"; shift 2 ;;
    --limit)    LIMIT="${2:-}"; shift 2 ;;
    --context)  CONTEXT="${2:-}"; shift 2 ;;
    --status)   STATUS="${2:-}"; STATUS_SET=1; shift 2 ;;
    --no-color) NO_COLOR=1; shift ;;
    --json)     JSON_OUTPUT=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *)
      # If query wasn't set yet, treat as query
      if [[ -z "$QUERY" ]]; then
        QUERY="$1"
        shift
      else
        echo "Unknown arg: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

# Recall preset defaults to cross-source short-term+durable memory retrieval.
if [[ "$RECALL_MODE" -eq 1 ]]; then
  if [[ "$SCOPE_SET" -eq 0 ]]; then
    SCOPE="recall"
  fi
  if [[ "$STATUS_SET" -eq 0 ]]; then
    STATUS="active"
  fi
fi

if [[ -z "$QUERY" ]]; then
  echo "Error: search query is required." >&2
  usage
  exit 2
fi

# --- Resolve Python ---
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "ERR | 4 | Python 3 not found in PATH" >&2
  exit 4
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR="${PY_VERSION%%.*}"
if [[ "$PY_MAJOR" -lt 3 ]]; then
  echo "ERR | 4 | Python 3 required (found $PY_VERSION)" >&2
  exit 4
fi

# --- Delegate to Python ---
exec "$PYTHON" "$SCRIPT_DIR/../lib/dil_search.py" \
  --base "$BASE" \
  --query "$QUERY" \
  --scope "$SCOPE" \
  --domain "$DOMAIN" \
  --limit "$LIMIT" \
  --context "$CONTEXT" \
  --status "$STATUS" \
  $([ "$NO_COLOR" -eq 1 ] && echo "--no-color") \
  $([ "$JSON_OUTPUT" -eq 1 ] && echo "--json")
