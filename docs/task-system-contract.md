# Task System Contract

- Canonical task location: `_shared/tasks/{work,personal}`
- Work IDs: Jira-style (e.g., `DMDI-11330`)
- Personal IDs: `DIL-<number>`
- Allowed status values and transitions must be enforced by validator.

## User-Facing Operational Communication Rule

- For operational assistant replies tied to work execution (status, progress, blockers, completion, implementation notes), include the canonical `task_id`.
- If no canonical task exists, create one before continuing operational updates.
- Casual conversation does not require task-id tagging.
- Keep execution updates low-inference: include what changed, where it lives, and the exact next action without requiring the reader to reconstruct missing context.

## Execution Note Dual-Write Rule

- When providing execution notes to the user, persist the same note block in the canonical task file.
- Prefer tee-style dual-write so displayed and persisted content are identical:
  - `scripts/tee_task_execution_note.sh <task_id> "<note>"`
- Fallback append helper:
  - `scripts/append_task_execution_note.sh <task_id> "<note>"`

## Operational Tracking Defaults

- Tracked shell commands SHOULD include a task marker:
  - `# DIL-<task_id>: <short-description>`
- Future to-do requests SHOULD be converted into canonical shared tasks before execution begins.
