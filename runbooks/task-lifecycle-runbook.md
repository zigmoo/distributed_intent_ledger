---
title: "Task Lifecycle Runbook"
date: 2026-03-17
machine: shared
assistant: shared
category: system
memoryType: reference
priority: critical
tags: [runbook, tasks, lifecycle, low-inference, jira, task-creation]
updated: 2026-03-17
source: internal
domain: operations
project: dil-active
status: active
owner: shared
due:
---

# Task Lifecycle Runbook

Step-by-step procedure for creating a task and working it through to completion. Designed for zero-inference execution — any model can follow these steps mechanically.

Canonical source: `READ_THIS_DIL_FIRST.md` § Task Lifecycle Runbook

## Safe Defaults (use when user doesn't specify)

| Parameter | Default | Notes |
| --- | --- | --- |
| priority | normal | Escalate to high/critical only if user says urgent/emergency |
| work_type | chore | Use feature for new functionality, bug for fixes, research for investigation |
| task_type | kanban | Use sprint only if user explicitly mentions sprints |
| effort_type | medium | Use low for quick fixes, high for multi-day work |
| project | (look up) | Match task description against `_shared/_meta/project_registry.md` aliases column. If no match, ask the user. |

## Path Variables

```bash
BASE="/home/moo/Documents/dil_agentic_memory_0001"
TASK_DIR_WORK="$BASE/_shared/domains/work/tasks/active"
TASK_DIR_PERSONAL="$BASE/_shared/domains/personal/tasks/active"
TASK_DIR_TRIV="$BASE/_shared/domains/triv/tasks/active"
```

## Steps

### 1. Create in remote system (if applicable)

For work domain tasks mirrored to a remote tracker:
```bash
jira_tool create --summary "<title>"
# Returns: OK | DMDI-XXXXX | created
# Note the returned task ID
```

For personal/triv domain tasks, skip this step — IDs are auto-allocated.

### 2. Create DIL task file

```bash
_shared/scripts/create_task.sh \
  --domain <domain> \
  --task-id <ID>           # required for work domain; omit for personal/triv \
  --title "<title>" \
  --project <slug>         # from project registry aliases lookup \
  --priority <priority> \
  --work-type <work_type> \
  --task-type <task_type> \
  --effort-type <effort_type>
```

**Project slug resolution**: Read `_shared/_meta/project_registry.md`. Match the task description against the `aliases` column (case-insensitive, partial match OK). Use the `slug` from the matched row. If ambiguous or no match, ask the user.

### 3. Transition to In Progress

**DO NOT SKIP THIS STEP.** This is the most commonly forgotten step — agents and humans both tend to jump straight from creation to doing the work. Transition BEFORE posting comments or doing work.

```bash
# Remote system (if applicable)
jira_tool transition <ID> "In Progress"
# Returns: OK | <ID> | Backlog → In Progress (handles multi-step chaining)
```

Update the DIL task file `status:` field to `in_progress`.

**Self-check before step 4:** If you are about to run `jira_tool comment` on a ticket, verify it is already In Progress. If not, transition it first.

### 4. Do the work / log evidence

Perform the actual work. Collect evidence (terminal output, screenshots, verification commands).

### 5. Add completion evidence

```bash
# Remote system (if applicable)
# Wrap terminal output in {noformat} blocks for Jira wiki markup
jira_tool comment <ID> '{noformat}<terminal output>{noformat}'
```

Append execution notes to the DIL task file's `## Execution Notes` section.

### 6. Transition to Done

```bash
# Remote system (if applicable)
jira_tool transition <ID> "Done"
```

Update the DIL task file `status:` field to `done`.

### 7. Verify

```bash
jira_tool status <ID>           # should show Done
grep "^status:" <task_file>     # should show done
```

## Partial Completion

Not every task goes through all steps in one session:
- If only creating: do steps 1-2, leave status as `todo`
- If starting work: do steps 1-3
- If finishing later: pick up at step 4 with the existing task ID
- User may ask to do any subset — follow their lead

## Jira Wiki Markup Quick Reference

When posting to Jira via `jira_tool comment`, use Jira wiki markup (not Markdown):

| Markdown | Jira Wiki Markup |
| --- | --- |
| \`\`\`code\`\`\` | `{noformat}code{noformat}` |
| **bold** | `*bold*` |
| *italic* | `_italic_` |
| `- item` | `* item` |
| `1. item` | `# item` |
| `### Heading` | `h3. Heading Text` |
| `[text](url)` | `[text\|url]` |

Use `md2jira` to convert Markdown to Jira markup if needed.

## Example: Complete Lifecycle

```bash
# 1. Create in Jira
jira_tool create --summary "Fix broken cron job on dv-dmdi-etl-01"
# OK | DMDI-11900 | created

# 2. Create DIL task file
_shared/scripts/create_task.sh \
  --domain work --task-id DMDI-11900 \
  --title "Fix broken cron job on dv-dmdi-etl-01" \
  --project autozone-server-admin \
  --priority high --work-type bug --task-type kanban --effort-type low

# 3. Transition to In Progress
jira_tool transition DMDI-11900 "In Progress"

# 4. Do the work...

# 5. Add evidence
jira_tool comment DMDI-11900 '{noformat}$ crontab -l | grep backup
0 2 * * * /home/talend/scripts/backup.sh{noformat}'

# 6. Transition to Done
jira_tool transition DMDI-11900 "Done"

# 7. Update DIL task file status to done
```
