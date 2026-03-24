#!/usr/bin/env bash
set -euo pipefail

# morning_brief.sh — Generate a daily task briefing and prepend to reminders file.
#
# Usage:
#   morning_brief.sh [--dry-run] [--base PATH]
#
# Output is prepended as a timestamped section to _shared/reminders.md.
# With --dry-run, prints to stdout only.
#
# Features:
#   - Domains read dynamically from domain_registry.json (display_order, briefing_label)
#   - Each item has a checkbox (- [ ]) for tracking in Obsidian
#   - De-duplicated: each task appears in exactly one section (URGENT > domain subsection)
#   - Unchecked items from the previous briefing are carried forward into their
#     appropriate section (URGENT or domain), not as a separate block
#   - Within a domain, each task appears in exactly one subsection
#     (due/overdue > blocked > in_progress > stale > new_todo)
#   - URGENT section includes:
#     - Critical-priority items from non-primary domains
#     - Tasks approaching due date within effort-based lead time (low=3d, medium=14d, high=30d)
#     - Overdue tasks from any domain
#     - Recurring/seasonal reminders triggered by date proximity
#     - Carried-forward items with no matching fresh task (orphaned)
#   - Requires: jq, bash 4+

BASE="${BASE_DIL:-/home/moo/Documents/dil_agentic_memory_0001}"
REMINDERS_FILE="$BASE/_shared/reminders.md"
REGISTRY="$BASE/_shared/_meta/domain_registry.json"
RECURRING_FILE="$BASE/_shared/recurring_reminders.md"
DRY_RUN=0
TODAY=$(date +%Y-%m-%d)
TODAY_EPOCH=$(date +%s)
CURRENT_YEAR=$(date +%Y)
NOW=$(date "+%Y-%m-%d %H:%M %Z")
STALE_DAYS=7

# Effort-based lead times (days before due date to escalate to URGENT)
LEAD_LOW=3
LEAD_MEDIUM=14
LEAD_HIGH=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --base) BASE="$2"; REMINDERS_FILE="$BASE/_shared/reminders.md"; REGISTRY="$BASE/_shared/_meta/domain_registry.json"; RECURRING_FILE="$BASE/_shared/recurring_reminders.md"; shift 2 ;;
    -h|--help)
      cat << 'USAGE'
Usage: morning_brief.sh [--dry-run] [--base PATH]

Generates a morning task briefing and prepends to _shared/reminders.md.
Domains and order read from domain_registry.json (display_order field).
Unchecked items from the previous briefing are carried forward.

URGENT escalation:
  - Critical-priority tasks from non-primary domains
  - Tasks within effort-based lead time of due date:
    low effort  = 3 days    medium effort = 14 days    high effort = 30 days
  - Overdue tasks (any domain, any priority)
  - Recurring reminders from _shared/recurring_reminders.md
USAGE
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# --- Require jq ---
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

# --- Read domain registry ---
if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: domain registry not found: $REGISTRY" >&2
  exit 1
fi

