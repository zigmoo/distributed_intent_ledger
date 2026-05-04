#!/usr/bin/env bash
# duckdb_sql_test_script — golden file diff test suite for duckdb_sql
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="duckdb_sql"
TEST_SCRIPT_NAME="duckdb_sql_test_script"
GOLDEN_DIR="$SCRIPT_DIR/test/golden"
TEST_INPUT="$SCRIPT_DIR/test/input"
LOG_DIR="$BASE/_shared/logs/$TEST_SCRIPT_NAME"
mkdir -p "$LOG_DIR" "$GOLDEN_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${TEST_SCRIPT_NAME}.run.${TIMESTAMP}.log"

DUCKDB_SQL="$SCRIPT_DIR/duckdb_sql.bash"

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
    -h|--help) echo "Usage: $TEST_SCRIPT_NAME [--rebuild] [--test N] [--keep-temp] [--quiet]"; exit 0 ;;
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
    -e "s|$SCRIPT_DIR|<SCRIPT_DIR>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g'
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

  if ! $QUIET; then printf "\n[%s] %s\n" "$test_number" "$test_label"; fi

  local actual_file="$ACTUAL_DIR/test_$(printf '%02d' "$test_number").actual"
  local golden_file="$GOLDEN_DIR/test_$(printf '%02d' "$test_number").golden"

  $test_function 2>&1 | normalize > "$actual_file"

  if $REBUILD; then
    cp "$actual_file" "$golden_file"
    if ! $QUIET; then echo "  REBUILT: $golden_file"; fi
    PASSED=$((PASSED + 1))
    return
  fi

  if [[ ! -f "$golden_file" ]]; then
    echo "  SKIP: no golden file (run with --rebuild)"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  if diff -u "$golden_file" "$actual_file" > /dev/null 2>&1; then
    if ! $QUIET; then echo "  PASS"; fi
    PASSED=$((PASSED + 1))
  else
    echo "  FAIL: output differs from golden baseline"
    diff -u "$golden_file" "$actual_file" || true
    FAILED=$((FAILED + 1))
  fi
}

# ─── CSV: basic queries ───

test_01_csv_count_table() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT COUNT(*) FROM people"
}

test_02_csv_count_single_value() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT COUNT(*) FROM people" -S
}

test_03_csv_no_grid() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT COUNT(*) FROM people" -g
}

test_04_csv_no_headers() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT name FROM people" -H
}

test_05_csv_no_grid_no_headers() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT name, age FROM people" -g -H
}

test_06_csv_auto_from() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT name, age WHERE age > 25"
}

test_07_csv_json_output() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT name, city FROM people WHERE city = 'Dallas'" -j
}

test_08_csv_pipe_delimiter() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/pipe_data.csv" -s "SELECT COUNT(*) FROM pipe_data" --sep '|' -S
}

test_09_csv_dot_schema() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s ".schema"
}

# ─── CSV: output file ───

test_10_csv_output_file() {
  local out
  out=$("$DUCKDB_SQL" -d "$TEST_INPUT/people.csv" -s "SELECT COUNT(*) FROM people" -S -F 2>&1)
  local fpath
  fpath=$(echo "$out" | grep "Output written to:" | sed 's/Output written to: //')
  if [[ -f "$fpath" ]]; then
    echo "FILE_EXISTS=true"
    echo "CONTENT=$(cat "$fpath")"
  else
    echo "FILE_EXISTS=false"
  fi
}

# ─── JSONL: single file ───

test_11_jsonl_count() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/accounts.jsonl" -s "SELECT COUNT(*) FROM accounts" -S
}

test_12_jsonl_select() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/accounts.jsonl" -s "SELECT handle, displayName FROM accounts ORDER BY handle" -g -H
}

test_13_jsonl_filter() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/accounts.jsonl" -s "SELECT handle FROM accounts WHERE followerCount > 1000" -H
}

test_14_jsonl_json_output() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/accounts.jsonl" -s "SELECT accountId, handle FROM accounts WHERE accountId = '1001'" -j
}

test_15_jsonl_auto_from() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/accounts.jsonl" -s "SELECT handle WHERE followerCount > 100000" -H
}

# ─── Multi-file: CSV + CSV join ───

test_16_multi_csv_join() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/people.csv" \
    -d "$TEST_INPUT/orders.csv" \
    -s "SELECT p.name, p.city, SUM(o.amount) as total FROM people p JOIN orders o ON p.name = o.name GROUP BY p.name, p.city ORDER BY total DESC, p.name"
}

