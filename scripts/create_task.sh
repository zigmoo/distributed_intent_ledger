#!/usr/bin/env bash
set -euo pipefail

# create_task.sh — Create canonical DIL task files
# Supports CLI args and JSON sidecar mode (create_task.sh json <manifest.json>)
# Exit codes: 0=success, 2=validation, 3=duplicate, 4=missing prereq, 5=post-creation validation failure

SCRIPT_NAME="create_task"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Source domain registry
# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/lib/domains.sh"

# --- Environment-aware defaults ---
_resolve_actor() {
  if [[ -n "${ACTOR:-}" ]]; then printf '%s' "$ACTOR"; return; fi
  if [[ -n "${ASSISTANT_ID:-}" ]]; then printf '%s' "$ASSISTANT_ID"; return; fi
  if [[ -n "${AGENT_NAME:-}" ]]; then printf '%s' "$AGENT_NAME"; return; fi
  if [[ -n "${AGENT_ID:-}" ]]; then printf '%s' "$AGENT_ID"; return; fi
  local ppid_name
  ppid_name="$(ps -p "$PPID" -o comm= 2>/dev/null | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')" || true
  if [[ -n "$ppid_name" ]]; then printf '%s' "$ppid_name"; return; fi
  printf 'unknown'
}

_resolve_model() {
  if [[ -n "${MODEL:-}" ]]; then printf '%s' "$MODEL"; return; fi
  if [[ -n "${AGENT_MODEL:-}" ]]; then printf '%s' "$AGENT_MODEL"; return; fi
  printf 'unknown'
}

DOMAIN=""
TASK_ID=""
TITLE=""
PROJECT=""
SUBCATEGORY=""
PARENT_TASK_ID=""
PRIORITY="normal"
STATUS="todo"
WORK_TYPE=""
TASK_TYPE="kanban"
EFFORT_TYPE="medium"
OWNER=""
DUE=""
ACTOR="${ACTOR:-}"
MODEL="${MODEL:-}"
SUMMARY=""
DRY_RUN=0
ELUCUBRATE_NOTIFY="${ELUCUBRATE_NOTIFY:-auto}"
ELUCUBRATE_URL="${ELUCUBRATE_URL:-http://127.0.0.1:3000}"
LOG_FILE=""

# --- Logging ---
_init_logging() {
  local domain="$1"
  if resolve_domain "$domain" 2>/dev/null; then
    local log_dir="$LOG_DIR/$SCRIPT_NAME"
    mkdir -p "$log_dir"
    LOG_FILE="$log_dir/${SCRIPT_NAME}.create.${TIMESTAMP}.log"
    _log "=== $SCRIPT_NAME create started ==="
    _log "Host: $(hostname)"
    _log "Actor: $ACTOR"
    _log "Model: $MODEL"
    _log "Domain: $domain"
  fi
}

_log() {
  if [[ -n "$LOG_FILE" ]]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG_FILE"
  fi
}

# --- Output ---
_output() {
  local task_id="$1" domain="$2" status="$3" path="$4"
  echo "OK | $task_id | $domain | $status | $path"
}

_output_error() {
  local code="$1" msg="$2"
  echo "ERR | $code | $msg" >&2
}

# --- Usage ---
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
  --base PATH             Default: auto-detected from script location
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

# --- Helpers ---
trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

q() {
  printf '%s' "$1" | sed 's/"/\\"/g'
}

valid_status() {
  case "$1" in
    todo|assigned|in_progress|blocked|done|cancelled|retired) return 0 ;;
    *) return 1 ;;
  esac
}

valid_priority() {
  case "$1" in
    low|normal|medium|high|critical) return 0 ;;
    *) return 1 ;;
  esac
}

valid_work_type() {
  case "$1" in
    feature|bug|chore|research|infrastructure) return 0 ;;
    *) return 1 ;;
  esac
}

valid_task_type() {
  case "$1" in
    kanban|sprint|epic|spike) return 0 ;;
    *) return 1 ;;
  esac
}

valid_effort_type() {
  case "$1" in
    low|medium|high) return 0 ;;
    *) return 1 ;;
  esac
}

