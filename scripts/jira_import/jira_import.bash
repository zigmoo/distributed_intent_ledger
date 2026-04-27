#!/usr/bin/env bash
set -euo pipefail

# jira_import.sh - Import Jira tickets as Distributed Intent Ledger (DIL) work tasks
# Fetches ticket details from Jira REST API and creates tasks via task_tool create
#
# Prerequisites:
#   - getSecret command available (for Jira token)
#   - jq installed
#   - task_tool in PATH
#
# Usage:
#   jira_import.sh --assignee 10831728                     # Import all open tickets for assignee
#   jira_import.sh --jql "project=DMDI AND status=Backlog" # Import by JQL
#   jira_import.sh --ticket DMDI-10927                     # Import single ticket
#   jira_import.sh --ticket DMDI-10927,DMDI-10926          # Import multiple tickets
#   jira_import.sh --assignee 10831728 --dry-run           # Preview without creating

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
JIRA_URL="https://jira.autozone.com"
# task_tool is called via PATH (extensionless symlink in bin/)
INDEX_FILE="$BASE/_shared/_meta/task_index.md"
TOKEN_CACHE="/tmp/jira_token_temp.txt"

ASSIGNEE=""
JQL=""
TICKETS=""
DRY_RUN=0
MAX_RESULTS=100
ACTOR="claude-code"
MODEL="claude-opus-4-6"
OWNER="charlie"
SKIP_EXISTING=1

usage() {
  cat << 'USAGE'
Usage:
  jira_import.sh --assignee <id>                  Import open tickets for Jira assignee
  jira_import.sh --jql "<jql-query>"              Import tickets matching JQL
  jira_import.sh --ticket <KEY>[,<KEY>,...]       Import specific ticket(s)

Options:
  --dry-run           Preview mappings without creating tasks
  --max-results N     Max tickets to fetch (default: 100)
  --actor TEXT        Actor for task_tool create (default: claude-code)
  --model TEXT        Model for task_tool create (default: claude-opus-4-6)
  --owner TEXT        Owner for tasks (default: charlie)
  --no-skip-existing  Error on existing instead of skipping
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --assignee) ASSIGNEE="${2:-}"; shift 2 ;;
    --jql) JQL="${2:-}"; shift 2 ;;
    --ticket) TICKETS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --max-results) MAX_RESULTS="${2:-100}"; shift 2 ;;
    --actor) ACTOR="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --owner) OWNER="${2:-}"; shift 2 ;;
    --no-skip-existing) SKIP_EXISTING=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$ASSIGNEE" && -z "$JQL" && -z "$TICKETS" ]]; then
  echo "Must specify --assignee, --jql, or --ticket" >&2
  usage
  exit 1
fi

# --- Token ---
ensure_token() {
  if [[ -f "$TOKEN_CACHE" ]] && [[ -s "$TOKEN_CACHE" ]]; then
    cat "$TOKEN_CACHE"
    return
  fi
  if command -v getSecret &>/dev/null; then
    getSecret z_az_jira_personal_access_token 2>&1 | grep -v "^Retrieving" | grep -v "^Secret:" > "$TOKEN_CACHE"
    cat "$TOKEN_CACHE"
  else
    echo "getSecret not found and no cached token" >&2
    exit 1
  fi
}

TOKEN="$(ensure_token)"
if [[ -z "$TOKEN" ]]; then
  echo "Failed to retrieve Jira token" >&2
  exit 1
fi

# --- Build JQL ---
if [[ -n "$TICKETS" ]]; then
  # Convert comma-separated tickets to JQL IN clause
  ticket_list=""
  IFS=',' read -r -a ticket_arr <<< "$TICKETS"
  for t in "${ticket_arr[@]}"; do
    t="$(echo "$t" | xargs)"
    if [[ -n "$ticket_list" ]]; then
      ticket_list="$ticket_list,$t"
    else
      ticket_list="$t"
    fi
  done
  JQL="key IN ($ticket_list)"
elif [[ -n "$ASSIGNEE" ]]; then
  JQL="assignee=$ASSIGNEE AND status NOT IN (Done,Closed,Cancelled)"
fi
# else JQL is already set from --jql

# --- Fetch tickets ---
ENCODED_JQL="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$JQL")"
RESPONSE_FILE="$(mktemp /tmp/jira_import_XXXXXX.json)"
trap "rm -f '$RESPONSE_FILE'" EXIT

curl -s -X GET \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$JIRA_URL/rest/api/2/search?jql=$ENCODED_JQL&maxResults=$MAX_RESULTS" > "$RESPONSE_FILE"

TOTAL="$(jq '.total // 0' "$RESPONSE_FILE")"
COUNT="$(jq '.issues | length' "$RESPONSE_FILE")"

echo "Jira query returned $COUNT of $TOTAL tickets"
echo "JQL: $JQL"
echo ""

if [[ "$COUNT" -eq 0 ]]; then
  echo "No tickets to import."
  exit 0
fi

