#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
KEEP_TEMP=0
QUIET=0

usage() {
  cat << 'USAGE'
Usage:
  test_validate_tasks.sh [options]

Options:
  --base PATH        Base path for agentic_memory (default: auto-detected from script location)
  --keep-temp        Keep temporary test workspace for debugging
  --quiet            Show only summary/errors
  -h, --help         Show help

What it tests (in isolated temp workspace — live vault is never modified):
  0. Live vault baseline pass
  1. Clean minimal vault passes
  2. Enum validation: invalid status, priority, work_type, task_type, effort_type
  3. Schema version enforcement (task_schema != v1)
  4. Empty required field detection (empty title)
  5. Domain/directory mismatch (personal domain in work/ dir)
  6. Task ID format enforcement (wrong pattern for domain)
  7. Agent constraints: wrong role, wrong order, owner != agent id
  8. Missing agents list
  9. Parent references: self-reference, missing parent, cycle detection
 10. Index integrity: missing row, duplicate row, mismatched row data
 10d. Malformed frontmatter isolation (single error, not 20+ missing-key cascade)
 11. Counter mismatch (next_id wrong)
 12. Change log: invalid status transition
 13. Change log: status mismatch (log says X, file says Y)
 14. JSON output mode: ok/errors/skipped_files structure
 15. Bash fallback parity (if python3 available, confirms both paths match)
USAGE
}

# --- color support ---
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  C_GREEN=$'\033[1;32m'
  C_RED=$'\033[1;31m'
  C_YELLOW=$'\033[1;33m'
  C_CYAN=$'\033[1;36m'
  C_BOLD=$'\033[1m'
  C_RESET=$'\033[0m'
else
  C_GREEN="" C_RED="" C_YELLOW="" C_CYAN="" C_BOLD="" C_RESET=""
fi

log() {
  if (( QUIET == 0 )); then
    echo "$*"
  fi
}

pass_count=0
fail_count=0
skip_count=0

pass() {
  pass_count=$((pass_count + 1))
  log "  ${C_GREEN}PASS${C_RESET}: $*"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "  ${C_RED}FAIL${C_RESET}: $*" >&2
}

skip() {
  skip_count=$((skip_count + 1))
  log "  ${C_YELLOW}SKIP${C_RESET}: $*"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --keep-temp) KEEP_TEMP=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

VALIDATOR="$DIL_BASE/_shared/scripts/validate_tasks.sh"
PY_VALIDATOR="$DIL_BASE/_shared/scripts/validate_tasks.py"

if [[ ! -d "$DIL_BASE" ]]; then
  echo "Base path not found: $DIL_BASE" >&2
  exit 1
fi

if [[ ! -x "$VALIDATOR" ]]; then
  echo "Missing executable validator: $VALIDATOR" >&2
  exit 1
fi

# --- helpers ---

TMP_ROOT="$(mktemp -d /tmp/dil-validator-test.XXXXXX)"
TEST_BASE="$TMP_ROOT/dil"

cleanup() {
  if (( KEEP_TEMP == 1 )); then
    echo "Temp workspace preserved at: $TMP_ROOT"
  else
    rm -rf "$TMP_ROOT"
  fi
}
trap cleanup EXIT

make_test_vault() {
  rm -rf "$TEST_BASE"
  mkdir -p "$TEST_BASE/_shared/tasks/work"
  mkdir -p "$TEST_BASE/_shared/tasks/personal"
  mkdir -p "$TEST_BASE/_shared/tasks/_meta"
  mkdir -p "$TEST_BASE/_shared/_meta"
}

# Write a valid task file. Arguments: $1=task_id $2=domain $3=status $4=priority
# $5=work_type $6=task_type $7=effort_type $8=parent_task_id $9=owner
# $10=title $11=extra_frontmatter_lines (optional, newline-separated)
write_task() {
  local task_id="$1" domain="$2" status="$3" priority="$4"
  local work_type="$5" task_type="$6" effort_type="$7"
  local parent="${8:-}" owner="${9:-moo}" title="${10:-Test task $task_id}"
  local extra="${11:-}"

  local dir="$TEST_BASE/_shared/tasks/$domain"
  cat > "$dir/$task_id.md" << TASK
---
title: "$title"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: $priority
tags: [task, $domain]
updated: 2026-03-10
source: internal
domain: $domain
project: test
status: $status
owner: "$owner"
due:
work_type: $work_type
task_type: $task_type
effort_type: $effort_type
task_id: $task_id
created_by: test-harness
model: test-model
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: "$parent"
$extra
agents:
  - id: "$owner"
    role: accountable
    responsibility_order: 1
---

# $title
TASK
}

