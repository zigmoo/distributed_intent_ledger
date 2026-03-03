#!/usr/bin/env bash
set -euo pipefail

BASE="/home/moo/Documents/dil_agentic_memory_0001"
KEEP_TEMP=0
QUIET=0

usage() {
  cat << 'USAGE'
Usage:
  test_task_system.sh [options]

Options:
  --base PATH        Base path for agentic_memory (default: /home/moo/Documents/dil_agentic_memory_0001)
  --keep-temp        Keep temporary test workspace for debugging
  --quiet            Show only summary/errors
  -h, --help         Show help

What it tests (in isolated temp copy):
- baseline validator pass
- create_task.sh (work, personal, dry-run, invalid-id, duplicate-id)
- set_task_status.sh (valid and invalid transitions)
- assign_task.sh owner reassignment behavior
- final validator pass after test mutations
USAGE
}

log() {
  if (( QUIET == 0 )); then
    echo "$*"
  fi
}

pass_count=0
fail_count=0

pass() {
  pass_count=$((pass_count + 1))
  log "PASS: $*"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "FAIL: $*" >&2
}

expect_success() {
  local name="$1"
  shift
  if "$@" >/tmp/task_test.out 2>/tmp/task_test.err; then
    pass "$name"
  else
    fail "$name"
    cat /tmp/task_test.out >&2 || true
    cat /tmp/task_test.err >&2 || true
  fi
}

expect_failure() {
  local name="$1"
  shift
  if "$@" >/tmp/task_test.out 2>/tmp/task_test.err; then
    fail "$name (unexpected success)"
    cat /tmp/task_test.out >&2 || true
  else
    pass "$name"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="${2:-}"; shift 2 ;;
    --keep-temp) KEEP_TEMP=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ ! -d "$BASE" ]]; then
  echo "Base path not found: $BASE" >&2
  exit 1
fi

for req in \
  "$BASE/_shared/scripts/validate_tasks.sh" \
  "$BASE/_shared/scripts/create_task.sh" \
  "$BASE/_shared/scripts/set_task_status.sh" \
  "$BASE/_shared/scripts/assign_task.sh"
do
  if [[ ! -x "$req" ]]; then
    echo "Missing executable script: $req" >&2
    exit 1
  fi
done

TMP_ROOT="$(mktemp -d /tmp/agentic-memory-tests.XXXXXX)"
TEST_BASE="$TMP_ROOT/agentic_memory"
cp -a "$BASE" "$TEST_BASE"

cleanup() {
  if (( KEEP_TEMP == 0 )); then
    rm -rf "$TMP_ROOT"
  else
    echo "Kept temp workspace: $TMP_ROOT"
  fi
}
trap cleanup EXIT

VALIDATE="$TEST_BASE/_shared/scripts/validate_tasks.sh"
CREATE="$TEST_BASE/_shared/scripts/create_task.sh"
SET_STATUS="$TEST_BASE/_shared/scripts/set_task_status.sh"
ASSIGN="$TEST_BASE/_shared/scripts/assign_task.sh"
COUNTER="$TEST_BASE/_shared/_meta/task_id_counter.md"
WORK_DIR="$TEST_BASE/_shared/tasks/work"
PERSONAL_DIR="$TEST_BASE/_shared/tasks/personal"

# 1) Baseline consistency
expect_success "baseline validator" "$VALIDATE" "$TEST_BASE"

# pick a unique work id
work_num=$((50000 + RANDOM % 40000))
WORK_ID="DMDI-$work_num"
while [[ -f "$WORK_DIR/$WORK_ID.md" ]]; do
  work_num=$((50000 + RANDOM % 40000))
  WORK_ID="DMDI-$work_num"
done

# snapshot personal counter before create
next_before="$(awk -F: '/^- next_id:/ {gsub(/ /, "", $2); print $2; exit}' "$COUNTER")"
if [[ -z "$next_before" || ! "$next_before" =~ ^[0-9]+$ ]]; then
  fail "read personal counter before"
fi
PERSONAL_ID="MOO-$next_before"

