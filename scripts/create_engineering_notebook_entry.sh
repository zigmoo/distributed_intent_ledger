#!/usr/bin/env bash
set -euo pipefail

BASE="${DIL_BASE:-/home/moo/Documents/dil_agentic_memory_0001}"
TARGET_DIR="$BASE/_shared/engineering-notebook"
INDEX_FILE="$BASE/_shared/_meta/vault_index.md"

TITLE=""
PROJECT=""
SUMMARY=""
CONTEXT=""
FINDINGS=""
EVIDENCE=""
INTERPRETATION=""
FOLLOW_UP=""
OPEN_QUESTIONS=""
ENTRY_TYPE="reference"
SOURCE="internal"
DOMAIN="operations"
STATUS="active"
OWNER="shared"
PRIORITY="notable"
TAGS=""
CONTENT_FILE=""
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  create_engineering_notebook_entry.sh \
    --title "Title" \
    --project openclaw \
    --summary "One-line summary" \
    --findings "Bullet-ready finding" \
    --evidence "What evidence supports it"

Required:
  --title TEXT            Human-readable title
  --project TEXT          Project slug or shared topic
  --summary TEXT          One-line summary for quick scanning
  --findings TEXT         Core finding(s); use literal newlines for multiple bullets
  --evidence TEXT         Evidence basis; file/timestamp/user-confirmed/etc.

Options:
  --context TEXT          Problem/setup context
  --interpretation TEXT   Meaning or conclusion drawn from the evidence
  --follow-up TEXT        Concrete next actions or maintenance notes
  --open-questions TEXT   Outstanding unknowns
  --entry-type TEXT       reference|chronology|incident|pattern|investigation (default: reference)
  --source TEXT           internal|user-directive|external (default: internal)
  --domain TEXT           Default: operations
  --status TEXT           active|archived|superseded (default: active)
  --owner TEXT            Default: shared
  --priority TEXT         low|normal|notable|high (default: notable)
  --tags CSV              Extra tags, comma-separated
  --content-file PATH     Optional markdown file appended after standard sections
  --dry-run               Print output path and preview without writing
  -h, --help              Show this help

Contract:
  - Writes to _shared/engineering-notebook/
  - Enforces standard sections:
      Summary, Context, Findings, Evidence, Interpretation, Open Questions, Follow-up
  - Appends an entry to _shared/_meta/vault_index.md
USAGE
}

slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9._-]/-/g' \
    | sed 's/-\{2,\}/-/g' \
    | sed 's/^-//; s/-$//'
}

expand_escapes() {
  printf '%b' "$1"
}

require_nonempty() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "ERROR: $name is required" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title) TITLE="${2:-}"; shift 2 ;;
    --project) PROJECT="${2:-}"; shift 2 ;;
    --summary) SUMMARY="${2:-}"; shift 2 ;;
    --context) CONTEXT="${2:-}"; shift 2 ;;
    --findings) FINDINGS="${2:-}"; shift 2 ;;
    --evidence) EVIDENCE="${2:-}"; shift 2 ;;
    --interpretation) INTERPRETATION="${2:-}"; shift 2 ;;
    --follow-up) FOLLOW_UP="${2:-}"; shift 2 ;;
    --open-questions) OPEN_QUESTIONS="${2:-}"; shift 2 ;;
    --entry-type) ENTRY_TYPE="${2:-}"; shift 2 ;;
    --source) SOURCE="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --status) STATUS="${2:-}"; shift 2 ;;
    --owner) OWNER="${2:-}"; shift 2 ;;
    --priority) PRIORITY="${2:-}"; shift 2 ;;
    --tags) TAGS="${2:-}"; shift 2 ;;
    --content-file) CONTENT_FILE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

require_nonempty "--title" "$TITLE"
require_nonempty "--project" "$PROJECT"
require_nonempty "--summary" "$SUMMARY"
require_nonempty "--findings" "$FINDINGS"
require_nonempty "--evidence" "$EVIDENCE"

