#!/usr/bin/env bash
set -euo pipefail

# archive_tasks.sh — Move terminal tasks past their domain's archive window to archived/{year}/
# Idempotent: safe to run repeatedly or via cron.
# Usage: archive_tasks.sh [--dry-run] [BASE]

SCRIPT_NAME="archive_tasks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${BASE_DIL:-/home/moo/Documents/dil_agentic_memory_0001}"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    /*) BASE="$arg" ;;
  esac
done

# Source domain registry
source "$SCRIPT_DIR/lib/domains.sh"

TERMINAL_STATUSES="done cancelled retired"

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

is_terminal() {
  local status="$1"
  for s in $TERMINAL_STATUSES; do
    [[ "$status" == "$s" ]] && return 0
  done
  return 1
}

# Convert a date string (YYYY-MM-DD) to epoch seconds
date_to_epoch() {
  date -d "$1" +%s 2>/dev/null || date -jf "%Y-%m-%d" "$1" +%s 2>/dev/null || echo 0
}

moved=0
skipped=0
errors=0

for domain in $(list_domains); do
  resolve_domain "$domain" || continue

  active_dir="$TASK_DIR/active"
  archived_base="$TASK_DIR/archived"

  [[ -d "$active_dir" ]] || continue

  after_days="$ARCHIVE_AFTER_DAYS"
  if [[ "$after_days" == "null" || -z "$after_days" || "$after_days" -le 0 ]] 2>/dev/null; then
    continue
  fi

  cutoff_seconds=$((after_days * 86400))

  for f in "$active_dir"/*.md; do
    [[ -f "$f" ]] || continue
    [[ "$(basename "$f")" == "index.md" ]] && continue

    status="$(get_key "$f" status)"
    if ! is_terminal "$status"; then
      continue
    fi

    # Use updated date as proxy for terminal_date
    updated="$(get_key "$f" updated)"
    if [[ -z "$updated" ]]; then
      skipped=$((skipped + 1))
      continue
    fi

    updated_epoch="$(date_to_epoch "$updated")"
    if [[ "$updated_epoch" -eq 0 ]]; then
      skipped=$((skipped + 1))
      continue
    fi

    # Find the newest file in active/ to anchor the trailing window
    # (cached per domain to avoid repeated scans)
    if [[ -z "${newest_epoch:-}" ]]; then
      newest_epoch=0
      while IFS= read -r af; do
        [[ -f "$af" ]] || continue
        af_updated="$(get_key "$af" updated)"
        [[ -z "$af_updated" ]] && continue
        af_epoch="$(date_to_epoch "$af_updated")"
        (( af_epoch > newest_epoch )) && newest_epoch="$af_epoch"
      done < <(find "$active_dir" -maxdepth 1 -type f -name '*.md' ! -name 'index.md' 2>/dev/null)
    fi

    age_from_newest=$(( newest_epoch - updated_epoch ))
    if (( age_from_newest < cutoff_seconds )); then
      continue
    fi

    year="${updated:0:4}"
    dest_dir="$archived_base/$year"
    fname="$(basename "$f")"

    if (( DRY_RUN )); then
      echo "[DRY RUN] ARCHIVE $f -> $dest_dir/$fname (status=$status, updated=$updated, age=${age_from_newest}s)"
    else
      mkdir -p "$dest_dir"
      if ! mv "$f" "$dest_dir/$fname"; then
        echo "ERROR: failed to move $f" >&2
        errors=$((errors + 1))
        continue
      fi
    fi
    moved=$((moved + 1))
  done

  # Reset newest_epoch for next domain
  unset newest_epoch

  # Regenerate archive indexes for this domain (unless dry-run)
  if (( ! DRY_RUN )) && [[ -d "$archived_base" ]]; then
    for year_dir in "$archived_base"/*/; do
      [[ -d "$year_dir" ]] || continue
      year="$(basename "$year_dir")"
      index_file="$year_dir/index.md"

      {
        echo "---"
        echo "title: \"$domain archived tasks $year\""
        echo "date: $(date -u +%Y-%m-%d)"
        echo "category: system"
        echo "memoryType: index"
        echo "domain: $domain"
        echo "status: active"
        echo "---"
        echo ""
        echo "# $domain archived tasks — $year"
        echo ""
        echo "| task_id | title | status | updated | archived_date |"
        echo "| --- | --- | --- | --- | --- |"

        for af in "$year_dir"/*.md; do
          [[ -f "$af" ]] || continue
          [[ "$(basename "$af")" == "index.md" ]] && continue
          tid="$(get_key "$af" task_id)"
          title="$(get_key "$af" title)"
          st="$(get_key "$af" status)"
          upd="$(get_key "$af" updated)"
          echo "| $tid | $title | $st | $upd | $(date -u +%Y-%m-%d) |"
        done
      } > "$index_file"
    done
  fi
done

echo ""
echo "=== Archive summary ==="
echo "Archived: $moved"
echo "Skipped (missing date): $skipped"
echo "Errors: $errors"

if (( DRY_RUN )); then
  echo ""
  echo "[DRY RUN] No files were moved."
  exit 0
fi

if (( moved > 0 )); then
  echo ""
  echo "Rebuilding task index..."
  "$BASE/_shared/scripts/rebuild_task_index.sh" "$BASE"
fi

if (( errors > 0 )); then
  exit 1
fi