# Write an index row. Arguments: $1=task_id $2=domain $3=status $4=priority $5=owner $6=project
write_index_row() {
  local tid="$1" dom="$2" st="$3" pri="$4" own="$5" proj="${6:-test}"
  echo "| $tid | $dom | $st | $pri | $own |  | $proj | _shared/tasks/$dom/$tid.md | 2026-03-10 |" >> "$TEST_BASE/_shared/_meta/task_index.md"
}

write_index_header() {
  cat > "$TEST_BASE/_shared/_meta/task_index.md" << 'IDX'
---
title: "Test Task Index"
---

# Test Task Index

| task_id | domain | status | priority | owner | due | project | path | updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
IDX
}

write_counter() {
  local next_id="$1"
  cat > "$TEST_BASE/_shared/_meta/task_id_counter.md" << COUNTER
---
title: "Test Counter"
---

# Test Counter

- prefix: DIL
- next_id: $next_id
- last_allocator: test
COUNTER
}

write_changelog_header() {
  cat > "$TEST_BASE/_shared/tasks/_meta/change_log.md" << 'LOG'
---
title: "Test Change Log"
---

# Test Change Log

| timestamp | actor | model | task_id | action | field_changes | reason |
| --- | --- | --- | --- | --- | --- | --- |
LOG
}

write_changelog_row() {
  echo "| 2026-03-10T00:00:00Z | test | test-model | $1 | update | $2 | test |" >> "$TEST_BASE/_shared/tasks/_meta/change_log.md"
}

run_validator() {
  "$VALIDATOR" "$TEST_BASE" 2>&1
}

run_py_validator() {
  python3 "$PY_VALIDATOR" "$TEST_BASE" 2>&1
}

run_bash_validator() {
  PATH="/usr/bin:/bin" "$VALIDATOR" "$TEST_BASE" 2>&1
}

expect_pass() {
  local name="$1"
  local output
  if output="$(run_validator)"; then
    pass "$name"
  else
    fail "$name"
    echo "$output" >&2
  fi
}

expect_fail_with() {
  local name="$1" pattern="$2"
  local output
  if output="$(run_validator)"; then
    fail "$name (unexpected pass)"
    echo "$output" >&2
    return
  fi
  if echo "$output" | grep -qF "$pattern"; then
    pass "$name"
  else
    fail "$name (expected pattern not found: $pattern)"
    echo "$output" >&2
  fi
}

expect_error_count() {
  local name="$1" expected="$2"
  local output
  output="$(run_validator)" || true
  local actual
  actual="$(echo "$output" | grep -c '^ERROR:' || true)"
  if [[ "$actual" == "$expected" ]]; then
    pass "$name ($expected errors)"
  else
    fail "$name (expected $expected errors, got $actual)"
    echo "$output" >&2
  fi
}

# ============================================================
log "${C_BOLD}=== test_validate_tasks.sh ===${C_RESET}"
log ""

# --- Test 0: Live vault baseline ---
log "${C_CYAN}[0] Live vault baseline${C_RESET}"
if "$VALIDATOR" "$DIL_BASE" >/dev/null 2>&1; then
  pass "Live vault validates clean"
else
  fail "Live vault has errors — fix before trusting other results"
  "$VALIDATOR" "$DIL_BASE" 2>&1 | head -20 >&2
fi
log ""

# --- Test 1: Clean minimal vault ---
log "${C_CYAN}[1] Clean minimal vault${C_RESET}"
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium "" moo
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_pass "Minimal valid vault passes"
log ""

# --- Test 2: Invalid enum values ---
log "${C_CYAN}[2] Enum validation${C_RESET}"
make_test_vault
write_index_header
write_changelog_header

# status
write_task "DIL-9001" personal exploding high chore kanban medium
write_index_row DIL-9001 personal exploding high moo
expect_fail_with "Invalid status detected" "invalid status 'exploding'"

make_test_vault
write_index_header
write_changelog_header

# priority
write_task "DIL-9001" personal todo ultra chore kanban medium
write_index_row DIL-9001 personal todo ultra moo
expect_fail_with "Invalid priority detected" "invalid priority 'ultra'"

make_test_vault
write_index_header
write_changelog_header

