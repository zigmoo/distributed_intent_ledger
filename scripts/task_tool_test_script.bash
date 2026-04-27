#!/usr/bin/env bash
set -euo pipefail

# task_tool_test_script.bash — Diff-stable progressive test suite for task_tool
#
# Pattern: each test captures normalized output to a file, then diffs against
# a golden baseline. Null diff = pass. Any diff = functional regression.
#
# Usage:
#   task_tool_test_script.bash                    # run all, diff against golden
#   task_tool_test_script.bash --rebuild           # regenerate golden baselines
#   task_tool_test_script.bash --test 5            # run single test by number
#   task_tool_test_script.bash --keep-temp         # preserve temp workspace
#   task_tool_test_script.bash --quiet             # summary only
#
# Exit codes: 0=all pass, 1=failures detected, 2=setup error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR")"

# Ensure DIL bin/ is in PATH — tests must call tools by symlink name, not full path
export PATH="$SCRIPT_DIR/bin:$PATH"

GOLDEN_DIR="$SCRIPT_DIR/task_tool_test_golden"
KEEP_TEMP=0
QUIET=0
REBUILD=0
SINGLE_TEST=""

# --- logging (Script Forge Standard #5) ---
TIMESTAMP_VAL="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$BASE/_shared/logs/task_tool_test_script"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/task_tool_test_script.run.${TIMESTAMP_VAL}.log"

log_to_file() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG_FILE"
}

# Begin log with full path (Standard #5: logs begin and end with full path)
{
  echo "================================================================================"
  echo "LOG_FILE: $LOG_FILE"
  echo "================================================================================"
  echo ""
  echo "Section 1: Test Run Configuration"
  echo "--------------------------------------------------------------------------------"
  echo "timestamp:  $(date '+%Y-%m-%d %H:%M:%S')"
  echo "base:       $BASE"
  echo "golden_dir: $GOLDEN_DIR"
  echo "machine:    $(hostname -s | tr '[:upper:]' '[:lower:]')"
  echo "agent:      ${AGENT_NAME:-${AGENT_ID:-${ASSISTANT_ID:-unknown}}}"
  echo "script:     ${BASH_SOURCE[0]}"
  echo ""
} > "$LOG_FILE"

# --- color support ---
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  C_GREEN=$'\033[1;32m'
  C_RED=$'\033[1;31m'
  C_YELLOW=$'\033[1;33m'
  C_CYAN=$'\033[1;36m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RESET=$'\033[0m'
else
  C_GREEN="" C_RED="" C_YELLOW="" C_CYAN="" C_BOLD="" C_DIM="" C_RESET=""
fi

usage() {
  cat << 'USAGE'
task_tool_test_script.bash — Diff-stable progressive test suite for task_tool

Usage:
  task_tool_test_script.bash [options]

Options:
  --rebuild             Regenerate golden baseline files from current output
  --test N              Run only test number N
  --keep-temp           Preserve temp workspace for debugging
  --quiet               Show only summary and failures
  --base PATH           Override DIL base path
  -h, --help            Show this help

Test Pattern:
  Each test captures normalized output (timestamps stripped, paths generalized)
  and diffs against a golden baseline file. Null diff = pass. Any variance
  from the golden baseline indicates a functional regression.

  Golden files live in: _shared/scripts/task_tool_test_golden/
USAGE
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=1; shift ;;
    --test) SINGLE_TEST="$2"; shift 2 ;;
    --keep-temp) KEEP_TEMP=1; shift ;;
    --quiet) QUIET=1; shift ;;
    --base) BASE="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

log() {
  if (( QUIET == 0 )); then
    echo "$*"
  fi
}

# --- counters ---
pass_count=0
fail_count=0
skip_count=0
rebuild_count=0

# --- temp workspace ---
TMP_ROOT="$(mktemp -d /tmp/task-tool-test.XXXXXX)"
TEST_BASE="$TMP_ROOT/dil"
ACTUAL_DIR="$TMP_ROOT/actual"
mkdir -p "$ACTUAL_DIR"

