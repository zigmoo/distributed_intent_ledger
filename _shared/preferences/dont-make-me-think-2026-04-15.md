---
title: "Don't Make Me Think — Universal Communication Principle"
date: 2026-04-15
machine: shared
assistant: shared
category: preferences
memoryType: preference
priority: high
tags: [communication, principle, dont-make-me-think, ux, design, agents]
updated: 2026-04-15
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Don't Make Me Think — Universal Communication Principle

This principle applies to ALL communication: code, configs, error messages, log output, chat messages (Teams, Slack, email), Jira comments, agent-to-human replies, and agent-to-agent handoffs.

**The less inference required by the consumer of any message, the more likely the sender achieves the desired result.**

## Rules

1. **Lead with the action.** "Action needed: approve these two tickets" — not a paragraph that buries the ask.
2. **Links on their own line.** Not embedded in prose where they're hard to spot or click.
3. **One message, one ask.** Don't combine status updates with action requests.
4. **Copy-paste ready.** Commands, URLs, file paths — always show them ready to use.
5. **Answer "what do I do next?"** Every output should make the next step obvious without the reader leaving the screen.
6. **No mental mapping.** Show literal tool names, not concepts. Show file paths, not "check the docs."
7. **Self-documenting.** Variable names, function names, comments, config keys — a reader should understand intent without tracing call chains.
8. **Whitespace between thoughts.** Humans parse blocks of text faster when sentences are separated by blank lines. A wall of text forces the reader to find paragraph boundaries mentally. In chat messages, Jira comments, and agent output: one idea per paragraph, blank line between them.

## Assume Self-Taught Users

DIL users are likely self-taught in Linux/Unix, programming, and systems administration. No formal training or CS degree should be assumed.

- **Knowledge is deep but non-comprehensive.** Users may be extremely strong in areas they've worked in hands-on, with occasional gaps in foundational concepts (POSIX idioms, networking primitives, language specification details, academic CS terminology).
- **Explain the "why" behind conventions when they come up.** Don't just say "use X" — say why X exists and what problem it solves. A one-sentence explanation turns a gap into permanent knowledge.
- **Never condescend.** Self-taught engineers learn fast and retain permanently once something clicks. Treat gaps as normal, not as deficiencies.
- **Don't assume jargon is understood.** If a term like "shebang," "symlink indirection," or "file descriptor" comes up naturally, briefly define it in context.
- **Show, don't lecture.** A concrete example beats an abstract explanation. `#!/usr/bin/env bash` with "this searches PATH for bash so it works on systems where bash isn't at /bin/bash" is better than a paragraph about POSIX interpreter directives.

## Applies To

- Agent chat replies
- Messages to colleagues (Teams, Slack, email)
- Jira/SMAX/ticketing comments
- Error messages and log output
- Config files and help text
- TUI displays and CLI output
- Handoff notes between agents
