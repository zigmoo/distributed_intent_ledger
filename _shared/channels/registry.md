---
title: Channel Registry
created: 2026-05-01
status: active
owner: shared
---

# Channel Registry

| channel_id | platform | nozzle | delivery_tool | confirm_method | auth | format_in | format_out | constraints | status |
|---|---|---|---|---|---|---|---|---|---|
| `teams-chat` | Teams | none (raw HTML) | `wl-copy --type text/html` → user paste / CDP paste | visual / seen icon / screenshot | SSO session in browser | HTML | HTML | Shift+Enter between thoughts; never compose in Teams box directly; Ctrl+Enter to send | active |
| `teams-channel` | Teams | none (raw HTML) | `wl-copy --type text/html` → user paste / CDP paste | visual / screenshot | SSO session in browser | HTML | HTML | same as teams-chat; tag relevant people | active |
| `jira-comment` | Jira | `md2jira` | `jira_tool comment` | API response OK + comment ID | PAT via `getSecret` / `/tmp/jira_token_temp.txt` | Markdown | Jira wiki markup | use `[~userID]` tilde syntax for mentions; `jira-panel` for panels | active |
| `jira-attach` | Jira | image optimize (JPEG 1280px) | `jira_tool attach` | API response OK | same as jira-comment | binary | binary | Akamai WAF ~32KB threshold; auto-optimize | active |
| `agent-session` | Agent | none | filesystem write to `_shared/messages/` or `_hot.md` | file exists + mtime check | filesystem (local) | Markdown | as-is | target session must poll or read on bootstrap | active |
| `dil-agent` | Agent | none | write to `_shared/messages/` | `status: read` + `read_by` in frontmatter | filesystem (local/Obsidian sync) | Markdown | as-is | recipient scans by agent slug; update status to `read` after reading | active |
| `console-report` | Console | none (raw Markdown) | emit to conversation as text output | user sees it in terminal/UI | none (local session) | Markdown | Markdown | activity reports, task summaries, session briefs, any composed output for the user's console | active |
| `agent-drop` | Agent | none | write to `_shared/drops/<target_session>/` | file exists | filesystem (local) | any | any | one-way fire-and-forget; receiver picks up async | planned |
| `email` | Email | TBD | TBD | TBD | TBD | HTML | HTML/MIME | TBD | planned |
| `slack` | Slack | TBD | TBD | TBD | TBD | Markdown | Slack mrkdwn | TBD | planned |
| `gitlab-mr-comment` | GitLab | none (Markdown) | GitLab API / CDP | comment ID in API response | SSO session / PAT | Markdown | Markdown | Atlantis commands in comments (`atlantis apply`) | planned |
