#!/usr/bin/env bash
set -euo pipefail

# list_archived.sh — Search and list archived tasks
# Usage: list_archived.sh [--domain DOMAIN] [--year YEAR] [--grep PATTERN] [--status STATUS] [--json]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Source domain registry
source "$SCRIPT_DIR/lib/domains.sh"

FILTER_DOMAIN=""
FILTER_YEAR=""
FILTER_GREP=""
FILTER_STATUS=""
JSON_OUTPUT=0

usage() {
  cat << 'USAGE'
Usage:
  list_archived.sh [options]

Options:
  --domain DOMAIN    Filter by domain (e.g., personal, work, triv)
  --year YEAR        Filter by archive year (e.g., 2026)
  --grep PATTERN     Filter by pattern in task_id or title
  --status STATUS    Filter by status (done, cancelled, retired)
  --json             Output as JSON array
  -h, --help         Show this help

Examples:
  list_archived.sh --domain personal --year 2026
  list_archived.sh --grep triv
  list_archived.sh --domain work --status retired --json
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) FILTER_DOMAIN="${2:-}"; shift 2 ;;
    --year) FILTER_YEAR="${2:-}"; shift 2 ;;
    --grep) FILTER_GREP="${2:-}"; shift 2 ;;
    --status) FILTER_STATUS="${2:-}"; shift 2 ;;
    --json) JSON_OUTPUT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

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

# Collect domains to scan
if [[ -n "$FILTER_DOMAIN" ]]; then
  domains=("$FILTER_DOMAIN")
else
  mapfile -t domains < <(list_domains)
fi

count=0
json_items=()

for domain in "${domains[@]}"; do
  if ! resolve_domain "$domain" 2>/dev/null; then
    continue
  fi

  archived_base="$TASK_DIR/archived"
  [[ -d "$archived_base" ]] || continue

  for year_dir in "$archived_base"/*/; do
    [[ -d "$year_dir" ]] || continue
    year="$(basename "$year_dir")"

    if [[ -n "$FILTER_YEAR" && "$year" != "$FILTER_YEAR" ]]; then
      continue
    fi

    for f in "$year_dir"/*.md; do
      [[ -f "$f" ]] || continue
      [[ "$(basename "$f")" == "index.md" ]] && continue

      task_id="$(get_key "$f" task_id)"
      title="$(get_key "$f" title)"
      status="$(get_key "$f" status)"
      updated="$(get_key "$f" updated)"
      project="$(get_key "$f" project)"

      if [[ -n "$FILTER_STATUS" && "$status" != "$FILTER_STATUS" ]]; then
        continue
      fi

      if [[ -n "$FILTER_GREP" ]]; then
        if ! echo "$task_id $title $project" | grep -qi "$FILTER_GREP"; then
          continue
        fi
      fi

      if (( JSON_OUTPUT )); then
        json_items+=("{\"task_id\":\"$task_id\",\"domain\":\"$domain\",\"year\":\"$year\",\"status\":\"$status\",\"title\":\"$title\",\"project\":\"$project\",\"updated\":\"$updated\"}")
      else
        printf '| %s | %s | %s | %s | %s | %s |\n' "$task_id" "$domain" "$year" "$status" "$title" "$updated"
      fi
      count=$((count + 1))
    done
  done
done

if (( JSON_OUTPUT )); then
  printf '[\n'
  for i in "${!json_items[@]}"; do
    if (( i < ${#json_items[@]} - 1 )); then
      printf '  %s,\n' "${json_items[$i]}"
    else
      printf '  %s\n' "${json_items[$i]}"
    fi
  done
  printf ']\n'
else
  if (( count == 0 )); then
    echo "No archived tasks found matching filters."
  else
    echo ""
    echo "$count archived task(s) found."
  fi
fi
