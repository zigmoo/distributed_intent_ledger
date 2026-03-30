#!/usr/bin/env bash
# file path: _shared/scripts/task_tool.sh (canonical)
#
# task_tool — Fast task discovery and filtering against the DIL task index
#
# Subcommands:
#   search     Filter and list tasks from the index (default if omitted)
#   review     Show full task file contents for a single task
#
# Usage:
#   task_tool search [--status STATUS] [--project SLUG] [--domain DOMAIN] [--latest N] [--count] [--json]
#   task_tool review <TASK_ID> [--json]
#
# Output:
#   search (TTY):    clickable task_id | domain | status | priority | owner | due | project | updated
#   search (piped):  task_id | domain | status | priority | owner | due | project | path | updated
#   search (--json): {"ok":true,"count":N,"data":[...]}
#   review (TTY):    key-value frontmatter + body
#   review (--json): {"ok":true,"data":{...}}
#
# Filters (search mode, combinable with AND logic):
#   --status    Comma-separated status values (e.g. todo,in_progress)
#   --project   Exact project slug match
#   --domain    Registered domain name
#   --latest    Top N results by descending updated date
#   --count     Print match count only
#
# Clickable task IDs:
#   When stdout is a TTY, task IDs are wrapped in OSC 8 hyperlinks.
#   URLs are resolved via url_tool using the domain_registry ticket_systems.
#   Work-domain IDs link to Jira; personal/triv IDs link to Obsidian.
#
# Exit codes:
#   0  Success (including zero matches)
#   2  Invalid arguments
#   4  Missing prerequisite (index + domain registry both unavailable)
#
# Contract:
#   - Index-first: reads task_index.md, never scans task bodies in search mode
#   - Fallback: if index is missing, scans domain active/ dirs
#   - Delegates all URL formatting to url_tool.sh
#   - Sources lib/domains.sh for domain validation
#
# Related:
#   - DIL-1414: contract/spec task
#   - DIL-1413: implementation task

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
INDEX_FILE="$DIL_BASE/_shared/_meta/task_index.md"
URL_TOOL="$SCRIPT_DIR/url_tool.sh"

# Force url_tool to use the DIL registry (not the scripts-library work-only copy)
export URL_TOOL_REGISTRY="$DIL_BASE/_shared/_meta/domain_registry.json"

# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/lib/domains.sh"

# --- globals ---
OUTPUT_MODE="text"
FILTER_STATUS=""
FILTER_PROJECT=""
FILTER_DOMAIN=""
LATEST=0
COUNT_ONLY=0
IS_TTY=0
[[ -t 1 ]] && IS_TTY=1

# --- helpers ---

die() { echo "ERR | ${2:-2} | $1" >&2; exit "${2:-2}"; }

usage() {
  cat <<'EOF'
task_tool — Fast task discovery and filtering

Usage:
  task_tool search [--status STATUS] [--project SLUG] [--domain DOMAIN] [--latest N] [--count] [--json]
  task_tool review <TASK_ID> [--json]

Search filters (combinable, AND logic):
  --status    Comma-separated: todo,in_progress,blocked,assigned,done,cancelled,retired
  --project   Exact project slug
  --domain    Registered domain name (personal, work, triv, ...)
  --latest N  Top N by most recently updated
  --count     Print match count only

Options:
  --json      JSON output
  -h, --help  Show this help
EOF
  exit 0
}

# Wrap a task ID in an OSC 8 clickable link (TTY only)
linkify_task_id() {
  local task_id="$1"
  if (( IS_TTY )) && [[ -x "$URL_TOOL" ]]; then
    local url
    url=$("$URL_TOOL" ticket "$task_id" --plain 2>/dev/null) || true
    if [[ -n "$url" ]]; then
      printf '\e]8;;%s\e\\%s\e]8;;\e\\' "$url" "$task_id"
      return
    fi
  fi
  printf '%s' "$task_id"
}

# Extract frontmatter value from a task file
get_key() {
  local file="$1" key="$2"
  awk -v k="$key" '
    BEGIN {dash=0; inside=0}
    $0=="---" {dash++; if (dash==1) {inside=1; next} if (dash==2) {inside=0}}
    inside && $0 ~ ("^" k ":") {
      sub("^" k ":[[:space:]]*", "", $0)
      print $0
      exit
    }
  ' "$file" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//'
}

