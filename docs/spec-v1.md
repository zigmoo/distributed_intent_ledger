# DIL Protocol Spec v1

## 1. Identity Resolution

Implementations MUST derive:
- `machine` from host runtime identity
- `assistant` from explicit runtime identity (env/process)

Implementations MUST NOT infer identity by scanning directory names.

## 2. Scope and Ownership

Writes MUST target the narrowest valid scope first:
- `<vault>/<machine>/<assistant>/...`

Promotion to `_shared` SHOULD occur only for cross-machine/cross-assistant facts.

## 3. Frontmatter Contract

Memory notes MUST include required fields:
`title,date,machine,assistant,category,memoryType,priority,tags,updated,source,domain,project,status,owner,due`

## 4. Retrieval Order

Implementations MUST resolve memory in this order:
1. `<machine>/<assistant>` scope
2. `<machine>/_meta` scope
3. `_shared/preferences|rules|policies`
4. `_shared`

## 5. Anti-Parrot Proof

After write operations, implementations MUST return:
- changed file paths
- placement proof (tree/list)
- excerpt proof (first lines/keys)

## 6. Task Canon

Canonical tasks MUST reside under `_shared/tasks/{work,personal}`.

Task mutations MUST be logged in `_shared/tasks/_meta/change_log.md`.

## 7. Validation Gate

Before claiming task mutations complete, implementations MUST run task validation and report pass/fail output.

## 8. Machine and Agent Registries

Implementations MUST maintain shared runtime inventories under `_shared/_meta`:
- `machine_registry.json` (machines and `agent_runtime_host` routing data)
- `agent_registry.json` (agents, capabilities, model/runtime profiles)

If the current machine or agent is missing during bootstrap, implementations MUST add a record with discoverable attributes and return proof of the write.

## 9. Format and Runtime Capability Declaration

Each agent record MUST declare:
- supported input/output formats (MIME or wildcard categories)
- runtime profiles (local/cloud/hybrid) with optional model inventories

This requirement ensures DIL can route work safely across mixed environments (for example local Ollama inventories plus cloud models).

## 10. Fallback LLM Policy Declaration

Each agent record MUST declare fallback support explicitly:
- `supports_fallback_llms`
- `model_config.fallback_models`
- `model_config.fallback_strategy`

Agents/runtimes that do not support fallback (for example current `zeroclaw` behavior) MUST declare fallback disabled and an empty fallback list.

## 11. Operational Tracking and Execution Defaults

Implementations SHOULD apply these defaults for operational reliability:
- tracked shell commands include a task marker (for example `# DIL-1101: short note`)
- implementation work starts only after canonical task/doc node exists
- future to-do requests are converted into canonical shared tasks
- agents execute runnable steps directly instead of bouncing to the user
- safe in-scope non-destructive steps are treated as implicitly approved
