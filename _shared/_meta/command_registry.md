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
| "search tasks", "list tasks", "show tasks", "find task" | `_shared/scripts/task_tool.sh search [--status STATUS] [--project SLUG] [--domain DOMAIN] [--latest N] [--count] [--json]` | Fast task discovery and filtering from index |
| "review task", "show task details" | `_shared/scripts/task_tool.sh review <TASK_ID> [--json]` | Show full task details for a single task |
| "validate tasks" | `_shared/scripts/validate_tasks.sh` | Run before claiming task-system completion |
| "archive tasks" | `_shared/scripts/archive_tasks.sh` | Moves terminal tasks to archived/ |
| "list archived" | `_shared/scripts/list_archived.sh` | Search/filter archived tasks |
| "rebuild index" | `_shared/scripts/rebuild_task_index.sh` | Regenerate task_index.md from files |
| "identify agent" | `_shared/scripts/identify_agent.sh` | Resolve assistant ID from runtime |
| "search dil", "dil search", "find in dil", "recall" | `_shared/scripts/dil_search.sh "<query>" [--recall] [--scope SCOPE] [--domain DOMAIN] [--limit N] [--json]` | Hybrid search across DIL memory/tasks/preferences. Use `--recall` for protocol-aligned retrieval. |
| "ingest source", "ingest file", "ingest url", "import file" | `_shared/scripts/ingest_source.sh <path-or-url>` | Ingest an external asset with manifest, provenance, and adapter routing |
| "list ingested", "show ingested", "ingestion status" | `_shared/scripts/list_ingest.sh [--state STATE] [--domain DOMAIN]` | Query knowledge registry: filter by status/domain/tier/actor |
| "retry ingest", "retry failed" | `_shared/scripts/retry_ingest.sh <ingest_id> [--check-tooling] [--abandon] [--force-promote]` | Retry/triage failed ingestion items |
| "ingestion runbook", "should I ingest this" | `_shared/runbooks/knowledge-ingestion-runbook.md` | Decision rule: ingest_source.sh vs create_memory.sh |
| "create memory", "remember this" | `_shared/scripts/create_memory.sh --type <type> --title "<title>"` | Create authored DIL memory note. NOT for external assets. |
| "remove memory" | `_shared/scripts/remove_memory.sh` | Remove a DIL memory note |

## External Tool Integration (customize per instance)

| Trigger | Command | Notes |
| --- | --- | --- |
| "create jira task" | `_shared/scripts/create_jira_task.sh` | Creates Jira ticket + mirroring DIL task |
| Jira operations | `/path/to/jira_tool` | Do NOT tell user to update Jira manually |
| SMAX operations | `/path/to/smax_tool` | Firewall requests, change records |
| Teams notifications | `/path/to/teams_tool` | Webhook notifications |

## Notes

- **Script portability rule**: all DIL scripts must resolve base path in this order: `BASE_DIL` -> repo-relative from script location -> legacy `$HOME/Documents/dil_agentic_memory_0001`; fail clearly if unresolved.
- **Never hardcode user-specific paths** (for example `/home/moo/...`) as default DIL base resolution.
