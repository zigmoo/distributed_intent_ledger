#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  some_command | tee_task_execution_note.sh --task-id DIL-1334
  cat notes.md | tee_task_execution_note.sh --file /abs/path/task.md

Behavior:
  - Reads note content from stdin.
  - Echoes the exact same content to stdout.
  - Appends the same content into the task markdown Execution Notes section.

Required:
  One of:
    --task-id ID
    --file PATH

Options:
  --base PATH            Vault base path (default: auto-detected from script location)
  --timestamp ISO8601    Override timestamp
  -h, --help             Show this help
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TASK_ID=""
TASK_FILE=""
TS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --file) TASK_FILE="${2:-}"; shift 2 ;;
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --timestamp) TS="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" && -z "$TASK_FILE" ]]; then
  echo "ERROR: provide --task-id or --file" >&2
  usage
  exit 2
fi

if [[ -n "$TASK_ID" && -n "$TASK_FILE" ]]; then
  echo "ERROR: use only one of --task-id or --file" >&2
  exit 2
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"

if [[ ! -s "$tmp" ]]; then
  echo "ERROR: no stdin content" >&2
  exit 2
fi

cat "$tmp"

args=(--base "$DIL_BASE" --content-file "$tmp")
if [[ -n "$TASK_ID" ]]; then
  args+=(--task-id "$TASK_ID")
else
  args+=(--file "$TASK_FILE")
fi
if [[ -n "$TS" ]]; then
  args+=(--timestamp "$TS")
fi

"$DIL_BASE/_shared/scripts/append_task_execution_note.sh" "${args[@]}" >/dev/null