SUMMARY="$(expand_escapes "$SUMMARY")"
CONTEXT="$(expand_escapes "$CONTEXT")"
FINDINGS="$(expand_escapes "$FINDINGS")"
EVIDENCE="$(expand_escapes "$EVIDENCE")"
INTERPRETATION="$(expand_escapes "$INTERPRETATION")"
FOLLOW_UP="$(expand_escapes "$FOLLOW_UP")"
OPEN_QUESTIONS="$(expand_escapes "$OPEN_QUESTIONS")"

case "$ENTRY_TYPE" in
  reference|chronology|incident|pattern|investigation) ;;
  *)
    echo "ERROR: --entry-type must be one of reference|chronology|incident|pattern|investigation" >&2
    exit 2
    ;;
esac

case "$SOURCE" in
  internal|user-directive|external) ;;
  *)
    echo "ERROR: --source must be one of internal|user-directive|external" >&2
    exit 2
    ;;
esac

case "$STATUS" in
  active|archived|superseded) ;;
  *)
    echo "ERROR: --status must be one of active|archived|superseded" >&2
    exit 2
    ;;
esac

case "$PRIORITY" in
  low|normal|notable|high) ;;
  *)
    echo "ERROR: --priority must be one of low|normal|notable|high" >&2
    exit 2
    ;;
esac

DATE_VAL="$(date +%Y-%m-%d)"
TIMESTAMP_VAL="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TITLE_SLUG="$(slugify "$TITLE")"
FILE_BASENAME="${TITLE_SLUG}-${DATE_VAL}.md"
FILE_PATH="$TARGET_DIR/$FILE_BASENAME"

if [[ -f "$FILE_PATH" ]]; then
  echo "ERROR: target file already exists: $FILE_PATH" >&2
  exit 2
fi

EXTRA_TAGS=""
if [[ -n "$TAGS" ]]; then
  EXTRA_TAGS=", $TAGS"
fi

EXTRA_CONTENT=""
if [[ -n "$CONTENT_FILE" ]]; then
  if [[ ! -f "$CONTENT_FILE" ]]; then
    echo "ERROR: content file not found: $CONTENT_FILE" >&2
    exit 2
  fi
  EXTRA_CONTENT="$(cat "$CONTENT_FILE")"
fi

NOTE_CONTENT=$(cat <<EOF
---
title: "$TITLE"
date: $DATE_VAL
machine: shared
assistant: shared
category: reference
memoryType: note
priority: $PRIORITY
tags: [engineering-notebook, $ENTRY_TYPE, $PROJECT$EXTRA_TAGS]
updated: $DATE_VAL
source: $SOURCE
domain: $DOMAIN
project: $PROJECT
status: $STATUS
owner: $OWNER
due:
entry_type: $ENTRY_TYPE
summary: "$SUMMARY"
---

# $TITLE

## Summary
$SUMMARY

## Context
${CONTEXT:--}

## Findings
$FINDINGS

## Evidence
$EVIDENCE

## Interpretation
${INTERPRETATION:--}

## Open Questions
${OPEN_QUESTIONS:--}

## Follow-up
${FOLLOW_UP:--}
EOF
)

if [[ -n "$EXTRA_CONTENT" ]]; then
  NOTE_CONTENT+=$'\n\n'"## Appendix"$'\n'"$EXTRA_CONTENT"$'\n'
fi

INDEX_ENTRY="| _shared/engineering-notebook/$FILE_BASENAME | $TITLE | shared |"

if (( DRY_RUN == 1 )); then
  printf 'Target: %s\n\n' "$FILE_PATH"
  printf '%s\n\n' "$NOTE_CONTENT"
  printf 'Index entry: %s\n' "$INDEX_ENTRY"
  exit 0
fi

mkdir -p "$TARGET_DIR"
printf '%s\n' "$NOTE_CONTENT" > "$FILE_PATH"
printf '%s\n' "$INDEX_ENTRY" >> "$INDEX_FILE"

printf 'Created engineering notebook entry: %s\n' "$FILE_PATH"
printf 'Indexed in: %s\n' "$INDEX_FILE"
