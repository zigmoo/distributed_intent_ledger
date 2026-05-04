---
title: Message Object Contract
created: 2026-05-01
status: active
owner: shared
---

# Message Object Contract

## Purpose

An agentic thought object. Durable, inspectable records of composed messages sent through external channels (Teams, Slack, email, Jira comments). Survives session crashes, syncs via Obsidian, and provides an audit trail correlating messages to sessions, tasks, and recipients.

## File Location

```
_shared/messages/<YYYYMMDD_HHMMSS>.<task>.<channel>.<recipient_slug>.md
```

## Naming Rules (Deterministic)

Every segment is derived mechanically — no freeform text, no creative slugs.

### Segment 1: Timestamp — `YYYYMMDD_HHMMSS`
- Local time, 24-hour, zero-padded
- Resolution to the second to avoid collisions on rapid-fire messages
- Example: `20260501_170832`

### Segment 2: Task ID — `<task>`
- Jira ID lowercase with hyphen: `work-12540`, `itb-4506`, `dil-1353`
- If no task: `notask`
- Never omit — always present

### Segment 3: Channel — `<channel>`
- One of: `teams-chat`, `teams-channel`, `jira-comment`, `email`, `slack`, `dil-agent`
- `dil-agent` is for inter-agent messages within DIL — any agent can discover these by scanning `_shared/messages/`
- Determines which nozzle/formatter to use downstream

### Segment 4: Recipient slug — `<recipient_slug>`
- Last name lowercase, first initial: `poreddy-v`, `perez-a`, `akula-b`
- Groups use the group short name: `ccp-group`, `di-team`, `mechwarriors`
- No spaces, no special characters, hyphens only

### Separator
- Dot (`.`) between segments — parseable by `cut -d. -f1,2,3,4`
- Dot chosen over underscore because timestamps already use underscores internally

### Full Examples

```
20260501_170832.work-12540.teams-chat.poreddy-v.md
20260501_171005.work-12610.teams-chat.perez-a.md
20260501_171200.work-12540.teams-chat.akula-b.md
20260501_171500.work-12540.teams-channel.ccp-group.md
20260501_163000.work-12610.jira-comment.work-12610.md
```

### Parsing

Any tool can extract metadata from the filename alone:
```bash
TIMESTAMP=$(echo "$f" | cut -d. -f1)
TASK=$(echo "$f" | cut -d. -f2)
CHANNEL=$(echo "$f" | cut -d. -f3)
RECIPIENT=$(echo "$f" | cut -d. -f4 | sed 's/\.md//')
```

Frontmatter is authoritative. Filename is a fast index for `ls`, `find`, `grep` without opening the file.

## Tool Forge Integration

### jira_tool
When `jira_tool comment` posts a comment, it SHOULD also write a message object:
```bash
jira_tool comment WORK-12540 @_shared/messages/<file>.md
# jira_tool reads the file, strips frontmatter, converts Markdown→Jira wiki, posts,
# then sets status: sent and adds sent: timestamp in the frontmatter
```

### msg (planned helper)
```bash
msg compose --task WORK-12540 --to "Poreddy, Vamshi Reddy" --channel teams-chat
# Creates the file with frontmatter, opens $EDITOR or returns the path for agent use

msg send <file>.md
# Strips frontmatter, pipes body through the appropriate nozzle:
#   teams-chat    → wl-copy --type text/html (user pastes)
#   jira-comment  → md2jira | jira_tool comment
#   email         → future
# Updates status → sent, adds sent timestamp

msg list [--status draft|sent|failed] [--task WORK-*] [--today]
# Lists message objects with filters

msg retry <file>.md
# Re-attempts delivery of a failed message
```

### md2jira / jira-panel
Existing formatters work as nozzles — message body pipes through them based on channel type.

### Teams CDP workflow
For `teams-chat` and `teams-channel`, the nozzle is `wl-copy --type text/html` — the agent or user pastes. The message object records the intent; the paste confirms delivery.

## Required Frontmatter

```yaml
---
session: <session-id from registry>
task: <WORK-XXXXX or DIL-XXXX>
recipient: <Display Name>
channel: teams-chat | teams-channel | jira-comment | email | slack
status: draft | sent | read | failed
composed: <ISO 8601 timestamp>
author: <who composed — e.g., "Z + Pedro", "moo", "pedro">
model: <model ID if agentic — e.g., "claude-opus-4-6">
sent: <ISO 8601 timestamp, added after send>
read_by: <agent slug that read the message, added when status → read>
read_at: <ISO 8601 timestamp, added when status → read>
---
```

## Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `session` | yes | Session registry ID (e.g., `pedro-framemoowork-20260501`) |
| `task` | yes | Jira or DIL task ID this message relates to. Use `none` if untied |
| `recipient` | yes | Display name of the person or group |
| `channel` | yes | Delivery channel |
| `status` | yes | `draft` until sent, `sent` after confirmed delivery, `read` after a receiving agent reads it (inter-agent), `failed` if delivery failed |
| `composed` | yes | When the message was written |
| `author` | yes | Who composed the message (e.g., `Z + Pedro`, `moo`, `pedro`) |
| `model` | no | Model ID if agentic (e.g., `claude-opus-4-6`). Omit for human-only compositions |
| `sent` | no | When the message was confirmed delivered. Omit while draft |
| `read_by` | no | Agent slug that read the message (inter-agent only). Omit until read |
| `read_at` | no | When the message was read by the receiving agent. Omit until read |

## Body

Markdown below the frontmatter. This is the universal authoring format. Nozzles convert it to the target channel's format at delivery time (HTML for Teams, Jira wiki markup for Jira, plain text for email, etc.).

## Clipboard Workflow

```bash
# Load a message to clipboard for Teams paste
cat _shared/messages/<file>.md | sed '1,/^---$/d' | sed '1,/^---$/d' | wl-copy --type text/html

# Or use a helper that strips frontmatter automatically
_shared/scripts/msg_to_clipboard.sh <file>.md
```

## Session Registry Correlation

Each session registry row may include:
- `msg_count`: number of messages composed during the session
- `msg_latest`: filename of the most recent message

These are updated at session close or when writing `_hot.md`.

## Retention

- Messages are ephemeral work artifacts, not permanent records
- The Jira comment or Teams delivery is the durable record
- Prune messages older than 30 days unless flagged for retention
- Files with `status: failed` should be investigated before pruning

## When to Use (Mandatory)

All agent-composed prose — internal or external — must use this contract. Compose in a message file, format through nozzles, deliver to any channel. This includes Teams messages, group posts, stories, narrative Jira comments, reports, briefings, email drafts, and any other composed artifact. Routine one-liner `jira_tool comment` posts (status updates, evidence) are exempt.

Message files are thinking artifacts, not just delivery artifacts. They give any agent or session the ability to discover, resume, or build on composed thought from another agent or session — without relying on hot files or context recovery. The frontmatter makes each composition self-describing: who it's for, what task it belongs to, whether it was sent.

Full policy: `_shared/policies/compose-via-message-contract-2026-05-02.md`

## Anti-Patterns

- Do NOT compose messages in `/tmp` — they won't survive crashes or sync to Obsidian
- Do NOT compose directly in the Teams input box — use the file + clipboard workflow
- Do NOT skip frontmatter — a message without metadata is just loose text