notify_elucubrate_cache_refresh() {
  case "$ELUCUBRATE_NOTIFY" in
    off|false|0) return 0 ;;
  esac
  if ! command -v curl >/dev/null 2>&1; then return 0; fi
  if curl -fsS --max-time 1 "$ELUCUBRATE_URL/api/health" >/dev/null 2>&1; then
    if curl -fsS --max-time 2 -X POST "$ELUCUBRATE_URL/api/cache/refresh" >/dev/null 2>&1; then
      _log "Elucubrate cache refreshed"
    fi
  fi
}

# --- Counter helpers ---
# Read next_id for a given prefix from the multi-prefix counter file
read_counter() {
  local prefix="$1"
  local counter_file="$2"
  # Find the section for this prefix and extract next_id
  awk -v prefix="$prefix" '
    BEGIN { in_section=0 }
    /^### / { in_section=0 }
    $0 ~ ("^### " prefix " ") { in_section=1; next }
    in_section && /^- next_id:/ { sub(/^- next_id:[[:space:]]*/, ""); print; exit }
  ' "$counter_file" | tr -d ' '
}

# Update next_id, last_allocator, last_model for a given prefix
update_counter() {
  local prefix="$1"
  local new_next_id="$2"
  local actor="$3"
  local model="$4"
  local counter_file="$5"
  # Use awk to update in-place
  local tmp
  tmp="$(mktemp)"
  awk -v prefix="$prefix" -v nid="$new_next_id" -v act="$actor" -v mod="$model" '
    BEGIN { in_section=0 }
    /^### / { in_section=0 }
    $0 ~ ("^### " prefix " ") { in_section=1; print; next }
    in_section && /^- next_id:/ { print "- next_id: " nid; next }
    in_section && /^- last_allocator:/ { print "- last_allocator: " act; next }
    in_section && /^- last_model:/ { print "- last_model: " mod; next }
    { print }
  ' "$counter_file" > "$tmp"
  mv "$tmp" "$counter_file"
}

