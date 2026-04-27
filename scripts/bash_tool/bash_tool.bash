#!/usr/bin/env bash
# bash_tool - DIL-compliant shell execution tool for humans and agents.
#
# This is intentionally flexible: it runs a command string through `bash -lc`.
# Normal mode blocks obvious destructive/system-control patterns. Explicit
# `--dangerous-ok` is required to bypass those checks.

set -euo pipefail

SCRIPT_NAME="bash_tool"
SCRIPT_VERSION="2026-04-15"
SCRIPT_AUTHOR="codex"
SCRIPT_MODEL="gpt-5.4"
SCRIPT_OWNER="moo"
IMPLEMENTATION_TASK_ID="DIL-1454"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/../lib/domains.sh"

BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
resolve_domain personal

ACTION="exec"
OUTPUT_MODE="text"
COMMAND=""
CWD="${PWD}"
TIMEOUT_SECONDS="120"
DANGEROUS_OK=0
PURPOSE=""
SHOW_HELP=0

START_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
START_US="$(date -u +%s%6N)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
HOSTNAME_SHORT="$(hostname -s | tr '[:upper:]' '[:lower:]')"

LOG_ROOT="$LOG_DIR/$SCRIPT_NAME"
DATA_ROOT="$DATA_DIR/$SCRIPT_NAME"
mkdir -p "$LOG_ROOT" "$DATA_ROOT"

LOG_FILE="$LOG_ROOT/${SCRIPT_NAME}.${ACTION}.${STAMP}.$$.log"
DATA_FILE="$DATA_ROOT/${SCRIPT_NAME}.${ACTION}.${STAMP}.$$.json"
LATEST_DATA_FILE="$DATA_ROOT/${SCRIPT_NAME}.${ACTION}.latest.json"
TMP_OUT="$(mktemp)"
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_OUT" "$TMP_ERR"' EXIT

usage() {
  cat <<'USAGE'
bash_tool - DIL-compliant shell execution tool for humans and agents

Usage:
  bash_tool --command 'COMMAND' [options]
  bash_tool --cwd PATH -- COMMAND [ARGS...]

Options:
  --command TEXT       Command string executed by bash -lc.
  --cwd PATH           Working directory. Defaults to current directory.
  --timeout SECONDS    Timeout. Default: 120. Max without --dangerous-ok: 900.
  --purpose TEXT       Human-readable reason for audit logs.
  --dangerous-ok       Bypass destructive-pattern refusal. Use only after user authorization.
  --json               Emit JSON artifact content to stdout.
  -h, --help           Show help.

Normal-mode refused patterns include obvious destructive filesystem, disk,
process, privilege, reboot/shutdown, fork-bomb, and raw block-device commands.
USAGE
}

die() {
  local message="$1"
  local code="${2:-1}"
  echo "ERROR: $message" >&2
  exit "$code"
}

log_line() {
  local level="$1"
  shift
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  printf '[%s] [%s] [%s] %s\n' "$ts" "$SCRIPT_NAME" "$level" "$*" >> "$LOG_FILE"
}

format_duration() {
  local total_us="$1"
  local hours=$((total_us / 3600000000))
  local rem=$((total_us % 3600000000))
  local mins=$((rem / 60000000))
  rem=$((rem % 60000000))
  local secs=$((rem / 1000000))
  local frac=$(((rem % 1000000) / 100))
  printf '%02dh%02dm%02d.%04ds' "$hours" "$mins" "$secs" "$frac"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --command)
        COMMAND="${2:-}"
        [[ -n "$COMMAND" ]] || die "--command requires text" 2
        shift 2
        ;;
      --cwd)
        CWD="${2:-}"
        [[ -n "$CWD" ]] || die "--cwd requires a path" 2
        shift 2
        ;;
      --timeout)
        TIMEOUT_SECONDS="${2:-}"
        [[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout requires an integer" 2
        shift 2
        ;;
      --purpose)
        PURPOSE="${2:-}"
        [[ -n "$PURPOSE" ]] || die "--purpose requires text" 2
        shift 2
        ;;
      --dangerous-ok)
        DANGEROUS_OK=1
        shift
        ;;
      --json)
        OUTPUT_MODE="json"
        shift
        ;;
      --)
        shift
        [[ $# -gt 0 ]] || die "-- requires a command" 2
        COMMAND="$*"
        break
        ;;
      -h|--help|help)
        SHOW_HELP=1
        shift
        ;;
      *)
        if [[ -z "$COMMAND" ]]; then
          COMMAND="$*"
          break
        fi
        die "Unknown argument: $1" 2
        ;;
    esac
  done
}

normalize_cwd() {
  [[ -d "$CWD" ]] || die "Working directory does not exist: $CWD" 2
  CWD="$(cd "$CWD" && pwd)"
}

classify_risk() {
  local cmd="$1"
  local compact lowered
  compact="$(printf '%s' "$cmd" | tr '\n' ' ')"
  lowered="$(printf '%s' "$compact" | tr '[:upper:]' '[:lower:]')"

  if [[ "$lowered" =~ \:\(\)\{.*\|.*\&.*\} ]]; then
    echo "fork_bomb_pattern"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])sudo([[:space:]]|$) ]]; then
    echo "sudo_requires_explicit_authorization"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])(su|doas)([[:space:]]|$) ]]; then
    echo "privilege_switch_requires_explicit_authorization"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])(shutdown|reboot|poweroff|halt|systemctl[[:space:]]+(reboot|poweroff|halt))([[:space:]]|$) ]]; then
    echo "system_power_control"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])rm[[:space:]].*(-rf|-fr|--recursive).*[[:space:]]/($|[[:space:]]) ]]; then
    echo "recursive_delete_root"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])rm[[:space:]].*(-rf|-fr|--recursive).*(/home|/etc|/usr|/var|/opt|/boot|/root)(/|[[:space:]]|$) ]]; then
    echo "recursive_delete_sensitive_path"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])(mkfs|fdisk|parted|wipefs|blkdiscard)(\.|[[:space:]]|$) ]]; then
    echo "disk_partition_or_format"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])dd[[:space:]].*of=/dev/ ]]; then
    echo "raw_block_device_write"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])(chmod|chown)[[:space:]].*(-r|--recursive).*[[:space:]]/($|[[:space:]]) ]]; then
    echo "recursive_permission_change_root"
    return 0
  fi
  if [[ "$lowered" =~ (^|[[:space:];|&])killall[[:space:]]+-9([[:space:]]|$) ]]; then
    echo "mass_process_kill"
    return 0
  fi
  echo "normal"
}

