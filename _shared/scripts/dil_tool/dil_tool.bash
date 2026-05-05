#!/usr/bin/env bash
set -euo pipefail

# dil_tool — DIL management CLI
# Subcommands:
#   base_setup    Create/verify agent config symlinks from the manifest
#   status        Health check (symlinks, index drift, unmirrored tasks)

SCRIPT_NAME="dil_tool"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
AGENTS_DIR="${BASE}/_shared/agents"
MANIFEST="${AGENTS_DIR}/symlink_manifest.conf"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="${BASE}/_shared/logs/${SCRIPT_NAME}"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/${SCRIPT_NAME}.${1:-help}.${TIMESTAMP}.log"

# --- Logging ---
dil_log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" >> "$LOG_FILE"
}

dil_log_and_echo() {
    local msg="$*"
    echo "$msg"
    dil_log "$msg"
}

# --- Expand ~ in paths ---
expand_path() {
    local p="$1"
    if [[ "$p" == "~/"* ]]; then
        p="${HOME}/${p#\~/}"
    elif [[ "$p" == "~" ]]; then
        p="$HOME"
    fi
    echo "$p"
}

# --- base_setup ---
cmd_base_setup() {
    local dry_run=false
    local force=false
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) dry_run=true; shift ;;
            --force) force=true; shift ;;
            -h|--help)
                echo "Usage: dil_tool base_setup [--dry-run] [--force]"
                echo "  Creates symlinks from agent platform config locations to DIL vault."
                echo "  --dry-run   Show what would be done without making changes"
                echo "  --force     Replace existing files (not symlinks) with symlinks"
                return 0
                ;;
            *) echo "Unknown option: $1" >&2; return 1 ;;
        esac
    done

    if [[ ! -f "$MANIFEST" ]]; then
        echo "ERROR: Manifest not found: $MANIFEST" >&2
        return 1
    fi

    dil_log "=== base_setup started ==="
    dil_log "Host: $(hostname -s | tr '[:upper:]' '[:lower:]')"
    dil_log "User: $(whoami)"
    dil_log "Dry run: $dry_run"
    dil_log "Force: $force"

    local created=0 skipped=0 updated=0 errors=0

    # Helper: process a single source->target symlink pair
    _process_link() {
        local src_abs="$1" src_label="$2" target="$3"

        # Ensure target parent directory exists
        local target_dir
        target_dir=$(dirname "$target")
        if [[ ! -d "$target_dir" ]]; then
            if [[ "$dry_run" == true ]]; then
                dil_log_and_echo "DRY  | mkdir -p $target_dir"
            else
                mkdir -p "$target_dir"
                dil_log "Created directory: $target_dir"
            fi
        fi

        # Check current state of target
        if [[ -L "$target" ]]; then
            local current_target expected_target
            current_target=$(readlink -f "$target")
            expected_target=$(readlink -f "$src_abs")
            if [[ "$current_target" == "$expected_target" ]]; then
                dil_log_and_echo "OK   | $target -> $src_label (already correct)"
                skipped=$((skipped + 1))
                return
            else
                if [[ "$dry_run" == true ]]; then
                    dil_log_and_echo "DRY  | $target -> $src_label (would update from: $(readlink "$target"))"
                else
                    ln -sf "$src_abs" "$target"
                    dil_log_and_echo "UPD  | $target -> $src_label (was: $(readlink "$target" 2>/dev/null || echo 'broken'))"
                    updated=$((updated + 1))
                fi
            fi
        elif [[ -e "$target" ]]; then
            if [[ "$force" == true ]]; then
                if [[ "$dry_run" == true ]]; then
                    dil_log_and_echo "DRY  | $target -> $src_label (would replace existing file, --force)"
                else
                    local backup="${target}.bak.${TIMESTAMP}"
                    cp "$target" "$backup"
                    dil_log_and_echo "BAK  | $target backed up to $backup"
                    ln -sf "$src_abs" "$target"
                    dil_log_and_echo "UPD  | $target -> $src_label (replaced existing file)"
                    updated=$((updated + 1))
                fi
            else
                dil_log_and_echo "SKIP | $target exists as regular file (use --force to replace)"
                skipped=$((skipped + 1))
            fi
        else
            if [[ "$dry_run" == true ]]; then
                dil_log_and_echo "DRY  | $target -> $src_label (would create)"
            else
                ln -s "$src_abs" "$target"
                dil_log_and_echo "NEW  | $target -> $src_label"
                created=$((created + 1))
            fi
        fi
    }

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip comments and blank lines
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

        # Parse: source_file  target_path
        local src_rel target_raw
        src_rel=$(echo "$line" | awk '{print $1}')
        target_raw=$(echo "$line" | awk '{print $2}')

        if [[ -z "$src_rel" || -z "$target_raw" ]]; then
            dil_log "WARN: Skipping malformed line: $line"
            continue
        fi

        # Handle glob: prefix — expand target pattern to multiple directories
        if [[ "$src_rel" == glob:* ]]; then
            local actual_src="${src_rel#glob:}"
            local src_abs="${AGENTS_DIR}/${actual_src}"
            if [[ ! -f "$src_abs" ]]; then
                dil_log_and_echo "WARN | $actual_src | Source file not found: $src_abs (skipping)"
                skipped=$((skipped + 1))
                continue
            fi
            local target_pattern
            target_pattern=$(expand_path "$target_raw")
            local target_filename
            target_filename=$(basename "$target_pattern")
            local dir_pattern
            dir_pattern=$(dirname "$target_pattern")
            # Expand the glob pattern to find matching directories
            local found_dirs=0
            for expanded_dir in $dir_pattern; do
                [[ -d "$expanded_dir" ]] || continue
                found_dirs=$((found_dirs + 1))
                _process_link "$src_abs" "$actual_src" "${expanded_dir}/${target_filename}"
            done
            if [[ $found_dirs -eq 0 ]]; then
                dil_log_and_echo "WARN | $actual_src | No directories matched pattern: $dir_pattern"
            fi
            continue
        fi

        local src_abs="${AGENTS_DIR}/${src_rel}"
        local target
        target=$(expand_path "$target_raw")

        # Verify source exists
        if [[ ! -f "$src_abs" ]]; then
            dil_log_and_echo "WARN | $src_rel | Source file not found: $src_abs (skipping)"
            skipped=$((skipped + 1))
            continue
        fi

        _process_link "$src_abs" "$src_rel" "$target"
    done < "$MANIFEST"

    echo "---"
    dil_log_and_echo "Summary: created=$created updated=$updated skipped=$skipped errors=$errors"
    dil_log "=== base_setup finished ==="
}

