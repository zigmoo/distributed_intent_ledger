---
title: "Tool Forge Standards (formerly Script Forge)"
date: 2026-04-27
machine: shared
assistant: shared
category: policy
memoryType: policy
priority: critical
tags: [tool-forge, script-forge, tooling, standards, agentic-tools, symlinks, path, conventions]
updated: 2026-04-28
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Tool Forge Standards

These standards govern all tools created within the DIL Tool Forge (`_shared/scripts/`) and any Tool Forge-compatible repository (e.g., `/org/platform/scripts/`). Formerly known as "Script Forge" — both names may appear in historical references.

## 1. Extensionless Symlink Rule (Non-Negotiable)

The command registered in `$PATH` is ALWAYS the extensionless stem name as a symbolic link. Never a script with an extension.

- The symlink lives in `bin/` (e.g., `_shared/scripts/bin/` or `$BASE_DIR/scripts/bin/`).
- `bin/` is included in the system `$PATH`.
- The symlink points to the actual executable (the Bash wrapper).
- The symlink name has **no extension** — not `.sh`, not `.py`, not `.bash`, nothing.

**Correct:**
```
bin/jira_tool  →  ../jira_tool.sh        (symlink, no extension)
bin/task_tool  →  ../task_tool/task_tool.bash  (symlink, no extension)
bin/x_tool     →  ../x_tool              (symlink, no extension)
```

**Wrong:**
```
bin/jira_tool.sh  →  ../jira_tool.sh     (WRONG: extension in symlink)
bin/task_tool.py  →  ../task_tool/task_tool.py  (WRONG: extension, and pointing to Python directly)
```

**Why:** Agents and humans call tools by name, not by implementation language. `jira_tool comment WORK-12523 "text"` — the caller doesn't know or care that it's Bash wrapping Python. Extensions leak implementation details into the interface. If we port a tool from Bash to Python to Rust, the symlink name never changes. The contract is the name, not the file extension.

## 2. The Bash/Python Pair Pattern

Every substantial tool follows a two-file structure:

```
tool_name.sh   — Bash wrapper (bootstrapper, venv manager, entry point)
tool_name.py   — Python implementation (business logic, structured I/O)
```

**Bash wrapper responsibilities:**
- Resolve base directory path (relative, never hardcoded absolute)
- Detect and bootstrap Python virtual environment (create venv, install deps if missing)
- Find Python interpreter (python3 → python fallback)
- Pass arguments through to the Python script
- Capture and relay exit codes

**Python script responsibilities:**
- Argument parsing (argparse with subcommands)
- All business logic
- Structured output (pipe-delimited, JSON, or machine-parseable text)
- Deterministic exit codes
- Logging to domain-specific timestamped log files

**Python dependency rule (Non-Negotiable):**
- Tool Forge Python MUST be vanilla stdlib Python by default.
- Do not add pip dependencies to Tool Forge tools, helpers, tests, renderers, or templates unless the user has explicitly set the architecture/design for that tool or standard and named the dependency as part of that design.
- The default rule exists to prevent agents from casually importing dependency stacks. It is not meant to override a user-approved architecture decision.
- Any dependency exception MUST be documented in the tool drawer README or standard that authorizes it, including dependency name, purpose, scope, and fallback/installation expectation.
- Tool Forge tools MUST use the existing `duckdb_sql` command for DuckDB work.
- Direct Python `duckdb` imports are only allowed inside the `duckdb_sql` implementation itself, unless a task explicitly documents why `duckdb_sql` cannot support the needed operation and adds that missing capability back to `duckdb_sql` when practical.
- For agentic use, prefer `duckdb_sql -g` to suppress grid formatting. Grids waste tokens; use plain, JSON, single-value, or delimiter-controlled output unless a human explicitly needs a pretty table.
- J2/Jinja-style templates should be rendered by a DIL-owned stdlib renderer or a committed local implementation by default. External `jinja2` is allowed only when the user-approved architecture explicitly calls for it and the dependency exception is documented.

**Small tools** that don't need Python's capabilities may remain pure Bash. The pair pattern is for substantial tools, not one-liners.

## 3. Named Shims for Subcommand Access

