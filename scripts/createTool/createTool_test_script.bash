#!/usr/bin/env bash
# createTool_test_script.bash — golden file diff test suite for createTool
# Tool Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="createTool"
TEST_SCRIPT_NAME="createTool_test_script"
GOLDEN_DIR="$SCRIPT_DIR/createTool_test_golden"
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

TEST_WORKSPACE="$(mktemp -d /tmp/createTool-test.XXXXXX)"
if ! $KEEP_TEMP; then
  trap 'rm -rf "$TEST_WORKSPACE"' EXIT
fi

normalize() {
  sed \
    -e "s|$TEST_WORKSPACE|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e 's|/dil_[0-9]\{10,\}|/dil|g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g' \
    -e 's/pid=[0-9]*/pid=<PID>/g'
}

ACTUAL_DIR="$TEST_WORKSPACE/actual"
mkdir -p "$ACTUAL_DIR"

make_test_base() {
  local test_base="$TEST_WORKSPACE/dil_$(date +%s%N)"
  mkdir -p "$test_base/_shared/_meta"
  mkdir -p "$test_base/_shared/scripts/lib"
  mkdir -p "$test_base/_shared/scripts/bin"
  mkdir -p "$test_base/_shared/logs"
  cp "$SCRIPTS_DIR/lib/resolve_base.sh" "$test_base/_shared/scripts/lib/"
  for optional_library in resolve_base.py script_forge_log.py script_forge_log.sh; do
    if [[ -f "$SCRIPTS_DIR/lib/$optional_library" ]]; then
      cp "$SCRIPTS_DIR/lib/$optional_library" "$test_base/_shared/scripts/lib/"
    fi
  done
  echo "$test_base"
}

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

test_01_dry_run() {
  createTool --name scaffold_test --description "test tool" --base "$BASE" --dry-run 2>&1
}

test_02_create_and_verify_layout() {
  local test_base
  test_base="$(make_test_base)"
  createTool --name scaffold_test --description "test tool" --base "$test_base" 2>&1
  echo "=== LAYOUT ==="
  find "$test_base/_shared/scripts/scaffold_test" -type f -o -type d | sort | sed "s|$test_base|<TMP>/dil|g"
  echo "=== SYMLINK ==="
  readlink "$test_base/_shared/scripts/bin/scaffold_test" || echo "NO SYMLINK"
}

test_03_bash_has_readlink() {
  local test_base
  test_base="$(make_test_base)"
  createTool --name scaffold_test --description "test tool" --base "$test_base" >/dev/null 2>&1
  echo "=== READLINK CHECK ==="
  grep -c 'readlink -f' "$test_base/_shared/scripts/scaffold_test/scaffold_test.bash"
}

test_04_python_has_script_forge_logger() {
  local test_base
  test_base="$(make_test_base)"
  createTool --name scaffold_test --description "test tool" --base "$test_base" >/dev/null 2>&1
  echo "=== SCRIPT_FORGE_LOGGER CHECK ==="
  grep -c 'ScriptForgeLogger' "$test_base/_shared/scripts/scaffold_test/scaffold_test.py"
}

test_05_bash_only_skips_python() {
  local test_base
  test_base="$(make_test_base)"
  createTool --name scaffold_test --description "test tool" --bash-only --base "$test_base" 2>&1
  echo "=== PYTHON FILE EXISTS ==="
  test -f "$test_base/_shared/scripts/scaffold_test/scaffold_test.py" && echo "YES" || echo "NO"
}

test_06_rejects_invalid_name() {
  createTool --name "Bad-Name" --base "$BASE" 2>&1 || true
}

test_07_rejects_existing_drawer() {
  local test_base
  test_base="$(make_test_base)"
  createTool --name scaffold_test --description "first" --base "$test_base" >/dev/null 2>&1
  createTool --name scaffold_test --description "second" --base "$test_base" 2>&1 || true
}

# --- Run tests ---

run_test 1 "dry run"                          test_01_dry_run
run_test 2 "create and verify layout"         test_02_create_and_verify_layout
run_test 3 "bash wrapper has readlink -f"     test_03_bash_has_readlink
run_test 4 "python has ScriptForgeLogger"     test_04_python_has_script_forge_logger
run_test 5 "bash-only skips python file"      test_05_bash_only_skips_python
run_test 6 "rejects invalid name"             test_06_rejects_invalid_name
run_test 7 "rejects existing drawer"          test_07_rejects_existing_drawer

# --- Summary ---

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
