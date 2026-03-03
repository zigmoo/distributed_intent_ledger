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
