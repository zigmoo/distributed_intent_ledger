---
title: "Compose Via Message Contract"
date: 2026-05-02
machine: shared
assistant: shared
category: policy
memoryType: policy
priority: high
tags: [messages, composition, policy, agentic-tools]
updated: 2026-05-02
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Compose Via Message Contract

All composed prose — internal or external — MUST use the message object contract (`_shared/messages/CONTRACT.md`).

## Scope

This applies whenever an agent composes prose of any substance, regardless of audience:

- Teams messages (chat or channel)
- Jira comments with narrative content (not routine status updates)
- Group posts (CCP, HMAVC, etc.)
- Stories, briefs, or summaries for colleagues, leadership, or personal reference
- Email drafts
- Slack messages
- Internal reports, briefings, or composed artifacts for the user
- Commit messages (subject and body/trailers)

## Why

- **Durability:** compositions survive session crashes, context compaction, and agent restarts
- **Portability:** Obsidian syncs them across machines — a draft started on one machine is visible everywhere
- **Formatting:** the message file is the input to deterministic nozzles (`md2jira`, `jira-panel`, `wl-copy --type text/html`, future formatters). Compose once, deliver anywhere.
- **Audit trail:** frontmatter ties the composition to a task, session, and recipient
- **Retry:** if delivery fails, the draft is still there. If the session dies mid-composition, the work isn't lost.
- **Cross-session and cross-agent visibility:** a message file is a thinking artifact, not just a delivery artifact. One agent session composes a draft, gets compacted or dies, and the next session — or a completely different agent — picks it up cold from the file. The frontmatter tells it who the message is for, what task it belongs to, and whether it was ever sent. No hot file entry needed, no context recovery guesswork. This makes composed thought durable and transferable across the entire agent mesh.

## What This Means in Practice

1. Create the file in `_shared/messages/` using the deterministic naming convention
2. Include required frontmatter (session, task, recipient, channel, status)
3. Set `status: draft` until delivery is confirmed
4. Compose the body as HTML (for Teams/email) or plain text (for Jira, using `md2jira` at send time)
5. After delivery, update `status: sent` and add the `sent:` timestamp
6. For git commits, include a `message_ref: _shared/messages/<file>.md` line in the commit message body/trailers so the commit links to the canonical message artifact

## What This Does NOT Cover

- Routine `jira_tool comment` one-liners (status updates, evidence posts) — these are operational, not prose
- Task file updates, memory files, execution notes — these are vault records, not compositions
- Conversational chat replies to the user — this policy is about composed artifacts, not interactive dialogue

## Reference

Full format spec: `_shared/messages/CONTRACT.md`