# work_type
write_task "DIL-9001" personal todo high dance kanban medium
write_index_row DIL-9001 personal todo high moo
expect_fail_with "Invalid work_type detected" "invalid work_type 'dance'"

make_test_vault
write_index_header
write_changelog_header

# task_type
write_task "DIL-9001" personal todo high chore waterfall medium
write_index_row DIL-9001 personal todo high moo
expect_fail_with "Invalid task_type detected" "invalid task_type 'waterfall'"

make_test_vault
write_index_header
write_changelog_header

# effort_type
write_task "DIL-9001" personal todo high chore kanban extreme
write_index_row DIL-9001 personal todo high moo
expect_fail_with "Invalid effort_type detected" "invalid effort_type 'extreme'"
log ""

# --- Test 3: Schema version ---
log "${C_CYAN}[3] Schema version enforcement${C_RESET}"
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
# overwrite task_schema
sed -i 's/task_schema: v1/task_schema: v2/' "$TEST_BASE/_shared/tasks/personal/DIL-9001.md"
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "task_schema v2 rejected" "task_schema must be v1"
log ""

# --- Test 4: Empty required field ---
log "${C_CYAN}[4] Empty required field${C_RESET}"
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
---
title: ""
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: accountable
    responsibility_order: 1
---
TASK
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Empty title detected" "empty required value: title"
log ""

# --- Test 5: Domain/directory mismatch ---
log "${C_CYAN}[5] Domain/directory mismatch${C_RESET}"
make_test_vault
# Write a task with domain=personal into the work/ directory
write_task "DMDI-5555" personal todo normal feature kanban high
# Move it to work/
mv "$TEST_BASE/_shared/tasks/personal/DMDI-5555.md" "$TEST_BASE/_shared/tasks/work/DMDI-5555.md"
write_index_header
write_counter 1100
write_changelog_header
expect_fail_with "Domain mismatch detected" "does not match directory domain"
log ""

# --- Test 6: Task ID format ---
log "${C_CYAN}[6] Task ID format enforcement${C_RESET}"
make_test_vault
# personal task with wrong ID format — write directly
cat > "$TEST_BASE/_shared/tasks/personal/WRONG-1.md" << 'TASK'
---
title: "Wrong ID format"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: WRONG-1
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: accountable
    responsibility_order: 1
---
TASK
write_index_header
write_index_row WRONG-1 personal todo high moo
write_counter 1100
write_changelog_header
expect_fail_with "Wrong personal task_id format detected" "personal task_id must match"
log ""

# --- Test 7: Agent constraints ---
log "${C_CYAN}[7] Agent constraints${C_RESET}"

# 7a: wrong role
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
---
title: "Wrong agent role"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: reviewer
    responsibility_order: 1
---
TASK
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Wrong agent role detected" "first agent role must be accountable"

# 7b: wrong responsibility_order
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
---
title: "Wrong agent order"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: accountable
    responsibility_order: 5
---
TASK
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Wrong responsibility_order detected" "first agent responsibility_order must be 1"

# 7c: owner != agent id
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
---
title: "Owner mismatch"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "charlie"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
  - id: "moo"
    role: accountable
    responsibility_order: 1
---
TASK
write_index_header
write_index_row DIL-9001 personal todo high charlie
write_counter 9002
write_changelog_header
expect_fail_with "Owner/agent mismatch detected" "owner must match accountable agent id"
log ""

# --- Test 8: Missing agents ---
log "${C_CYAN}[8] Missing agents list${C_RESET}"
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
---
title: "No agents"
date: 2026-03-10
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: high
tags: [task, personal]
updated: 2026-03-10
source: internal
domain: personal
project: test
status: todo
owner: "moo"
due:
work_type: chore
task_type: kanban
effort_type: medium
task_id: DIL-9001
created_by: test
model: test
created_at: 2026-03-10T00:00:00Z
task_schema: v1
parent_task_id: ""
agents:
---
TASK
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Empty agents detected" "must include at least one agent"
log ""

# --- Test 9: Parent references ---
log "${C_CYAN}[9] Parent reference validation${C_RESET}"

# 9a: self-reference
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium "DIL-9001"
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Self-referencing parent detected" "parent_task_id cannot self-reference"

# 9b: missing parent
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium "DIL-9999"
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Missing parent detected" "references missing parent_task_id"

