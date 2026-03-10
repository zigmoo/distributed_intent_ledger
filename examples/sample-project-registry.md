---
title: "Project Registry"
date: 2026-03-10
machine: shared
assistant: shared
category: system
memoryType: registry
priority: critical
tags: [registry, projects, shared]
updated: 2026-03-10
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Project Registry

Canonical list of valid project slugs. Tasks must reference a registered slug in their `project:` field.

New projects are added with `create_project.sh`:

```bash
create_project.sh --slug my-project --name "My Project" --domain personal --description "What this project is about"
create_project.sh --slug sub-project --name "Sub Project" --domain personal --parent my-project --description "A child project"
```

The task validator (`validate_tasks.sh`) warns on unregistered project slugs.

| slug | name | domain | status | parent | owner | description | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dil | Distributed Intent Ledger | personal | active | | moo | DIL protocol, spec, tooling, and vault maintenance | |
| example-project | Example Project | personal | active | | moo | A sample project to demonstrate the registry format | |
| example-sub | Example Sub-Project | personal | active | example-project | moo | Demonstrates parent-child project hierarchy | |