cleanup() {
  if (( KEEP_TEMP == 1 )); then
    echo "Temp workspace preserved at: $TMP_ROOT"
  else
    rm -rf "$TMP_ROOT"
  fi
}
trap cleanup EXIT

# --- normalize output for diff stability ---
# Strips timestamps, absolute paths, PIDs, and other run-specific variance
normalize_output() {
  sed \
    -e "s|$TMP_ROOT|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}[Z+0-9:]*/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/\.[0-9]\{6\}\./.<PID>./g' \
    -e 's/pid=[0-9]*/pid=<PID>/g'
}

# --- vault construction helpers ---

make_test_vault() {
  rm -rf "$TEST_BASE"
  mkdir -p "$TEST_BASE/_shared/domains/personal/tasks/active"
  mkdir -p "$TEST_BASE/_shared/domains/work/tasks/active"
  mkdir -p "$TEST_BASE/_shared/tasks/_meta"
  mkdir -p "$TEST_BASE/_shared/_meta"
  # Domain registry — matches real DIL layout
  cat > "$TEST_BASE/_shared/_meta/domain_registry.json" << 'REGISTRY'
{
  "domains": {
    "personal": {
      "name": "Personal",
      "task_dir": "_shared/domains/personal/tasks",
      "log_dir": "_shared/domains/personal/logs",
      "data_dir": "_shared/domains/personal/data",
      "id_prefix": "DIL",
      "id_mode": "auto",
      "default_owner": "moo",
      "archive": {"after_days": 30, "strategy": "active_archived"}
    },
    "work": {
      "name": "Work",
      "task_dir": "_shared/domains/work/tasks",
      "log_dir": "_shared/domains/work/logs",
      "data_dir": "_shared/domains/work/data",
      "id_prefix": "DMDI",
      "id_mode": "external",
      "default_owner": "moo",
      "archive": {"after_days": 30, "strategy": "active_archived"}
    }
  }
}
REGISTRY
}

write_task() {
  local task_id="$1" domain="$2" status="$3" priority="$4"
  local work_type="$5" task_type="$6" effort_type="$7"
  local parent="${8:-}" owner="${9:-moo}" title="${10:-Test task $task_id}"

  local dir="$TEST_BASE/_shared/domains/$domain/tasks/active"
  cat > "$dir/$task_id.md" << TASK
---
title: "$title"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: $priority
tags: [task, $domain]
updated: 2026-03-10
source: internal
domain: $domain
project: test
status: $status
owner: "$owner"
due:
work_type: $work_type
task_type: $task_type
effort_type: $effort_type
task_id: $task_id
created_by: test-harness
model: test-model
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: "$parent"
agents:
  - id: "$owner"
    role: accountable
    responsibility_order: 1
---

# $title
TASK
}

write_index_header() {
  cat > "$TEST_BASE/_shared/_meta/task_index.md" << 'IDX'
---
title: "Test Task Index"
---

# Test Task Index

| task_id | domain | status | priority | owner | due | project | path | updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
IDX
}

write_index_row() {
  local tid="$1" dom="$2" st="$3" pri="$4" own="$5" proj="${6:-test}"
  echo "| $tid | $dom | $st | $pri | $own |  | $proj | _shared/domains/$dom/tasks/active/$tid.md | 2026-03-10 |" >> "$TEST_BASE/_shared/_meta/task_index.md"
}

write_counter() {
  local next_id="$1"
  cat > "$TEST_BASE/_shared/_meta/task_id_counter.md" << COUNTER
---
title: "Test Counter"
---

# Test Counter

- prefix: DIL
- next_id: $next_id
- last_allocator: test
COUNTER
}

write_changelog_header() {
  cat > "$TEST_BASE/_shared/tasks/_meta/change_log.md" << 'LOG'
---
title: "Test Change Log"
---

# Test Change Log

| timestamp | actor | model | task_id | action | field_changes | reason |
| --- | --- | --- | --- | --- | --- | --- |
LOG
}

