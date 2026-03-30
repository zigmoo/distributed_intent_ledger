#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  append_task_execution_note.sh --task-id DIL-1334 [--content-file note.md] [options]
  echo "note text" | append_task_execution_note.sh --task-id DIL-1334
  append_task_execution_note.sh --file /abs/path/to/task.md --content-file note.md

Required:
  One of:
    --task-id ID         Task id, e.g. DIL-1334
    --file PATH          Explicit task markdown path

Options:
  --content-file PATH    Read note content from file (default: stdin)
  --base PATH            Vault base path (default: auto-detected from script location)
  --timestamp ISO8601    Override timestamp (default: current UTC)
  --dry-run              Print output preview only
  -h, --help             Show this help
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
TASK_ID=""
TASK_FILE=""
CONTENT_FILE=""
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --file) TASK_FILE="${2:-}"; shift 2 ;;
    --content-file) CONTENT_FILE="${2:-}"; shift 2 ;;
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --timestamp) TS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
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

if [[ -n "$TASK_ID" ]]; then
  TASK_FILE="$DIL_BASE/_shared/tasks/personal/${TASK_ID}.md"
fi

if [[ ! -f "$TASK_FILE" ]]; then
  echo "ERROR: task file not found: $TASK_FILE" >&2
  exit 2
fi

tmp_content="$(mktemp)"
tmp_block="$(mktemp)"
tmp_out="$(mktemp)"
trap 'rm -f "$tmp_content" "$tmp_block" "$tmp_out"' EXIT

if [[ -n "$CONTENT_FILE" ]]; then
  cat "$CONTENT_FILE" > "$tmp_content"
else
  cat > "$tmp_content"
fi

if [[ ! -s "$tmp_content" ]]; then
  echo "ERROR: no content provided" >&2
  exit 2
fi

{
  echo "- ${TS} Execution detail:"
  sed 's/^/  /' "$tmp_content"
} > "$tmp_block"

awk -v block_file="$tmp_block" '
BEGIN {
  in_exec = 0;
  inserted = 0;
  block = "";
  while ((getline line < block_file) > 0) {
    block = block line "\n";
  }
  close(block_file);
}
{
  if ($0 ~ /^## Execution Notes[[:space:]]*$/) {
    in_exec = 1;
    print;
    next;
  }

  if (in_exec && !inserted && $0 ~ /^## /) {
    print "";
    printf "%s", block;
    print "";
    inserted = 1;
    in_exec = 0;
  }

  print;
}
END {
  if (!inserted) {
    if (!in_exec) {
      print "";
      print "## Execution Notes";
    }
    print "";
    printf "%s", block;
  }
}
' "$TASK_FILE" > "$tmp_out"

if (( DRY_RUN == 1 )); then
  cat "$tmp_out"
  exit 0
fi

cp "$tmp_out" "$TASK_FILE"
echo "Appended execution note to: $TASK_FILE"
