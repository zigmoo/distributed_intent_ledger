#!/usr/bin/env bash
# llm_tool.test_script.bash — golden file diff test suite for llm_tool
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="llm_tool"
TEST_SCRIPT_NAME="llm_tool.test_script"
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
    -h|--help) echo "Usage: $TEST_SCRIPT_NAME [--rebuild] [--test N] [--keep-temp] [--quiet]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

TEST_WORKSPACE="$(mktemp -d /tmp/${TOOL_NAME}-test.XXXXXX)"
if ! $KEEP_TEMP; then
  trap 'rm -rf "$TEST_WORKSPACE"' EXIT
fi

PYTHON_PATH=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_PATH="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_PATH" ]]; then
  echo "ERR: Python 3 not found" >&2
  exit 4
fi

normalize() {
  sed \
    -e "s|$TEST_WORKSPACE|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e "s|$SCRIPT_DIR|<TOOL_DIR>|g" \
    -e 's|/tmp/tmp\.[A-Za-z0-9]*|<TMP>|g' \
    -e "s|/tmp/${TOOL_NAME}-test\.[A-Za-z0-9]*|<TMP>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}[+-][0-9]\{2\}:[0-9]\{2\}/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g' \
    -e 's/pid=[0-9]*/pid=<PID>/g' \
    -e 's/Python [0-9]\.[0-9]*\.[0-9]*/Python X.Y.Z/g'
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
  mkdir -p "$test_base/_shared/logs/llm_tool"
  echo "$test_base"
}

# --- Test cases ---

test_01_help_output() {
  BASE_DIL="$TEST_WORKSPACE/dil_help" "$PYTHON_PATH" "$SCRIPT_DIR/llm_tool.py" --help 2>&1
}

test_02_path_resolution() {
  local test_base
  test_base="$(make_test_base pathres)"
  "$PYTHON_PATH" -c "
import sys, os
os.environ['BASE_DIL'] = '$test_base'
sys.path.insert(0, '$SCRIPT_DIR')
import importlib
import llm_tool as lmt
importlib.reload(lmt)
print(f'DIL_BASE={lmt.DIL_BASE}')
print(f'REGISTRY_relative={str(lmt.REGISTRY).replace(str(lmt.DIL_BASE), \"<BASE>\")}')
print(f'RUN_LEDGER_relative={str(lmt.RUN_LEDGER).replace(str(lmt.DIL_BASE), \"<BASE>\")}')
print(f'CONTEXT_CACHE_relative={str(lmt.CONTEXT_CACHE).replace(str(lmt.DIL_BASE), \"<BASE>\")}')
print(f'EVENTS_CSV_starts_with_base={str(lmt.EVENTS_CSV).startswith(str(lmt.DIL_BASE))}')
print('path_resolution=ok')
" 2>&1
}

test_03_shlex_escaping() {
  local test_base
  test_base="$(make_test_base shlex)"
  "$PYTHON_PATH" -c "
import sys, os, subprocess, shlex
from unittest import mock
os.environ['BASE_DIL'] = '$test_base'
sys.path.insert(0, '$SCRIPT_DIR')
import importlib
import llm_tool as lmt
importlib.reload(lmt)

lmt.ARGS = lmt.parse_args(['--remote-timeout', '10'])
mock_run = mock.patch('llm_tool.run',
    return_value=subprocess.CompletedProcess([], 0, stdout='', stderr='')).start()

malicious_ids = [
    \"model'; rm -rf /; echo '\",
    'model\$(whoami)',
    'model;echo pwned',
    'model|cat /etc/passwd',
]

results = []
for mid in malicious_ids:
    rec = lmt.ModelRuntimeRecord(
        host='test', server='lmstudio', provider='lmstudio', registry_key='k', api_model_id=mid)
    lmt.load_remote_model(rec, 8192)
    shell_cmd = mock_run.call_args[0][0][-1]
    safe = shlex.quote(mid)
    ok = safe in shell_cmd
    results.append(f'load_remote_model mid={mid!r} quoted={ok}')
    mock_run.reset_mock()

    lmt.remote_current_context('test', mid)
    shell_cmd = mock_run.call_args[0][0][-1]
    ok = safe in shell_cmd and 'sys.argv[1]' in shell_cmd
    results.append(f'remote_current_context mid={mid!r} quoted={ok} sys_argv={\"sys.argv[1]\" in shell_cmd}')
    mock_run.reset_mock()

for r in results:
    print(r)

all_ok = all('quoted=True' in r for r in results)
print(f'all_escaped={all_ok}')
" 2>&1
}

