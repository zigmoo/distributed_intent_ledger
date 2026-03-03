#!/usr/bin/env bash
set -euo pipefail

BASE="/home/moo/Documents/dil_agentic_memory_0001"
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
OWNER="moo"
DUE=""
ACTOR="codex"
MODEL="gpt-5"
DRY_RUN=0
ELUCUBRATE_NOTIFY="${ELUCUBRATE_NOTIFY:-auto}"
ELUCUBRATE_URL="${ELUCUBRATE_URL:-http://127.0.0.1:3000}"

usage() {
  cat << 'USAGE'
Usage:
  create_task.sh --domain work --task-id DMDI-11331 --title "..." --project "..." [options]
  create_task.sh --domain personal --title "..." --project "..." [options]

Required:
  --domain work|personal
  --title TEXT
  --project TEXT

Work-only required:
  --task-id JIRA-KEY      Example: DMDI-11331

Options:
  --subcategory TEXT
  --parent-task-id TEXT   Optional parent task id (DIL-1234 or DMDI-12345)
  --priority low|normal|high|critical
  --status todo|assigned|in_progress|blocked|done|cancelled
  --work-type feature|bug|chore|research|infrastructure
  --task-type kanban|sprint|epic|spike
  --effort-type low|medium|high
  --owner TEXT            Default: moo
  --due YYYY-MM-DD|TEXT
  --actor TEXT            Default: codex
  --model TEXT            Default: gpt-5
  --base PATH             Default: /home/moo/Documents/dil_agentic_memory_0001
  --dry-run
  -h, --help
USAGE
}

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
    low|normal|high|critical) return 0 ;;
    *) return 1 ;;
  esac
}

notify_elucubrate_cache_refresh() {
  case "$ELUCUBRATE_NOTIFY" in
    off|false|0) return 0 ;;
  esac

  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi

  if curl -fsS --max-time 1 "$ELUCUBRATE_URL/api/health" >/dev/null 2>&1; then
    if curl -fsS --max-time 2 -X POST "$ELUCUBRATE_URL/api/cache/refresh" >/dev/null 2>&1; then
      echo "Elucubrate cache refreshed at: $ELUCUBRATE_URL"
    fi
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    --project) PROJECT="${2:-}"; shift 2 ;;
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
    --base) BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

DOMAIN="$(printf '%s' "$DOMAIN" | trim)"
TITLE="$(printf '%s' "$TITLE" | trim)"
PROJECT="$(printf '%s' "$PROJECT" | trim)"
PARENT_TASK_ID="$(printf '%s' "$PARENT_TASK_ID" | trim)"

if [[ -z "$DOMAIN" || -z "$TITLE" || -z "$PROJECT" ]]; then
  echo "Missing required args" >&2
  usage
  exit 1
fi

if [[ "$DOMAIN" != "work" && "$DOMAIN" != "personal" ]]; then
  echo "--domain must be work or personal" >&2
  exit 1
fi

if ! valid_status "$STATUS"; then
  echo "Invalid --status: $STATUS" >&2
  exit 1
fi

if ! valid_priority "$PRIORITY"; then
  echo "Invalid --priority: $PRIORITY" >&2
  exit 1
fi

if [[ -n "$PARENT_TASK_ID" ]] && [[ ! "$PARENT_TASK_ID" =~ ^(DIL-[0-9]+|[A-Z]+-[0-9]+)$ ]]; then
  echo "Invalid --parent-task-id format: $PARENT_TASK_ID" >&2
  exit 1
fi

if [[ -z "$WORK_TYPE" ]]; then
  if [[ "$DOMAIN" == "work" ]]; then
    WORK_TYPE="feature"
  else
    WORK_TYPE="chore"
  fi
fi

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

if ! valid_work_type "$WORK_TYPE"; then
  echo "Invalid --work-type: $WORK_TYPE" >&2
  exit 1
fi

if ! valid_task_type "$TASK_TYPE"; then
  echo "Invalid --task-type: $TASK_TYPE" >&2
  exit 1
fi

if ! valid_effort_type "$EFFORT_TYPE"; then
  echo "Invalid --effort-type: $EFFORT_TYPE" >&2
  exit 1
fi