write_artifact() {
  local status="$1"
  local exit_code="$2"
  local risk="$3"
  local end_ts end_us duration_us duration_human
  end_ts="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  end_us="$(date -u +%s%6N)"
  duration_us=$((end_us - START_US))
  duration_human="$(format_duration "$duration_us")"

  jq -n \
    --arg script_name "$SCRIPT_NAME" \
    --arg script_version "$SCRIPT_VERSION" \
    --arg implementation_task_id "$IMPLEMENTATION_TASK_ID" \
    --arg status "$status" \
    --argjson exit_code "$exit_code" \
    --arg hostname_short "$HOSTNAME_SHORT" \
    --arg start_ts_utc "$START_TS" \
    --arg end_ts_utc "$end_ts" \
    --arg duration_human "$duration_human" \
    --arg cwd "$CWD" \
    --arg command "$COMMAND" \
    --arg purpose "$PURPOSE" \
    --arg risk "$risk" \
    --argjson dangerous_ok "$DANGEROUS_OK" \
    --argjson timeout_seconds "$TIMEOUT_SECONDS" \
    --arg log_file "$LOG_FILE" \
    --arg data_file "$DATA_FILE" \
    --rawfile stdout "$TMP_OUT" \
    --rawfile stderr "$TMP_ERR" \
    '{script_name:$script_name,script_version:$script_version,implementation_task_id:$implementation_task_id,status:$status,exit_code:$exit_code,hostname_short:$hostname_short,start_ts_utc:$start_ts_utc,end_ts_utc:$end_ts_utc,duration_human:$duration_human,cwd:$cwd,command:$command,purpose:$purpose,risk:$risk,dangerous_ok:$dangerous_ok,timeout_seconds:$timeout_seconds,stdout:$stdout,stderr:$stderr,log_file:$log_file,data_file:$data_file}' \
    > "$DATA_FILE"
  cp "$DATA_FILE" "$LATEST_DATA_FILE"
}

main() {
  parse_args "$@"
  if [[ "$SHOW_HELP" == 1 ]]; then
    usage
    exit 0
  fi
  [[ -n "$COMMAND" ]] || die "No command supplied. Use --command TEXT or -- COMMAND ARGS." 2
  normalize_cwd
  if [[ "$DANGEROUS_OK" != 1 && "$TIMEOUT_SECONDS" -gt 900 ]]; then
    die "Timeout above 900 seconds requires --dangerous-ok" 2
  fi

  local risk exit_code status timeout_cmd
  risk="$(classify_risk "$COMMAND")"
  log_line "INFO" "script_version=$SCRIPT_VERSION task_id=$IMPLEMENTATION_TASK_ID"
  log_line "INFO" "hostname_short=$HOSTNAME_SHORT pid=$$ start_ts_utc=$START_TS"
  log_line "INFO" "cwd=$CWD timeout_seconds=$TIMEOUT_SECONDS dangerous_ok=$DANGEROUS_OK risk=$risk"
  log_line "INFO" "purpose=$PURPOSE"
  log_line "INFO" "command=$COMMAND"

  if [[ "$risk" != "normal" && "$DANGEROUS_OK" != 1 ]]; then
    printf 'Refused high-risk command pattern: %s\nUse --dangerous-ok only after explicit user authorization.\n' "$risk" > "$TMP_ERR"
    write_artifact "refused" 4 "$risk"
    if [[ "$OUTPUT_MODE" == "json" ]]; then
      cat "$DATA_FILE"
    else
      cat "$TMP_ERR" >&2
      echo "log_file=$LOG_FILE" >&2
      echo "data_file=$DATA_FILE" >&2
    fi
    exit 4
  fi

  set +e
  if command -v timeout >/dev/null 2>&1; then
    (cd "$CWD" && timeout --kill-after=5s "${TIMEOUT_SECONDS}s" bash -lc "$COMMAND") >"$TMP_OUT" 2>"$TMP_ERR"
    exit_code=$?
  else
    (cd "$CWD" && bash -lc "$COMMAND") >"$TMP_OUT" 2>"$TMP_ERR"
    exit_code=$?
  fi
  set -e

  if [[ "$exit_code" == 0 ]]; then
    status="ok"
  elif [[ "$exit_code" == 124 || "$exit_code" == 137 ]]; then
    status="timeout"
  else
    status="error"
  fi

  write_artifact "$status" "$exit_code" "$risk"
  log_line "INFO" "exit_code=$exit_code status=$status data_file=$DATA_FILE"

  if [[ "$OUTPUT_MODE" == "json" ]]; then
    cat "$DATA_FILE"
  else
    cat "$TMP_OUT"
    if [[ -s "$TMP_ERR" ]]; then
      cat "$TMP_ERR" >&2
    fi
    echo "log_file=$LOG_FILE" >&2
    echo "data_file=$DATA_FILE" >&2
  fi
  exit "$exit_code"
}

main "$@"