# 2) create_task.sh: work success
expect_success "create work task" \
  "$CREATE" --base "$TEST_BASE" --domain work --task-id "$WORK_ID" \
  --title "Integration Work Task" --project "test-suite" --priority high --status todo \
  --owner moo --actor codex --model gpt-5

if [[ -f "$WORK_DIR/$WORK_ID.md" ]]; then
  pass "work task file created"
else
  fail "work task file created"
fi

# 3) create_task.sh: work invalid id fails
expect_failure "create work task invalid ID" \
  "$CREATE" --base "$TEST_BASE" --domain work --task-id "BADID" \
  --title "Bad Work Task" --project "test-suite"

# 4) create_task.sh: duplicate work id fails
expect_failure "create duplicate work task ID" \
  "$CREATE" --base "$TEST_BASE" --domain work --task-id "$WORK_ID" \
  --title "Dup Work Task" --project "test-suite"

# 5) create_task.sh: personal dry-run should not mutate counter or file
expect_success "personal dry-run create" \
  "$CREATE" --base "$TEST_BASE" --domain personal --title "Dry Run Personal" --project "test-suite" --dry-run

next_after_dry="$(awk -F: '/^- next_id:/ {gsub(/ /, "", $2); print $2; exit}' "$COUNTER")"
if [[ "$next_after_dry" == "$next_before" && ! -f "$PERSONAL_DIR/$PERSONAL_ID.md" ]]; then
  pass "dry-run no side effects"
else
  fail "dry-run no side effects"
fi

# 6) create_task.sh: personal success + counter increment
expect_success "create personal task" \
  "$CREATE" --base "$TEST_BASE" --domain personal --title "Integration Personal Task" \
  --project "test-suite" --priority normal --status todo --owner moo --actor codex --model gpt-5

if [[ -f "$PERSONAL_DIR/$PERSONAL_ID.md" ]]; then
  pass "personal task file created"
else
  fail "personal task file created"
fi

next_after="$(awk -F: '/^- next_id:/ {gsub(/ /, "", $2); print $2; exit}' "$COUNTER")"
if [[ "$next_after" =~ ^[0-9]+$ ]] && (( next_after == next_before + 1 )); then
  pass "personal counter incremented"
else
  fail "personal counter incremented"
fi

# 7) set_task_status.sh valid transitions
expect_success "status todo->assigned" \
  "$SET_STATUS" --base "$TEST_BASE" --task-id "$PERSONAL_ID" --status assigned --reason "integration status 1"

expect_success "status assigned->in_progress" \
  "$SET_STATUS" --base "$TEST_BASE" --task-id "$PERSONAL_ID" --status in_progress --reason "integration status 2"

# 8) set_task_status.sh invalid transition should fail (in_progress -> todo)
expect_failure "invalid transition in_progress->todo" \
  "$SET_STATUS" --base "$TEST_BASE" --task-id "$PERSONAL_ID" --status todo --reason "integration invalid transition"

# 9) assign_task.sh owner reassignment keeps status
expect_success "assign owner to codex" \
  "$ASSIGN" --base "$TEST_BASE" --task-id "$PERSONAL_ID" --owner codex --reason "integration assign"

status_now="$(awk -F': ' '/^status:/ {print $2; exit}' "$PERSONAL_DIR/$PERSONAL_ID.md")"
owner_now="$(awk -F': ' '/^owner:/ {print $2; exit}' "$PERSONAL_DIR/$PERSONAL_ID.md")"
if [[ "$status_now" == "in_progress" && "$owner_now" == "codex" ]]; then
  pass "assign helper preserves status and updates owner"
else
  fail "assign helper preserves status and updates owner"
fi

# restore owner to moo for validator expectation
expect_success "assign owner back to moo" \
  "$ASSIGN" --base "$TEST_BASE" --task-id "$PERSONAL_ID" --owner moo --reason "integration restore owner"

# 10) final validator should pass after all operations
expect_success "final validator" "$VALIDATE" "$TEST_BASE"

echo
echo "Task System Integration Test Summary"
echo "- Base under test: $BASE"
echo "- Temp workspace: $TMP_ROOT"
echo "- Passed: $pass_count"
echo "- Failed: $fail_count"

if (( fail_count > 0 )); then
  exit 1
fi

exit 0
