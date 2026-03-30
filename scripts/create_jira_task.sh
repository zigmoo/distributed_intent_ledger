#!/usr/bin/env bash
set -euo pipefail

# create_jira_task.sh — Create a Jira ticket and mirror it as a DIL active task.
#
# Usage:
#   create_jira_task.sh --summary "Title" [jira opts] [dil opts]
#
# Jira options (passed to jira_tool create):
#   --summary TEXT        Ticket title (required)
#   --description TEXT    Ticket body
#   --assignee ID         Ignition ID
#   --priority NAME       Highest|High|Medium|Low|Lowest (Jira values)
#   --epic EPIC-KEY       Epic Link (e.g. PROJ-8850)
#
# DIL options (passed to create_task.sh):
#   --project TEXT        DIL project slug (required)
#   --dil-priority TEXT   DIL priority: low|normal|medium|high|critical (default: normal)
#   --work-type TEXT      feature|bug|chore|research|infrastructure (default: chore)
#   --task-type TEXT      kanban|sprint|epic|spike (default: kanban)
#   --effort-type TEXT    low|medium|high (default: medium)
#   --parent-task-id TEXT Optional parent task
#   --due TEXT            Due date
#   --dil-summary TEXT    Populate DIL Summary section (defaults to --description)
#
# Output:
#   OK | <JIRA-KEY> | jira created | dil created | <DIL-PATH>
#   ERR | <stage> | <message>
#
# Requires: jira_tool, create_task.sh

DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
JIRA_TOOL="/path/to/jira_tool"
CREATE_TASK="$DIL_BASE/_shared/scripts/create_task.sh"

# --- Parse args into jira vs dil buckets ---
SUMMARY=""
DESCRIPTION=""
ASSIGNEE=""
JIRA_PRIORITY=""
EPIC=""
PROJECT=""
DIL_PRIORITY="normal"
WORK_TYPE="chore"
TASK_TYPE="kanban"
EFFORT_TYPE="medium"
PARENT_TASK_ID=""
DUE=""
DIL_SUMMARY=""
DRY_RUN=0

print_help() {
  sed -n '3,/^$/p' "$0" | sed 's/^# \?//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --summary)        SUMMARY="$2"; shift 2 ;;
    --description)    DESCRIPTION="$2"; shift 2 ;;
    --assignee)       ASSIGNEE="$2"; shift 2 ;;
    --priority)       JIRA_PRIORITY="$2"; shift 2 ;;
    --epic)           EPIC="$2"; shift 2 ;;
    --project)        PROJECT="$2"; shift 2 ;;
    --dil-priority)   DIL_PRIORITY="$2"; shift 2 ;;
    --work-type)      WORK_TYPE="$2"; shift 2 ;;
    --task-type)      TASK_TYPE="$2"; shift 2 ;;
    --effort-type)    EFFORT_TYPE="$2"; shift 2 ;;
    --parent-task-id) PARENT_TASK_ID="$2"; shift 2 ;;
    --due)            DUE="$2"; shift 2 ;;
    --dil-summary)    DIL_SUMMARY="$2"; shift 2 ;;
    --dry-run)        DRY_RUN=1; shift ;;
    -h|--help)        print_help ;;
    *)                echo "ERR | args | Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# --- Validate required args ---
if [[ -z "$SUMMARY" ]]; then
  echo "ERR | args | --summary is required" >&2
  exit 2
fi

if [[ -z "$PROJECT" ]]; then
  echo "ERR | args | --project is required (DIL project slug)" >&2
  exit 2
fi

# --- Build jira_tool create command ---
jira_args=(create --summary "$SUMMARY")
[[ -n "$DESCRIPTION" ]]  && jira_args+=(--description "$DESCRIPTION")
[[ -n "$ASSIGNEE" ]]      && jira_args+=(--assignee "$ASSIGNEE")
[[ -n "$JIRA_PRIORITY" ]] && jira_args+=(--priority "$JIRA_PRIORITY")
[[ -n "$EPIC" ]]          && jira_args+=(--epic "$EPIC")

# --- Step 1: Create Jira ticket ---
if (( DRY_RUN )); then
  echo "[dry-run] Would run: jira_tool ${jira_args[*]}"
  echo "[dry-run] Would run: create_task.sh --domain work --title \"$SUMMARY\" --project \"$PROJECT\" --task-id <JIRA-KEY>"
  exit 0
fi

jira_output=$("$JIRA_TOOL" "${jira_args[@]}" 2>&1)
jira_exit=$?

if [[ $jira_exit -ne 0 ]] || [[ ! "$jira_output" =~ ^OK ]]; then
  echo "ERR | jira | jira_tool create failed: $jira_output" >&2
  exit 3
fi

# Parse: "OK | PROJ-11906 | created"
JIRA_KEY=$(echo "$jira_output" | awk -F' \\| ' '{print $2}' | tr -d ' ')

if [[ -z "$JIRA_KEY" ]]; then
  echo "ERR | jira | Could not parse ticket key from: $jira_output" >&2
  exit 3
fi

# --- Step 2: Create DIL task mirroring the Jira ticket ---
dil_args=(--domain work --title "$SUMMARY" --project "$PROJECT" --task-id "$JIRA_KEY")
dil_args+=(--priority "$DIL_PRIORITY")
dil_args+=(--work-type "$WORK_TYPE")
dil_args+=(--task-type "$TASK_TYPE")
dil_args+=(--effort-type "$EFFORT_TYPE")
[[ -n "$PARENT_TASK_ID" ]] && dil_args+=(--parent-task-id "$PARENT_TASK_ID")
[[ -n "$DUE" ]]            && dil_args+=(--due "$DUE")
[[ -n "$DIL_SUMMARY" ]]    && dil_args+=(--summary "$DIL_SUMMARY")
[[ -z "$DIL_SUMMARY" && -n "$DESCRIPTION" ]] && dil_args+=(--summary "$DESCRIPTION")

dil_output=$("$CREATE_TASK" "${dil_args[@]}" 2>&1)
dil_exit=$?

# Exit code 5 = created but post-validation warnings (index drift) — treat as success
if [[ $dil_exit -ne 0 && $dil_exit -ne 5 ]]; then
  echo "ERR | dil | Jira ticket $JIRA_KEY created, but DIL task creation failed: $dil_output" >&2
  exit 4
fi

# Parse DIL path from output: "OK | PROJ-11906 | work | todo | <path>"
dil_path=$(echo "$dil_output" | grep '^OK' | awk -F' \\| ' '{print $5}' | tr -d ' ')

echo "OK | $JIRA_KEY | jira created | dil created | ${dil_path:-unknown}"
