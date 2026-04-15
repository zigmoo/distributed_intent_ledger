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

## Applies To

- Agent chat replies
- Messages to colleagues (Teams, Slack, email)
- Jira/SMAX/ticketing comments
- Error messages and log output
- Config files and help text
- TUI displays and CLI output
- Handoff notes between agents
