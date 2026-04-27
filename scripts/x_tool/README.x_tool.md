# x_tool

Unified DIL surface for all X/Twitter operations: bookmark search, classification, post composition, and CDP-assisted posting. Wraps Field Theory CLI (`ft`) for data acquisition, queries the local SQLite FTS5 index for search, and delegates text rendering to `message_tool`'s nozzle pipeline.

## Path

- Script: `_shared/scripts/x_tool`
- Contract: `_shared/contracts/x-tool-requirements-contract-2026-04-25T195355Z.md`

## Subcommands

### Search & Browse (SQLite FTS5)

```bash
x_tool search <query> [--author HANDLE] [--after DATE] [--before DATE] [--limit N] [--json]
x_tool list [--author HANDLE] [--after DATE] [--before DATE] [--category CAT] [--domain DOM] [--sort-by FIELD] [--limit N] [--json]
x_tool show <id> [--json]
x_tool stats [--json]
x_tool categories [--json]
x_tool domains [--json]
```

### Bookmark Management (ft delegation)

```bash
x_tool sync [--browser NAME] [--agent-browser]
x_tool find <query> [--limit N]              # legacy JSONL search
x_tool refresh-find <query>                  # sync then search
x_tool recent [--days N] [--limit N]         # legacy JSONL recent
x_tool tag (--url URL | --id ID) --tag TEXT
x_tool status
```

### Post Composition (message_tool delegation)

```bash
x_tool compose --body "text" [--file PATH] [--reply-to ID]
x_tool post [--send] [--send --yes]
x_tool drafts [--limit N]
```

### Post Dispatch Modes

| Command | Behavior |
|---|---|
| `x_tool post` | Clipboard + CDP sequence. Paste + screenshot, stop. You post manually. |
| `x_tool post --send` | Clipboard + CDP sequence. Paste + screenshot + confirm gate + click Post. |
| `x_tool post --send --yes` | Clipboard + CDP sequence. Paste + click Post immediately. No gate. |

## Base / Log / Data Standards

- **DIL base resolution** follows the canonical resolver (`lib/resolve_base.sh`)
- **Logs**: `_shared/logs/x_tool/<hostname>.x_tool.<timestamp>.log`
- **Data dir** default: `~/.ft-bookmarks` (override: `--data-dir` or `X_TOOL_DATA_DIR`)
- **SQLite DB**: `$DATA_DIR/bookmarks.db` (FTS5-indexed, built by `ft index`)
- **JSONL cache**: `$DATA_DIR/bookmarks.jsonl` (source of truth for raw records)
- **Drafts**: `_shared/signals/drafts/` (managed by `message_tool`)

## Dependencies

| Dependency | Required By | Notes |
|---|---|---|
| `ft` (Field Theory CLI) | sync, reindex, classify, wiki, ask | npm global install (`fieldtheory@1.3.2`) |
| `sqlite3` | search, list, show, stats, categories, domains | system package |
| `jq` | find (legacy), recent (legacy), tag | system package |
| `message_tool` | compose, post, drafts | `_shared/scripts/message_tool` |
| `wl-copy` | clipboard dispatch | wayland clipboard |
| nozzles library | xpost nozzle | `/az/talend/scripts/python/lib/nozzles/` |
| `python3` | show (JSON parsing) | system |

## Token Savings: x_tool vs Raw Commands

Agents interacting with X bookmarks without x_tool must carry ~1,600 chars of SQL instructions in their context, compose ~420-char sqlite3 commands per query, and handle FTS5 syntax, BM25 weights, date format conversion, null fields, and tab escaping. With x_tool, they need ~400 chars of instruction and ~54-char commands.

### Per-session estimate (4 searches, 1 list, 2 shows, 1 compose)

| | Without x_tool | With x_tool | Savings |
|---|---|---|---|
| Instructions in context | ~1,600 chars | ~400 chars | 75% |
| Per-query command | ~420 chars | ~54 chars | 87% |
| Session total (commands) | ~5,280 tokens | ~781 tokens | 85% |
| Error/retry surface | Agent debugs SQL, FTS5 syntax, nulls | Zero — tool handles it | ~100% |

**~4,500 tokens saved per session, ~85% reduction.** This excludes the retry/reasoning loop when raw SQL fails (wrong BM25 weights, null view_count, text with embedded newlines breaking tab separation), which can burn 2,000-5,000 additional tokens per failure.

### Speed comparison

| | JSONL (legacy find) | SQLite FTS5 (search) | Improvement |
|---|---|---|---|
| Query time | 3.87s | 0.016s | 242x faster |
| Data scanned | 9MB (full file) | ~20KB (index pages) | 450x less I/O |
| Ranking | None (first match wins) | BM25 with porter stemming | Relevance-ranked |

## Example Commands

```bash
x_tool search "agentic memory" --limit 5
x_tool search "docker" --author sysxplore --json
x_tool list --author dhh --limit 10
x_tool show 2009278842867708312
x_tool stats
x_tool compose --body "Interesting thread on local-first agent memory"
x_tool post --send
```
