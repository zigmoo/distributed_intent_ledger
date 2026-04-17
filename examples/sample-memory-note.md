---
title: "Runtime Registry Sanitization Rules for Public Example Content"
date: 2026-03-04
machine: framemoowork
assistant: codex
category: decisions
memoryType: note
priority: notable
tags: [examples, docs, sanitization, governance]
updated: 2026-03-04
source: internal
domain: operations
project: dil
status: active
owner: codex
due:
---

# Runtime Registry Sanitization Rules for Public Example Content

## Context
Public sample files must demonstrate realistic structure without leaking environment-specific details.

## Decision
When building GitHub-facing examples:
- Keep machine shortnames for readability (`framemoowork`, `pi500`, `omarchy-zbook`).
- Replace custom/private network domains with neutral placeholders (for example `tailnet.example`).
- Avoid raw IPv4/IPv6 literals in examples.

## Rationale
- Preserves educational quality while reducing accidental environment disclosure.
- Makes examples portable for teams adopting DIL in different infrastructures.

## Follow-up
- Expand examples to include active/paused/offline style coverage.
- Keep schema-valid examples for both agent and machine registries.
- Make example notes and tasks explicit enough that a reader does not need to infer missing context or hunt through other files for the next step.
