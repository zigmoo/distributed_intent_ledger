# Distributed Intent Ledger (DIL) Overview

The Distributed Intent Ledger (DIL) is a filesystem-first protocol for durable AI memory, coordination, and task tracking across multiple machines and assistants.

It is designed to solve context amnesia by treating the filesystem, not a model context window, as the source of truth. In practice, that means memory is stored as plain Markdown with structured frontmatter, kept human-auditable in tools like Obsidian, and organized so different agents can collaborate without guessing where information belongs.

## Core Idea

DIL is "Git for Agentic Intent."

It gives agents a shared operating model for:
- where memory lives
- how identity is resolved
- how writes are scoped and verified
- how canonical tasks are created and advanced
- how humans can inspect, repair, and trust what agents recorded

## Filesystem Model

DIL scopes information hierarchically:

- `_shared/`
  - cross-machine, cross-assistant knowledge, policies, indexes, templates, and tasks
- `<machine>/`
  - machine-specific memory and machine metadata
- `<machine>/<assistant>/`
  - the narrowest runtime scope for a specific assistant on a specific machine

The operating rule is simple:
- write to the narrowest valid scope first
- promote to `_shared` only when the information is truly broader than one assistant or one machine

## Runtime Identity

Agents must derive their identity from the real runtime environment, not by guessing from folder names.

- `machine` comes from the host runtime, typically `hostname -s`
- `assistant` comes from explicit environment variables first, then process/runtime identity

This is one of DIL's most important guardrails because it prevents split-brain behavior and mis-scoped writes.

## Memory Contract

DIL memory is plain Markdown with consistent frontmatter.

Each note carries structured fields such as:
- title
- date
- machine
- assistant
- category
- memoryType
- priority
- tags
- updated
- source
- domain
- project
- status
- owner

This makes notes both human-readable and machine-validated.

## Retrieval and Write Discipline

When answering memory-sensitive questions, agents should retrieve in this order:

1. local assistant scope
2. machine scope
3. shared preferences, rules, and policies
4. broader shared material

When writing:
- use the narrowest valid scope
- keep indexes current
- maintain change logs where required
- return proof of persistence after writes

That proof requirement is part of the DIL anti-parrot rule: agents should not merely claim they saved something, they should show where it was written.

## Task System

DIL also defines a canonical task system stored under `_shared/tasks/`.

- work tasks typically use external IDs such as Jira keys
- personal tasks use `DIL-<number>`
- task lifecycle is explicit and validated
- shared indexes and change logs provide auditability

Agents are expected to use the provided scripts for task creation and mutation so IDs, indexes, and logs stay consistent.

## Ownership and Safety

DIL is deliberately strict about ownership and scope.

- agents should only write inside their own scope unless explicitly authorized otherwise
- every note has an owner field
- secrets and credentials should not be stored in the ledger
- conflict-prone or sensitive edits should remain auditable

## Why It Matters

DIL is not just a memory folder.

It is a protocol for making AI work inspectable, durable, and portable across:
- multiple assistants
- multiple machines
- multiple sessions
- mixed model quality levels

The result is a system where humans can verify what happened, agents can recover context reliably, and shared operational memory survives beyond any single chat session.

## Elucubrate and the Active DIL

In current deployments, DIL often works alongside Elucubrate, the operational dashboard that surfaces tasks, agent state, machine health, and developer checks while still treating the vault as the canonical source of truth.

In conversation, it can be useful to distinguish:
- the generic/template DIL repository
- the "Active DIL", meaning the live DIL vault currently in use

## Suggested Reading

- `README.md`
- `READ_THIS_DIL_FIRST.md`
- `docs/spec-v1.md`
- `docs/retrieval-order.md`
- `docs/write-policy.md`
- `docs/identity-resolution.md`
