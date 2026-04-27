---
title: "Agent Workspace Setup Runbook — Browser & Terminal Isolation"
date: 2026-04-23
machine: shared
assistant: shared
category: runbook
memoryType: reference
priority: notable
tags: [runbook, agent-workspace, browser, tmux, chromium, isolation, assistant-setup]
updated: 2026-04-23
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Agent Workspace Setup Runbook — Browser & Terminal Isolation

## Purpose

Turn an AI coding agent into a visible, observable assistant by giving it dedicated browser and terminal instances that operate independently from the human operator. The agent works without stealing focus, and the operator can watch everything in real time.

## Problem Statement

By default, agent tools (Chrome DevTools MCP, Bash) either share the operator's browser (risky — agent can mess with tabs) or run invisibly (no observability). This runbook creates clean separation:

- **Agent browser**: isolated Chromium instance with remote debugging, separate profile
- **Operator browser**: clean Chromium with no debug port
- **Agent terminal**: named tmux session the agent drives via `send-keys`, visible to the operator

## Prerequisites

- Chromium (or Chrome) installed
- tmux installed
- A tiling window manager (Hyprland/Sway/i3) recommended for multi-monitor layout
- Chrome DevTools MCP or equivalent CDP-based agent tool

## Step 1: Remove Debug Port from Default Browser

The debug port should NOT be on the operator's daily browser.

```bash
# Check if debug port is in the global flags file
cat ~/.config/chromium-flags.conf

# Remove these lines if present:
#   --remote-debugging-port=9222
#   --remote-allow-origins=*
```

The remaining flags (Wayland, extensions, etc.) stay.

## Step 2: Create Agent Browser Desktop Entry

Create a `.desktop` file so the agent browser appears in your app launcher (Walker, Rofi, dmenu, etc.).

```bash
cat > ~/.local/share/applications/Chromium-Agent.desktop << 'EOF'
[Desktop Entry]
Version=1.0
Name=Chromium for Agents
GenericName=Agent Web Browser
Comment=Chromium with remote debugging for AI agent use
Exec=/usr/bin/chromium --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=%h/.config/chromium-agent --class=chromium-agent %U
StartupNotify=true
StartupWMClass=chromium-agent
Terminal=false
Icon=chromium
Type=Application
Categories=Network;WebBrowser;
EOF

chmod +x ~/.local/share/applications/Chromium-Agent.desktop
```

Key flags:
- `--remote-debugging-port=9222` — enables CDP for agent tools
- `--user-data-dir=%h/.config/chromium-agent` — isolated profile (cookies, sessions, history separate from operator)
- `--class=chromium-agent` — custom window class so the window manager can apply distinct rules (workspace assignment, border color, opacity)

## Step 3: Create Agent tmux Session

The agent drives a named tmux session. The operator attaches to watch.

```bash
# Agent creates the session
tmux new-session -d -s Pedro    # or any agent name

# Operator attaches in a visible terminal
tmux attach -t Pedro
```

The agent sends commands via:
```bash
tmux send-keys -t Pedro "echo hello" Enter
```

This does NOT steal focus from the operator's windows. The operator sees every command and its output in real time.

## Step 4: Launch Both Browsers

```bash
# Agent browser (with debug port)
setsid /usr/bin/chromium \
  --remote-debugging-port=9222 \
  --remote-allow-origins=* \
  --user-data-dir=$HOME/.config/chromium-agent \
  --class=chromium-agent &>/dev/null &

# Operator browser (clean, no debug port)
setsid /usr/bin/chromium &>/dev/null &
```

Or launch via app launcher — both "Chromium" and "Chromium for Agents" will appear.

## Step 5: Window Manager Placement (Hyprland Example)

Use the custom window class to auto-place the agent browser:

```conf
# In ~/.config/hypr/hyprland.conf or apps/*.conf
# Auto-send agent browser to a specific workspace
windowrule = workspace 3, class:chromium-agent

# Optional: distinct border color for agent browser
windowrule = bordercolor rgb(ff6600), class:chromium-agent
```

Move windows manually:
```bash
# Move agent browser to workspace 3 (e.g., portrait monitor)
hyprctl dispatch focuswindow "class:chromium-agent"
hyprctl dispatch movetoworkspace 3

# Move operator browser to workspace 2 (e.g., primary monitor)
hyprctl dispatch focuswindow "class:^(chromium)$"
hyprctl dispatch movetoworkspace 2
```

## Step 6: Auth the Agent Browser

The agent browser starts with a fresh profile — no saved logins. The operator needs to sign into services the agent will use:

- Gmail / Google accounts
- GitHub
- Jira
- GitLab
- Any other authenticated services

Sessions persist in `~/.config/chromium-agent/` across launches.

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Operator's Desktop                    │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │   Chromium        │  │  Chromium for     │            │
│  │   (personal)      │  │  Agents           │            │
│  │                   │  │                   │            │
│  │  No debug port    │  │  CDP port 9222    │            │
│  │  ~/.config/       │  │  ~/.config/       │            │
│  │    chromium/      │  │    chromium-agent/ │            │
│  │  class: chromium  │  │  class:            │            │
│  │                   │  │   chromium-agent   │            │
│  └──────────────────┘  └────────┬──────────┘            │
│                                  │                       │
│                          Chrome DevTools MCP             │
│                          (websocket, no focus steal)     │
│                                  │                       │
│  ┌──────────────────┐           │                       │
│  │  tmux: Pedro      │◄──── tmux send-keys              │
│  │  (visible to      │     (no focus steal)              │
│  │   operator)       │           │                       │
│  └──────────────────┘           │                       │
│                                  │                       │
│                          ┌──────┴──────┐                │
│                          │  AI Agent    │                │
│                          │  (Claude     │                │
│                          │   Code etc)  │                │
│                          └─────────────┘                │
└─────────────────────────────────────────────────────────┘
```

## Key Properties

| Property | Agent Browser | Agent Terminal | Operator Browser |
|---|---|---|---|
| Focus steal | No (CDP websocket) | No (tmux send-keys) | N/A |
| Profile isolation | Yes (separate user-data-dir) | Yes (separate tmux session) | Yes (default profile) |
| Observable by operator | Yes (visible window) | Yes (tmux attach) | N/A |
| Survives agent restart | Yes (persistent profile) | Yes (tmux persists) | N/A |
| Window manager targetable | Yes (custom class) | Yes (terminal class) | Yes (default class) |

## Troubleshooting

**Agent can't connect to browser**: Check `curl http://127.0.0.1:9222/json/version` — if it fails, the agent browser isn't running or the debug port is wrong.

**Both browsers look the same**: Use a different theme in the agent browser, or add a Hyprland border color rule on `class:chromium-agent`.

**tmux session doesn't exist**: Create it with `tmux new-session -d -s Pedro`. The agent can create it; the operator just needs to attach.

**Agent browser has no logins**: Expected on first launch — operator needs to authenticate once. Sessions persist in `~/.config/chromium-agent/`.