# --- Priority mapping ---
# Highest/High → high, Medium → normal, Low/Lowest → low
map_priority() {
  case "$1" in
    Highest|High) echo "high" ;;
    Medium)       echo "normal" ;;
    Low|Lowest)   echo "low" ;;
    *)            echo "normal" ;;
  esac
}

# --- Status mapping ---
# Best-guess per ticket; include original in description
map_status() {
  case "$1" in
    "In Progress"|"Code Review") echo "in_progress" ;;
    "Blocked / In Waiting"|"Blocked") echo "blocked" ;;
    "Backlog"|"To Do"|"Open"|"New") echo "todo" ;;
    "Done"|"Closed"|"Resolved") echo "done" ;;
    "Cancelled") echo "cancelled" ;;
    *) echo "todo" ;;
  esac
}

# --- Project derivation from summary prefix ---
derive_project() {
  local summary="$1"
  local prefix
  # Extract prefix pattern like "AUTOMATION:", "RESEARCH:", "DECOMM:", etc.
  prefix="$(echo "$summary" | grep -oP '^[A-Z][A-Z /\-]+(?=:)' | head -1 | xargs 2>/dev/null || true)"
  case "$prefix" in
    "AUTOMATION"|"AUTOMATION SUPPORT") echo "autozone-automation" ;;
    "AUTOMATION-POD")                  echo "autozone-automation-pod" ;;
    "AUTOMATION/ARCH")                 echo "autozone-architecture" ;;
    "ARCH"|"ARCH SUPPORT")             echo "autozone-architecture" ;;
    "RESEARCH")                        echo "autozone-research" ;;
    "DECOMM")                          echo "autozone-decommission" ;;
    "SERVER ADMIN")                    echo "autozone-server-admin" ;;
    "GPG Update")                      echo "autozone-gpg" ;;
    *)                                 echo "autozone-general" ;;
  esac
}

# --- Clean title: strip prefix ---
clean_title() {
  local summary="$1"
  # Remove leading prefix like "AUTOMATION: " or "RESEARCH: "
  echo "$summary" | sed -E 's/^[A-Z][A-Z /\-]+:[[:space:]]*//'
}

# --- Process tickets ---
created=0
skipped=0
failed=0
errors=""

for i in $(seq 0 $((COUNT - 1))); do
  key="$(jq -r ".issues[$i].key" "$RESPONSE_FILE")"
  summary="$(jq -r ".issues[$i].fields.summary" "$RESPONSE_FILE")"
  jira_status="$(jq -r ".issues[$i].fields.status.name" "$RESPONSE_FILE")"
  jira_priority="$(jq -r ".issues[$i].fields.priority.name" "$RESPONSE_FILE")"

  mapped_priority="$(map_priority "$jira_priority")"
  mapped_status="$(map_status "$jira_status")"
  project="$(derive_project "$summary")"
  title="$(clean_title "$summary")"

  # Check if already in index
  if rg -q "^\|[[:space:]]*${key}[[:space:]]*\|" "$INDEX_FILE" 2>/dev/null; then
    if (( SKIP_EXISTING == 1 )); then
      echo "SKIP  $key (already in task index)"
      skipped=$((skipped + 1))
      continue
    else
      echo "ERROR $key already exists" >&2
      failed=$((failed + 1))
      continue
    fi
  fi

  if (( DRY_RUN == 1 )); then
    printf "DRY   %-14s  %-12s→%-12s  %-8s→%-7s  project=%-28s  %s\n" \
      "$key" "$jira_status" "$mapped_status" "$jira_priority" "$mapped_priority" "$project" "$title"
    created=$((created + 1))
    continue
  fi

  # Create task
  if output="$(task_tool --base "$BASE" create \
    --domain work \
    --task-id "$key" \
    --title "$title" \
    --project "$project" \
    --priority "$mapped_priority" \
    --status "$mapped_status" \
    --owner "$OWNER" \
    --actor "$ACTOR" \
    --model "$MODEL" 2>&1)"; then
    # Append raw Jira JSON to task file body
    task_file="$BASE/_shared/domains/work/tasks/active/$key.md"
    if [[ -f "$task_file" ]]; then
      {
        echo ""
        echo "## Jira Source Data"
        echo ""
        echo "Original Jira status: \`$jira_status\`"
        echo ""
        echo '```json'
        jq ".issues[$i]" "$RESPONSE_FILE"
        echo '```'
      } >> "$task_file"
    fi
    echo "OK    $key  →  $mapped_status/$mapped_priority  $title"
    created=$((created + 1))
  else
    echo "FAIL  $key: $output" >&2
    errors="$errors\n$key: $output"
    failed=$((failed + 1))
  fi
done

echo ""
echo "=== Import Summary ==="
if (( DRY_RUN == 1 )); then
  echo "Mode:    DRY RUN (no tasks created)"
  echo "Would create: $created"
else
  echo "Created: $created"
fi
echo "Skipped: $skipped (already exist)"
echo "Failed:  $failed"
if [[ -n "$errors" ]]; then
  echo ""
  echo "Errors:"
  printf '%b\n' "$errors"
fi
