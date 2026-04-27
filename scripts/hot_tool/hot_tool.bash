#!/usr/bin/env bash
set -euo pipefail
# hot_tool — Read, write, and manage _shared/_hot.md session continuity file
#
# Subcommands:
#   read          Print current _hot.md contents
#   write         Overwrite _hot.md from stdin or --file
#   append        Add a section to _hot.md without overwriting
#   clear         Reset _hot.md to empty template
#   status        One-line summary (last updated, agent, machine)
#
# Usage:
#   hot_tool read
#   hot_tool status
#   hot_tool write --agent claude-code --machine framemoowork --model claude-opus-4-6 --file /tmp/session_state.md
#   hot_tool write --agent claude-code --machine framemoowork --model claude-opus-4-6 <<< "session notes here"
#   hot_tool append --section "Pending Responses" --content "| Vijay | TAC_801 | DBR-27106 | Tonight |"
#   hot_tool clear
#
# DMDI-12406

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
HOT_FILE="$BASE/_shared/_hot.md"

AGENT="${AGENT_NAME:-${AGENT_ID:-${ASSISTANT_ID:-}}}"
MACHINE="$(hostname -s | tr '[:upper:]' '[:lower:]')"
MODEL=""
INPUT_FILE=""
SECTION=""
CONTENT=""
TIMESTAMP_VAL="$(date +%Y%m%d_%H%M%S)"

# Logging — _hot.md is _shared-level (not domain-specific), so logs go to _shared/logs/
LOG_DIR="$BASE/_shared/logs/hot_tool"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/hot_tool.${TIMESTAMP_VAL}.log"

hot_log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG_FILE"
}

usage() {
    cat <<'EOF'
hot_tool — Read, write, and manage _shared/_hot.md session continuity

Usage:
  hot_tool read                        Print current _hot.md
  hot_tool status                      One-line summary
  hot_tool write [OPTIONS]             Overwrite _hot.md (reads body from stdin or --file)
  hot_tool append --section NAME       Add content to a section
  hot_tool clear                       Reset to empty template

Write options:
  --agent NAME       Agent name (claude-code, opencode, codex, etc.)
  --machine NAME     Machine hostname (default: current hostname)
  --model ID         Model ID (claude-opus-4-6, gpt-5, etc.)
  --file PATH        Read body from file instead of stdin

Append options:
  --section NAME     Section header to append under (e.g. "Pending Responses")
  --content TEXT     Content to append

Examples:
  hot_tool read
  hot_tool status
  hot_tool write --agent claude-code --model claude-opus-4-6 < session_notes.md
  hot_tool append --section "Next Immediate Actions" --content "6. Check email"
  hot_tool clear

EOF
    exit 0
}

cmd_read() {
    hot_log "read | $HOT_FILE"
    if [[ -f "$HOT_FILE" ]]; then
        cat "$HOT_FILE"
    else
        echo "No _hot.md found at $HOT_FILE"
        exit 1
    fi
}

cmd_status() {
    hot_log "status | $HOT_FILE"
    if [[ ! -f "$HOT_FILE" ]]; then
        echo "NO_HOT | no _hot.md found"
        exit 1
    fi
    local updated agent machine model
    updated=$(grep '^updated:' "$HOT_FILE" | head -1 | sed 's/^updated: *//')
    agent=$(grep '^session_agent:' "$HOT_FILE" | head -1 | sed 's/^session_agent: *//')
    machine=$(grep '^session_machine:' "$HOT_FILE" | head -1 | sed 's/^session_machine: *//')
    model=$(grep '^session_model:' "$HOT_FILE" | head -1 | sed 's/^session_model: *//')
    echo "$updated | $agent | $machine | $model"
}

cmd_write() {
    local body=""
    if [[ -n "$INPUT_FILE" ]]; then
        if [[ ! -f "$INPUT_FILE" ]]; then
            echo "Error: File not found: $INPUT_FILE" >&2
            exit 1
        fi
        body=$(cat "$INPUT_FILE")
    elif [[ ! -t 0 ]]; then
        body=$(cat)
    else
        echo "Error: Provide body via stdin or --file" >&2
        exit 1
    fi

    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    cat > "$HOT_FILE" << HOTEOF
---
title: Session Hot State
updated: $timestamp
session_agent: ${AGENT:-unknown}
session_machine: $MACHINE
session_model: ${MODEL:-unknown}
---

# Hot State — Last Session End

$body
HOTEOF
    hot_log "write | $timestamp | agent=$AGENT | machine=$MACHINE | model=$MODEL"
    echo "OK | _hot.md updated | $timestamp | $AGENT | $MACHINE"
}

cmd_append() {
    if [[ -z "$SECTION" ]]; then
        echo "Error: --section is required for append" >&2
        exit 1
    fi
    if [[ -z "$CONTENT" ]]; then
        echo "Error: --content is required for append" >&2
        exit 1
    fi
    if [[ ! -f "$HOT_FILE" ]]; then
        echo "Error: No _hot.md to append to" >&2
        exit 1
    fi

    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    # Update the timestamp in frontmatter
    sed -i "s/^updated: .*/updated: $timestamp/" "$HOT_FILE"

    # Append content after the section header
    if grep -q "## $SECTION" "$HOT_FILE"; then
        sed -i "/## $SECTION/a\\$CONTENT" "$HOT_FILE"
    else
        echo -e "\n## $SECTION\n\n$CONTENT" >> "$HOT_FILE"
    fi
    hot_log "append | section=$SECTION | $timestamp"
    echo "OK | appended to '$SECTION' | $timestamp"
}

cmd_clear() {
    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    cat > "$HOT_FILE" << HOTEOF
---
title: Session Hot State
updated: $timestamp
session_agent: ${AGENT:-}
session_machine: $MACHINE
session_model: ${MODEL:-}
---

# Hot State — Last Session End

## What We Were Doing

(No active session state)

## Next Immediate Actions

1. (Start here)

## Pending Responses

| From | What | Ticket | Expected |
|------|------|--------|----------|
HOTEOF
    hot_log "clear | $timestamp"
    echo "OK | _hot.md cleared | $timestamp"
}

# --- Argument Parsing ---

if [[ $# -lt 1 ]]; then
    usage
fi

SUBCOMMAND="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent) AGENT="$2"; shift 2 ;;
        --machine) MACHINE="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --file) INPUT_FILE="$2"; shift 2 ;;
        --section) SECTION="$2"; shift 2 ;;
        --content) CONTENT="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

case "$SUBCOMMAND" in
    read) cmd_read ;;
    status) cmd_status ;;
    write) cmd_write ;;
    append) cmd_append ;;
    clear) cmd_clear ;;
    -h|--help) usage ;;
    *) echo "Unknown subcommand: $SUBCOMMAND" >&2; usage ;;
esac
