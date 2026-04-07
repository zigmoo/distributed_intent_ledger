#!/usr/bin/env bash
set -euo pipefail

# create_task.sh — Create canonical DIL task files
# Thin bash wrapper; delegates to lib/create_task.py for performance.
# Supports CLI args and JSON sidecar mode (create_task.sh json <manifest.json>)
# Exit codes: 0=success, 2=validation, 3=duplicate, 4=missing prereq, 5=post-creation validation failure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

usage() {
  cat << 'USAGE'
Usage:
  create_task.sh --domain <domain> --title "..." --project "..." [options]
  create_task.sh json <manifest.json>

Required:
  --domain DOMAIN         Registered domain (e.g., personal, work, triv)
  --title TEXT
  --project TEXT

External-ID domains (e.g., work) also require:
  --task-id JIRA-KEY      Example: DMDI-11331

Options:
  --summary TEXT          Populate Summary section at creation time
  --subcategory TEXT
  --parent-task-id TEXT   Optional parent task id
  --priority low|normal|medium|high|critical
  --status todo|assigned|in_progress|blocked|done|cancelled|retired
  --work-type feature|bug|chore|research|infrastructure
  --task-type kanban|sprint|epic|spike
  --effort-type low|medium|high
  --owner TEXT            Default: domain's default_owner from registry
  --due YYYY-MM-DD|TEXT
  --actor TEXT            Default: detected from env/process
  --model TEXT            Default: detected from env
  --base PATH             Default: BASE_DIL -> repo-relative -> $HOME/Documents/dil_agentic_memory_0001
  --dry-run
  -h, --help

JSON sidecar mode:
  create_task.sh json <manifest.json>
  Reads all fields from JSON manifest and dispatches creation.
  Manifest is archived to $DATA_DIR/create_task/ after execution.

Exit codes:
  0  Success
  2  Input validation error
  3  Duplicate task ID or file
  4  Missing prerequisite (path, counter, registry)
  5  Post-creation validation failure
USAGE
}

# Handle --help before resolving Python
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
  esac
done

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

# --- Translate json subcommand for backwards compatibility ---
# Scan for "json" anywhere in args (e.g. create_task.sh --base /path json manifest.json)
ARGS=()
JSON_NEXT=0
for arg in "$@"; do
  if [[ "$arg" == "json" && $JSON_NEXT -eq 0 ]]; then
    ARGS+=("--json-manifest")
    JSON_NEXT=1
  else
    ARGS+=("$arg")
    JSON_NEXT=0
  fi
done

# --- Delegate to Python ---
exec "$PYTHON" "$SCRIPT_DIR/lib/create_task.py" --base "$BASE" "${ARGS[@]}"