test_17_multi_csv_count_both() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/people.csv" \
    -d "$TEST_INPUT/orders.csv" \
    -s "SELECT (SELECT COUNT(*) FROM people) as people_count, (SELECT COUNT(*) FROM orders) as order_count" -g -H
}

# ─── Multi-file: JSONL + JSONL join ───

test_18_multi_jsonl_join() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/accounts.jsonl" \
    -d "$TEST_INPUT/account_posts.jsonl" \
    -s "SELECT a.handle, ap.role, ap.tweetId FROM account_posts ap JOIN accounts a ON ap.accountId = a.accountId ORDER BY a.handle, ap.tweetId"
}

test_19_multi_jsonl_group() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/accounts.jsonl" \
    -d "$TEST_INPUT/account_posts.jsonl" \
    -s "SELECT a.handle, COUNT(*) as post_count FROM account_posts ap JOIN accounts a ON ap.accountId = a.accountId GROUP BY a.handle ORDER BY post_count DESC, a.handle" -g -H
}

test_20_multi_jsonl_filter_by_source() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/accounts.jsonl" \
    -d "$TEST_INPUT/account_posts.jsonl" \
    -s "SELECT a.handle, ap.role, ap.sourceTweetId FROM account_posts ap JOIN accounts a ON ap.accountId = a.accountId WHERE ap.sourceTweetId = 't100' ORDER BY a.handle"
}

# ─── Multi-file: mixed CSV + JSONL ───

test_21_multi_mixed_csv_jsonl() {
  "$DUCKDB_SQL" \
    -d "$TEST_INPUT/people.csv" \
    -d "$TEST_INPUT/accounts.jsonl" \
    -s "SELECT p.name, a.handle FROM people p, accounts a WHERE p.name = 'John' AND a.accountId = '1001'" -g -H
}

# ─── Edge cases ───

test_22_nonexistent_file() {
  "$DUCKDB_SQL" -d "$TEST_INPUT/nope.csv" -s "SELECT 1" 2>&1 || true
}

test_23_help_output() {
  "$DUCKDB_SQL" --help 2>&1 | head -5
}

# ─── Register and run all tests ───

run_test  1 "CSV: count with table format"       test_01_csv_count_table
run_test  2 "CSV: count single value"             test_02_csv_count_single_value
run_test  3 "CSV: count no grid"                  test_03_csv_no_grid
run_test  4 "CSV: select no headers"              test_04_csv_no_headers
run_test  5 "CSV: select no grid + no headers"    test_05_csv_no_grid_no_headers
run_test  6 "CSV: auto FROM injection"            test_06_csv_auto_from
run_test  7 "CSV: JSON output"                    test_07_csv_json_output
run_test  8 "CSV: pipe delimiter"                 test_08_csv_pipe_delimiter
run_test  9 "CSV: dot schema"                     test_09_csv_dot_schema
run_test 10 "CSV: output file (-F)"               test_10_csv_output_file
run_test 11 "JSONL: single file count"            test_11_jsonl_count
run_test 12 "JSONL: select with sort"             test_12_jsonl_select
run_test 13 "JSONL: filter by numeric field"      test_13_jsonl_filter
run_test 14 "JSONL: JSON output mode"             test_14_jsonl_json_output
run_test 15 "JSONL: auto FROM injection"          test_15_jsonl_auto_from
run_test 16 "Multi-CSV: JOIN two files"           test_16_multi_csv_join
run_test 17 "Multi-CSV: subquery both tables"     test_17_multi_csv_count_both
run_test 18 "Multi-JSONL: JOIN two files"         test_18_multi_jsonl_join
run_test 19 "Multi-JSONL: GROUP BY across files"  test_19_multi_jsonl_group
run_test 20 "Multi-JSONL: filter by sourceTweet"  test_20_multi_jsonl_filter_by_source
run_test 21 "Mixed: CSV + JSONL cross-query"      test_21_multi_mixed_csv_jsonl
run_test 22 "Edge: nonexistent file error"        test_22_nonexistent_file
run_test 23 "Edge: help output"                   test_23_help_output

echo ""
if $REBUILD; then
  echo "=== REBUILT: $PASSED golden baselines regenerated ==="
elif [[ $FAILED -eq 0 ]]; then
  echo "=== ALL PASSED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
else
  echo "=== FAILED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
fi
echo "Golden dir: $GOLDEN_DIR"
echo "Log: $LOG_FILE"

[[ $FAILED -eq 0 ]]
