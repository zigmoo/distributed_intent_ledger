# Recommended Tools

Canonical tool matrix for DIL workflows: what each tool is for, where it is
known to run, and how we use it.

Status date: `2026-04-26`.

Environment labels:
- `Linux (confirmed)`: observed working in DIL-active on `framemoowork`
- `Windows (known)`: upstream/package ecosystem indicates support
- `Windows (unknown)`: not yet validated in this DIL workflow

## Tool Matrix

| Tool | Primary DIL Use | Known To Run | How (install/use in DIL) |
|---|---|---|---|
| `ft` (Field Theory) | Bookmark sync/search archive backbone for `x_tool` workflows | Linux (confirmed), Windows (unknown) | Install globally (`npm i -g fieldtheory`), then use `_shared/scripts/x_tool sync/search/list/show` |
| `sqlite3` | Indexed query engine for bookmark/search paths (`x_tool`) and diagnostics | Linux (confirmed), Windows (known) | Install system package, use via `_shared/scripts/x_tool` (direct SQL only for debugging) |
| `himalaya` | Email engine behind `email_tool` (IMAP/SMTP/OAuth2/keyring) | Linux (confirmed), Windows (known) | Install with required features, then use `_shared/scripts/email_tool` for agent-safe send/reply/read flows |
| `jq` | Deterministic JSON parsing/transform in DIL scripts and evidence extraction | Linux (confirmed), Windows (known) | System package; used heavily across `_shared/scripts/*.sh` |
| `rg` | Default lexical recall/search primitive across tasks/memory/logs | Linux (confirmed), Windows (known) | System package; preferred search tool in DIL/SOPs |
| `fd` | Fast file discovery in large DIL trees | Linux (confirmed), Windows (known) | System package; use for file/path lookup |
| `fzf` | Interactive fuzzy selection for task IDs/paths/results | Linux (confirmed), Windows (known) | System package; use as shell-side selector in ops flows |
| `bat` | Readable file/code preview with line numbers | Linux (confirmed), Windows (known) | System package; use for quick review evidence snippets |
| `tmux` | Durable long-running sessions and resumable ops context | Linux (confirmed), Windows (known via WSL/MSYS2) | System package; use for persistent service/tool sessions |
| `yazi` | High-speed TUI file manager for DIL/repo navigation | Linux (confirmed), Windows (known) | System package; interactive navigation aid |
| `tig` | Fast git history/diff TUI during reviews and debugging | Linux (confirmed), Windows (known via MSYS2/Cygwin) | System package; interactive git inspection |
| `btop` | Runtime/system-resource observation during heavy workflows | Linux (confirmed), Windows (known via `btop4win`) | System package (or `btop4win` on Windows) |
| `caligula` | Terminal charting/visualization in diagnostics | Linux (confirmed), Windows (unknown) | Cargo install; use for quick visual analysis |
| `sio` | Hardware/sensor/device inventory and monitoring evidence | Linux (confirmed), Windows (unknown) | Cargo install; use `sio --monitor` or `sio <subcommand> --format json` and attach task evidence |
| `sigye` | Terminal image inspection for screenshot-driven debugging | Linux (confirmed), Windows (unknown) | Cargo install; use for local visual verification |
| `oxker` | Docker/container TUI observability | Linux (confirmed), Windows (unknown) | Cargo install; use during container diagnostics |
| `termDRAW` | ASCII/Unicode diagramming for low-ambiguity intent handoff | Linux (known), Windows (unknown) | Install `@termdraw/app`; save output and paste into task notes |
| `omarchy` | Standardized host baseline for consistent DIL runtime behavior | Linux (known), Windows (no) | Use as machine baseline where applicable |

## High-Impact Defaults

Default recommendation set for most DIL deployments:

- `ft`
- `sqlite3`
- `himalaya`

## Example Token and Speed Gains

| Tool | Example | Token Savings | Speedup | Evidence Basis |
|---|---|---|---|---|
| `ft` (via `x_tool`) | Bookmark workflows through one DIL command surface instead of raw SQL/query logic | ~4,500 tokens/session (~85% reduction) | Fewer commands and less retry/debug overhead | `_shared/scripts/README.x_tool.md` measured comparison |
| `sqlite3` (FTS5 path via `x_tool`) | Indexed FTS5 search vs legacy JSONL scan | Included in session savings above | `3.87s -> 0.016s` (~242x), ~450x less I/O | `_shared/scripts/README.x_tool.md` benchmark table |
| `himalaya` (via `email_tool`) | Headless non-interactive send/reply flows | Avoids repeated TTY-compose troubleshooting context overhead | Converts blocked interactive flows into one-command scriptable actions | `_shared/scripts/README.email_tool.md` architecture docs |

## Notes

- Keep writes low-inference: prefer DIL wrapper scripts (`x_tool`, `email_tool`) over direct raw command sequences in agent runs.
- If Windows support is required for a specific tool marked `unknown`, run a one-machine validation and then promote status in this table.
