#!/usr/bin/env bash
set -euo pipefail

BASE="/home/moo/Documents/dil_agentic_memory_0001"
TASK_ID=""
OWNER=""
REASON="assign_task.sh"
ACTOR="codex"
MODEL="gpt-5"
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  assign_task.sh --task-id <ID> --owner <OWNER> [options]

Required:
  --task-id ID
  --owner OWNER

Options:
  --reason TEXT           Change reason for log
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
    --owner) OWNER="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --actor) ACTOR="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --base) BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

TASK_ID="$(printf '%s' "$TASK_ID" | trim)"
OWNER="$(printf '%s' "$OWNER" | trim)"

if [[ -z "$TASK_ID" || -z "$OWNER" ]]; then
  echo "Missing required args" >&2
  usage
  exit 1
fi

WORK_DIR="$BASE/_shared/tasks/work"
PERSONAL_DIR="$BASE/_shared/tasks/personal"
STATUS_SCRIPT="$BASE/_shared/scripts/set_task_status.sh"

for req in "$WORK_DIR" "$PERSONAL_DIR" "$STATUS_SCRIPT"; do
  if [[ ! -e "$req" ]]; then
    echo "Missing required path: $req" >&2
    exit 1
  fi
done

mapfile -t matches < <(find "$WORK_DIR" "$PERSONAL_DIR" -maxdepth 1 -type f -name "$TASK_ID.md" | sort)
if [[ ${#matches[@]} -ne 1 ]]; then
  echo "Expected exactly one task file for $TASK_ID, found ${#matches[@]}" >&2
  exit 1
fi
TASK_FILE="${matches[0]}"
current_status="$(get_key "$TASK_FILE" status)"

if [[ -z "$current_status" ]]; then
  echo "Task has no status: $TASK_FILE" >&2
  exit 1
fi

cmd=(
  "$STATUS_SCRIPT"
  --base "$BASE"
  --task-id "$TASK_ID"
  --status "$current_status"
  --owner "$OWNER"
  --reason "$REASON"
  --actor "$ACTOR"
  --model "$MODEL"
)

if (( DRY_RUN == 1 )); then
  cmd+=(--dry-run)
fi

"${cmd[@]}"
