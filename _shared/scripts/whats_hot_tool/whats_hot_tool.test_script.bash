#!/usr/bin/env bash
# whats_hot_tool.test_script.bash — golden file diff test suite for whats_hot_tool
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_CMD="$SCRIPT_DIR/whats_hot_tool.bash"
TOOL_NAME="whats_hot_tool"
TEST_SCRIPT_NAME="whats_hot_tool.test_script"
GOLDEN_DIR="$SCRIPT_DIR/${TEST_SCRIPT_NAME%.test_script}.test_golden"
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

normalize() {
  sed \
    -e "s|$TEST_WORKSPACE|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}\.[0-9]\+/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g' \
    -e 's/pid=[0-9]*/pid=<PID>/g'
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
    echo "  FAIL: output differs from golden baseline"
    diff -u "$golden_file" "$actual_file" || true
    FAILED=$((FAILED + 1))
  fi
}

# --- Test cases ---

test_01_help_output() {
  $TOOL_CMD --help 2>&1 || true
}

test_02_status_empty_file() {
  local hot="$TEST_WORKSPACE/empty_hot.md"
  touch "$hot"
  $TOOL_CMD --hot-path "$hot" status
}

test_03_write_and_read_latest() {
  local hot="$TEST_WORKSPACE/hot_03.md"
  printf '# Entry One\n\nFirst content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Entry One" --agent opencode --machine framemoowork --model kimi-k2.6
  $TOOL_CMD --hot-path "$hot" read --latest --raw
}

test_04_multiple_writes_indexed_read() {
  local hot="$TEST_WORKSPACE/hot_04.md"
  printf '# Alpha\n\nAlpha content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Alpha" --agent codex --machine framemoowork --model gpt-5-codex
  printf '# Beta\n\nBeta content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Beta" --agent opencode --machine framemoowork --model kimi-k2.6
  printf '# Gamma\n\nGamma content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Gamma" --agent opencode --machine framemoowork --model kimi-k2.6
  echo "--- LATEST ---"
  $TOOL_CMD --hot-path "$hot" read --latest --raw
  echo "--- N=1 ---"
  $TOOL_CMD --hot-path "$hot" read -N 1 --raw
  echo "--- N=2 ---"
  $TOOL_CMD --hot-path "$hot" read -N 2 --raw
}

test_05_legacy_content_preserved() {
  local hot="$TEST_WORKSPACE/hot_05.md"
  cat <<'EOF' > "$hot"
---
title: Session Hot State
updated: 2026-04-28T10:00:00-05:00
---

# Legacy Content

Original content here.
EOF
  printf '# New Entry\n\nNew content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "New Entry" --agent opencode --machine framemoowork --model kimi-k2.6
  echo "--- STATUS ---"
  $TOOL_CMD --hot-path "$hot" status
  echo "--- N=1 (legacy) ---"
  $TOOL_CMD --hot-path "$hot" read -N 1 --raw
  echo "--- FILE ---"
  cat "$hot"
}

test_06_dry_run() {
  local hot="$TEST_WORKSPACE/hot_06.md"
  printf '# Dry Run Entry\n\nShould not write.' | $TOOL_CMD --hot-path "$hot" --dry-run write --stdin --title "Dry Run" --agent opencode --machine framemoowork --model kimi-k2.6
  echo "--- FILE AFTER DRY RUN ---"
  cat "$hot" || echo "(file does not exist)"
}

test_07_date_filter() {
  local hot="$TEST_WORKSPACE/hot_07.md"
  printf '# Today Entry\n\nToday content.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Today" --agent opencode --machine framemoowork --model kimi-k2.6
  echo "--- DATE TODAY ---"
  $TOOL_CMD --hot-path "$hot" read --date "$(date -I)" --raw
}

test_08_all_entries() {
  local hot="$TEST_WORKSPACE/hot_08.md"
  printf '# A\n\nContent A.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "A" --agent a --machine m --model x
  printf '# B\n\nContent B.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "B" --agent b --machine m --model y
  $TOOL_CMD --hot-path "$hot" read --all --raw
}

test_09_read_out_of_range() {
  local hot="$TEST_WORKSPACE/hot_09.md"
  printf '# Only\n\nOne entry.' | $TOOL_CMD --hot-path "$hot" write --stdin --title "Only" --agent opencode --machine framemoowork --model kimi-k2.6
  $TOOL_CMD --hot-path "$hot" read -N 5 --raw || true
}

# --- Run tests ---

run_test 1 "help output" test_01_help_output
run_test 2 "status on empty file" test_02_status_empty_file
run_test 3 "write and read latest" test_03_write_and_read_latest
run_test 4 "multiple writes and indexed read" test_04_multiple_writes_indexed_read
run_test 5 "legacy content preserved" test_05_legacy_content_preserved
run_test 6 "dry run does not write" test_06_dry_run
run_test 7 "date filter" test_07_date_filter
run_test 8 "all entries" test_08_all_entries
run_test 9 "read out of range" test_09_read_out_of_range

# --- Summary ---

echo ""
if $REBUILD; then
  echo "=== REBUILT: $PASSED golden baselines regenerated ==="
elif [[ $FAILED -eq 0 ]]; then
  echo "=== ALL PASSED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
else
  echo "=== FAILED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
fi
echo "Log: $LOG_FILE"

[[ $FAILED -eq 0 ]]