WORK_DIR="$BASE/_shared/tasks/work"
PERSONAL_DIR="$BASE/_shared/tasks/personal"
INDEX_FILE="$BASE/_shared/_meta/task_index.md"
COUNTER_FILE="$BASE/_shared/_meta/task_id_counter.md"
CHANGE_LOG="$BASE/_shared/tasks/_meta/change_log.md"
VALIDATOR="$BASE/_shared/tasks/_meta/scripts/validate_tasks.sh"

for req in "$WORK_DIR" "$PERSONAL_DIR" "$INDEX_FILE" "$COUNTER_FILE" "$CHANGE_LOG"; do
  if [[ ! -e "$req" ]]; then
    echo "Missing required path: $req" >&2
    exit 1
  fi
done

DATE_UTC="$(date -u +%Y-%m-%d)"
TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ "$DOMAIN" == "work" ]]; then
  if [[ -z "$TASK_ID" ]]; then
    echo "--task-id is required for work tasks" >&2
    exit 1
  fi
  if [[ ! "$TASK_ID" =~ ^[A-Z]+-[0-9]+$ ]]; then
    echo "Invalid work task id format: $TASK_ID" >&2
    exit 1
  fi
  TASK_PATH="$WORK_DIR/$TASK_ID.md"
else
  if [[ -n "$TASK_ID" ]]; then
    echo "Do not pass --task-id for personal tasks; it is allocated automatically" >&2
    exit 1
  fi
  next_id="$(awk -F: '/^- next_id:/ {gsub(/ /, "", $2); print $2; exit}' "$COUNTER_FILE")"
  if [[ -z "$next_id" || ! "$next_id" =~ ^[0-9]+$ ]]; then
    echo "Invalid next_id in $COUNTER_FILE" >&2
    exit 1
  fi
  TASK_ID="DIL-$next_id"
  TASK_PATH="$PERSONAL_DIR/$TASK_ID.md"
fi

if [[ -n "$PARENT_TASK_ID" ]]; then
  if [[ "$PARENT_TASK_ID" == "$TASK_ID" ]]; then
    echo "--parent-task-id cannot equal task_id ($TASK_ID)" >&2
    exit 1
  fi
  if [[ ! -f "$WORK_DIR/$PARENT_TASK_ID.md" && ! -f "$PERSONAL_DIR/$PARENT_TASK_ID.md" ]]; then
    echo "--parent-task-id not found in canonical tasks: $PARENT_TASK_ID" >&2
    exit 1
  fi
fi

if [[ -e "$TASK_PATH" ]]; then
  echo "Task file already exists: $TASK_PATH" >&2
  exit 1
fi

if rg -q "^\|[[:space:]]*$TASK_ID[[:space:]]*\|" "$INDEX_FILE"; then
  echo "Task ID already present in index: $TASK_ID" >&2
  exit 1
fi

TASK_REL="_shared/tasks/$DOMAIN/$TASK_ID.md"

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
-

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
  if [[ "$DOMAIN" == "personal" ]]; then
    echo "Would update counter next_id: $next_id -> $((next_id + 1))"
  fi
  echo "Would append change-log entries for create/index/counter"
  exit 0
fi

printf '%s\n' "$task_content" > "$TASK_PATH"

printf '%s\n' "$index_row" >> "$INDEX_FILE"

if [[ "$DOMAIN" == "personal" ]]; then
  new_next_id=$((next_id + 1))
  sed -i "s/^- next_id: .*/- next_id: $new_next_id/" "$COUNTER_FILE"
  sed -i "s/^- last_allocator: .*/- last_allocator: $ACTOR/" "$COUNTER_FILE"
  if rg -q "^- last_model:" "$COUNTER_FILE"; then
    sed -i "s/^- last_model: .*/- last_model: $MODEL/" "$COUNTER_FILE"
  else
    printf '%s\n' "- last_model: $MODEL" >> "$COUNTER_FILE"
  fi
fi

{
  printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "$TASK_ID" "create" "created canonical $DOMAIN task" "create_task.sh"
  printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "N/A" "update" "task_index appended $TASK_ID" "create_task.sh"
  if [[ "$DOMAIN" == "personal" ]]; then
    printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "$TASK_ID" "update" "counter next_id: $next_id->$new_next_id" "create_task.sh"
  fi
} >> "$CHANGE_LOG"

notify_elucubrate_cache_refresh || true

"$VALIDATOR" "$BASE"

echo "Created task: $TASK_ID"
echo "Path: $TASK_PATH"
