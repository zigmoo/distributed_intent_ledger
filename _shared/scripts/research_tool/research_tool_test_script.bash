#!/usr/bin/env bash
# research_tool_test_script.bash — golden file diff test suite for research_tool
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="research_tool"
TEST_SCRIPT_NAME="research_tool_test_script"
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
    -e 's|/tmp/tmp\.[A-Za-z0-9]*|<TMP>|g' \
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

make_test_base() {
  local test_base="$TEST_WORKSPACE/dil_$1"
  mkdir -p "$test_base/_shared/_meta"
  cp "$BASE/_shared/_meta/research_artifact_registry.json" "$test_base/_shared/_meta/research_artifact_registry.json"
  cp "$BASE/_shared/_meta/research_artifact_registry.md" "$test_base/_shared/_meta/research_artifact_registry.md"
  : > "$test_base/_shared/_meta/vault_index.md"
  echo "$test_base"
}

run_tool() {
  local test_base="$1"
  shift
  BASE_DIL="$test_base" research_tool "$@"
}

run_create() {
  local test_base="$1"
  local body="$2"
  shift 2
  printf '%s\n' "$body" | BASE_DIL="$test_base" research_tool "$@"
}

test_01_help_output() {
  research_tool --help 2>&1 | sed -n '1,80p'
}

test_02_create_builtin_families() {
  local test_base
  test_base="$(make_test_base builtin)"
  run_create "$test_base" "# benchmark body" benchmark --task-id DIL-2001 --title built-in-benchmark --timestamp 2026-04-29T100001Z
  run_create "$test_base" "# execution body" execution --task-id DIL-2002 --title built-in-execution --timestamp 2026-04-29T100002Z
  run_create "$test_base" "# conclusion body" conclude --task-id DIL-2003 --title built-in-conclusion --timestamp 2026-04-29T100003Z
  run_create "$test_base" "# idea body" ideas --task-id DIL-2004 --title built-in-idea --timestamp 2026-04-29T100004Z
  run_create "$test_base" "# comparison body" comparisons --task-id DIL-2005 --title built-in-comparison --timestamp 2026-04-29T100005Z
  run_create "$test_base" "# prompt body" prompts --task-id DIL-2006 --title built-in-prompt --timestamp 2026-04-29T100006Z
  run_create "$test_base" "# correction body" errata --task-id DIL-2007 --title built-in-correction --timestamp 2026-04-29T100007Z
  echo "artifact_count=$(find "$test_base/_shared/research" -type f -name 'DIL-*.md' | wc -l)"
  echo "index_rows=$(grep -c '| DIL-20' "$test_base/_shared/research/_meta/index.md")"
}

test_03_alias_override_and_duplicates() {
  local test_base override_json dup_path
  test_base="$(make_test_base override)"
  run_create "$test_base" "# alias idea body" create --type idea --task-id DIL-2008 --title alias-idea --timestamp 2026-04-29T100008Z
  override_json='{"types":{"digests":{"dir":"digests","category":"digests","memoryType":"observation","kind":"digest","default_status":"active"}},"aliases":{"digest":"digests"}}'
  printf '%s\n' "# digest body" | BASE_DIL="$test_base" RESEARCH_TOOL_ARTIFACT_TYPES_JSON="$override_json" research_tool create --type digest --task-id DIL-2009 --title override-digest --timestamp 2026-04-29T100009Z
  run_create "$test_base" "# seed body" ideas --task-id DIL-2010 --title duplicate-guard --timestamp 2026-04-29T100010Z
  if run_create "$test_base" "# replacement body" ideas --task-id DIL-2010 --title duplicate-guard --timestamp 2026-04-29T100010Z; then
    echo "duplicate_without_force=unexpected_success"
  else
    echo "duplicate_without_force=failed_as_expected"
  fi
  run_create "$test_base" "# replacement body" ideas --task-id DIL-2010 --title duplicate-guard --timestamp 2026-04-29T100010Z --force
  dup_path="$test_base/_shared/research/ideas/DIL-2010-idea-2026-04-29T100010Z-duplicate-guard.md"
  echo "override_dir_exists=$([[ -d "$test_base/_shared/research/digests" ]] && echo yes || echo no)"
  echo "force_replaced=$([[ -f "$dup_path" ]] && grep -q 'replacement body' "$dup_path" && echo yes || echo no)"
}

test_04_validate_and_registry_errors() {
  local test_base artifact_path bad_spec bad_file
  test_base="$(make_test_base validate)"
  run_create "$test_base" "# idea body" ideas --task-id DIL-2011 --title validate-me --timestamp 2026-04-29T100011Z >/dev/null
  artifact_path="$(find "$test_base/_shared/research/ideas" -maxdepth 1 -type f -name 'DIL-2011-*' | head -n 1)"
  run_tool "$test_base" validate --artifact "$artifact_path"
  if printf '%s\n' "# bad json body" | BASE_DIL="$test_base" RESEARCH_TOOL_ARTIFACT_TYPES_JSON='{bad json' research_tool create --type ideas --task-id DIL-2012 --title bad-json-string; then
    echo "bad_json_string=unexpected_success"
  else
    echo "bad_json_string=failed_as_expected"
  fi
  bad_spec="$TEST_WORKSPACE/bad-spec.json"
  printf '%s\n' '{"types": {"broken": {"dir": "broken", "category": "broken", "memoryType": "observation"}}}' > "$bad_spec"
  if printf '%s\n' "# bad spec body" | BASE_DIL="$test_base" RESEARCH_TOOL_ARTIFACT_TYPES_FILE="$bad_spec" research_tool create --type ideas --task-id DIL-2013 --title bad-spec; then
    echo "bad_spec=unexpected_success"
  else
    echo "bad_spec=failed_as_expected"
  fi
  bad_file="$TEST_WORKSPACE/bad-registry.json"
  printf '%s\n' '{"types": {"broken": {"dir": "broken"}}' > "$bad_file"
  if printf '%s\n' "# bad file body" | BASE_DIL="$test_base" RESEARCH_TOOL_ARTIFACT_TYPES_FILE="$bad_file" research_tool create --type ideas --task-id DIL-2014 --title bad-json-file; then
    echo "bad_file=unexpected_success"
  else
    echo "bad_file=failed_as_expected"
  fi
}

run_test 1 "help output" test_01_help_output
run_test 2 "create builtin families" test_02_create_builtin_families
run_test 3 "alias override and duplicates" test_03_alias_override_and_duplicates
run_test 4 "validate and registry errors" test_04_validate_and_registry_errors

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
