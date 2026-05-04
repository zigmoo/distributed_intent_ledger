---
title: Channel Registry Contract
created: 2026-05-01
status: active
owner: shared
---

# Channel Registry Contract

## Purpose

Deterministic mapping from a channel ID to the tools, nozzles, and behaviors required to deliver a message through that channel. Every message object references a `channel` — this registry defines what that channel means operationally.

## Registry Location

```
_shared/channels/CONTRACT.md     — this contract
_shared/channels/registry.md     — the live registry table
_shared/channels/<channel_id>/   — optional per-channel config, templates, or nozzle scripts
```

## Channel ID Rules

- Lowercase, hyphenated: `teams-chat`, `jira-comment`, `agent-session`
- Two segments: `<platform>-<mode>`
- Platform is the system: `teams`, `jira`, `email`, `slack`, `agent`, `file`
- Mode is the delivery style: `chat`, `channel`, `comment`, `attach`, `session`, `drop`
- New channels are added to the registry, not invented ad-hoc in message frontmatter

## Registry Schema

| Field | Description |
|-------|-------------|
| `channel_id` | Unique identifier, used in message object frontmatter |
| `platform` | External system (Teams, Jira, Email, Slack, Agent, File) |
| `nozzle` | Formatter/transform applied to the message body before delivery |
| `delivery_tool` | Tool or mechanism that performs the actual send |
| `confirm_method` | How we verify the message was delivered |
| `auth` | What credentials or tokens are needed |
| `format_in` | What format the message body is authored in |
| `format_out` | What format the delivery tool expects |
| `constraints` | Behavioral rules (spacing, length, rate limits) |
| `status` | `active`, `planned`, `deprecated` |

## Live Registry

See `_shared/channels/registry.md` for the current table.

## Recipient Types

A message recipient can be one of:

### Person
- Slug: `lastname-firstinitial` (e.g., `poreddy-v`, `perez-a`)
- Source: org directory, Teams contacts

### Group
- Slug: group short name (e.g., `ccp-group`, `di-team`, `mechwarriors`)
- Source: Teams group chats, channels, distribution lists

### Agent Session
- Slug: session ID from session registry (e.g., `pedro-framemoowork-20260501-02`)
- Source: `_shared/sessions/registry.md`
- Delivery: filesystem write to a location the target session reads

### System
- Slug: system identifier (e.g., `jira-work-12540`, `gitlab-mr-36601`)
- Source: the system's own ID namespace
- Delivery: API call via the appropriate tool

## Channel-to-Nozzle Pipeline

```
┌──────────────┐    ┌──────────┐    ┌───────────────┐    ┌──────────────┐
│ Message Body │───►│  Nozzle  │───►│ Delivery Tool │───►│   Channel    │
│   (HTML)     │    │(formatter)│   │  (jira_tool,  │    │  (Teams,     │
│              │    │           │   │   wl-copy,    │    │   Jira,      │
│              │    │           │   │   file write)  │   │   Agent)     │
└──────────────┘    └──────────┘    └───────────────┘    └──────────────┘
                         │                  │                    │
                    format_out         confirm_method       constraints
```

## Adding a New Channel

1. Add a row to `_shared/channels/registry.md`
2. If the channel needs a custom nozzle, add it to `_shared/channels/<channel_id>/nozzle.sh`
3. Update the `msg send` tool to recognize the new channel_id
4. Test with a `status: draft` message before going live

## Anti-Patterns

- Do NOT invent channel IDs in message frontmatter without adding them to the registry
- Do NOT hardcode nozzle logic in agent sessions — look it up from the registry
- Do NOT skip confirmation — every delivery must update `status` in the message frontmatter
- Do NOT use a channel for a purpose it wasn't designed for (e.g., `jira-comment` for binary attachments — use `jira-attach`)
