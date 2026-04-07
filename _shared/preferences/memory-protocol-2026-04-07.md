---
title: DIL Memory Protocol
date: 2026-04-07
category: system
memoryType: preference
priority: critical
tags:
  - memory
  - protocol
  - retrieval
  - persistence
  - reconciliation
updated: 2026-04-07
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# DIL Memory Protocol

Governs how agents recall, verify, persist, and reconcile memory across sessions. This protocol is mandatory for all agents operating within the DIL ecosystem.

## Protocol Steps

1. **RECALL** -- before answering factual questions, search DIL in order:
   MEMORY.md index -> memory/ files -> tasks/ -> preferences/
2. **VERIFY** -- if a recalled memory names a path, tool, function, or config,
   confirm it exists in current state before recommending
3. **PERSIST** -- immediately write durable findings (corrections, decisions,
   discoveries) to memory/ via DIL scripts; do not defer
4. **COMPACT_FALLBACK** -- if runtime exposes pre-compaction hooks, run a
   final persistence pass as best-effort backup
5. **RECONCILE** -- when memory conflicts with current state, update or retire
   the stale record and log what changed and why

## Design Rationale

- **RECALL ordering** follows the existing DIL Retrieval Order (local scope -> machine scope -> shared scope) but adds the MEMORY.md index as a fast first-pass filter.
- **VERIFY** prevents stale memory from generating bad recommendations. A memory that names a file/function/flag is a claim about a past state, not current reality.
- **PERSIST** is event-driven (triggered by corrections, decisions, discoveries), not timer-driven. This avoids noisy low-quality writes.
- **COMPACT_FALLBACK** is conditional -- only fires if the runtime exposes pre-compaction hooks. It is a best-effort backup, not the primary persistence trigger.
- **RECONCILE** adds an audit trail: when a stale record is updated or retired, the change and its reason are logged, preserving the ledger's integrity.

## Provenance

Derived from analysis of MemPalace (github.com/milla-jovovich/mempalace) "Palace Protocol" pattern, adapted for DIL's file-first, human-auditable architecture. Reviewed by Codex (peer review) and Claude Code (primary author). The key adaptation: MemPalace assumes an external memory service the agent queries; DIL assumes the agent IS the memory system and reads/writes directly, so write discipline matters more than query discipline.
