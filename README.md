# Distributed Intent Ledger (DIL)

Distributed Intent Ledger (DIL) is a local-first, filesystem-native protocol for persistent multi-agent and multi-environment memory coordination.

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
