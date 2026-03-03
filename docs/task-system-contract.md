# Task System Contract

- Canonical task location: `_shared/tasks/{work,personal}`
- Work IDs: Jira-style (e.g., `DMDI-11330`)
- Personal IDs: `DIL-<number>`
- Allowed status values and transitions must be enforced by validator.

## User-Facing Operational Communication Rule

- For operational assistant replies tied to work execution (status, progress, blockers, completion, implementation notes), include the canonical `task_id`.
- If no canonical task exists, create one before continuing operational updates.
- Casual conversation does not require task-id tagging.

## Execution Note Dual-Write Rule

- When providing execution notes to the user, persist the same note block in the canonical task file.
- Prefer tee-style dual-write so displayed and persisted content are identical:
  - `scripts/tee_task_execution_note.sh <task_id> "<note>"`
- Fallback append helper:
  - `scripts/append_task_execution_note.sh <task_id> "<note>"`