# 9c: cycle
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium "DIL-9002"
write_task "DIL-9002" personal todo high chore kanban medium "DIL-9001"
write_index_header
write_index_row DIL-9001 personal todo high moo
write_index_row DIL-9002 personal todo high moo
write_counter 9003
write_changelog_header
expect_fail_with "Parent cycle detected" "Cycle detected in parent_task_id chain"
log ""

# --- Test 10: Index integrity ---
log "${C_CYAN}[10] Index integrity${C_RESET}"

# 10a: missing row
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
# deliberately omit the index row
write_counter 9002
write_changelog_header
expect_fail_with "Missing index row detected" "missing exact row for DIL-9001"

# 10b: duplicate row
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
write_index_row DIL-9001 personal todo high moo
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Duplicate index row detected" "should contain exactly one row"

# 10c: mismatched row (status differs)
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
write_index_row DIL-9001 personal done high moo
write_counter 9002
write_changelog_header
expect_fail_with "Mismatched index row detected" "missing exact row for DIL-9001"
log ""

# --- Test 10d: Malformed frontmatter ---
log "${C_CYAN}[10d] Malformed frontmatter isolation${C_RESET}"
make_test_vault
# Write a valid task
write_task "DIL-9001" personal todo high chore kanban medium
# Write a file with no frontmatter boundaries
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9002.md" << 'TASK'
This file has no frontmatter at all.
Just some text without --- delimiters.
TASK
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
expect_fail_with "Malformed frontmatter detected" "malformed or missing frontmatter"

# Verify it reports exactly 1 error for the malformed file (not 20+ missing-key errors)
make_test_vault
cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
No frontmatter here either.
TASK
write_index_header
write_counter 1100
write_changelog_header
output="$(run_validator || true)"
malformed_errors="$(echo "$output" | grep -c '^ERROR:' || true)"
if [[ "$malformed_errors" == "1" ]]; then
  pass "Malformed file produces exactly 1 error (not 20+ missing-key errors)"
else
  fail "Malformed file should produce 1 error, got $malformed_errors"
  echo "$output" >&2
fi
log ""

# --- Test 11: Counter mismatch ---
log "${C_CYAN}[11] Counter validation${C_RESET}"
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9999
write_changelog_header
expect_fail_with "Counter mismatch detected" "Counter mismatch"
log ""

# --- Test 12: Change log invalid transition ---
log "${C_CYAN}[12] Change log transition validation${C_RESET}"
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
write_changelog_row "DIL-9001" "status: todo->done"
expect_fail_with "Invalid transition detected" "Invalid status transition"
log ""

# --- Test 13: Change log status mismatch ---
log "${C_CYAN}[13] Change log status mismatch${C_RESET}"
make_test_vault
write_task "DIL-9001" personal todo high chore kanban medium
write_index_header
write_index_row DIL-9001 personal todo high moo
write_counter 9002
write_changelog_header
write_changelog_row "DIL-9001" "status: todo->in_progress"
expect_fail_with "Status mismatch detected" "Status mismatch for DIL-9001"
log ""

# --- Test 13b: Project registry warnings ---
log "${C_CYAN}[13b] Project registry validation${C_RESET}"
if command -v python3 >/dev/null 2>&1 && [[ -f "$PY_VALIDATOR" ]]; then
  # Build a vault with a project registry and a task using an unregistered project
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header

  # Create a registry that only has "registered-proj"
  cat > "$TEST_BASE/_shared/_meta/project_registry.md" << 'REG'
---
title: "Test Registry"
---

# Test Registry

| slug | aliases | domain | name | status | parent | anchor_task | repo_path | owner | description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| registered-proj | | personal | Registered | active | | | | moo | A registered project |
REG

  # Task uses project "test" which is NOT in the registry — should produce a warning
  json_out="$(python3 "$PY_VALIDATOR" --json "$TEST_BASE" 2>&1)"
  if echo "$json_out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['warnings']>0 and any('not in project registry' in w for w in d['warning_messages']) else 1)" 2>/dev/null; then
    pass "Unregistered project produces warning"
  else
    fail "Should warn on unregistered project"
    echo "$json_out" >&2
  fi

  # Verify it still passes (warnings don't cause failure)
  if echo "$json_out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['ok'] else 1)" 2>/dev/null; then
    pass "Unregistered project is warning, not error (still passes)"
  else
    fail "Project warnings should not cause validation failure"
    echo "$json_out" >&2
  fi
else
  skip "python3 not available — cannot test project registry"
fi
log ""

