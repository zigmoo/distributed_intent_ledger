#!/usr/bin/env bash
# morning_brief.test_script.bash — golden file diff test suite for morning_brief
# Tool Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="morning_brief"
TEST_SCRIPT_NAME="morning_brief.test_script"
GOLDEN_DIR="$SCRIPT_DIR/${TOOL_NAME}_test_golden"
LOG_DIR="$BASE/_shared/logs/$TEST_SCRIPT_NAME"
mkdir -p "$LOG_DIR" "$GOLDEN_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${TEST_SCRIPT_NAME}.run.${TIMESTAMP}.log"

REBUILD=false
SINGLE_TEST=""
KEEP_TEMP=false
QUIET=false
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=true; shift ;;
    --test) SINGLE_TEST="$2"; shift 2 ;;
    --keep-temp) KEEP_TEMP=true; shift ;;
    --quiet) QUIET=true; shift ;;
    -h|--help)
      echo "Usage: $TEST_SCRIPT_NAME [--rebuild] [--test N] [--keep-temp] [--quiet]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

TEST_WORKSPACE="$(mktemp -d /tmp/${TOOL_NAME}-test.XXXXXX)"
if ! $KEEP_TEMP; then
  trap 'rm -rf "$TEST_WORKSPACE"' EXIT
fi

normalize() {
  sed \
    -e "s|$TEST_WORKSPACE|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g' \
    -e 's/pid=[0-9]*/pid=<PID>/g' \
    -e 's/Generated: .*/Generated: TIMESTAMP/g' \
    -e 's/^## Morning Brief.*/## Morning Brief — DATE/g'
}

ACTUAL_DIR="$TEST_WORKSPACE/actual"
mkdir -p "$ACTUAL_DIR"

run_test() {
  local test_number="$1"
  local test_label="$2"
  local test_function="$3"
  TOTAL=$((TOTAL + 1))

  if [[ -n "$SINGLE_TEST" && "$SINGLE_TEST" != "$test_number" ]]; then
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  if ! $QUIET; then
    printf "\n[%s] %s\n" "$test_number" "$test_label"
  fi

  local actual_file="$ACTUAL_DIR/test_$(printf '%02d' "$test_number").actual"
  local golden_file="$GOLDEN_DIR/test_$(printf '%02d' "$test_number").golden"

  $test_function 2>&1 | normalize > "$actual_file"

  if $REBUILD; then
    cp "$actual_file" "$golden_file"
    if ! $QUIET; then
      echo "  REBUILT: $golden_file"
    fi
    PASSED=$((PASSED + 1))
    return
  fi

  if [[ ! -f "$golden_file" ]]; then
    echo "  SKIP: no golden file (run with --rebuild)"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  if diff -u "$golden_file" "$actual_file" > /dev/null 2>&1; then
    if ! $QUIET; then
      echo "  PASS"
    fi
    PASSED=$((PASSED + 1))
  else
    echo "  FAIL"
    diff -u "$golden_file" "$actual_file" || true
    FAILED=$((FAILED + 1))
  fi
}

# --- Test environment setup ---
# Create a minimal DIL structure with controlled task data

setup_test_dil() {
  local test_base="$1"
  mkdir -p "$test_base/_shared/_meta"
  mkdir -p "$test_base/_shared/logs/morning_brief"
  mkdir -p "$test_base/_shared/signals"
  mkdir -p "$test_base/_shared/domains/personal/tasks/active"
  mkdir -p "$test_base/_shared/domains/work/tasks/active"

  # Domain registry
  cat > "$test_base/_shared/_meta/domain_registry.json" << 'DREOF'
{
  "domains": {
    "personal": {
      "path": "_shared/domains/personal",
      "task_prefix": "DIL",
      "archive_after_days": 30
    },
    "work": {
      "path": "_shared/domains/work",
      "task_prefix": "WORK",
      "archive_after_days": 30
    }
  }
}
DREOF

  # Task index CSV with controlled test data
  cat > "$test_base/_shared/_meta/task_index.csv" << 'CSVEOF'
task_id,title,status,priority,domain,project,due,updated,created_at
DIL-1001,Test task active todo,todo,high,personal,dil,,2026-05-01,2026-05-01T12:00:00Z
DIL-1002,Test task in progress,in-progress,medium,personal,dil,,2026-05-01,2026-05-01T12:00:00Z
DIL-1003,Test task done,done,low,personal,dil,,2026-05-01,2026-05-01T12:00:00Z
WORK-9999,Work task blocked,blocked,high,work,deploytool,2026-05-10,2026-04-20,2026-04-20T12:00:00Z
CSVEOF

  # Empty hot file
  touch "$test_base/_shared/_hot.md"

  # Empty reminders
  touch "$test_base/_shared/reminders.md"
}

# --- Tests ---

test_01_help() {
  python3 "$SCRIPT_DIR/morning_brief.py" --help
}

test_02_dry_run_minimal() {
  local test_base="$TEST_WORKSPACE/test_02"
  setup_test_dil "$test_base"
  python3 "$SCRIPT_DIR/morning_brief.py" --base "$test_base" --dry-run
}

test_03_dry_run_no_tasks() {
  local test_base="$TEST_WORKSPACE/test_03"
  setup_test_dil "$test_base"
  # Remove task index to simulate empty state
  rm -f "$test_base/_shared/_meta/task_index.csv"
  cat > "$test_base/_shared/_meta/task_index.csv" << 'CSVEOF'
task_id,title,status,priority,domain,project,due,updated,created_at
CSVEOF
  python3 "$SCRIPT_DIR/morning_brief.py" --base "$test_base" --dry-run
}

test_04_reminders_not_clobbered() {
  local test_base="$TEST_WORKSPACE/test_04"
  setup_test_dil "$test_base"
  echo "# Existing content" > "$test_base/_shared/reminders.md"
  echo "Do not delete this line" >> "$test_base/_shared/reminders.md"
  python3 "$SCRIPT_DIR/morning_brief.py" --base "$test_base" --dry-run > /dev/null 2>&1
  # Verify existing content is preserved (dry-run shouldn't touch it)
  cat "$test_base/_shared/reminders.md"
}

# --- Run tests ---

run_test 1 "help output"                    test_01_help
run_test 2 "dry run with minimal tasks"     test_02_dry_run_minimal
run_test 3 "dry run with no tasks"          test_03_dry_run_no_tasks
run_test 4 "reminders.md not clobbered"     test_04_reminders_not_clobbered

# --- Summary ---

echo ""
echo "========================================="
echo "  $TEST_SCRIPT_NAME results"
echo "  PASSED=$PASSED FAILED=$FAILED SKIPPED=$SKIPPED TOTAL=$TOTAL"
echo "  LOG=$LOG_FILE"
echo "========================================="

[[ $FAILED -eq 0 ]] || exit 1