When a tool has subcommands (e.g., `task_tool create`, `task_tool status`), named shims provide direct access for command registry speed:

```bash
#!/usr/bin/env bash
# create_task — named shim for task_tool create
exec task_tool create "$@"
```

- Shim is a one-line Bash script in `_shared/scripts/` (or equivalent).
- Shim gets its own extensionless symlink in `bin/`.
- Command registry maps trigger phrases to shim names, not to `tool subcommand` pairs.
- This converts subcommand reasoning (~40-80 tokens) into direct lookup (~10-15 tokens).

## 4. Base Directory Path Independence

Scripts resolve their base path from their own location, never from hardcoded absolute paths.

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# resolve upward to find the DIL root or repo root
```

The same tool must work at any install location — `$HOME/Documents/dil_agentic_memory_0001/`, `/home/paul/dil/`, `/org/platform/scripts/`, or anywhere else. No path surgery when moving between machines or repositories.

## 5. Domain-Specific Logging

Every tool operation logs to a timestamped file:

```
$LOG_DIR/{tool_name}/{tool_name}.{action}.{YYYYMMDD_HHMMSS}.log
```

- `$LOG_DIR` is resolved from the domain registry or from the tool's base directory.
- Log files begin and end with the full path to the log file.
- Numbered sections in main program flow, separated by horizontal lines.
- Logs should read like a storybook — easy to read, visually consistent.

## 6. Domain-Specific Data Locations

```
$DATA_DIR/{tool_name}/         — tool's data directory
$DATA_DIR/{tool_name}/input/   — input data (if applicable)
$DATA_DIR/{tool_name}/output/  — output data
```

JSON sidecar manifests are archived to `$DATA_DIR/{tool_name}/{tool_name}.{action}.{YYYYMMDD_HHMMSS}.json`.

## 7. Invocation Modes

Tools support multiple invocation modes as appropriate:

- **CLI args** — for simple operations: `tool action target "value"`
- **JSON sidecar** — for complex operations: `tool json manifest.json`
- **Stdin** — where piping is natural: `echo "text" | tool format`

The forge decides which modes are appropriate at design time.

## 8. Tool Creator (createTool)

New DIL Tool Forge tools MUST be scaffolded using `createTool`, the DIL-native tool creator, which generates both files (Bash wrapper + Python implementation) with all standards pre-wired:

- Extensionless symlink in `bin/`
- Logging boilerplate
- Data directory setup
- Venv bootstrapping in the wrapper
- Argparse skeleton in the Python script
- Test script stub
- Tool-owned `j2_templates/README.md` for presentation templates and report surfaces

Learnings and new patterns are folded back into the `createTool` templates so every future tool inherits them automatically.

`createTool` uses the same drawer-local J2 convention as generated tools. Its script-rendering sources live inside the tool drawer:

```text
_shared/scripts/createTool/j2_templates/*.j2
```

The templates are the durable standards surface. When Tool Forge standards evolve, update those template files first so every newly scaffolded script starts compliant before customization.

## 9. ALWAYS Invoke by Symlink Name

Always execute scripts using the extensionless symlink name with no prepended path:

**Correct:** `jira_tool comment WORK-12523 "text"`
**Wrong:** `bash _shared/scripts/jira_tool.sh comment WORK-12523 "text"`
**Wrong:** `./_shared/scripts/jira_tool.sh comment WORK-12523 "text"`
**Wrong:** `python3 _shared/scripts/jira_tool.py comment WORK-12523 "text"`

The symlink is the contract. Everything else is an implementation detail.

## 10. Diff-Stable Test Output

Every tool with a test suite uses the **golden file diff** pattern for regression detection.

**How it works:**
1. Each test case captures its output (stdout + stderr combined).
2. A **normalizer** strips run-specific variance: timestamps, absolute paths, PIDs, temp directory names. What remains is the functional shape of the output.
3. The normalized output is written to an `.actual` file.
4. On `--rebuild`, the `.actual` file becomes the `.golden` baseline.
5. On normal runs, `diff -u golden actual` determines pass/fail. **Null diff = pass. Any diff = functional regression.**

**Why this beats string matching:**
- `grep -qF "expected string"` asks "does this appear?" — it passes even when the output changes in unexpected ways (new warnings, missing lines, reordered output). It catches what you anticipated; it misses what you didn't.
- Golden file diff asks "is the output identical to the last known-good run?" — it catches *every* change, anticipated or not. Expected-failure tests have their own golden files, so the error output IS the expected output.

**Normalizer contract:**
The normalizer must strip exactly enough to make output deterministic across runs, but no more. Over-normalization hides real regressions. Under-normalization causes false failures.

Minimum normalizations:
- Timestamps (ISO 8601, dates, epoch seconds) → `TIMESTAMP` / `DATE`
- Absolute paths (temp dirs, home, base) → `<TMP>` / `<HOME>` / `<BASE>`
- PIDs and random suffixes → `<PID>`

**Naming convention (non-negotiable):**

The test script filename is derived from the tool it tests using this formula:

```
<tool_stem>_test_script.bash
```

Where `<tool_stem>` is the tool's filename without any extension (`.sh`, `.py`, `.bash`).

| Tool under test | Tool stem | Test script filename |
|----------------|-----------|---------------------|
| `task_tool/task_tool.bash` / `task_tool/task_tool.py` | `task_tool` | `task_tool_test_script.bash` |
| `research_tool/research_tool.bash` / `research_tool/research_tool.py` | `research_tool` | `research_tool_test_script.bash` |
| `url_tool.sh` | `url_tool` | `url_tool_test_script.bash` |
| `hot_tool.sh` | `hot_tool` | `hot_tool_test_script.bash` |

**Location:** The test script lives in the **same directory** as the tool it tests. Not in a `tests/` subdirectory. Not in `lib/`. Right next to the tool.

**Log directory (Standard #5 compliance):**

The log subdirectory name is the full test script stem — including the `_test_script` suffix. This is the script's identity for logging purposes.

| Test script | Log subdirectory | Log filename pattern |
|------------|-----------------|---------------------|
| `task_tool_test_script.bash` | `task_tool_test_script/` | `task_tool_test_script.run.YYYYMMDD_HHMMSS.log` |
| `research_tool_test_script.bash` | `research_tool_test_script/` | `research_tool_test_script.run.YYYYMMDD_HHMMSS.log` |

**WRONG:** `$LOG_DIR/task_tool_test/` — dropping `_script` truncates the identity.
**WRONG:** `$LOG_DIR/task_tool/` — collides with the tool's own operational logs.
**RIGHT:** `$LOG_DIR/task_tool_test_script/` — full composite name, no ambiguity.

**File layout (complete example):**
```
_shared/scripts/
  task_tool/
    task_tool.bash                         # tool bash wrapper
    task_tool.py                           # tool Python logic
    task_tool_test_script.bash             # test runner (same directory as tool)
    task_tool_test_golden/                 # golden baselines (committed to repo)
      test_01.golden
      test_02.golden
      ...

_shared/logs/
  task_tool/                               # tool operational logs
    task_tool.search.20260427_013000.log
  task_tool_test_script/                   # test run logs (full composite name)
    task_tool_test_script.run.20260427_013100.log
```

**Porting workflow:**
When consolidating a standalone script into a tool (e.g., `create_task.sh` → `task_tool create`), the test body changes from calling the old script to calling the new subcommand, but the golden output must remain identical. Any diff after porting = the port changed behavior.

**Required flags:**
- `--rebuild` — regenerate all golden baselines from current output
- `--test N` — run a single test by number
- `--keep-temp` — preserve temp workspace for debugging
- `--quiet` — summary and failures only

## 11. CSV-Primary Data Pattern (CSV + duckdb_sql + stdlib renderer)

When a tool maintains a structured index, registry, or tabular dataset, prefer the **CSV-primary** pattern over parsing markdown tables.

**Architecture:**
```
data.csv                    ← source of truth (duckdb_sql reads/writes)
data.md.template            ← committed template (layout + embedded query results)
data.md                     ← rendered output (never hand-edited, never parsed)
```

**How it works:**
1. All writes (create, update, delete) go through `duckdb_sql`.
2. All reads use `duckdb_sql` against the CSV for filters, joins, aggregates, and other native SQL operations.
3. The markdown file is rendered by DIL-owned stdlib Python logic. It is a **view**, not a data store.
4. The template can embed multiple query results and computed fields, but rendering stays inside DIL-owned code.
5. `rebuild` = re-render the template from the CSV. Idempotent, fast, no data loss.

**Why this pattern:**
- **Token savings:** Agents emit SQL (`SELECT * WHERE status='blocked'`) instead of reasoning about grep/awk/regex patterns to parse markdown tables. SQL is a known format — near-zero inference cost.
- **Speed:** DuckDB queries 1000 rows in microseconds. Parsing a markdown table line-by-line in Python is orders of magnitude slower.
- **Correctness:** CSV has a defined schema. Markdown tables have ambiguous quoting, alignment, and no type enforcement. CSV eliminates parse drift.
- **Separation of concerns:** Data (CSV), queries (SQL), presentation (J2+MD) are independent. Change the template without touching the data. Change the schema without touching the template.

**When to use:**
- Any `_index.md` or `_registry.md` that tools read and write programmatically
- Any tabular data that agents query with filters
- Any file where the markdown table is currently both the data store and the display format

**When NOT to use:**
- Human-authored prose documents
- Configuration files with complex nesting (use JSON/YAML)
- Files with fewer than ~10 rows where the overhead isn't justified

**Dependencies:** Tool Forge tools use the existing `duckdb_sql` command for SQL over CSV. Do not import the Python `duckdb` module directly outside the `duckdb_sql` implementation itself unless a task explicitly documents the gap and the missing capability is added back to `duckdb_sql` when practical. For agent-facing output, use `duckdb_sql -g` by default to avoid token-heavy grid formatting; prefer `-j`, `-S`, `-H`, or `--sep` when those modes fit the consumer. Template rendering should use DIL-owned stdlib Python logic by default. External `jinja2` is allowed only as a documented dependency exception when the user-approved architecture explicitly calls for it.

**Candidates in current DIL:**
- `task_index.md` (DIL-1491 — first implementation)
- `command_registry.md`
- `project_registry.md`
- `domain_registry.json` (already structured, but the rendered markdown views could use this pattern)
- Archive year indexes (`archived/2026/index.md`)

## 12. Shared Logging Library

All Tool Forge tools MUST use the shared logging library instead of inline `echo`/`date` calls. This ensures uniform log format across bash and Python tools, enabling `log_river` harvest and cross-tool diagnostics.

**Storybook logging:** Logs should read like a Richard Scarry picture book — not simple, but *clearly descriptive* with rich detail that's easy to follow. A reader opening the log cold should immediately understand: what happened, in what order, with what inputs, and what the outcome was. Every section tells a chapter of the story. The reader should never have to ask "so what exactly got done here?"

**Bash:**
```bash
source "$SCRIPT_DIR/lib/script_forge_log.sh"
script_forge_log_init "tool_name" "action" "$BASE"
script_forge_log "message"
script_forge_log_warn "warning message"
script_forge_log_error "error message"
script_forge_log_section "Section Name"
script_forge_log_close
```

**Python:**
```python
from script_forge_log import ScriptForgeLogger

with ScriptForgeLogger("tool_name", "action", base) as log:
    log.info("message")
    log.warn("warning message")
    log.error("error message")
    log.section("Section Name")
```

**Output format (identical from both languages):**
```
================================================================================
LOG_FILE: /path/to/log
================================================================================

Section 1: Configuration
--------------------------------------------------------------------------------
timestamp:  2026-04-27 02:50:51
tool:       tool_name
action:     run
machine:    framemoowork
agent:      claude-code
pid:        12345

2026-04-27 02:50:51.878 | INFO | message
2026-04-27 02:50:51.879 | WARN | warning
2026-04-27 02:50:51.880 | ERROR | error

================================================================================
LOG_FILE: /path/to/log
================================================================================
```

**Libraries:**
- Bash: `lib/script_forge_log.sh` — source it, zero dependencies
- Python: `lib/script_forge_log.py` — import it, stdlib-only (no pip)

**Provenance:** This pattern originates from `ScriptUtils.configure_logger()` in `/org/platform/scripts/python/libs/bin/utils/ScriptUtils.py`, adapted for DIL Tool Forge with stdlib-only constraint (no `loguru` dependency). The Exampleorg `createNewScript` templates in `/org/platform/scripts/` bake this pattern into every new script at creation time. DIL's equivalent creator is named `createTool`, and DIL's `lib/script_forge_log.sh` and `lib/script_forge_log.py` serve the same purpose for DIL-resident tools.

**Retrofit:** Existing tools should be migrated to use the shared library as they are touched. New DIL tools created via `createTool` or manually MUST use it from the start.

## 13. Symlink-Safe SCRIPT_DIR Resolution (Non-Negotiable)

Every bash script MUST resolve `SCRIPT_DIR` through symlinks using `readlink -f`. Without this, scripts called via `bin/` symlinks resolve to the `bin/` directory instead of their actual location, breaking all relative path references to `lib/`, sibling scripts, and Python files.

**Correct:**
```bash
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
```

**Wrong (breaks when called via symlink):**
```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
```

This is the **first line of defense** for the extensionless symlink system (Standard #1). If `SCRIPT_DIR` resolves wrong, every `source "$SCRIPT_DIR/lib/..."` and `exec python3 "$SCRIPT_DIR/tool.py"` fails. This was discovered and fixed across 17 tools during the DIL-1489 drawer migration.

## 14. Every Tool Deserves Its Own Drawer

Every tool gets its own directory within `_shared/scripts/`. No flat files in the scripts root except small legacy standalone utilities explicitly documented by the Tool Forge migration plan.

```
_shared/scripts/
  tool_name/
    tool_name.bash          ← bash wrapper (entry point)
    tool_name.py            ← Python logic (if applicable)
    tool_name.md            ← documentation (if applicable)
    j2_templates/           ← tool-owned display/report templates
      README.md             ← template purpose, conventions, dependency notes
    tool_name_test_script.bash  ← test suite (Standard #10)
    tool_name_test_golden/      ← golden baselines (Standard #10)
  bin/
    tool_name               ← extensionless symlink → ../tool_name/tool_name.bash
```

## 17. Structured Resultset Rendering

Report-producing tools MUST separate data retrieval from human presentation.

**Default pipeline:**
1. The tool gathers/searches/query results into a structured resultset (JSON, CSV, or equivalent).
2. The resultset is passed to a renderer/nozzle/linkifier layer.
3. The renderer applies a tool-owned template from the tool drawer.

**Template location:**

```text
_shared/scripts/<tool>/j2_templates/
```

Equivalent Tool Forge-compatible repositories follow the same drawer-local pattern, for example:

```text
/org/platform/scripts/bash/<tool>/j2_templates/
```

**Console report rules:**
- Use fixed-width deterministic columns for human console reports unless a different format is explicitly required.
- Do not use ad hoc pipe-delimited rows for human-facing report tables.
- Use `url_tool` or an approved nozzle/linkifier for ticket IDs and external references.
- Console links should render as clickable labels without exposing raw URLs when the terminal supports it.
- Keep machine-readable output separate via JSON, CSV, or delimiter-controlled modes.

The tool owns its templates. Shared rendering mechanics belong under `_shared/scripts/lib/`, especially reusable nozzles, linkifiers, and stdlib render helpers.

**Why:** The directory IS the tool's namespace. When a tool grows (tests, config, templates, golden files), the directory absorbs growth without restructuring. `ls scripts/` shows tool names, not a flat pile of files.

## 15. JSONL vs CSV Decision Rule

Standard #11 defines the CSV-primary pattern for queryable tabular data. JSONL (one JSON object per line, append with `>>`) is an alternative for append-only data. Use this decision rule to pick the right format at design time.

**Choose CSV when:**
- The schema is flat and fixed — every row has the same columns
- DuckDB will query the data (CSV is DuckDB's fastest, simplest reader)
- The data will feed a J2-rendered markdown view (Standard #11 pipeline)
- Columns are scalar values: strings, numbers, timestamps, booleans
- The file will be read by agents that benefit from SQL over JSON parsing

**Choose JSONL when:**
- Rows have variable or optional nested fields (arrays, objects, maps)
- The schema evolves frequently and rows from different versions coexist
- Each record is consumed independently and never joined/aggregated with SQL
- The data is a raw event stream where human readability per-line matters more than cross-row queries
- A nested `error` object, `tags` array, or `options` map would require awkward flattening into CSV columns

**Hybrid (append JSONL, materialize CSV):**
- When raw events are JSONL-shaped but reporting needs SQL, write JSONL as the append-only ingest format and periodically materialize a flat CSV summary via DuckDB's `read_json_auto()`. The CSV becomes the query layer; the JSONL is the durable event log. This adds a materialization step — only use it when both the nested raw shape and the flat query shape are genuinely needed.

**Decision shortcut:**
Ask one question: *"Does every row have the same columns with no nesting?"*
- Yes → CSV
- No → JSONL
- "Mostly yes, but one or two fields might be nested" → CSV with the nested fields as single text columns (JSON-encoded strings). Only escalate to JSONL if multiple fields need nesting or the nested structure is the primary query target.

**Applies to:** audit ledgers, run logs, attempt logs, sync records, and any append-only operational data produced by Tool Forge tools. This standard complements Standard #11 — when CSV is chosen, the full CSV + DuckDB + J2 pipeline applies.

## 16. Marker-Based Path Resolution (Non-Negotiable)

Scripts MUST resolve base directories by walking upward to a known marker — never by counting directory levels.

**Correct (marker-based, survives any restructuring):**
```bash
_cursor="$SCRIPT_DIR"
while [[ -n "$_cursor" && "$_cursor" != "/" ]]; do
  if [[ -d "$_cursor/_shared/_meta" ]]; then
    BASE_DIL="$_cursor"
    break
  fi
  _cursor="$(dirname "$_cursor")"
done
```

```python
cursor = Path(script_dir).resolve()
while cursor != cursor.parent:
    if (cursor / "_shared" / "_meta").is_dir():
        return str(cursor)
    cursor = cursor.parent
```

**Wrong (breaks when directory structure changes):**
```bash
BASE_DIL="$(cd "$SCRIPT_DIR/../.." && pwd)"
```

```python
repo_base = Path(script_dir).resolve().parent.parent
```

**Why this is a foundational principle, not a convenience:**

Hardcoded level counts (`../..`) embed a structural assumption into every script that uses them. When the structure changes — and it will, because tools grow, directories get reorganized, drawer layouts deepen — every hardcoded path breaks simultaneously. The `_shared/_shared` bug that hit x_tool, signal_tool, and message_tool after the Standard #14 drawer migration is the proof case: one structural change silently corrupted log paths, data paths, and signal paths across multiple tools.

The cascading effects of fragile path resolution reach beyond the developer's terminal. Logs land in wrong directories and get missed during incident response. Audit data writes to ghost paths and disappears. Guard files fail to protect concurrent runs. These are not cosmetic failures — they are operational failures that affect reliability for the people who depend on the systems we build.

Choosing marker-based resolution over hardcoded levels is a moral choice: it prioritizes the durability and mobility of the system over the convenience of writing `../..`. The marker approach works at any depth, survives any restructuring, and requires zero maintenance when tools move. The cost is a few extra lines of code. The alternative is silent breakage that compounds until someone gets paged.

**Marker selection:** Use the most specific structural marker available. For DIL repositories, `_shared/_meta` is the canonical root marker. For other repositories, choose a directory or file that exists only at the root and is unlikely to be duplicated at other levels.

**Applies to:** all base path resolution in Tool Forge tools — bash wrappers, Python implementations, shared libraries, and test scripts. No exceptions.

## Naming Transition Note (2026-05-01)

DIL is adopting **DIL Tool Forge** as the preferred name for the existing Script Forge system.

- Scope is unchanged: standards in this document continue to govern `_shared/scripts/` tools, wrappers, drawers, tests, and shared libs.
- During transition, both names may appear in docs and task notes:
  - `Script Forge` (legacy/current references)
  - `DIL Tool Forge` (preferred forward-facing name)
- Operational behavior and standards requirements do not change because of this naming update.
