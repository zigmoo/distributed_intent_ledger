#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="git_tool"
TEST_SCRIPT_NAME="git_tool.test_script"
GOLDEN_DIR="$SCRIPT_DIR/git_tool.test_golden"
LOG_DIR="$BASE/_shared/logs/$TEST_SCRIPT_NAME"
mkdir -p "$LOG_DIR" "$GOLDEN_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${TEST_SCRIPT_NAME}.run.${TIMESTAMP}.log"

REBUILD=false
SINGLE_TEST=""
QUIET=false
PASSED=0; FAILED=0; SKIPPED=0; TOTAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=true; shift ;;
    --test) SINGLE_TEST="$2"; shift 2 ;;
    --quiet) QUIET=true; shift ;;
    -h|--help) echo "Usage: $TEST_SCRIPT_NAME [--rebuild] [--test N] [--quiet]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

WORK="$(mktemp -d /tmp/${TOOL_NAME}-test.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
ACTUAL_DIR="$WORK/actual"
mkdir -p "$ACTUAL_DIR"

normalize() {
  sed -e "s|$WORK|<TMP>|g" -e "s|$BASE|<BASE>|g" -e "s|$HOME|<HOME>|g" -e 's/[0-9a-f]\{7,40\}/<SHA>/g'
}

run_test() {
  local n="$1" label="$2" fn="$3"
  TOTAL=$((TOTAL+1))
  if [[ -n "$SINGLE_TEST" && "$SINGLE_TEST" != "$n" ]]; then SKIPPED=$((SKIPPED+1)); return; fi
  $QUIET || printf "\n[%s] %s\n" "$n" "$label"
  local a="$ACTUAL_DIR/test_$(printf '%02d' "$n").actual"
  local g="$GOLDEN_DIR/test_$(printf '%02d' "$n").golden"
  $fn 2>&1 | normalize > "$a"
  if $REBUILD; then cp "$a" "$g"; PASSED=$((PASSED+1)); return; fi
  if diff -u "$g" "$a" >/dev/null 2>&1; then PASSED=$((PASSED+1)); else FAILED=$((FAILED+1)); diff -u "$g" "$a" || true; fi
}

test_01_template() {
  $TOOL_NAME commit-template --task-id DIL-9999 -m "Add deterministic commit templates" --message-ref _shared/messages/20260507_000000.DIL-9999.git-commit-message.test.md --why "enforce standard" --evidence "golden test"
}

test_02_commit_e2e() {
  local r="$WORK/repo"
  mkdir -p "$r"
  git -C "$r" init >/dev/null
  git -C "$r" config user.email test@example.com
  git -C "$r" config user.name "Git Tool Test"
  printf 'hello\n' > "$r/file.txt"
  git -C "$r" add file.txt
  $TOOL_NAME commit --repo "$r" --task-id DIL-9998 -m "Add file for commit template test" --message-ref _shared/messages/20260507_000001.DIL-9998.git-commit-message.test.md --why "test commit path" --evidence "git log"
  git -C "$r" log -1 --pretty=%B
}

test_03_message_file_driven() {
  local msgfile="$WORK/test_message.md"
  cat > "$msgfile" <<'MSGEOF'
---
title: "DIL-7777: Add message-file-driven commit rendering"
date: 2026-05-07
machine: testhost
assistant: test
category: message
memoryType: message
priority: high
tags: [test]
updated: 2026-05-07
source: internal
domain: personal
project: dil
status: draft
owner: test
due:
channel: git
recipient: test-repo
---

Message file body used as why field when no --why is provided on CLI.
MSGEOF
  $TOOL_NAME commit-template --message-ref "$msgfile"
}

test_04_message_file_cli_override() {
  local msgfile="$WORK/test_message_override.md"
  cat > "$msgfile" <<'MSGEOF'
---
title: "DIL-8888: Summary from file should be overridden"
date: 2026-05-07
machine: testhost
assistant: test
category: message
memoryType: message
tags: [test]
updated: 2026-05-07
source: internal
domain: personal
project: dil
status: draft
owner: test
channel: git
recipient: test-repo
---

Body from file should be overridden by --why.
MSGEOF
  $TOOL_NAME commit-template --message-ref "$msgfile" --task-id DIL-9000 -m "CLI summary wins over file" --why "CLI why wins" --evidence "CLI evidence wins"
}

run_test 1 "template render" test_01_template
run_test 2 "commit end-to-end" test_02_commit_e2e
run_test 3 "message-file-driven template" test_03_message_file_driven
run_test 4 "message-file with CLI overrides" test_04_message_file_cli_override

echo ""
if $REBUILD; then echo "=== REBUILT: $PASSED golden baselines regenerated ===";
elif [[ $FAILED -eq 0 ]]; then echo "=== ALL PASSED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ===";
else echo "=== FAILED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="; fi

echo "Log: $LOG_FILE"
[[ $FAILED -eq 0 ]]