# --- status ---
cmd_status() {
    echo "=== DIL Health Check ==="
    echo ""

    # 1. Check symlinks from manifest
    echo "-- Agent Config Symlinks --"
    if [[ -f "$MANIFEST" ]]; then
        while IFS= read -r line; do
            [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
            local src_rel target_raw
            src_rel=$(echo "$line" | awk '{print $1}')
            target_raw=$(echo "$line" | awk '{print $2}')
            [[ -z "$src_rel" || -z "$target_raw" ]] && continue

            # Helper to check one symlink
            _check_link() {
                local src_abs="$1" label="$2" target="$3"
                if [[ -L "$target" ]]; then
                    local current expected
                    current=$(readlink -f "$target")
                    expected=$(readlink -f "$src_abs")
                    if [[ "$current" == "$expected" ]]; then
                        echo "OK   | $target -> $label"
                    else
                        echo "WARN | $target -> wrong target ($(readlink "$target"))"
                    fi
                elif [[ -e "$target" ]]; then
                    echo "WARN | $target exists but is NOT a symlink (run: dil_tool base_setup --force)"
                else
                    echo "MISS | $target not found (run: dil_tool base_setup)"
                fi
            }

            # Handle glob: prefix
            if [[ "$src_rel" == glob:* ]]; then
                local actual_src="${src_rel#glob:}"
                local src_abs="${AGENTS_DIR}/${actual_src}"
                local target_pattern
                target_pattern=$(expand_path "$target_raw")
                local target_filename
                target_filename=$(basename "$target_pattern")
                local dir_pattern
                dir_pattern=$(dirname "$target_pattern")
                local found=0
                for expanded_dir in $dir_pattern; do
                    [[ -d "$expanded_dir" ]] || continue
                    found=$((found + 1))
                    _check_link "$src_abs" "$actual_src" "${expanded_dir}/${target_filename}"
                done
                if [[ $found -eq 0 ]]; then
                    echo "WARN | No directories matched: $target_raw"
                fi
                continue
            fi

            local src_abs="${AGENTS_DIR}/${src_rel}"
            local target
            target=$(expand_path "$target_raw")
            _check_link "$src_abs" "$src_rel" "$target"
        done < "$MANIFEST"
    else
        echo "ERROR: Manifest not found: $MANIFEST"
    fi

    echo ""

    # 2. Count active tasks
    echo "-- Active Tasks --"
    local work_count personal_count
    work_count=$(find "${BASE}/_shared/domains/work/tasks/active" -name '*.md' 2>/dev/null | wc -l)
    personal_count=$(find "${BASE}/_shared/domains/personal/tasks/active" -name '*.md' 2>/dev/null | wc -l)
    echo "Work:     $work_count"
    echo "Personal: $personal_count"

    echo ""

    # 3. DIL base info
    echo "-- DIL Base --"
    echo "Path: $BASE"
    echo "Manifest: $MANIFEST"
}

# --- help ---
cmd_help() {
    echo "Usage: dil_tool <command> [options]"
    echo ""
    echo "Commands:"
    echo "  base_setup    Create/verify agent config symlinks from the manifest"
    echo "  status        Health check (symlinks, task counts, DIL base info)"
    echo ""
    echo "Options:"
    echo "  -h, --help    Show this help"
    echo ""
    echo "DIL Base: $BASE"
    echo "Manifest: $MANIFEST"
}

# --- Main dispatch ---
if [[ $# -lt 1 ]]; then
    cmd_help
    exit 0
fi

action="$1"
shift

case "$action" in
    base_setup)  cmd_base_setup "$@" ;;
    status)      cmd_status "$@" ;;
    -h|--help|help) cmd_help ;;
    *) echo "Unknown command: $action" >&2; cmd_help; exit 1 ;;
esac