# --- test runner ---
# run_test <test_number> <test_name> <function_name>
#
# Captures the function's output, normalizes it, and either:
#   --rebuild: writes it as the golden file
#   default:   diffs against the golden file
run_test() {
  local num="$1" name="$2" func="$3"
  local test_label="$(printf '%02d' "$num")"
  local golden_file="$GOLDEN_DIR/test_${test_label}.golden"
  local actual_file="$ACTUAL_DIR/test_${test_label}.actual"

  if [[ -n "$SINGLE_TEST" && "$SINGLE_TEST" != "$num" ]]; then
    return
  fi

  log "${C_CYAN}[$num] $name${C_RESET}"
  log_to_file "TEST $test_label | $name | START"

  # Run the test function, capture all output
  local raw_output
  raw_output="$($func 2>&1)" || true

  # Normalize and write actual
  echo "$raw_output" | normalize_output > "$actual_file"

  if (( REBUILD == 1 )); then
    mkdir -p "$GOLDEN_DIR"
    cp "$actual_file" "$golden_file"
    rebuild_count=$((rebuild_count + 1))
    log "  ${C_YELLOW}REBUILT${C_RESET}: $golden_file"
    log_to_file "TEST $test_label | $name | REBUILT"
    return
  fi

  if [[ ! -f "$golden_file" ]]; then
    skip_count=$((skip_count + 1))
    log "  ${C_YELLOW}SKIP${C_RESET}: no golden file (run --rebuild to create)"
    log_to_file "TEST $test_label | $name | SKIP | no golden file"
    return
  fi

  local diff_output
  if diff_output="$(diff -u "$golden_file" "$actual_file")"; then
    pass_count=$((pass_count + 1))
    log "  ${C_GREEN}PASS${C_RESET}: output matches golden baseline"
    log_to_file "TEST $test_label | $name | PASS"
  else
    fail_count=$((fail_count + 1))
    echo "  ${C_RED}FAIL${C_RESET}: output differs from golden baseline" >&2
    echo "${C_DIM}$diff_output${C_RESET}" >&2
    log_to_file "TEST $test_label | $name | FAIL"
    echo "$diff_output" >> "$LOG_FILE"
  fi
}

# ============================================================
# TEST DEFINITIONS
# ============================================================
# Each test function writes to stdout/stderr. Output is captured
# by run_test, normalized, and diffed against golden.

# --- Tests for existing subcommands (1-4) ---

test_01_search_no_results() {
  make_test_vault
  write_index_header
  write_counter 1000
  task_tool --base "$TEST_BASE" search --status blocked 2>&1 || true
}

test_02_search_with_results() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_task "DIL-9002" personal in_progress normal feature kanban low
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_index_row DIL-9002 personal in_progress normal moo
  write_counter 9003
  task_tool --base "$TEST_BASE" search --status todo 2>&1 || true
  echo "---"
  task_tool --base "$TEST_BASE" search --count 2>&1 || true
}

test_03_review_existing_task() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium "" moo "Review target task"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  task_tool --base "$TEST_BASE" review DIL-9001 2>&1 || true
}

test_04_review_missing_task() {
  make_test_vault
  write_index_header
  write_counter 1000
  task_tool --base "$TEST_BASE" review DIL-9999 2>&1 || true
  echo "EXIT: $?"
}

# --- Tests for subcommands to be ported (5-16) ---
# These test the CURRENT standalone scripts. As each gets ported to task_tool,
# the test body changes from calling the standalone script to calling
# `task_tool <subcommand>`, but the golden output should remain identical.
# Any diff after porting = functional regression in the port.

test_05_create_personal_task() {
  make_test_vault
  write_index_header
  write_counter 9001
  write_changelog_header
  task_tool --base "$TEST_BASE" create --domain personal \
    --title "Test personal creation" --project test-suite \
    --priority normal --status todo --owner moo \
    --actor test-harness --model test-model 2>&1 || true
  echo "FILE_EXISTS: $(test -f "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" && echo yes || echo no)"
}