test_04_file_handle_leak() {
  local test_base
  test_base="$(make_test_base fhleak)"
  mkdir -p "$test_base/_shared/logs/llm_tool"
  "$PYTHON_PATH" -c "
import sys, os, json
os.environ['BASE_DIL'] = '$test_base'
sys.path.insert(0, '$SCRIPT_DIR')
import importlib
import llm_tool as lmt
importlib.reload(lmt)
from pathlib import Path

ledger = Path('$test_base') / '_shared' / 'logs' / 'llm_tool' / 'llm_tool_runs.jsonl'
lmt.RUN_LEDGER = ledger
lmt.ok = lmt.fail = lmt.retry_ok = lmt.retry_fail = 0
lmt.ratchet_retry_ok = lmt.ratchet_retry_fail = 0
lmt.optimize_ok = lmt.optimize_fail = 0
lmt.guardrail = lmt.bad_id = lmt.ctx_err = 0
lmt.print_summary(10, 5, run_mode='test')

exists = ledger.exists()
content = ledger.read_text().strip() if exists else ''
record = json.loads(content) if content else {}
print(f'ledger_exists={exists}')
print(f'tool={record.get(\"tool\", \"\")}')
print(f'total={record.get(\"total\", \"\")}')
print(f'selected={record.get(\"selected\", \"\")}')
print(f'mode={record.get(\"mode\", \"\")}')

import inspect
source = inspect.getsource(lmt.print_summary)
print(f'uses_with_block={\"with RUN_LEDGER.open\" in source}')
print('file_handle_test=ok')
" 2>&1
}

test_05_forge_logger_integration() {
  local test_base
  test_base="$(make_test_base logger)"
  mkdir -p "$test_base/_shared/logs/llm_tool"
  "$PYTHON_PATH" -c "
import sys, os
os.environ['BASE_DIL'] = '$test_base'
sys.path.insert(0, '$SCRIPT_DIR')
import importlib
import llm_tool as lmt
importlib.reload(lmt)

print(f'ToolForgeLogger_imported={\"ToolForgeLogger\" in dir(lmt)}')
print(f'LOG_var_exists={hasattr(lmt, \"LOG\")}')

from pathlib import Path
log_dir = Path('$test_base') / '_shared' / 'logs' / 'llm_tool'
from tool_forge_log import ToolForgeLogger
logger = ToolForgeLogger('llm_tool', 'test', '$test_base')
logger.info('test message')
logger.close()
log_files = list(log_dir.glob('llm_tool.test.*.log'))
print(f'forge_log_created={len(log_files) > 0}')
if log_files:
    content = log_files[0].read_text()
    print(f'has_log_file_header={\"LOG_FILE:\" in content}')
    print(f'has_info_line={\"INFO\" in content}')
    print(f'has_section_header={\"Section\" in content}')
print('forge_logger_test=ok')
" 2>&1
}

# --- Run tests ---

run_test 1 "help output" test_01_help_output
run_test 2 "path resolution via BASE_DIL" test_02_path_resolution
run_test 3 "shlex escaping of malicious model IDs" test_03_shlex_escaping
run_test 4 "file handle leak fix (with-block)" test_04_file_handle_leak
run_test 5 "ToolForgeLogger integration" test_05_forge_logger_integration

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