# --- JSON sidecar mode ---
cmd_json() {
  if [[ $# -lt 1 ]]; then
    echo "Usage: create_task.sh json <manifest.json>" >&2
    return 4
  fi

  local manifest="$1"
  if [[ ! -f "$manifest" ]]; then
    _output_error 4 "Manifest file not found: $manifest"
    return 4
  fi

  if ! command -v jq >/dev/null 2>&1; then
    _output_error 4 "jq is required for JSON mode"
    return 4
  fi

  # Extract fields from manifest
  local v
  local args=()

  v=$(jq -r '.domain // empty' "$manifest"); [[ -n "$v" ]] && args+=(--domain "$v")
  v=$(jq -r '.task_id // empty' "$manifest"); [[ -n "$v" ]] && args+=(--task-id "$v")
  v=$(jq -r '.title // empty' "$manifest"); [[ -n "$v" ]] && args+=(--title "$v")
  v=$(jq -r '.project // empty' "$manifest"); [[ -n "$v" ]] && args+=(--project "$v")
  v=$(jq -r '.summary // empty' "$manifest"); [[ -n "$v" ]] && args+=(--summary "$v")
  v=$(jq -r '.subcategory // empty' "$manifest"); [[ -n "$v" ]] && args+=(--subcategory "$v")
  v=$(jq -r '.parent_task_id // empty' "$manifest"); [[ -n "$v" ]] && args+=(--parent-task-id "$v")
  v=$(jq -r '.priority // empty' "$manifest"); [[ -n "$v" ]] && args+=(--priority "$v")
  v=$(jq -r '.status // empty' "$manifest"); [[ -n "$v" ]] && args+=(--status "$v")
  v=$(jq -r '.work_type // empty' "$manifest"); [[ -n "$v" ]] && args+=(--work-type "$v")
  v=$(jq -r '.task_type // empty' "$manifest"); [[ -n "$v" ]] && args+=(--task-type "$v")
  v=$(jq -r '.effort_type // empty' "$manifest"); [[ -n "$v" ]] && args+=(--effort-type "$v")
  v=$(jq -r '.owner // empty' "$manifest"); [[ -n "$v" ]] && args+=(--owner "$v")
  v=$(jq -r '.due // empty' "$manifest"); [[ -n "$v" ]] && args+=(--due "$v")
  v=$(jq -r '.actor // empty' "$manifest"); [[ -n "$v" ]] && args+=(--actor "$v")
  v=$(jq -r '.model // empty' "$manifest"); [[ -n "$v" ]] && args+=(--model "$v")

  _log "JSON mode: dispatching with args: ${args[*]}"

  # Re-invoke ourselves with extracted args
  cmd_create "${args[@]}"
  local rc=$?

  # Archive the manifest
  if [[ $rc -eq 0 ]] && resolve_domain "$(jq -r '.domain // "personal"' "$manifest")" 2>/dev/null; then
    local archive_dir="$DATA_DIR/$SCRIPT_NAME"
    mkdir -p "$archive_dir"
    cp "$manifest" "$archive_dir/${SCRIPT_NAME}.create.${TIMESTAMP}.json"
    _log "Manifest archived to $archive_dir"
  fi

  return $rc
}

# --- Main creation logic ---
cmd_create() {
  # Parse args (called from main or from cmd_json)
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --domain) DOMAIN="${2:-}"; shift 2 ;;
      --task-id) TASK_ID="${2:-}"; shift 2 ;;
      --title) TITLE="${2:-}"; shift 2 ;;
      --project) PROJECT="${2:-}"; shift 2 ;;
      --summary) SUMMARY="${2:-}"; shift 2 ;;
      --subcategory) SUBCATEGORY="${2:-}"; shift 2 ;;
      --parent-task-id) PARENT_TASK_ID="${2:-}"; shift 2 ;;
      --priority) PRIORITY="${2:-}"; shift 2 ;;
      --status) STATUS="${2:-}"; shift 2 ;;
      --work-type) WORK_TYPE="${2:-}"; shift 2 ;;
      --task-type) TASK_TYPE="${2:-}"; shift 2 ;;
      --effort-type) EFFORT_TYPE="${2:-}"; shift 2 ;;
      --owner) OWNER="${2:-}"; shift 2 ;;
      --due) DUE="${2:-}"; shift 2 ;;
      --actor) ACTOR="${2:-}"; shift 2 ;;
      --model) MODEL="${2:-}"; shift 2 ;;
      --base) DIL_BASE="${2:-}"; shift 2 ;;
      --dry-run) DRY_RUN=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) _output_error 2 "Unknown arg: $1"; usage; exit 2 ;;
    esac
  done

  # Resolve actor/model from environment if not set via args
  ACTOR="$(_resolve_actor)"
  MODEL="$(_resolve_model)"

  DOMAIN="$(printf '%s' "$DOMAIN" | trim)"
  TITLE="$(printf '%s' "$TITLE" | trim)"
  PROJECT="$(printf '%s' "$PROJECT" | trim)"
  PARENT_TASK_ID="$(printf '%s' "$PARENT_TASK_ID" | trim)"

  if [[ -z "$DOMAIN" || -z "$TITLE" || -z "$PROJECT" ]]; then
    _output_error 2 "Missing required args: --domain, --title, --project"
    exit 2
  fi

  # Resolve domain from registry
  if ! resolve_domain "$DOMAIN"; then
    _output_error 4 "Unknown domain: $DOMAIN"
    exit 4
  fi

  # Set owner to domain default if not specified
  if [[ -z "$OWNER" ]]; then
    OWNER="$DEFAULT_OWNER"
  fi

  # Initialize logging after domain resolution
  _init_logging "$DOMAIN"
  _log "Title: $TITLE"
  _log "Project: $PROJECT"

  if ! valid_status "$STATUS"; then
    _output_error 2 "Invalid --status: $STATUS"
    exit 2
  fi

  if ! valid_priority "$PRIORITY"; then
    _output_error 2 "Invalid --priority: $PRIORITY"
    exit 2
  fi

  if [[ -n "$PARENT_TASK_ID" ]] && [[ ! "$PARENT_TASK_ID" =~ ^(DIL-[0-9]+|TRIV-[0-9]+|[A-Z]+-[0-9]+)$ ]]; then
    _output_error 2 "Invalid --parent-task-id format: $PARENT_TASK_ID"
    exit 2
  fi

  if [[ -z "$WORK_TYPE" ]]; then
    if [[ "$ID_MODE" == "external" ]]; then
      WORK_TYPE="feature"
    else
      WORK_TYPE="chore"
    fi
  fi

  if ! valid_work_type "$WORK_TYPE"; then
    _output_error 2 "Invalid --work-type: $WORK_TYPE"
    exit 2
  fi
  if ! valid_task_type "$TASK_TYPE"; then
    _output_error 2 "Invalid --task-type: $TASK_TYPE"
    exit 2
  fi
  if ! valid_effort_type "$EFFORT_TYPE"; then
    _output_error 2 "Invalid --effort-type: $EFFORT_TYPE"
    exit 2
  fi

  # Paths
  INDEX_FILE="$DIL_BASE/_shared/_meta/task_index.md"
  COUNTER_FILE="$DIL_BASE/_shared/_meta/task_id_counter.md"
  CHANGE_LOG="$DIL_BASE/_shared/tasks/_meta/change_log.md"
  VALIDATOR="$DIL_BASE/_shared/tasks/_meta/scripts/validate_tasks.sh"
  ACTIVE_DIR="$TASK_DIR/active"

  for req in "$INDEX_FILE" "$COUNTER_FILE" "$CHANGE_LOG"; do
    if [[ ! -e "$req" ]]; then
      _output_error 4 "Missing required path: $req"
      exit 4
    fi
  done

  if [[ ! -d "$ACTIVE_DIR" ]]; then
    _output_error 4 "Missing active task directory: $ACTIVE_DIR"
    exit 4
  fi

  DATE_UTC="$(date -u +%Y-%m-%d)"
  TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # ID allocation
  local next_id=""
  if [[ "$ID_MODE" == "external" ]]; then
    if [[ -z "$TASK_ID" ]]; then
      _output_error 2 "--task-id is required for external-ID domain '$DOMAIN'"
      exit 2
    fi
    if [[ ! "$TASK_ID" =~ ^[A-Z]+-[0-9]+$ ]]; then
      _output_error 2 "Invalid task id format for external domain: $TASK_ID"
      exit 2
    fi
  elif [[ "$ID_MODE" == "auto" ]]; then
    if [[ -n "$TASK_ID" ]]; then
      _output_error 2 "Do not pass --task-id for auto-ID domain '$DOMAIN'; it is allocated automatically"
      exit 2
    fi
    next_id="$(read_counter "$ID_PREFIX" "$COUNTER_FILE")"
    if [[ -z "$next_id" || ! "$next_id" =~ ^[0-9]+$ ]]; then
      _output_error 4 "Invalid next_id for prefix $ID_PREFIX in $COUNTER_FILE"
      exit 4
    fi
    TASK_ID="${ID_PREFIX}-${next_id}"
  fi

  TASK_PATH="$ACTIVE_DIR/$TASK_ID.md"

  # Parent validation: search across all domain active+archived dirs
  if [[ -n "$PARENT_TASK_ID" ]]; then
    if [[ "$PARENT_TASK_ID" == "$TASK_ID" ]]; then
      _output_error 2 "--parent-task-id cannot equal task_id ($TASK_ID)"
      exit 2
    fi
    local parent_found=0
    while IFS= read -r dname; do
      local raw_td
      raw_td=$(jq -r --arg d "$dname" '.domains[$d].task_dir' "$_DOMAIN_REGISTRY")
      local resolved_td
      if [[ "$raw_td" == /* ]]; then resolved_td="$raw_td"; else resolved_td="$DIL_BASE/$raw_td"; fi
      if [[ -f "$resolved_td/active/$PARENT_TASK_ID.md" ]]; then parent_found=1; break; fi
      if find "$resolved_td/archived" -name "$PARENT_TASK_ID.md" -print -quit 2>/dev/null | grep -q .; then parent_found=1; break; fi
    done < <(list_domains)
    if (( ! parent_found )); then
      _output_error 2 "--parent-task-id not found in canonical tasks: $PARENT_TASK_ID"
      exit 2
    fi
  fi

  if [[ -e "$TASK_PATH" ]]; then
    _output_error 3 "Task file already exists: $TASK_PATH"
    exit 3
  fi

  if rg -q "^\|[[:space:]]*$TASK_ID[[:space:]]*\|" "$INDEX_FILE"; then
    _output_error 3 "Task ID already present in index: $TASK_ID"
    exit 3
  fi

  TASK_REL="${TASK_PATH#$DIL_BASE/}"

  # Build summary section
  local summary_content
  if [[ -n "$SUMMARY" ]]; then
    summary_content="- $SUMMARY"
  else
    summary_content="-"
  fi

  task_content=$(cat <<EOT
---
title: "$(q "$TITLE")"
date: $DATE_UTC
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: $PRIORITY
tags: [task, $DOMAIN]
updated: $DATE_UTC
source: internal
domain: $DOMAIN
project: $(q "$PROJECT")
status: $STATUS
owner: $(q "$OWNER")
due: $(q "$DUE")
work_type: $WORK_TYPE
task_type: $TASK_TYPE
effort_type: $EFFORT_TYPE
task_id: $TASK_ID
created_by: $(q "$ACTOR")
model: $(q "$MODEL")
created_at: $TS_UTC
task_schema: v1
parent_task_id: "$(q "$PARENT_TASK_ID")"
agents:
  - id: "$(q "$OWNER")"
    role: accountable
    responsibility_order: 1
subcategory: $(q "$SUBCATEGORY")
---

# $(q "$TITLE")

## Summary
$summary_content

## Links
- Related tasks:
- Related notes:

## Execution Notes
- Created via create_task.sh.
EOT
)

  index_row="| $TASK_ID | $DOMAIN | $STATUS | $PRIORITY | $OWNER | $DUE | $PROJECT | $TASK_REL | $DATE_UTC |"

  if (( DRY_RUN == 1 )); then
    echo "DRY RUN"
    echo "Would create: $TASK_PATH"
    echo "$task_content" | sed -n '1,32p'
    echo "Would append to index: $index_row"
    if [[ "$ID_MODE" == "auto" ]]; then
      echo "Would update counter ${ID_PREFIX} next_id: $next_id -> $((next_id + 1))"
    fi
    echo "Would append change-log entries for create/index/counter"
    exit 0
  fi

  _log "Creating task file: $TASK_PATH"
  printf '%s\n' "$task_content" > "$TASK_PATH"

  printf '%s\n' "$index_row" >> "$INDEX_FILE"

  if [[ "$ID_MODE" == "auto" ]]; then
    local new_next_id=$((next_id + 1))
    update_counter "$ID_PREFIX" "$new_next_id" "$ACTOR" "$MODEL" "$COUNTER_FILE"
    _log "Counter updated: ${ID_PREFIX} next_id $next_id -> $new_next_id"
  fi

  {
    printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "$TASK_ID" "create" "created canonical $DOMAIN task" "$SCRIPT_NAME"
    printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "N/A" "update" "task_index appended $TASK_ID" "$SCRIPT_NAME"
    if [[ "$ID_MODE" == "auto" ]]; then
      printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "$TASK_ID" "update" "counter ${ID_PREFIX} next_id: $next_id->$new_next_id" "$SCRIPT_NAME"
    fi
  } >> "$CHANGE_LOG"

  notify_elucubrate_cache_refresh || true

  _log "Running post-creation validation..."
  if ! "$VALIDATOR" "$DIL_BASE"; then
    _log "POST-CREATION VALIDATION FAILED"
    _output_error 5 "Task $TASK_ID created but post-creation validation failed. File: $TASK_PATH"
    exit 5
  fi

  _log "Task created successfully: $TASK_ID at $TASK_PATH"
  _output "$TASK_ID" "$DOMAIN" "created" "$TASK_PATH"
}

# --- Main dispatch ---
if [[ $# -eq 0 ]]; then
  usage
  exit 2
fi

case "$1" in
  json)
    shift
    cmd_json "$@"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    cmd_create "$@"
    ;;
esac