# Extract body (everything after second ---) from a task file
get_body() {
  local file="$1"
  awk '
    BEGIN {dash=0}
    $0=="---" {dash++; if (dash==2) {getline; found=1}; next}
    found {print}
  ' "$file"
}

# --- search ---

cmd_search() {
  if [[ ! -f "$INDEX_FILE" ]]; then
    die "Index not found: $INDEX_FILE — run rebuild_task_index.sh" 4
  fi

  # Read index rows (skip header + separator)
  local rows=()
  while IFS= read -r line; do
    # Skip frontmatter
    [[ "$line" == "---" ]] && continue
    # Skip non-table lines
    [[ "$line" != \|* ]] && continue
    # Skip header row and separator
    [[ "$line" == *"task_id"*"domain"*"status"* ]] && continue
    [[ "$line" == \|*---* ]] && continue
    rows+=("$line")
  done < "$INDEX_FILE"

  # Apply filters
  local filtered=()
  for row in "${rows[@]}"; do
    # Parse pipe-delimited fields (trim whitespace)
    IFS='|' read -ra cols <<< "$row"
    # cols[0] is empty (leading pipe), fields start at 1
    local task_id domain status priority owner due project path updated
    task_id="$(echo "${cols[1]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    domain="$(echo "${cols[2]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    status="$(echo "${cols[3]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    priority="$(echo "${cols[4]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    owner="$(echo "${cols[5]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    due="$(echo "${cols[6]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    project="$(echo "${cols[7]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    path="$(echo "${cols[8]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    updated="$(echo "${cols[9]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

    # Filter: status (comma-separated match)
    if [[ -n "$FILTER_STATUS" ]]; then
      local match=0
      IFS=',' read -ra statuses <<< "$FILTER_STATUS"
      for s in "${statuses[@]}"; do
        [[ "$status" == "$s" ]] && match=1 && break
      done
      (( match )) || continue
    fi

    # Filter: project
    if [[ -n "$FILTER_PROJECT" && "$project" != "$FILTER_PROJECT" ]]; then
      continue
    fi

    # Filter: domain
    if [[ -n "$FILTER_DOMAIN" && "$domain" != "$FILTER_DOMAIN" ]]; then
      continue
    fi

    filtered+=("$updated|$task_id|$domain|$status|$priority|$owner|$due|$project|$path")
  done

  # Sort by updated descending
  local sorted=()
  if [[ ${#filtered[@]} -gt 0 ]]; then
    mapfile -t sorted < <(printf '%s\n' "${filtered[@]}" | sort -t'|' -k1,1r)
  fi

  # Apply --latest
  if (( LATEST > 0 )) && [[ ${#sorted[@]} -gt $LATEST ]]; then
    sorted=("${sorted[@]:0:$LATEST}")
  fi

  # Output
  local count=${#sorted[@]}

  if (( COUNT_ONLY )); then
    if [[ "$OUTPUT_MODE" == "json" ]]; then
      printf '{"ok":true,"count":%d}\n' "$count"
    else
      echo "$count"
    fi
    return
  fi

  if [[ "$OUTPUT_MODE" == "json" ]]; then
    local json_items=()
    for entry in "${sorted[@]}"; do
      IFS='|' read -r updated task_id domain status priority owner due project path <<< "$entry"
      json_items+=("$(jq -n \
        --arg ti "$task_id" --arg do "$domain" --arg st "$status" \
        --arg pr "$priority" --arg ow "$owner" --arg du "$due" \
        --arg pj "$project" --arg pa "$path" --arg up "$updated" \
        '{task_id:$ti,domain:$do,status:$st,priority:$pr,owner:$ow,due:$du,project:$pj,path:$pa,updated:$up}')")
    done
    local joined
    joined=$(printf '%s\n' "${json_items[@]}" | jq -s '.')
    jq -n --argjson c "$count" --argjson d "$joined" '{ok:true,count:$c,data:$d}'
    return
  fi

  # Text output
  for entry in "${sorted[@]}"; do
    IFS='|' read -r updated task_id domain status priority owner due project path <<< "$entry"
    local display_id
    display_id="$(linkify_task_id "$task_id")"
    if (( IS_TTY )); then
      # TTY: omit path (it's in the link), show remaining fields
      printf '%s | %s | %s | %s | %s | %s | %s | %s\n' \
        "$display_id" "$domain" "$status" "$priority" "$owner" "$due" "$project" "$updated"
    else
      # Piped: include path, bare task_id
      printf '%s | %s | %s | %s | %s | %s | %s | %s | %s\n' \
        "$task_id" "$domain" "$status" "$priority" "$owner" "$due" "$project" "$path" "$updated"
    fi
  done
}

# --- review ---

cmd_review() {
  local task_id="$1"
  [[ -n "$task_id" ]] || die "Usage: task_tool review <TASK_ID>" 2

  # Find the task file via index
  local task_path=""
  if [[ -f "$INDEX_FILE" ]]; then
    task_path=$(awk -v id="$task_id" -F'|' '
      {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
        if ($2 == id) {
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", $9)
          print $9
          exit
        }
      }
    ' "$INDEX_FILE")
  fi

  local task_file=""
  if [[ -n "$task_path" ]]; then
    task_file="$DIL_BASE/$task_path"
  fi

  # Fallback: scan domain dirs
  if [[ -z "$task_file" || ! -f "$task_file" ]]; then
    export DIL_BASE="$DIL_BASE"
    local found=()
    while IFS= read -r dom; do
      resolve_domain "$dom"
      local candidate="$TASK_DIR/active/$task_id.md"
      [[ -f "$candidate" ]] && found+=("$candidate")
    done < <(list_domains)
    if [[ ${#found[@]} -eq 1 ]]; then
      task_file="${found[0]}"
    elif [[ ${#found[@]} -eq 0 ]]; then
      die "task not found: $task_id" 2
    else
      die "multiple files found for $task_id" 2
    fi
  fi

  if [[ ! -f "$task_file" ]]; then
    die "task not found: $task_id" 2
  fi

  # Review fields to display (suppress constant/structural fields)
  local display_keys=(task_id title date domain status priority owner due project
    work_type task_type effort_type created_by created_at parent_task_id subcategory)

  if [[ "$OUTPUT_MODE" == "json" ]]; then
    local json_obj="{}"
    for key in "${display_keys[@]}"; do
      local val
      val="$(get_key "$task_file" "$key")"
      json_obj=$(printf '%s' "$json_obj" | jq --arg k "$key" --arg v "$val" '.[$k] = $v')
    done
    local body
    body="$(get_body "$task_file")"
    json_obj=$(printf '%s' "$json_obj" | jq --arg b "$body" '.body = $b')
    jq -n --argjson d "$json_obj" '{ok:true,data:$d}'
    return
  fi

  # Text output
  for key in "${display_keys[@]}"; do
    local val
    val="$(get_key "$task_file" "$key")"
    printf '%s: %s\n' "$key" "$val"
  done
  echo "---"
  get_body "$task_file"
}

# --- main ---

main() {
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)    OUTPUT_MODE="json"; shift ;;
      --status)  FILTER_STATUS="${2:-}"; shift 2 ;;
      --project) FILTER_PROJECT="${2:-}"; shift 2 ;;
      --domain)  FILTER_DOMAIN="${2:-}"; shift 2 ;;
      --latest)  LATEST="${2:-0}"; shift 2 ;;
      --count)   COUNT_ONLY=1; shift ;;
      -h|--help) usage ;;
      *)         args+=("$1"); shift ;;
    esac
  done
  set -- "${args[@]+"${args[@]}"}"

  local cmd="${1:-search}"
  shift || true

  # Validate domain filter if provided
  if [[ -n "$FILTER_DOMAIN" ]]; then
    export DIL_BASE="$DIL_BASE"
    if ! domain_exists "$FILTER_DOMAIN"; then
      die "unknown domain: $FILTER_DOMAIN" 2
    fi
  fi

  case "$cmd" in
    search)  cmd_search ;;
    review)  cmd_review "${1:-}" ;;
    -h|--help) usage ;;
    *)       die "Unknown subcommand: $cmd. Run 'task_tool --help' for usage." 2 ;;
  esac
}

main "$@"
