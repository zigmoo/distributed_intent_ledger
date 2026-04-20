---
title: "url_tool — Clickable Ticket Links in Console Output"
date: 2026-04-20
machine: shared
assistant: shared
category: preferences
memoryType: preference
priority: high
tags: [url_tool, jira, smax, links, console, output, agents, dont-make-me-think]
updated: 2026-04-20
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# url_tool — Clickable Ticket Links in Console Output

When displaying Jira, SMAX, or other ticket IDs in console output, **always use `url_tool`** to generate clickable links. Never output bare ticket IDs as plain text.

## Tool

Canonical: `_shared/scripts/url_tool.sh`
Work mirror: `/az/talend/scripts/bin/url_tool`

## Usage

```bash
url_tool ticket <TICKET_ID>          # auto-detect system by prefix
url_tool ticket DMDI-11909           # → [DMDI-11909](https://jira.autozone.com/browse/DMDI-11909)
url_tool smax <REQUEST_ID>           # SMAX request link
url_tool comment <TICKET_ID> <CID>   # Jira comment deep link
url_tool --plain ticket DMDI-11909   # bare URL (no markdown)
```

## When to Use

- Search results listing ticket IDs
- Status checks referencing a ticket
- Reports, summaries, or tables containing ticket IDs
- Any output where a human might want to click through to the ticket

## Applies to All Prefixes

DMDI-, BIT-, BIN-, CAR-, CAOD-, DMOS-, DBR-, DMDAS-, HRD-, MFIT-, BISUP-, STAT-, IPAP-, ITEA-, MD-, MADP-, ADS-, BURS-, and SMAX numeric IDs.

## URLs Must Be Clickable in Console

All URLs emitted to the console — not just ticket links — should be clickable. This includes:

- **File paths**: use `file://` URIs when referencing local files in output meant for the user
- **Web URLs**: always emit full `https://` URLs, never truncated or partial
- **Markdown links**: terminals that support OSC 8 hyperlinks render `[text](url)` as clickable; use this format by default
- **Bare URLs on their own line**: when a URL is the primary content (not inline), put it on its own line for easy click targeting

If a tool or script generates output with ticket IDs or URLs, it should use `url_tool` or equivalent formatting to ensure clickability.

## Why

Extends the "Don't Make Me Think" principle to ticket references and URLs. A clickable link eliminates the manual step of copying an ID and pasting it into a browser. This is especially valuable when reviewing search results with dozens of tickets.