domain_list=$(jq -r '
  .domains | to_entries
  | sort_by(.value.display_order // 999)
  | .[]
  | [.key, (.value.display_order // 999), (.value.briefing_label // .value.name), .value.task_dir]
  | join("|")
' "$REGISTRY")

primary_domain=$(echo "$domain_list" | head -1 | cut -d'|' -f1)

# --- Carry forward: extract unchecked items from previous briefing ---
carried_forward=""
if [[ -f "$REMINDERS_FILE" ]]; then
  prev_briefing=$(awk '
    /^## Morning Briefing/ { found=1; next }
    found && /^---$/ { exit }
    found { print }
  ' "$REMINDERS_FILE")

  if [[ -n "$prev_briefing" ]]; then
    while IFS= read -r line; do
      if [[ "$line" =~ ^-\ \[\ \] ]]; then
        carried_forward+="${line}"$'\n'
      fi
    done <<< "$prev_briefing"
  fi
fi

# --- Helper functions ---
get_field() {
  local file="$1" field="$2"
  grep "^${field}:" "$file" 2>/dev/null | head -1 | sed "s/^${field}: *//" | tr -d '"'
}

days_since() {
  local date_str="$1"
  [[ -z "$date_str" ]] && { echo "999"; return; }
  local then_epoch
  then_epoch=$(date -d "$date_str" +%s 2>/dev/null) || { echo "999"; return; }
  echo $(( (TODAY_EPOCH - then_epoch) / 86400 ))
}

days_until() {
  local date_str="$1"
  [[ -z "$date_str" ]] && { echo ""; return; }
  local then_epoch
  then_epoch=$(date -d "$date_str" +%s 2>/dev/null) || { echo ""; return; }
  echo $(( (then_epoch - TODAY_EPOCH) / 86400 ))
}

# Get lead time based on effort_type
lead_time_for_effort() {
  case "$1" in
    low)    echo "$LEAD_LOW" ;;
    medium) echo "$LEAD_MEDIUM" ;;
    high)   echo "$LEAD_HIGH" ;;
    *)      echo "$LEAD_MEDIUM" ;;  # default to medium
  esac
}

# --- Temp dir for intermediate results ---
TMPDIR_BRIEF=$(mktemp -d)
trap 'rm -rf "$TMPDIR_BRIEF"' EXIT

# --- Recurring reminders ---
recurring_urgent=""
if [[ -f "$RECURRING_FILE" ]]; then
  # Read only pipe-delimited table rows, skip frontmatter/headers/separators
  grep '^|' "$RECURRING_FILE" | grep -v '^| ---' | grep -v '^| reminder' | while IFS='|' read -r _empty reminder trigger_date lead_days last_completed notes _trail; do
    # Trim whitespace (sed instead of xargs to avoid quote issues)
    reminder=$(echo "$reminder" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    trigger_date=$(echo "$trigger_date" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    lead_days=$(echo "$lead_days" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    last_completed=$(echo "$last_completed" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    notes=$(echo "$notes" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

    [[ -z "$reminder" || -z "$trigger_date" ]] && continue

    # Build this year's trigger date
    trigger_this_year="${CURRENT_YEAR}-${trigger_date}"
    remaining=$(days_until "$trigger_this_year")

    # If we can't parse the date, skip
    [[ -z "$remaining" ]] && continue

    # Already completed this year? Skip.
    [[ "$last_completed" == "$CURRENT_YEAR" ]] && continue

    # Within lead window or overdue?
    if [[ "$remaining" -le "$lead_days" ]]; then
      if [[ "$remaining" -lt 0 ]]; then
        echo "- [ ] **RECURRING** — ${reminder} — **OVERDUE by $(( remaining * -1 )) day(s)** [${notes}]"
      elif [[ "$remaining" -eq 0 ]]; then
        echo "- [ ] **RECURRING** — ${reminder} — **DUE TODAY** [${notes}]"
      else
        echo "- [ ] **RECURRING** — ${reminder} — due in ${remaining} day(s) [${notes}]"
      fi
    fi
  done > "$TMPDIR_BRIEF/_recurring"

  if [[ -f "$TMPDIR_BRIEF/_recurring" && -s "$TMPDIR_BRIEF/_recurring" ]]; then
    recurring_urgent=$(cat "$TMPDIR_BRIEF/_recurring")
    recurring_urgent+=$'\n'
  fi
fi

# --- Global seen-set: each task appears in exactly one section ---
declare -A seen_ids        # task IDs already emitted (keyed by "PROJ-1234")
declare -A fresh_task_ids  # all task IDs found in the fresh scan (for carry-forward matching)

# --- Scan tasks per domain ---
urgent_items=""

while IFS='|' read -r domain_key display_order briefing_label task_dir_raw; do
  if [[ "$task_dir_raw" == /* ]]; then
    active_dir="${task_dir_raw}/active"
  else
    active_dir="${BASE}/${task_dir_raw}/active"
  fi

  [[ -d "$active_dir" ]] || continue

  blocked=""
  in_progress=""
  due_soon=""
  stale=""
  new_todo=""

  for task_file in "$active_dir"/*.md; do
    [[ -f "$task_file" ]] || continue
    [[ "$(basename "$task_file")" == "index.md" ]] && continue

    task_id=$(get_field "$task_file" "task_id")
    title=$(get_field "$task_file" "title")
    status=$(get_field "$task_file" "status")
    priority=$(get_field "$task_file" "priority")
    updated=$(get_field "$task_file" "updated")
    due=$(get_field "$task_file" "due")
    project=$(get_field "$task_file" "project")
    effort=$(get_field "$task_file" "effort_type")

    [[ "$status" == "done" || "$status" == "cancelled" || "$status" == "retired" ]] && continue

    fresh_task_ids["$task_id"]=1

    if [[ ${#title} -gt 80 ]]; then
      title="${title:0:77}..."
    fi

    line="- [ ] **${task_id}** (${priority}) — ${title} [${project}]"

    # --- URGENT escalation logic ---
    is_urgent=0
    urgent_reason=""

    # 1. Critical priority from non-primary domains
    if [[ "$priority" == "critical" && "$domain_key" != "$primary_domain" ]]; then
      is_urgent=1
      urgent_reason="critical priority"
    fi

    # 2. Due-date escalation based on effort lead time
    if [[ -n "$due" ]]; then
      remaining=$(days_until "$due")
      if [[ -n "$remaining" ]]; then
        lead=$(lead_time_for_effort "$effort")

        if [[ "$remaining" -lt 0 ]]; then
          is_urgent=1
          urgent_reason="OVERDUE by $(( remaining * -1 )) day(s)"
        elif [[ "$remaining" -le "$lead" ]]; then
          is_urgent=1
          if [[ "$remaining" -eq 0 ]]; then
            urgent_reason="DUE TODAY"
          else
            urgent_reason="due in ${remaining} day(s) (${effort} effort, ${lead}d lead)"
          fi
        fi
      fi
    fi

    # If urgent, emit to URGENT and mark seen — skip domain section
    if [[ "$is_urgent" -eq 1 ]]; then
      urgent_items+="- [ ] **${task_id}** (${priority}) — ${title} [${project}] — **${urgent_reason}**"$'\n'
      seen_ids["$task_id"]=1
      continue
    fi

    # --- Standard categorization: each task in exactly one subsection ---
    # Priority: due/overdue > blocked > in_progress (stale variant) > in_progress > new_todo
    placed=0

    if [[ -n "$due" && "$placed" -eq 0 ]]; then
      remaining=$(days_until "$due")
      if [[ -n "$remaining" && "$remaining" -le 7 ]]; then
        if [[ "$remaining" -lt 0 ]]; then
          due_soon+="- [ ] **${task_id}** (${priority}) — ${title} [${project}] — **OVERDUE by $(( remaining * -1 )) day(s)**"$'\n'
        elif [[ "$remaining" -eq 0 ]]; then
          due_soon+="- [ ] **${task_id}** (${priority}) — ${title} [${project}] — **DUE TODAY**"$'\n'
        else
          due_soon+="- [ ] **${task_id}** (${priority}) — ${title} [${project}] — due in ${remaining} day(s)"$'\n'
        fi
        placed=1
      fi
    fi

    if [[ "$status" == "blocked" && "$placed" -eq 0 ]]; then
      blocked+="${line}"$'\n'
      placed=1
    fi

    if [[ ("$status" == "in_progress" || "$status" == "assigned") && "$placed" -eq 0 ]]; then
      age=$(days_since "$updated")
      if [[ "$age" -ge "$STALE_DAYS" ]]; then
        stale+="- [ ] **${task_id}** (${priority}) — ${title} [${project}] — last updated ${age} day(s) ago"$'\n'
      else
        in_progress+="${line}"$'\n'
      fi
      placed=1
    fi

    if [[ "$status" == "todo" && "$placed" -eq 0 ]]; then
      created=$(get_field "$task_file" "date")
      age=$(days_since "$created")
      if [[ "$age" -le 3 ]]; then
        new_todo+="${line}"$'\n'
        placed=1
      fi
    fi

    if [[ "$placed" -eq 1 ]]; then
      seen_ids["$task_id"]=1
    fi
  done

  # Write domain section to temp file
  domain_section=""
  has_content=0

  if [[ -n "$blocked" ]]; then
    domain_section+="#### Blocked / Waiting"$'\n'"${blocked}"$'\n'
    has_content=1
  fi
  if [[ -n "$due_soon" ]]; then
    domain_section+="#### Due Soon / Overdue"$'\n'"${due_soon}"$'\n'
    has_content=1
  fi
  if [[ -n "$in_progress" ]]; then
    domain_section+="#### In Progress"$'\n'"${in_progress}"$'\n'
    has_content=1
  fi
  if [[ -n "$stale" ]]; then
    domain_section+="#### Stale (no update in ${STALE_DAYS}+ days)"$'\n'"${stale}"$'\n'
    has_content=1
  fi
  if [[ -n "$new_todo" ]]; then
    domain_section+="#### New (created in last 3 days, still todo)"$'\n'"${new_todo}"$'\n'
    has_content=1
  fi

  if [[ "$has_content" -eq 1 ]]; then
    domain_count=$(echo -n "${blocked}${in_progress}${due_soon}${new_todo}" | grep -c '^- \[' || true)
    stale_count=$(echo -n "$stale" | grep -c '^- \[' || true)

    printf '%s' "### ${briefing_label} (${domain_count} active, ${stale_count} stale)"$'\n\n' > "$TMPDIR_BRIEF/${display_order}_${domain_key}"
    printf '%s' "$domain_section" >> "$TMPDIR_BRIEF/${display_order}_${domain_key}"
  fi

done <<< "$domain_list"

# --- Integrate carried-forward items ---
# Items whose task ID appears in the fresh scan are already represented — drop them.
# Orphaned items (task ID not in fresh scan, or non-task items like RECURRING) go to URGENT.
carried_to_urgent=""
if [[ -n "$carried_forward" ]]; then
  while IFS= read -r cline; do
    [[ -z "$cline" ]] && continue
    cline_id=$(echo "$cline" | grep -oP '\*\*[A-Z]+-[0-9]+\*\*' | head -1 || true)
    cline_id_bare=$(echo "$cline_id" | tr -d '*')

    if [[ -n "$cline_id_bare" && -n "${fresh_task_ids[$cline_id_bare]+x}" ]]; then
      # Task exists in fresh scan — already placed in URGENT or domain section
      continue
    fi

    # Orphaned task or non-task item (e.g. RECURRING) — carry into URGENT
    if [[ "$cline" == *"RECURRING"* ]]; then
      # Check if this exact recurring reminder is already in urgent via fresh scan
      reminder_text=$(echo "$cline" | grep -oP '(?<=RECURRING\*\* — ).*?(?= —)' || true)
      if [[ -n "$reminder_text" ]] && echo "$recurring_urgent" | grep -qF "$reminder_text"; then
        continue
      fi
    fi
    carried_to_urgent+="${cline} *(carried)*"$'\n'
  done <<< "$carried_forward"
fi

# --- Build the briefing ---
briefing="## Morning Briefing — ${NOW}"$'\n\n'

# URGENT section (critical priority + due-date escalation + recurring + carried orphans)
all_urgent="${urgent_items}${recurring_urgent}${carried_to_urgent}"
if [[ -n "$all_urgent" ]]; then
  urgent_count=$(echo -n "$all_urgent" | grep -c '^- \[' || true)
  briefing+="### URGENT (${urgent_count} items)"$'\n'
  briefing+="${all_urgent}"$'\n'
fi

# Domain sections in display_order (skip _recurring which is handled above)
for f in $(ls "$TMPDIR_BRIEF"/ 2>/dev/null | grep -v '^_' | sort); do
  briefing+=$(cat "$TMPDIR_BRIEF/$f")
  briefing+=$'\n'
done

# Summary
total_carried=$(echo -n "${carried_to_urgent:-}" | grep -c '^- \[' || true)
total_urgent=$(echo -n "${all_urgent:-}" | grep -c '^- \[' || true)

briefing+="### Summary"$'\n'
briefing+="Urgent: ${total_urgent} (${total_carried} carried) | Lead times: low=${LEAD_LOW}d med=${LEAD_MEDIUM}d high=${LEAD_HIGH}d"$'\n'
briefing+=$'\n---\n\n'

if (( DRY_RUN == 1 )); then
  echo "$briefing"
  exit 0
fi

# --- Prepend to reminders file ---
if [[ -f "$REMINDERS_FILE" ]]; then
  existing=$(cat "$REMINDERS_FILE")
  if [[ "$existing" == ---* ]]; then
    frontmatter=$(echo "$existing" | sed -n '1,/^---$/p' | head -n -1)
    second_dash=$(echo "$existing" | grep -n "^---$" | sed -n '2p' | cut -d: -f1)
    body=$(echo "$existing" | tail -n +"$((second_dash + 1))")
    printf '%s\n---\n\n%s%s\n' "$frontmatter" "$briefing" "$body" > "$REMINDERS_FILE"
  else
    printf '%s%s\n' "$briefing" "$existing" > "$REMINDERS_FILE"
  fi
else
  cat > "$REMINDERS_FILE" << FRONTMATTER
---
title: "Daily Reminders & Briefings"
date: ${TODAY}
machine: shared
assistant: shared
category: system
memoryType: reference
priority: notable
tags: [reminders, briefing, daily]
updated: ${TODAY}
source: internal
domain: operations
project: dil-active
status: active
owner: shared
due:
---

# Daily Reminders & Briefings

Generated by \`morning_brief.sh\`. Newest briefing appears first.
Check items with \`[x]\` to mark complete — unchecked items carry forward to the next briefing.
Tasks escalate to URGENT based on effort-based lead times (low=3d, med=14d, high=30d).
Recurring reminders from \`_shared/recurring_reminders.md\` also appear in URGENT.
Manual notes can be added under any section.

FRONTMATTER
  printf '%s' "$briefing" >> "$REMINDERS_FILE"
fi

echo "Briefing written to $REMINDERS_FILE"
echo "Urgent: ${total_urgent} | Carried: ${total_carried} | Lead times: low=${LEAD_LOW}d med=${LEAD_MEDIUM}d high=${LEAD_HIGH}d"
