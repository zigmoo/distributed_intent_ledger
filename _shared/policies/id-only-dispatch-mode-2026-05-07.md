---
title: "ID-Only Dispatch Mode"
date: 2026-05-07
machine: shared
assistant: shared
category: policy
memoryType: policy
priority: critical
tags: [policy, dispatch, tasks, low-inference, handoff]
updated: 2026-05-07
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# ID-Only Dispatch Mode

## Purpose

Define deterministic behavior when an operator dispatches work by task ID list only.

## Policy

When the operator provides ordered task IDs as the work queue:

1. Agents MUST execute IDs in the exact order provided.
2. Agents MUST NOT request additional framing unless blocked by a hard execution error.
3. If a task lacks detail, agents MUST use parent-task execution notes as authoritative context.
4. After completing each task, agents MUST proceed immediately to the next ID.

## Scope

- Applies to all agent runtimes using DIL task lifecycle workflows.
- Intended to reduce inference drift and increase handoff reliability for lesser/smaller models.

## Relationship to Runbooks

- Bootstrap policy source: `READ_THIS_DIL_FIRST.md`
- Procedure source: `_shared/runbooks/task-lifecycle-runbook.md`

## Non-Goals

- This policy does not change task status semantics.
- This policy does not bypass safety constraints, approvals, or credential requirements.