test_06_create_work_task() {
  make_test_vault
  write_index_header
  write_counter 9001
  write_changelog_header
  task_tool --base "$TEST_BASE" create --domain work \
    --task-id "DMDI-50001" --title "Test work creation" --project test-suite \
    --priority high --status todo --owner moo \
    --actor test-harness --model test-model 2>&1 || true
  echo "FILE_EXISTS: $(test -f "$TEST_BASE/_shared/domains/work/tasks/active/DMDI-50001.md" && echo yes || echo no)"
}

test_07_create_duplicate_fails() {
  make_test_vault
  write_task "DMDI-50001" work todo high chore kanban medium "" moo "Already exists"
  write_index_header
  write_index_row DMDI-50001 work todo high moo
  write_counter 9001
  write_changelog_header
  task_tool --base "$TEST_BASE" create --domain work \
    --task-id "DMDI-50001" --title "Duplicate" --project test-suite 2>&1 || true
  echo "EXIT: $?"
}

test_08_create_invalid_id_fails() {
  make_test_vault
  write_index_header
  write_counter 9001
  write_changelog_header
  task_tool --base "$TEST_BASE" create --domain work \
    --task-id "BADID" --title "Bad ID" --project test-suite 2>&1 || true
  echo "EXIT: $?"
}

test_09_status_transitions() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  echo "=== todo -> assigned ==="
  task_tool --base "$TEST_BASE" status --task-id DIL-9001 --status assigned --reason "test transition 1" 2>&1 || true
  echo "=== assigned -> in_progress ==="
  task_tool --base "$TEST_BASE" status --task-id DIL-9001 --status in_progress --reason "test transition 2" 2>&1 || true
  echo "=== STATUS NOW ==="
  grep '^status:' "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" || true
}

test_10_status_invalid_transition() {
  make_test_vault
  write_task "DIL-9001" personal in_progress high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal in_progress high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" status --task-id DIL-9001 --status todo --reason "invalid rewind" 2>&1 || true
  echo "EXIT: $?"
}

test_11_assign_task() {
  make_test_vault
  write_task "DIL-9001" personal in_progress high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal in_progress high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" assign --task-id DIL-9001 --owner codex --reason "test assign" 2>&1 || true
  echo "=== OWNER NOW ==="
  grep '^owner:' "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" || true
  echo "=== STATUS PRESERVED ==="
  grep '^status:' "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" || true
}

test_12_append_note() {
  make_test_vault
  write_task "DIL-9001" personal in_progress high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal in_progress high moo
  write_counter 9002
  echo "Test execution note content" | \
    task_tool --base "$TEST_BASE" append-note --task-id DIL-9001 2>&1 || true
  echo "=== NOTE APPENDED ==="
  grep -c "Test execution note content" "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" || echo "0"
}

test_13_tee_note() {
  make_test_vault
  write_task "DIL-9001" personal in_progress high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal in_progress high moo
  write_counter 9002
  echo "Tee note content" | \
    task_tool --base "$TEST_BASE" tee-note --task-id DIL-9001 2>&1 || true
  echo "=== NOTE IN FILE ==="
  grep -c "Tee note content" "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" || echo "0"
}

test_14_validate_clean_vault() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
  echo "EXIT: $?"
}

test_15_validate_broken_vault() {
  make_test_vault
  write_task "DIL-9001" personal exploding high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal exploding high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
  echo "EXIT: $?"
}

test_16_rebuild_index() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_task "DIL-9002" personal done normal feature kanban low
  # Deliberately write an empty index
  write_index_header
  write_counter 9003
  write_changelog_header
  task_tool --base "$TEST_BASE" rebuild-index 2>&1 || true
  echo "=== INDEX ROW COUNT ==="
  grep -c '^|' "$TEST_BASE/_shared/_meta/task_index.md" || echo "0"
}