# --- Test 14: JSON output mode ---
log "${C_CYAN}[14] JSON output mode${C_RESET}"
if command -v python3 >/dev/null 2>&1 && [[ -f "$PY_VALIDATOR" ]]; then
  # 14a: clean vault produces ok=true
  make_test_vault
  write_task "DIL-9001" personal todo high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal todo high moo
  write_counter 9002
  write_changelog_header
  json_out="$(python3 "$PY_VALIDATOR" --json "$TEST_BASE" 2>&1)"
  if echo "$json_out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['ok'] and d['errors']==0 else 1)" 2>/dev/null; then
    pass "JSON ok=true on clean vault"
  else
    fail "JSON ok should be true on clean vault"
    echo "$json_out" >&2
  fi

  # 14b: broken vault produces ok=false with error_messages array
  make_test_vault
  write_task "DIL-9001" personal exploding high chore kanban medium
  write_index_header
  write_index_row DIL-9001 personal exploding high moo
  write_counter 9002
  write_changelog_header
  json_out="$(python3 "$PY_VALIDATOR" --json "$TEST_BASE" 2>&1 || true)"
  if echo "$json_out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if not d['ok'] and d['errors']>0 and len(d['error_messages'])>0 else 1)" 2>/dev/null; then
    pass "JSON ok=false with error_messages on broken vault"
  else
    fail "JSON should report ok=false with error_messages"
    echo "$json_out" >&2
  fi

  # 14c: malformed file appears in skipped_files
  make_test_vault
  cat > "$TEST_BASE/_shared/tasks/personal/DIL-9001.md" << 'TASK'
No frontmatter here.
TASK
  write_index_header
  write_counter 1100
  write_changelog_header
  json_out="$(python3 "$PY_VALIDATOR" --json "$TEST_BASE" 2>&1 || true)"
  if echo "$json_out" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if len(d['skipped_files'])>0 else 1)" 2>/dev/null; then
    pass "JSON skipped_files populated for malformed frontmatter"
  else
    fail "JSON should list skipped files"
    echo "$json_out" >&2
  fi
else
  skip "python3 or validate_tasks.py not available — cannot test JSON mode"
fi
log ""

# --- Test 15: Bash fallback parity ---
log "${C_CYAN}[15] Bash fallback parity${C_RESET}"
if command -v python3 >/dev/null 2>&1 && [[ -f "$PY_VALIDATOR" ]]; then
  # Build a vault with multiple known errors
  make_test_vault
  write_task "DIL-9001" personal exploding ultra dance waterfall extreme
  write_task "DIL-9002" personal todo high chore kanban medium "DIL-9999"
  write_index_header
  write_index_row DIL-9001 personal exploding ultra moo
  write_index_row DIL-9002 personal todo high moo
  write_counter 9999
  write_changelog_header

  py_output="$(run_py_validator || true)"
  bash_output="$(run_bash_validator || true)"

  py_errors="$(echo "$py_output" | grep -c '^ERROR:' || true)"
  bash_errors="$(echo "$bash_output" | grep -c '^ERROR:' || true)"

  if [[ "$py_errors" == "$bash_errors" ]]; then
    pass "Python and bash produce same error count ($py_errors)"
  else
    fail "Error count mismatch: Python=$py_errors Bash=$bash_errors"
    echo "--- Python output ---" >&2
    echo "$py_output" >&2
    echo "--- Bash output ---" >&2
    echo "$bash_output" >&2
  fi

  # Check that error messages match line by line (just ERROR: lines)
  py_sorted="$(echo "$py_output" | grep '^ERROR:' | sort)"
  bash_sorted="$(echo "$bash_output" | grep '^ERROR:' | sort)"
  if [[ "$py_sorted" == "$bash_sorted" ]]; then
    pass "Python and bash error messages match exactly"
  else
    fail "Error messages differ between Python and bash"
    diff <(echo "$py_sorted") <(echo "$bash_sorted") >&2 || true
  fi
else
  skip "python3 or validate_tasks.py not available — cannot test parity"
fi
log ""

# --- Summary ---
total=$((pass_count + fail_count + skip_count))
echo ""
if (( fail_count > 0 )); then
  echo "${C_RED}${C_BOLD}=== FAILED: ${pass_count} passed, ${fail_count} failed, ${skip_count} skipped (${total} total) ===${C_RESET}"
  exit 1
else
  echo "${C_GREEN}${C_BOLD}=== ALL PASSED: ${pass_count} passed, ${fail_count} failed, ${skip_count} skipped (${total} total) ===${C_RESET}"
  exit 0
fi
