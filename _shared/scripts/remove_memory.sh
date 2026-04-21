#!/usr/bin/env bash
set -euo pipefail

# remove_memory.sh
# Safely removes or retires DIL memory notes with audit logging and index cleanup.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-${CLAWVAULT_BASE:-}}")"
FILE_PATH=""
REASON=""
PERMANENT=0
RESTORE=0
PRUNE_TRASH=0
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  remove_memory.sh --file <path-relative-to-base> --reason "..." [options]

Required:
  --file PATH        Path to the memory note (relative to vault base)
  --reason TEXT      Explanation for removing the memory

Options:
  --permanent        Actually delete the file (default: move to _shared/_trash/)
  --restore          Restore a file from _shared/_trash/ to its original location
  --prune-trash      Permanently delete trash files older than 30 days
  --base PATH        Base vault path (default: BASE_DIL -> repo-relative -> $HOME/Documents/dil_agentic_memory_0001)
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
    --restore) RESTORE=1; shift ;;
    --prune-trash) PRUNE_TRASH=1; shift ;;
    --base) BASE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

# Validation
if [[ "$PRUNE_TRASH" -eq 1 ]]; then
  : # No file/reason needed for prune
elif [[ -z "$FILE_PATH" || ( -z "$REASON" && "$RESTORE" -eq 0 ) ]]; then
  echo "Error: --file and --reason are required." >&2
  usage
  exit 1
fi

FULL_PATH="$BASE/$FILE_PATH"
if [[ "$PRUNE_TRASH" -eq 0 && "$RESTORE" -eq 0 && ! -f "$FULL_PATH" ]]; then
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

# 1. Soft-Delete (Move to _trash/ with metadata)
retire_note() {
  local trash_dir="$BASE/_shared/_trash"
  local relative_dir
  relative_dir=$(dirname "$FILE_PATH")
  local trash_dest="$trash_dir/$relative_dir"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would move $FILE_PATH to _shared/_trash/$FILE_PATH"
    echo "Would update frontmatter: status: trashed"
  else
    mkdir -p "$trash_dest"
    # Update frontmatter before moving
    sed -i 's/^status: .*/status: trashed/' "$FULL_PATH"
    sed -i "s/^updated: .*/updated: $(date +%Y-%m-%d)/" "$FULL_PATH"
    echo -e "\n\n---\n**TRASHED**: $TIMESTAMP_VAL by $ASSISTANT\n**Reason**: $REASON\n**Original location**: $FILE_PATH" >> "$FULL_PATH"
    mv "$FULL_PATH" "$trash_dest/"
    echo "Moved to _shared/_trash/$FILE_PATH"
  fi
}

# 2. Hard-Delete
delete_note() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would permanently delete file: $FULL_PATH"
  else
    rm "$FULL_PATH"
  fi
}

# Restore a trashed file to its original location
restore_note() {
  local trash_path="$BASE/_shared/_trash/$FILE_PATH"
  if [[ ! -f "$trash_path" ]]; then
    echo "Error: File not found in trash at $trash_path" >&2
    exit 1
  fi
  local dest_dir
  dest_dir=$(dirname "$FULL_PATH")
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would restore $FILE_PATH from _shared/_trash/ to original location"
  else
    mkdir -p "$dest_dir"
    mv "$trash_path" "$FULL_PATH"
    sed -i 's/^status: trashed/status: active/' "$FULL_PATH"
    sed -i "s/^updated: .*/updated: $(date +%Y-%m-%d)/" "$FULL_PATH"
    echo "Restored $FILE_PATH to original location"
  fi
}

# Prune trash older than 30 days
prune_trash() {
  local trash_dir="$BASE/_shared/_trash"
  if [[ ! -d "$trash_dir" ]]; then
    echo "No trash directory found."
    return
  fi
  local count
  count=$(find "$trash_dir" -type f -mtime +30 2>/dev/null | wc -l)
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Would permanently delete $count files older than 30 days from _shared/_trash/"
  else
    find "$trash_dir" -type f -mtime +30 -delete 2>/dev/null
    find "$trash_dir" -type d -empty -delete 2>/dev/null
    echo "Pruned $count files older than 30 days from _shared/_trash/"
  fi
}

# 3. Index Cleanup
cleanup_index() {
  # Find nearest index file
  local current_dir=$(dirname "$FULL_PATH")
  local index_file=""
  
  # Search upwards for _meta/vault_index.md
  while [[ "$current_dir" != "$BASE" && "$current_dir" != "/" ]]; do
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
  
  while [[ "$current_dir" != "$BASE" && "$current_dir" != "/" ]]; do
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
if [[ "$PRUNE_TRASH" -eq 1 ]]; then
  prune_trash
elif [[ "$RESTORE" -eq 1 ]]; then
  if [[ -z "$FILE_PATH" ]]; then
    echo "Error: --file is required with --restore." >&2
    exit 1
  fi
  restore_note
elif [[ "$PERMANENT" -eq 1 ]]; then
  echo "Performing permanent deletion for $FILE_PATH..."
  cleanup_index
  log_action
  delete_note
else
  echo "Moving memory note $FILE_PATH to _shared/_trash/..."
  cleanup_index
  log_action
  retire_note
fi

echo "Done."