test_17_archive_terminal_task() {
  make_test_vault
  # Create a recent active task (today) and an old terminal task (300 days ago)
  write_task "DIL-9001" personal todo high chore kanban medium
  write_task "DIL-9002" personal done normal chore kanban medium
  # Backdate DIL-9002's updated field to 300 days ago
  local old_date
  old_date=$(date -d "300 days ago" +%Y-%m-%d 2>/dev/null || date -v-300d +%Y-%m-%d 2>/dev/null)
  sed -i "s/^updated: .*/updated: $old_date/" "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9002.md"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_index_row DIL-9002 personal done normal moo
  write_counter 9003
  write_changelog_header
  task_tool --base "$TEST_BASE" archive --dry-run 2>&1 || true
  echo "=== STILL IN ACTIVE ==="
  ls "$TEST_BASE/_shared/domains/personal/tasks/active/"*.md 2>/dev/null | xargs -I{} basename {} | sort || echo "NONE"
}

# --- Validation edge cases ---

test_18_validate_invalid_priority() {
  make_test_vault
  write_task "DIL-9001" personal todo ultra chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo ultra moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_19_validate_invalid_work_type() {
  make_test_vault
  write_task "DIL-9001" personal todo high dance kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_20_validate_invalid_task_type() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore waterfall medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_21_validate_invalid_effort_type() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban extreme
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_22_validate_schema_version() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  sed -i 's/task_schema: v1/task_schema: v2/' "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_23_validate_empty_title() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium "" moo ""
  # Overwrite with empty title
  sed -i 's/^title: ".*"/title: ""/' "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_24_validate_domain_mismatch() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  # Move personal task into work directory
  mv "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" "$TEST_BASE/_shared/domains/work/tasks/active/DIL-9001.md"
  write_index_header
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_25_validate_wrong_agent_role() {
  make_test_vault
  cat > "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" << 'TASK'
---
title: "Wrong agent role"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: reviewer
    responsibility_order: 1
---
TASK
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_26_validate_parent_self_reference() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium "DIL-9001"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_27_validate_parent_missing() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium "DIL-9999"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_28_validate_parent_cycle() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium "DIL-9002"
  write_task "DIL-9002" personal todo high chore kanban medium "DIL-9001"
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_index_row DIL-9002 personal todo high moo
  write_counter 9003
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_29_validate_duplicate_index_row() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_30_validate_counter_mismatch() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9999
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_31_validate_changelog_invalid_transition() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  echo "| 2026-03-10T00:00:00Z | test | test-model | DIL-9001 | update | status: todo->done | test |" >> "$TEST_BASE/_shared/tasks/_meta/change_log.md"
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_32_validate_changelog_status_mismatch() {
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  echo "| 2026-03-10T00:00:00Z | test | test-model | DIL-9001 | update | status: todo->in_progress | test |" >> "$TEST_BASE/_shared/tasks/_meta/change_log.md"
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

test_33_validate_malformed_frontmatter() {
  make_test_vault
  cat > "$TEST_BASE/_shared/domains/personal/tasks/active/DIL-9001.md" << 'TASK'
This file has no frontmatter at all.
Just text without --- delimiters.
TASK
  write_index_header
  write_counter 9002
  write_changelog_header
  task_tool --base "$TEST_BASE" validate 2>&1 || true
}

# ============================================================
# MAIN
# ============================================================

log "${C_BOLD}=== task_tool progressive test suite ===${C_RESET}"
log "${C_DIM}Golden dir: $GOLDEN_DIR${C_RESET}"
log "${C_DIM}Temp workspace: $TMP_ROOT${C_RESET}"
log ""

run_test  1 "search: no results"              test_01_search_no_results
run_test  2 "search: with results + count"    test_02_search_with_results
run_test  3 "review: existing task"           test_03_review_existing_task
run_test  4 "review: missing task"            test_04_review_missing_task
run_test  5 "create: personal task"           test_05_create_personal_task
run_test  6 "create: work task"               test_06_create_work_task
run_test  7 "create: duplicate fails"         test_07_create_duplicate_fails
run_test  8 "create: invalid ID fails"        test_08_create_invalid_id_fails
run_test  9 "status: valid transitions"       test_09_status_transitions
run_test 10 "status: invalid transition"      test_10_status_invalid_transition
run_test 11 "assign: owner reassignment"      test_11_assign_task
run_test 12 "append-note: execution note"     test_12_append_note
run_test 13 "tee-note: tee to stdout + file"  test_13_tee_note
run_test 14 "validate: clean vault"           test_14_validate_clean_vault
run_test 15 "validate: broken vault"          test_15_validate_broken_vault
run_test 16 "rebuild-index: regenerate"       test_16_rebuild_index
run_test 17 "archive: dry-run terminal task"  test_17_archive_terminal_task
run_test 18 "validate: invalid priority"      test_18_validate_invalid_priority
run_test 19 "validate: invalid work_type"     test_19_validate_invalid_work_type
run_test 20 "validate: invalid task_type"     test_20_validate_invalid_task_type
run_test 21 "validate: invalid effort_type"   test_21_validate_invalid_effort_type
run_test 22 "validate: schema version"        test_22_validate_schema_version
run_test 23 "validate: empty title"           test_23_validate_empty_title
run_test 24 "validate: domain mismatch"       test_24_validate_domain_mismatch
run_test 25 "validate: wrong agent role"      test_25_validate_wrong_agent_role
run_test 26 "validate: parent self-ref"       test_26_validate_parent_self_reference
run_test 27 "validate: parent missing"        test_27_validate_parent_missing
run_test 28 "validate: parent cycle"          test_28_validate_parent_cycle
run_test 29 "validate: duplicate index row"   test_29_validate_duplicate_index_row
run_test 30 "validate: counter mismatch"      test_30_validate_counter_mismatch
run_test 31 "validate: changelog bad trans"   test_31_validate_changelog_invalid_transition
run_test 32 "validate: changelog status mm"   test_32_validate_changelog_status_mismatch
run_test 33 "validate: malformed frontmatter" test_33_validate_malformed_frontmatter

# --- Summary ---
echo ""
total=$((pass_count + fail_count + skip_count + rebuild_count))

# Log summary (Standard #5: numbered sections, logs end with full path)
{
  echo ""
  echo "Section 2: Test Results Summary"
  echo "--------------------------------------------------------------------------------"
  echo "passed:  $pass_count"
  echo "failed:  $fail_count"
  echo "skipped: $skip_count"
  echo "rebuilt: $rebuild_count"
  echo "total:   $total"
  echo "result:  $(if (( fail_count > 0 )); then echo FAIL; elif (( REBUILD == 1 )); then echo REBUILD; else echo PASS; fi)"
  echo ""
  echo "================================================================================"
  echo "LOG_FILE: $LOG_FILE"
  echo "================================================================================"
} >> "$LOG_FILE"

if (( REBUILD == 1 )); then
  echo "${C_YELLOW}${C_BOLD}=== REBUILT: ${rebuild_count} golden baselines regenerated ===${C_RESET}"
  echo "Golden files at: $GOLDEN_DIR/"
  echo "Log: $LOG_FILE"
  exit 0
fi

if (( fail_count > 0 )); then
  echo "${C_RED}${C_BOLD}=== FAILED: ${pass_count} passed, ${fail_count} failed, ${skip_count} skipped (${total} total) ===${C_RESET}"
  echo "Log: $LOG_FILE"
  exit 1
else
  echo "${C_GREEN}${C_BOLD}=== ALL PASSED: ${pass_count} passed, ${fail_count} failed, ${skip_count} skipped (${total} total) ===${C_RESET}"
  echo "Log: $LOG_FILE"
  exit 0
fi
