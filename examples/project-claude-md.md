# CLAUDE.md

Persistent project memory and guidance for AI coding agents.
Load this at session start. Keep it concise and specific to the project.

This template pairs well with a shared DIL policy such as `_shared/policies/agent-workflow-discipline.md`, but it can also stand alone.

## 1. Project Overview

Mission: [REPLACE with project mission]
Success criteria: [REPLACE with measurable goals]

## 2. Architecture and Repo Map

- Framework: [e.g. Next.js, Express, FastAPI]
- Language: [e.g. TypeScript strict, Python 3.12]
- Styling: [e.g. Tailwind, CSS modules, none]
- Data layer: [e.g. PostgreSQL, SQLite, file-backed]
- Auth: [e.g. Clerk, Auth.js, none]
- Testing: [e.g. Vitest, Playwright, pytest]
- Key folders:
  - `src/` -> [describe]
  - `lib/` -> [describe]
  - `tests/` -> [describe]
  - `scripts/` -> [describe]
- Never touch directly: [e.g. `node_modules/`, build output, generated files]

## 3. Code Style and Conventions

- [describe linting and formatting rules]
- [describe naming and export patterns]
- [describe error-handling expectations]
- Commits: [project prefix]: message

## 4. Commands Cheat Sheet

```text
dev      -> [e.g. pnpm dev]
build    -> [e.g. pnpm build]
test     -> [e.g. pnpm test]
lint     -> [e.g. pnpm lint]
check    -> [e.g. pnpm lint && pnpm test]
```

## 5. Workflow Rules

1. For uncertain architecture, choose whether to problem-solve through or stop and ask first.
2. For multi-file or longer tasks, start with a plan.
3. After changes, run the relevant checks and summarize the result.
4. Keep changes focused and avoid unrelated cleanup.
5. Do not commit secrets or sensitive data.

## 6. Lessons and Anti-Patterns

- YYYY-MM-DD: [short lesson]

## 7. Project-Specific Security Notes

- [e.g. verify webhook signatures]
- [e.g. enforce auth server-side]
- [e.g. scrub secrets from logs]
