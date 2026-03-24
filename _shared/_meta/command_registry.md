---
title: "Command Registry"
date: 2026-03-18
machine: shared
assistant: shared
category: system
memoryType: registry
priority: critical
tags: [registry, commands, shared, zero-inference]
updated: 2026-03-18
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Command Registry

Zero-inference lookup table for agent commands. Before doing any work, check this registry for an existing script/tool that matches the user's intent. **Do NOT manually replicate what a script does — run the script.**

## DIL Operations

| Trigger | Command | Notes |
| --- | --- | --- |
| "morning brief" | `_shared/scripts/morning_brief.sh` | Do NOT manually gather task data |
| "create task" | `_shared/scripts/create_task.sh` | Handles ID allocation, index update |
| "create project" | `_shared/scripts/create_project.sh` | Adds to project registry |
| "validate tasks" | `_shared/scripts/validate_tasks.sh` | Run before claiming task-system completion |
| "archive tasks" | `_shared/scripts/archive_tasks.sh` | Moves terminal tasks to archived/ |
| "list archived" | `_shared/scripts/list_archived.sh` | Search/filter archived tasks |
| "rebuild index" | `_shared/scripts/rebuild_task_index.sh` | Regenerate task_index.md from files |
| "identify agent" | `_shared/scripts/identify_agent.sh` | Resolve assistant ID from runtime |

## External Tool Integration (customize per instance)

| Trigger | Command | Notes |
| --- | --- | --- |
| "create jira task" | `_shared/scripts/create_jira_task.sh` | Creates Jira ticket + mirroring DIL task |
| Jira operations | `/path/to/jira_tool` | Do NOT tell user to update Jira manually |
| SMAX operations | `/path/to/smax_tool` | Firewall requests, change records |
| Teams notifications | `/path/to/teams_tool` | Webhook notifications |
