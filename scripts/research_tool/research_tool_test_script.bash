#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
KEEP_TEMP=0
QUIET=0

usage() {
  cat <<'USAGE'
Usage:
  test_research_tool.sh [options]

Options:
  --base PATH        Base path for DIL (default: BASE_DIL -> repo-relative -> $HOME fallback)
  --keep-temp        Keep the isolated temp vault for debugging
  --quiet            Show only summary/errors
  -h, --help         Show help

What it tests (in isolated temp vault — live vault is never modified):
- registry loading from shared JSON
- create/validate for all built-in families
- alias handling via `create --type ...`
- additive registry override via RESEARCH_TOOL_ARTIFACT_TYPES_JSON
- duplicate-artifact handling with and without `--force`
- research index updates for every created artifact
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
  if "$@" >/tmp/research_tool_test.out 2>/tmp/research_tool_test.err; then
    pass "$name"
  else
    fail "$name"
    cat /tmp/research_tool_test.out >&2 || true
    cat /tmp/research_tool_test.err >&2 || true
  fi
}

expect_failure() {
  local name="$1"
  shift
  if "$@" >/tmp/research_tool_test.out 2>/tmp/research_tool_test.err; then
    fail "$name (unexpected success)"
    cat /tmp/research_tool_test.out >&2 || true
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
  "$BASE/_shared/scripts/research_tool.sh" \
  "$BASE/_shared/_meta/research_artifact_registry.json" \
  "$BASE/_shared/_meta/research_artifact_registry.md"
do
  if [[ ! -e "$req" ]]; then
    echo "Missing required registry asset: $req" >&2
    exit 1
  fi
done

TMP_ROOT="$(mktemp -d /tmp/research-tool-tests.XXXXXX)"
TEST_BASE="$TMP_ROOT/vault"
mkdir -p "$TEST_BASE/_shared/_meta"
cp "$BASE/_shared/_meta/research_artifact_registry.json" "$TEST_BASE/_shared/_meta/research_artifact_registry.json"
cp "$BASE/_shared/_meta/research_artifact_registry.md" "$TEST_BASE/_shared/_meta/research_artifact_registry.md"
: > "$TEST_BASE/_shared/_meta/vault_index.md"

cleanup() {
  if (( KEEP_TEMP == 0 )); then
    rm -rf "$TMP_ROOT"
  else
    echo "Kept temp workspace: $TMP_ROOT"
  fi
}
trap cleanup EXIT

TOOL="$BASE/_shared/scripts/research_tool.sh"

run_tool() {
  BASE_DIL="$TEST_BASE" "$TOOL" "$@"
}

validate_artifact() {
  local path="$1"
  run_tool validate --artifact "$path"
}

run_create() {
  local body="$1"
  shift
  printf '%s\n' "$body" | BASE_DIL="$TEST_BASE" "$TOOL" "$@"
}

run_create_with_override() {
  local body="$1"
  local override_json="$2"
  shift 2
  printf '%s\n' "$body" | BASE_DIL="$TEST_BASE" RESEARCH_TOOL_ARTIFACT_TYPES_JSON="$override_json" "$TOOL" "$@"
}

run_create_with_registry_file() {
  local body="$1"
  local registry_file="$2"
  shift 2
  printf '%s\n' "$body" | BASE_DIL="$TEST_BASE" RESEARCH_TOOL_ARTIFACT_TYPES_FILE="$registry_file" "$TOOL" "$@"
}

# Built-in families
expect_success "create benchmarking" run_create "# benchmark body" benchmark --task-id DIL-2001 --title built-in-benchmark
expect_success "create execution-notes" run_create "# execution body" execution --task-id DIL-2002 --title built-in-execution
expect_success "create conclusions" run_create "# conclusion body" conclude --task-id DIL-2003 --title built-in-conclusion
expect_success "create ideas" run_create "# idea body" ideas --task-id DIL-2004 --title built-in-idea
expect_success "create comparisons" run_create "# comparison body" comparisons --task-id DIL-2005 --title built-in-comparison
expect_success "create prompts" run_create "# prompt body" prompts --task-id DIL-2006 --title built-in-prompt
expect_success "create errata" run_create "# correction body" errata --task-id DIL-2007 --title built-in-correction

# Alias and registry override coverage via create --type
expect_success "create alias type via create --type idea" run_create "# alias idea body" create --type idea --task-id DIL-2008 --title alias-idea
expect_success "create alias type via create --type comparison" run_create "# alias comparison body" create --type comparison --task-id DIL-2009 --title alias-comparison
expect_success "create alias type via create --type prompt" run_create "# alias prompt body" create --type prompt --task-id DIL-2010 --title alias-prompt
expect_success "create alias type via create --type correction" run_create "# alias correction body" create --type correction --task-id DIL-2011 --title alias-correction

# Additive registry override: introduce a new family without editing code.
OVERRIDE_JSON='{"types":{"digests":{"dir":"digests","category":"digests","memoryType":"observation","kind":"digest","default_status":"active"}},"aliases":{"digest":"digests"}}'
expect_success "create override type via registry JSON" run_create_with_override "# digest body" "$OVERRIDE_JSON" create --type digest --task-id DIL-2012 --title override-digest

# Negative registry cases: malformed JSON string/file and missing required spec fields should fail clearly.
expect_failure "malformed registry JSON string" bash -lc 'printf "%s\n" "# bad json body" | BASE_DIL="'$TEST_BASE'" RESEARCH_TOOL_ARTIFACT_TYPES_JSON="{bad json" "'$TOOL'" create --type ideas --task-id DIL-2014 --title bad-json-string'
BAD_SPEC_FILE="$TMP_ROOT/bad-spec.json"
printf '%s\n' '{"types": {"broken": {"dir": "broken", "category": "broken", "memoryType": "observation"}}}' > "$BAD_SPEC_FILE"
expect_failure "registry spec missing required field" run_create_with_registry_file "# bad spec body" "$BAD_SPEC_FILE" create --type ideas --task-id DIL-2015 --title bad-spec
BAD_REG_FILE="$TMP_ROOT/bad-registry.json"
printf '%s\n' '{"types": {"broken": {"dir": "broken"}}' > "$BAD_REG_FILE"
expect_failure "malformed registry JSON file" run_create_with_registry_file "# bad file body" "$BAD_REG_FILE" create --type ideas --task-id DIL-2016 --title bad-json-file

# Duplicate handling: same filename should fail without --force and succeed with it.
DUP_TS="2026-04-16T070000Z"
expect_success "create duplicate seed artifact" run_create "# seed body" ideas --task-id DIL-2013 --title duplicate-guard --timestamp "$DUP_TS"
expect_failure "duplicate artifact without --force" run_create "# replacement body" ideas --task-id DIL-2013 --title duplicate-guard --timestamp "$DUP_TS"
expect_success "duplicate artifact with --force" run_create "# replacement body" ideas --task-id DIL-2013 --title duplicate-guard --timestamp "$DUP_TS" --force

DUP_PATH="$TEST_BASE/_shared/research/ideas/DIL-2013-idea-${DUP_TS}-duplicate-guard.md"
if [[ -f "$DUP_PATH" ]] && grep -q "replacement body" "$DUP_PATH"; then
  pass "force overwrite updated duplicate artifact"
else
  fail "force overwrite updated duplicate artifact"
fi

# Validate created artifacts and ensure paths exist.
for tid in 2001 2002 2003 2004 2005 2006 2007 2008 2009 2010 2011 2012 2013; do
  case "$tid" in
    2001) family="benchmarking" ;;
    2002) family="execution-notes" ;;
    2003) family="conclusions" ;;
    2004) family="ideas" ;;
    2005) family="comparisons" ;;
    2006) family="prompts" ;;
    2007) family="errata" ;;
    2008) family="ideas" ;;
    2009) family="comparisons" ;;
    2010) family="prompts" ;;
    2011) family="errata" ;;
    2012) family="digests" ;;
    2013) family="ideas" ;;
  esac
  artifact_path=$(find "$TEST_BASE/_shared/research/$family" -maxdepth 1 -type f -name "DIL-$tid-*" | head -n 1)
  if [[ -n "$artifact_path" && -f "$artifact_path" ]]; then
    pass "artifact exists for DIL-$tid ($family)"
    validate_artifact "$artifact_path"
  else
    fail "artifact exists for DIL-$tid ($family)"
  fi
done

# Confirm the research index has rows for all created artifacts.
index_file="$TEST_BASE/_shared/research/_meta/index.md"
missing_rows=0
for tid in 2001 2002 2003 2004 2005 2006 2007 2008 2009 2010 2011 2012 2013; do
  if ! grep -q "| DIL-$tid |" "$index_file"; then
    fail "research index row for DIL-$tid"
    missing_rows=1
  else
    pass "research index row for DIL-$tid"
  fi
done

# Ensure alias acceptance works for create --type path and registry override exposed a new directory.
if [[ -d "$TEST_BASE/_shared/research/digests" ]]; then
  pass "override directory created"
else
  fail "override directory created"
fi

if (( fail_count == 0 )); then
  echo
  echo "Research Tool Integration Test Summary"
  echo "PASS: $pass_count"
  echo "FAIL: $fail_count"
  exit 0
fi

echo
 echo "Research Tool Integration Test Summary"
 echo "PASS: $pass_count"
 echo "FAIL: $fail_count"
 exit 1
