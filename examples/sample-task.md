---
task_id: DIL-1207
domain: personal
project: agent-runtime
status: in_progress
priority: high
owner: charlie
created_by: codex
created_at: 2026-03-04T00:00:00Z
model: gpt-5
subcategory: infrastructure
---

# Normalize Fleet Runtime Profiles Across Host Shortnames

## Summary
- Build a repeatable process for inventorying runtime configuration by host shortname.
- Ensure all canonical runtime docs avoid private network domains and raw IP literals.

## Links
- Related tasks: [[DIL-1206]], [[DIL-1189]]
- Related notes:
  - [[_shared/projects/runtime-profile-normalization-2026-03-04]]

## Acceptance Criteria
- [ ] Inventory includes at least three hosts with different lifecycle statuses.
- [ ] Agent registry and machine registry examples remain schema-valid.
- [ ] Example docs use host shortnames only (`framemoowork`, `pi500`, `omarchy-zbook`).
- [ ] No environment-specific domains or raw IPs in public examples.
- [ ] The example remains readable as a standalone artifact: a new reader can understand the action, constraints, and next step without cross-referencing hidden context.

## Execution Notes
- 2026-03-04T00:05:00Z: Collected baseline sample files and identified sparse sections.
- 2026-03-04T00:11:00Z: Expanded task/memory/change-log examples and added machine registry example.
