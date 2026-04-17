---
title: Recommended Agent Workflow Discipline
status: optional-guidance
updated: 2026-03-10
---

# Recommended Agent Workflow Discipline

This is an optional policy document for DIL deployments that want stronger execution discipline than the base spec requires.

Suggested live-vault destination:
- `_shared/policies/agent-workflow-discipline.md`

Use this when you want a shared policy that emphasizes planning, verification, self-correction, and security hygiene across multiple agents.

## 1. Exploration Mode Gate

When architecture or conventions are genuinely unclear, the agent should ask whether to:
- problem-solve through to a proof of concept, or
- stop and ask before making architectural decisions

If the path is clear and the user intent is unambiguous, skip the gate and execute.

## 2. Plan-First Gate

For multi-file or longer-running tasks:
- start with a concrete plan
- proceed immediately when confidence is high and risk is low
- pause for confirmation when the change is high-risk or the path is ambiguous

## 3. Verify After Change

After making code or configuration changes, the agent should:
- run the relevant lint, typecheck, validation, or test commands
- report what was run and the meaningful outcome
- fix failures in the same session when they are in scope

## 4. Self-Correct Loop

When verification fails:
- diagnose instead of retrying blindly
- apply a fix
- re-run verification
- repeat until passing or clearly blocked

## 5. Atomic Work Units

- keep changes focused
- avoid bundling unrelated refactors with the requested fix
- prefer one logical concern per commit or review unit

## 6. Lessons and Anti-Patterns

Capture recurring mistakes and project-specific gotchas in the narrowest useful scope:
- project-level guidance files such as `CLAUDE.md`
- DIL lessons notes under machine, assistant, or shared scope

## 7. Security Baseline

- never commit secrets or credentials
- sanitize inputs and parameterize queries
- enforce authorization server-side
- remove debug logging before considering work complete
- verify external webhook signatures when applicable

## 8. Minimize Inference, Maximize Determinism

Assume assistants are unreliable and context is partial. Prefer fixed action graphs, explicit commands, durable artifacts, typed schemas, and validated handoffs over free-form reasoning or memory-heavy planning.

Treat this document as a policy pack you can adopt, trim, or override per deployment.
