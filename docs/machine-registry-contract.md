# Machine Registry Contract (v1)

## Purpose

Define a canonical machine registry for DIL so agents can:
- resolve host identity consistently
- discover runtime routing targets (`agent_runtime_host`)
- maintain a shared, auditable machine inventory
- resolve hosts deterministically during handoff and recovery

## Canonical Location

- Suggested path in a DIL vault: `_shared/_meta/machine_registry.json`
- Schema: `schema/machine_registry.schema.json`

## Required Behavior During Bootstrap

1. Resolve current machine:
   - `machine = hostname -s | tr '[:upper:]' '[:lower:]'`
2. Load machine registry.
3. If current `machine` is missing:
   - add a new entry with all known/discoverable attributes
   - set `status` to `active` unless explicitly known otherwise
   - set `discovered_at` to current UTC timestamp
   - set `discovered_by` to current assistant/runtime id
4. If current `machine` exists:
   - update only discoverable, non-destructive runtime fields
   - do not clobber curated fields without explicit authorization
5. Persist update and return proof:
   - path updated
   - machine record excerpt
   - timestamp of mutation

## Minimum Discoverable Attributes

- `machine`
- `status`
- `agent_runtime_host.hostname`
- `agent_runtime_host.ssh_target`
- `attributes.os`
- `attributes.arch`
- `attributes.user_home`
- `attributes.tailscale_ips` (if available)
- `attributes.discovered_from` (signals used)

## Notes

- `agent_runtime_host` is the primary runtime routing block for cross-machine agent operations.
- MagicDNS names SHOULD be preferred when available and stable.
- Machine records should be explicit and discoverable so callers do not need to infer host identity or hunt through logs during session pickup.
