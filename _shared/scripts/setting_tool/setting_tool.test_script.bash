#!/usr/bin/env bash
# setting_tool.test_script.bash — golden file diff test suite for setting_tool
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="setting_tool"
TEST_SCRIPT_NAME="setting_tool.test_script"
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
  $TOOL_NAME --help 2>&1 || true
}

test_02_default_fallback() {
  local settings_file="$TEST_WORKSPACE/missing-settings.json"
  $TOOL_NAME --settings-file "$settings_file" get scriptForgeQcDashboardBuildRetentionCount
  $TOOL_NAME --settings-file "$settings_file" get scriptForgeQcDataRetentionWindowDays
  $TOOL_NAME --settings-file "$settings_file" get scriptForgeQcDataRetentionMaxTestExecutions
}

test_03_add_setting() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set alphaSetting '"one"'
  $TOOL_NAME --settings-file "$settings_file" get alphaSetting
}

test_04_update_setting() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set alphaSetting '"one"' >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set alphaSetting '"two"'
  $TOOL_NAME --settings-file "$settings_file" get alphaSetting
}

test_05_list_include_defaults() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set alphaSetting '"one"' >/dev/null
  $TOOL_NAME --settings-file "$settings_file" list --include-defaults
}

test_06_missing_setting() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" get missingSetting 2>&1 || true
}

test_07_typed_values() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set dateSetting 2026-04-28 --type date >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set timestampSetting 2026-04-28T06:45:00Z --type timestamp >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set integerSetting 30 --type int >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set decimalSetting 12.3400 --type decimal >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set sequenceSetting '["alpha","beta"]' --type sequence >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set pathSetting '~/Documents/dil_agentic_memory_0001/_shared/artifacts' --type path >/dev/null
  $TOOL_NAME --settings-file "$settings_file" set urlSetting 'https://example.com/path?q=1' --type url >/dev/null
  $TOOL_NAME --settings-file "$settings_file" get dateSetting
  $TOOL_NAME --settings-file "$settings_file" get timestampSetting
  $TOOL_NAME --settings-file "$settings_file" get integerSetting
  $TOOL_NAME --settings-file "$settings_file" get decimalSetting
  $TOOL_NAME --settings-file "$settings_file" get sequenceSetting
  $TOOL_NAME --settings-file "$settings_file" get pathSetting
  $TOOL_NAME --settings-file "$settings_file" get urlSetting
}

test_08_invalid_date() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set badDate 2026-99-99 --type date 2>&1 || true
}

test_09_invalid_url() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set badUrl 'example.com/path' --type url 2>&1 || true
}

test_10_invalid_path() {
  local settings_file="$TEST_WORKSPACE/settings.json"
  $TOOL_NAME --settings-file "$settings_file" set badPath '' --type path 2>&1 || true
}

# --- Run tests ---

run_test 1 "help output" test_01_help_output
run_test 2 "default fallback" test_02_default_fallback
run_test 3 "add setting" test_03_add_setting
run_test 4 "update setting" test_04_update_setting
run_test 5 "list include defaults" test_05_list_include_defaults
run_test 6 "missing setting" test_06_missing_setting
run_test 7 "typed values" test_07_typed_values
run_test 8 "invalid date" test_08_invalid_date
run_test 9 "invalid url" test_09_invalid_url
run_test 10 "invalid path" test_10_invalid_path

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
