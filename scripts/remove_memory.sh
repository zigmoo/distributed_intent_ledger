#!/usr/bin/env bash
set -euo pipefail

# remove_memory.sh
# Safely removes or retires DIL memory notes with audit logging and index cleanup.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FILE_PATH=""
REASON=""
PERMANENT=0
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  remove_memory.sh --file <path-relative-to-base> --reason "..." [options]

Required:
  --file PATH        Path to the memory note (relative to vault base)
  --reason TEXT      Explanation for removing the memory

Options:
  --permanent        Actually delete the file (default: soft-delete/retire)
  --base PATH        Base vault path (default: auto-detected from script location)
  --dry-run          Print actions without executing
  -h, --help         Show this help
USAGE
}

trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE_PATH="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --permanent) PERMANENT=1; shift ;;
    --base) DIL_BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

# Validation
if [[ -z "$FILE_PATH" || -z "$REASON" ]]; then
  echo "Error: --file and --reason are required." >&2
  usage
  exit 1
fi

FULL_PATH="$DIL_BASE/$FILE_PATH"
if [[ ! -f "$FULL_PATH" ]]; then
  echo "Error: File not found at $FULL_PATH" >&2
  exit 1
fi

# Resolve Identity (Assistant/Machine)
MACHINE=$(hostname -s | tr '[:upper:]' '[:lower:]')
ASSISTANT="${ASSISTANT_ID:-${AGENT_NAME:-${AGENT_ID:-}}}"
if [[ -z "$ASSISTANT" ]]; then
  ASSISTANT=$(ps -p "$PPID" -o comm= | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9._-]/-/g')
fi

# Timestamp
TIMESTAMP_VAL=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 1. Soft-Delete (Retire)
retire_note() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would update $FILE_PATH: status: retired, memoryType: retired"
  else
    # Use sed to update frontmatter
    sed -i 's/^status: .*/status: retired/' "$FULL_PATH"
    sed -i "s/^updated: .*/updated: $(date +%Y-%m-%d)/" "$FULL_PATH"
    # Append retirement note to body
    echo -e "\n\n---\n**RETIRED**: $TIMESTAMP_VAL by $ASSISTANT\n**Reason**: $REASON" >> "$FULL_PATH"
  fi
}

# 2. Hard-Delete
delete_note() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would delete file: $FULL_PATH"
  else
    rm "$FULL_PATH"
  fi
}

# 3. Index Cleanup
cleanup_index() {
  # Find nearest index file
  local current_dir=$(dirname "$FULL_PATH")
  local index_file=""
  
  # Search upwards for _meta/vault_index.md
  while [[ "$current_dir" != "$DIL_BASE" && "$current_dir" != "/" ]]; do
    if [[ -f "$current_dir/_meta/vault_index.md" ]]; then
      index_file="$current_dir/_meta/vault_index.md"
      break
    fi
    current_dir=$(dirname "$current_dir")
  done

  if [[ -n "$index_file" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "Would remove entry for $FILE_PATH from $index_file"
    else
      # Remove the line matching the relative path
      # We need to escape the path for sed
      local escaped_path=$(echo "$FILE_PATH" | sed 's/\//\\\//g')
      sed -i "/| $escaped_path |/d" "$index_file"
    fi
  else
    echo "Warning: No index file found for $FILE_PATH." >&2
  fi
}

# 4. Audit Log Update
log_action() {
  # Find nearest change_log.md
  local current_dir=$(dirname "$FULL_PATH")
  local log_file=""
  
  while [[ "$current_dir" != "$DIL_BASE" && "$current_dir" != "/" ]]; do
    if [[ -f "$current_dir/handoffs/change_log.md" ]]; then
      log_file="$current_dir/handoffs/change_log.md"
      break
    fi
    current_dir=$(dirname "$current_dir")
  done

  if [[ -n "$log_file" ]]; then
    local action="retire"
    [[ "$PERMANENT" -eq 1 ]] && action="delete"
    local log_entry="| $TIMESTAMP_VAL | $ASSISTANT | auto-script | $FILE_PATH | $action | $REASON |"
    
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "Would log to $log_file: $log_entry"
    else
      echo "$log_entry" >> "$log_file"
    fi
  fi
}

# --- Execution ---
if [[ "$PERMANENT" -eq 1 ]]; then
  echo "Performing permanent deletion for $FILE_PATH..."
  cleanup_index
  log_action
  delete_note
else
  echo "Retiring memory note $FILE_PATH..."
  cleanup_index
  log_action
  retire_note
fi

echo "Done."
