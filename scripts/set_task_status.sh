#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TASK_ID=""
NEW_STATUS=""
NEW_OWNER=""
REASON="set_task_status.sh"
ACTOR="codex"
MODEL="gpt-5"
DRY_RUN=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/lib/domains.sh"

usage() {
  cat << 'USAGE'
Usage:
  set_task_status.sh --task-id <ID> --status <STATUS> [options]

Required:
  --task-id ID
  --status todo|assigned|in_progress|blocked|done|cancelled|retired

Options:
  --owner TEXT            Optional owner update
  --reason TEXT           Change reason for log
  --actor TEXT            Default: codex
  --model TEXT            Default: gpt-5
  --base PATH             Default: auto-detected from script location
  --dry-run
  -h, --help
USAGE
}

trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

valid_status() {
  case "$1" in
    todo|assigned|in_progress|blocked|done|cancelled|retired) return 0 ;;
    *) return 1 ;;
  esac
}

valid_transition() {
  local old="$1"
  local new="$2"
  case "$old" in
    todo) [[ "$new" =~ ^(assigned|in_progress|blocked|cancelled|retired)$ ]] ;;
    assigned) [[ "$new" =~ ^(in_progress|blocked|done|cancelled|retired)$ ]] ;;
    in_progress) [[ "$new" =~ ^(blocked|done|assigned|cancelled|retired)$ ]] ;;
    blocked) [[ "$new" =~ ^(in_progress|assigned|cancelled|retired)$ ]] ;;
    done|cancelled) [[ "$new" =~ ^(retired)$ ]] ;;
    retired) [[ "$new" =~ ^(todo|in_progress)$ ]] ;;
    *) return 1 ;;
  esac
}

get_key() {
  local file="$1"
  local key="$2"
  awk -v k="$key" '
    BEGIN {dash=0; inside=0}
    $0=="---" {dash++; if (dash==1) {inside=1; next} if (dash==2) {inside=0}}
    inside && $0 ~ ("^" k ":") {
      sub("^" k ":[[:space:]]*", "", $0)
      print $0
      exit
    }
  ' "$file" | trim | sed -e 's/^"//' -e 's/"$//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --status) NEW_STATUS="${2:-}"; shift 2 ;;
    --owner) NEW_OWNER="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --actor) ACTOR="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

TASK_ID="$(printf '%s' "$TASK_ID" | trim)"
NEW_STATUS="$(printf '%s' "$NEW_STATUS" | trim)"

if [[ -z "$TASK_ID" || -z "$NEW_STATUS" ]]; then
  echo "Missing required args" >&2
  usage
  exit 1
fi

if ! valid_status "$NEW_STATUS"; then
  echo "Invalid --status: $NEW_STATUS" >&2
  exit 1
fi

# Build search dirs dynamically from domain registry
export DIL_BASE="$DIL_BASE"
SEARCH_DIRS=()
while IFS= read -r dom; do
  resolve_domain "$dom"
  active_dir="$TASK_DIR/active"
  if [[ -d "$active_dir" ]]; then
    SEARCH_DIRS+=("$active_dir")
  fi
done < <(list_domains)

INDEX_FILE="$DIL_BASE/_shared/_meta/task_index.md"
CHANGE_LOG="$DIL_BASE/_shared/tasks/_meta/change_log.md"
VALIDATOR="$DIL_BASE/_shared/scripts/validate_tasks.sh"

for req in "$INDEX_FILE" "$CHANGE_LOG" "$VALIDATOR"; do
  if [[ ! -e "$req" ]]; then
    echo "Missing required path: $req" >&2
    exit 1
  fi
done

