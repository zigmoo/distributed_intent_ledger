---
title: "Project Registry"
date: 2026-03-10
machine: shared
assistant: shared
category: system
memoryType: registry
priority: critical
tags: [registry, projects, shared, aliases, task-discovery]
updated: 2026-03-17
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Project Registry

Canonical list of valid project slugs. Tasks must reference a registered slug in their `project:` field.
Also serves as zero-inference lookup for task discovery: match user shorthand against the `aliases` column, then use `anchor_task` and `repo_path` to find related tasks and code.

This is one concrete example of the broader low-inference principle: the registry should let a caller map intent to the right project without model-side guesswork.

New projects are added with `create_project.sh`:

```bash
create_project.sh --slug my-project --name "My Project" --domain personal --description "What this project is about"
create_project.sh --slug sub-project --name "Sub Project" --domain personal --parent my-project --description "A child project"
create_project.sh --slug work-app --name "Work App" --domain work --anchor-task PRJ-100 --repo-path /path/to/app/ --description "Main work application"
```

The task validator (`validate_tasks.sh`) warns on unregistered project slugs.

| slug | aliases | domain | name | status | parent | anchor_task | repo_path | owner | description |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dil | DIL, intent ledger, agentic memory | personal | Distributed Intent Ledger | active | | | | moo | DIL protocol, spec, tooling, and vault maintenance |
| dil-infrastructure | DIL infra, dil scripts | personal | DIL Infrastructure | active | dil | | | moo | DIL scripts, automation, and tooling |
| example-project | example, sample app | personal | Example Project | active | | | | moo | A sample project to demonstrate the registry format |
| example-sub | sub example | personal | Example Sub-Project | active | example-project | | | moo | Demonstrates parent-child project hierarchy |
| example-work | work app, my app | work | Example Work Project | active | | PRJ-100 | /path/to/project/ | user | Example work-domain project with anchor task |

## Column Reference

- **slug**: kebab-case identifier used in task `project:` field
- **aliases**: comma-separated alternate names for zero-inference task discovery
- **domain**: which domain this project belongs to (personal, work, triv, etc.)
- **name**: human-readable display name
- **status**: active, archived, or retired
- **parent**: slug of parent project (for hierarchical grouping)
- **anchor_task**: root task ID that groups all tasks for this project (for discovery)
- **repo_path**: filesystem path to the project's code repository
- **owner**: default task owner for this project
- **description**: brief description of the project scope
