---
title: "_hot.md Contract"
date: 2026-04-20
category: contract
status: active
---

# _hot.md Contract

## Purpose

`_shared/_hot.md` captures ephemeral session state — what was happening when the last session ended. It bridges the gap between sessions that task files alone don't capture.

## Location

`_shared/_hot.md` (one file per DIL instance, at the _shared root)

## Lifecycle

- **Read** at session start, immediately after READ_THIS_DIL_FIRST.md
- **Overwritten** at session end with current working state
- When multiple agents are active concurrently, each session appends its state under a labeled section rather than overwriting the other

## Required Frontmatter

```yaml
---
title: Session Hot State
updated: <ISO 8601 timestamp>
session_agent: <agent name — claude-code, opencode, codex, etc.>
session_machine: <hostname>
session_model: <model ID — claude-opus-4-6, gpt-5, etc.>
---
```

## Required Sections

### What We Were Doing
One paragraph describing the active work when the session ended.

### Next Immediate Actions
Numbered list of the NEXT things to do — not the backlog, the literal next actions. Priority order. Include ticket IDs.

### Pending Responses
Table of things we're waiting on from other people:

```
| From | What | Ticket | Expected |
|------|------|--------|----------|
```

## Optional Sections

- **Tickets Created** — table of tickets created during the session
- **Commits Pushed** — numbered list of commits pushed
- **Open Browser Tabs** — notable tabs worth resuming
- **Session Notes** — anything ephemeral the next session needs

## What _hot.md Is NOT

- NOT a task file (those live in `_shared/domains/*/tasks/`)
- NOT a preference or policy (those live in `_shared/preferences/`)
- NOT durable knowledge (that lives in research/, decisions/, runbooks/)
- NOT a log file (ephemeral by design — each session overwrites)

## Multi-Agent Concurrency

When multiple agents run concurrently on the same DIL instance, each session writes its state under a clearly labeled section header (e.g. "## Session 1: Claude Code" / "## Session 2: GPT-5"). The next session reads all sections and knows what each agent was working on.

## Pruning

No pruning needed — the file is overwritten each session. Previous session state is intentionally discarded. If any session state needs to persist, it belongs in a task file or execution note, not _hot.md.
