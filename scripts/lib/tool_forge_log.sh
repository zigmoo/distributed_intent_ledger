#!/usr/bin/env bash
# tool_forge_log.sh — Script Forge shared logging library (bash)
#
# Source this file, call tool_forge_log_init to set up, then tool_forge_log to write entries.
# Produces logs compatible with log_river harvest.
#
# Usage:
#   source "$SCRIPT_DIR/lib/tool_forge_log.sh"
#   tool_forge_log_init "tool_name" "action" "$BASE"
#   tool_forge_log "Section 1: Starting work"
#   tool_forge_log "processed 42 items"
#   tool_forge_log_section "Section 2: Validation"
#   tool_forge_log "all checks passed"
#   tool_forge_log_close
#
# Log file: $LOG_DIR/<tool_name>/<tool_name>.<action>.<YYYYMMDD_HHMMSS>.log
# Format: YYYY-MM-DD HH:MM:SS.mmm | LEVEL | message

SF_LOG_FILE=""
SF_LOG_TOOL=""
SF_LOG_ACTION=""
SF_LOG_SECTION=0
SF_LOG_TIMESTAMP=""

tool_forge_log_init() {
  local tool_name="$1"
  local action="${2:-run}"
  local base="${3:-${BASE:-}}"

  SF_LOG_TOOL="$tool_name"
  SF_LOG_ACTION="$action"
  SF_LOG_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  SF_LOG_SECTION=0

  local log_dir
  if [[ -n "$base" ]]; then
    log_dir="$base/_shared/logs/$tool_name"
  else
    log_dir="/tmp/tool_forge_logs/$tool_name"
  fi
  mkdir -p "$log_dir"

  SF_LOG_FILE="$log_dir/${tool_name}.${action}.${SF_LOG_TIMESTAMP}.log"

  {
    echo "================================================================================"
    echo "LOG_FILE: $SF_LOG_FILE"
    echo "================================================================================"
    echo ""
    tool_forge_log_section_header "Configuration"
    echo "timestamp:  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "tool:       $tool_name"
    echo "action:     $action"
    echo "machine:    $(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo unknown)"
    echo "agent:      ${AGENT_NAME:-${AGENT_ID:-${ASSISTANT_ID:-unknown}}}"
    echo "pid:        $$"
    echo ""
  } > "$SF_LOG_FILE"
}

tool_forge_log() {
  [[ -n "$SF_LOG_FILE" ]] || return 0
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S.%3N' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')"
  echo "$ts | INFO | $*" >> "$SF_LOG_FILE"
}

tool_forge_log_error() {
  [[ -n "$SF_LOG_FILE" ]] || return 0
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S.%3N' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')"
  echo "$ts | ERROR | $*" >> "$SF_LOG_FILE"
}

tool_forge_log_warn() {
  [[ -n "$SF_LOG_FILE" ]] || return 0
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S.%3N' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')"
  echo "$ts | WARN | $*" >> "$SF_LOG_FILE"
}

tool_forge_log_section_header() {
  local name="$1"
  SF_LOG_SECTION=$((SF_LOG_SECTION + 1))
  echo "Section ${SF_LOG_SECTION}: ${name}" >> "$SF_LOG_FILE"
  echo "--------------------------------------------------------------------------------" >> "$SF_LOG_FILE"
}

tool_forge_log_section() {
  [[ -n "$SF_LOG_FILE" ]] || return 0
  echo "" >> "$SF_LOG_FILE"
  tool_forge_log_section_header "$1"
}

tool_forge_log_close() {
  [[ -n "$SF_LOG_FILE" ]] || return 0
  {
    echo ""
    echo "================================================================================"
    echo "LOG_FILE: $SF_LOG_FILE"
    echo "================================================================================"
  } >> "$SF_LOG_FILE"
}

tool_forge_log_file() {
  echo "$SF_LOG_FILE"
}
