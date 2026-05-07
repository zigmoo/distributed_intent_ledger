---
title: "git_tool Contract"
tool: git_tool
status: active
created: 2026-05-07
updated: 2026-05-07
owner: shared
---

# git_tool

Deterministic, agent-safe Git wrapper with template-backed commit composition.

## Core Guarantees

1. Commit subject must be ticket-prefixed: `<TICKET-ID>: <imperative description>`.
2. Commit body includes `message_ref` trailer pointing to `_shared/messages/<file>.md`.
3. Commit text is rendered from drawer-owned template: `j2_templates/commit_message.txt.j2`.
4. Non-commit operations are delegated to legacy backend during migration.

## Interface

- `git_tool <legacy-subcommand> [options]`
- `git_tool commit --task-id <ID> -m <summary> --message-ref <path> [--why <text>] [--evidence <text>] [--repo <path>] [--json]`
- `git_tool commit-template --task-id <ID> -m <summary> --message-ref <path> [--why <text>] [--evidence <text>]`

## Exit Codes

- `0` success
- `2` input validation failure
- `3` unsafe/empty commit guard triggered
- nonzero propagated from delegated backend for legacy subcommands

## Migration Note

Legacy implementation is preserved at `_shared/scripts/git_tool_bash/git_tool.bash` and remains the backend for non-commit subcommands until full Python parity is completed.