if [[ ${#SEARCH_DIRS[@]} -eq 0 ]]; then
  echo "No domain task directories found" >&2
  exit 1
fi

mapfile -t matches < <(find "${SEARCH_DIRS[@]}" -maxdepth 1 -type f -name "$TASK_ID.md" | sort)
if [[ ${#matches[@]} -ne 1 ]]; then
  echo "Expected exactly one task file for $TASK_ID, found ${#matches[@]}" >&2
  exit 1
fi
TASK_FILE="${matches[0]}"

domain="$(get_key "$TASK_FILE" domain)"
project="$(get_key "$TASK_FILE" project)"
priority="$(get_key "$TASK_FILE" priority)"
due="$(get_key "$TASK_FILE" due)"
old_status="$(get_key "$TASK_FILE" status)"
old_owner="$(get_key "$TASK_FILE" owner)"

if [[ -z "$old_status" ]]; then
  echo "Task has no status: $TASK_FILE" >&2
  exit 1
fi

if [[ -z "$NEW_OWNER" ]]; then
  NEW_OWNER="$old_owner"
fi

if [[ "$old_status" != "$NEW_STATUS" ]]; then
  if ! valid_transition "$old_status" "$NEW_STATUS"; then
    echo "Invalid status transition: $old_status -> $NEW_STATUS" >&2
    exit 1
  fi
fi

if [[ "$old_status" == "$NEW_STATUS" && "$old_owner" == "$NEW_OWNER" ]]; then
  echo "No changes required for $TASK_ID"
  exit 0
fi

DATE_UTC="$(date -u +%Y-%m-%d)"
TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Derive relative path from actual file location
TASK_REL="${TASK_FILE#"$DIL_BASE/"}"

row="| $TASK_ID | $domain | $NEW_STATUS | $priority | $NEW_OWNER | $due | $project | $TASK_REL | $DATE_UTC |"

field_changes=""
if [[ "$old_status" != "$NEW_STATUS" ]]; then
  field_changes="status: $old_status->$NEW_STATUS"
fi
if [[ "$old_owner" != "$NEW_OWNER" ]]; then
  if [[ -n "$field_changes" ]]; then
    field_changes="$field_changes; "
  fi
  field_changes="${field_changes}owner: $old_owner->$NEW_OWNER"
fi

if (( DRY_RUN == 1 )); then
  echo "DRY RUN"
  echo "Task: $TASK_ID"
  echo "File: $TASK_FILE"
  echo "Change: $field_changes"
  echo "Index row: $row"
  exit 0
fi

LOCKDIR="$DIL_BASE/_shared/tasks/_meta/.status_update.lock"
acquired=0
for _ in $(seq 1 50); do
  if mkdir "$LOCKDIR" 2>/dev/null; then
    acquired=1
    break
  fi
  sleep 0.1
done
if (( acquired == 0 )); then
  echo "Could not acquire lock: $LOCKDIR" >&2
  exit 1
fi
cleanup() {
  rmdir "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT

task_tmp="$(mktemp "$TASK_FILE.tmp.XXXXXX")"
index_tmp="$(mktemp "$INDEX_FILE.tmp.XXXXXX")"
log_tmp="$(mktemp "$CHANGE_LOG.tmp.XXXXXX")"

awk -v st="$NEW_STATUS" -v ow="$NEW_OWNER" -v up="$DATE_UTC" '
  BEGIN {dash=0; inside=0}
  $0=="---" {
    dash++
    if (dash==1) {inside=1; print; next}
    if (dash==2) {inside=0; print; next}
  }
  {
    if (inside && $0 ~ /^status:/) {print "status: " st; next}
    if (inside && $0 ~ /^owner:/) {print "owner: " ow; next}
    if (inside && $0 ~ /^updated:/) {print "updated: " up; next}
    print
  }
' "$TASK_FILE" > "$task_tmp"

awk -v id="$TASK_ID" -v row="$row" '
  BEGIN {updated=0}
  {
    if ($0 ~ "^\\|[[:space:]]*" id "[[:space:]]*\\|") {
      print row
      updated=1
    } else {
      print
    }
  }
  END {
    if (!updated) {
      print row
    }
  }
' "$INDEX_FILE" > "$index_tmp"

cat "$CHANGE_LOG" > "$log_tmp"
printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "$TASK_ID" "update" "$field_changes" "$REASON" >> "$log_tmp"
printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$TS_UTC" "$ACTOR" "$MODEL" "N/A" "update" "task_index updated $TASK_ID" "$REASON" >> "$log_tmp"

mv "$task_tmp" "$TASK_FILE"
mv "$index_tmp" "$INDEX_FILE"
mv "$log_tmp" "$CHANGE_LOG"

"$VALIDATOR"

echo "Updated task: $TASK_ID"
echo "Status: $old_status -> $NEW_STATUS"
if [[ "$old_owner" != "$NEW_OWNER" ]]; then
  echo "Owner: $old_owner -> $NEW_OWNER"
fi
