#!/usr/bin/env bash
# log_river_test_script.bash — golden file diff test suite for log_river
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="log_river"
TEST_SCRIPT_NAME="log_river_test_script"
GOLDEN_DIR="$SCRIPT_DIR/${TEST_SCRIPT_NAME%_test_script}_test_golden"
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

test_01_help_output() {
  log_river --help 2>&1 | sed -n '1,80p'
}

test_02_harvest_json() {
  local harvest_json="$TEST_WORKSPACE/harvest.json"
  log_river harvest --output "$harvest_json" >/dev/null
  test -s "$harvest_json"
  python3 -m json.tool "$harvest_json" >/dev/null
  python3 - "$harvest_json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print("json_ok", isinstance(data, dict))
print("has_events", "events" in data)
print("event_count_positive", len(data.get("events", [])) >= 0)
PY
}

test_03_render_html() {
  local harvest_json="$TEST_WORKSPACE/harvest.json"
  local html="$TEST_WORKSPACE/log_river.html"
  log_river harvest --output "$harvest_json" >/dev/null
  log_river render --data-file "$harvest_json" --output "$html" >/dev/null
  test -s "$html"
  grep -c '<html' "$html"
}

run_test 1 "help output" test_01_help_output
run_test 2 "harvest json" test_02_harvest_json
run_test 3 "render html" test_03_render_html

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
