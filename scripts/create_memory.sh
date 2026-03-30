#!/usr/bin/env bash
set -euo pipefail

# create_memory.sh
# Automates the creation of ClawVault memory notes with schema compliance and indexing.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TYPE=""
CATEGORY=""
TITLE=""
TAGS=""
MACHINE=""
ASSISTANT=""
CONTENT_FILE=""
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  create_memory.sh --type reference --title "My Note" --content-file body.md [options]
  echo "content" | create_memory.sh --type observation --title "An Observation" [options]

Required:
  --type TEXT          Memory type (e.g., reference, observation, decision, preference)
  --title TEXT         Title of the note

Options:
  --category TEXT      Category folder (default: based on type or 'general')
  --tags CSV           Comma-separated tags
  --machine TEXT       Target machine scope (default: derived from hostname)
  --assistant TEXT     Target assistant scope (default: derived from env/process)
  --content-file PATH  File containing the note body (if omitted, reads from stdin)
  --base PATH          Base vault path (default: auto-detected from script location)
  --dry-run            Print actions without executing
  -h, --help           Show this help
USAGE
}

trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

resolve_identity() {
  # 1. Machine
  if [[ -z "$MACHINE" ]]; then
    MACHINE=$(hostname -s | tr '[:upper:]' '[:lower:]')
  fi
  
  # 2. Assistant
  if [[ -z "$ASSISTANT" ]]; then
    # Try env vars first
    ASSISTANT="${ASSISTANT_ID:-${AGENT_NAME:-${AGENT_ID:-}}}"
    
    # Fallback to process name
    if [[ -z "$ASSISTANT" ]]; then
      ASSISTANT=$(ps -p "$PPID" -o comm= | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')
    fi
    
    # Apply aliases (hardcoded common ones for now, could be externalized)
    case "$ASSISTANT" in
      kilo|kilocode) ASSISTANT="opencode" ;;
      cc) ASSISTANT="claude-code" ;;
      bash|sh|zsh)
        # Smart fallback for interactive shells
        if [[ "$MACHINE" == "framemoowork" && "$USER" == "moo" ]]; then
           ASSISTANT="mainthread"
        fi
        ;;
    esac
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --type) TYPE="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    --category) CATEGORY="${2:-}"; shift 2 ;;
    --tags) TAGS="${2:-}"; shift 2 ;;
    --machine) MACHINE="${2:-}"; shift 2 ;;
    --assistant) ASSISTANT="${2:-}"; shift 2 ;;
    --content-file) CONTENT_FILE="${2:-}"; shift 2 ;;
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

# Validation
if [[ -z "$TYPE" || -z "$TITLE" ]]; then
  echo "Error: --type and --title are required." >&2
  usage
  exit 1
fi

resolve_identity

if [[ -z "$MACHINE" || -z "$ASSISTANT" ]]; then
  echo "Error: Could not resolve identity (MACHINE=$MACHINE, ASSISTANT=$ASSISTANT)." >&2
  exit 1
fi

# Determine Scope Paths
SCOPE_DIR="$DIL_BASE/$MACHINE/$ASSISTANT"
if [[ ! -d "$SCOPE_DIR" ]]; then
  echo "Error: Assistant scope directory not found: $SCOPE_DIR" >&2
  exit 1
fi

# Determine Category/Folder
if [[ -z "$CATEGORY" ]]; then
  # Auto-map type to category folder if it matches standard folder names
  case "$TYPE" in
    decision|preference|project|commitment|lesson|handoff|observation|people) CATEGORY="${TYPE}s" ;; # Pluralize standard types
    reference|system) CATEGORY="system" ;;
    *) CATEGORY="general" ;;
  esac
fi

TARGET_DIR="$SCOPE_DIR/$CATEGORY"
if [[ ! -d "$TARGET_DIR" ]]; then
    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$TARGET_DIR"
    else
        echo "Would create directory: $TARGET_DIR"
    fi
fi

# Generate Filename
DATE_SLUG=$(date +%Y-%m-%d)
TITLE_SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g' | sed 's/-\{2,\}/-/g' | sed 's/^-//;s/-$//')
FILENAME="${TITLE_SLUG}.md"
FILE_PATH="$TARGET_DIR/$FILENAME"

if [[ -f "$FILE_PATH" ]]; then
  # If it exists, check content or just append timestamp for uniqueness
  # For safety, append timestamp
  FILENAME="${TITLE_SLUG}-${DATE_SLUG}.md"
  FILE_PATH="$TARGET_DIR/$FILENAME"
fi

# Timestamps
DATE_VAL=$(date +%Y-%m-%d)
TIMESTAMP_VAL=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# Prepare Content
BODY=""
if [[ -n "$CONTENT_FILE" ]]; then
  if [[ -f "$CONTENT_FILE" ]]; then
    BODY=$(cat "$CONTENT_FILE")
  else
    echo "Error: Content file not found: $CONTENT_FILE" >&2
    exit 1
  fi
else
  # Read from stdin if no file provided
  if [ ! -t 0 ]; then
    BODY=$(cat)
  fi
fi

# Format Tags
TAG_LIST="[clawvault, $TYPE"
if [[ -n "$TAGS" ]]; then
  TAG_LIST="$TAG_LIST, $TAGS"
fi
TAG_LIST="$TAG_LIST]"

# Construct Note Content
NOTE_CONTENT="---
title: \"$TITLE\"
date: $DATE_VAL
machine: $MACHINE
assistant: $ASSISTANT
category: $CATEGORY
memoryType: $TYPE
priority: normal
tags: $TAG_LIST
updated: $DATE_VAL
source: internal
domain: operations
project: clawvault
status: active
owner: $ASSISTANT
due:
---

# $TITLE

$BODY
"

# Construct Index Entry
REL_PATH="$MACHINE/$ASSISTANT/$CATEGORY/$FILENAME"
INDEX_ENTRY="| $REL_PATH | $TITLE |"

# Construct Change Log Entry
CHANGE_LOG_ENTRY="| $TIMESTAMP_VAL | $ASSISTANT | auto-script | $REL_PATH | create | create memory via script |"

# Execution
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "--- DRY RUN ---"
  echo "Target: $FILE_PATH"
  echo "Content:"
  echo "$NOTE_CONTENT" | head -n 10
  echo "..."
  echo "Index Entry: $INDEX_ENTRY"
  echo "Change Log: $CHANGE_LOG_ENTRY"
  exit 0
fi

# Write File
echo "$NOTE_CONTENT" > "$FILE_PATH"

# Update Index
INDEX_FILE="$SCOPE_DIR/_meta/vault_index.md"
if [[ -f "$INDEX_FILE" ]]; then
  echo "$INDEX_ENTRY" >> "$INDEX_FILE"
else
  echo "Warning: Index file not found at $INDEX_FILE. Skipping index update." >&2
fi

# Update Change Log
CHANGE_LOG_FILE="$SCOPE_DIR/handoffs/change_log.md"
if [[ -f "$CHANGE_LOG_FILE" ]]; then
  echo "$CHANGE_LOG_ENTRY" >> "$CHANGE_LOG_FILE"
else
  echo "Warning: Change log not found at $CHANGE_LOG_FILE. Skipping log update." >&2
fi

echo "Memory created: $FILE_PATH"
