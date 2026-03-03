# Distributed Intent Ledger (DIL)

Have you ever wished your agents and assistants could share memories ... across one laptop to your servers and dev machines ... from Codex to Claude to OpenCode to OpenClaw?

Here's the plan for doing all those things and keeping memories and priorities straight.

Distributed Intent Ledger (DIL) is a local-first, filesystem-native protocol for persistent multi-agent and multi-environment memory coordination.
In current deployments, Tailscale is used as the private network fabric for secure cross-machine agent communication and coordination.

## What Sets DIL Apart

What sets DIL apart from other approaches is that it unifies memories and tasks across disparate environments for any assortment of AI Agents and AI Assistants by defining memory as a governed protocol, not just a storage format.

- Deterministic identity and scope boundaries:
  - Runtime-derived `machine` and `assistant` identities.
  - Scope-first writes to `<machine>/<assistant>` with explicit promotion to `_shared`.
  - Multi-agent collaboration is safe-by-default and auditable.
- Filesystem-native and human-auditable:
  - Plain files, frontmatter, and indexes (Obsidian-friendly).
  - No opaque memory database lock-in.
  - Humans can inspect, repair, and diff records directly.
- Protocolized read/write behavior:
  - Required frontmatter schema.
  - Mandatory retrieval order (`local -> machine -> shared`).
  - Mandatory index and change-log maintenance.
- Anti-parrot execution proof:
  - Write operations must return concrete file paths and excerpts.
  - Prevents false claims that persistence happened when it did not.
- Cross-agent task canon:
  - Shared canonical registry, lifecycle transitions, allocator, and validation.
  - Decouples task identity from any single runtime/model.
  - Enables reliable handoffs across machines and assistants.
- Mixed-model operational resilience:
  - Script-first, idempotent workflows.
  - Validation gates before side effects.
  - Fail-closed behavior suitable for weaker/local models as well as frontier models.

## Scope

DIL defines:
- deterministic runtime identity resolution (`machine`, `assistant`)
- scoped write boundaries and promotion rules
- retrieval order across local/machine/shared scopes
- frontmatter and task metadata contracts
- index and change-log maintenance requirements
- validation gates for task mutations

## License

This project is licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`.

## Repository Layout

- `docs/spec-v1.md`: normative protocol contract (MUST/SHOULD/MAY)
- `schema/`: JSON schemas for notes and tasks
- `examples/`: sample vault structure and records
- `scripts/`: reference helpers and validators
