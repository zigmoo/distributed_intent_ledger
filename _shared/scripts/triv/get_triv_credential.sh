#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="get_triv_credential"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE_DIL="$(resolve_dil_base_or_die "$SCRIPT_DIR/..")"

# Source domain registry for log path resolution
_DOMAINS_SH="$BASE_DIL/_shared/scripts/lib/domains.sh"
if [[ -f "$_DOMAINS_SH" ]] && command -v jq >/dev/null 2>&1; then
  source "$_DOMAINS_SH"
  if resolve_domain triv 2>/dev/null; then
    _TRIV_LOG_DIR="$LOG_DIR/$SCRIPT_NAME"
  fi
fi
LOG_DIR="${_TRIV_LOG_DIR:-$BASE_DIL/_shared/domains/triv/logs/$SCRIPT_NAME}"
mkdir -p "$LOG_DIR"
find "$LOG_DIR" -type f -mtime +180 -delete 2>/dev/null || true
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_$(date +%Y%m%d-%H%M%S).log"
START_TS="$(date +%s)"

log() {
  local line="[$(date +'%Y-%m-%d %H:%M:%S %Z')] $*"
  echo "$line" | tee -a "$LOG_FILE"
}

usage() {
  cat <<'USAGE'
Usage:
  get_triv_credential.sh [--secret-key KEY] [--registry-file PATH] [--item ITEM] [--vault VAULT] [--field FIELD] [--account ACCOUNT] [--reveal]

Examples:
  # Safe default (masked value)
  get_triv_credential.sh

  # Explicitly reveal value to stdout
  get_triv_credential.sh --reveal

  # Use a different registry key
  get_triv_credential.sh --secret-key triv_primary

Options:
  --secret-key KEY   Registry key in secret_lookup_registry.json (default: triv_primary)
  --registry-file    Shared registry path (default: DIL shared _meta path)
  --vault VAULT      1Password vault name (default: oc_pedro)
  --item ITEM        1Password item title (default: "threeriversduckclub.com (moo)")
  --field FIELD      Field label to read (default: password)
  --account ACCOUNT  Optional 1Password account shorthand/domain to target
  --reveal           Print the full value to stdout (default is masked)
  -h, --help         Show this help

Notes:
  - Reads secret at runtime from 1Password CLI (`op`).
  - Does not write secret values to disk.
  - Logs to: <DIL_BASE>/_shared/domains/triv/logs/get_triv_credential/ (default)
USAGE
}

mask_value() {
  local val="$1"
  local n="${#val}"
  if (( n <= 0 )); then
    printf '<empty>'
  elif (( n <= 4 )); then
    printf '****'
  else
    printf '%s****%s' "${val:0:2}" "${val:n-2:2}"
  fi
}

REGISTRY_FILE="$BASE_DIL/_shared/_meta/secret_lookup_registry.json"
SECRET_KEY="triv_primary"
VAULT=""
ITEM=""
FIELD=""
ACCOUNT=""
REVEAL="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secret-key) SECRET_KEY="${2:-}"; shift 2 ;;
    --registry-file) REGISTRY_FILE="${2:-}"; shift 2 ;;
    --vault) VAULT="${2:-}"; shift 2 ;;
    --item) ITEM="${2:-}"; shift 2 ;;
    --field) FIELD="${2:-}"; shift 2 ;;
    --account) ACCOUNT="${2:-}"; shift 2 ;;
    --reveal) REVEAL="1"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v op >/dev/null 2>&1; then
  echo "1Password CLI 'op' is not installed or not in PATH." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "'jq' is required but not installed/in PATH." >&2
  exit 1
fi

if [[ -f "$REGISTRY_FILE" ]]; then
  REG_ITEM="$(jq -r --arg k "$SECRET_KEY" '.entries[$k].itemTitle // empty' "$REGISTRY_FILE" 2>/dev/null || true)"
  REG_VAULT="$(jq -r --arg k "$SECRET_KEY" '.entries[$k].vault // empty' "$REGISTRY_FILE" 2>/dev/null || true)"
  REG_FIELD="$(jq -r --arg k "$SECRET_KEY" '.entries[$k].field // empty' "$REGISTRY_FILE" 2>/dev/null || true)"
else
  REG_ITEM=""
  REG_VAULT=""
  REG_FIELD=""
fi

if [[ -n "$REG_ITEM" && -z "$ITEM" ]]; then
  ITEM="$REG_ITEM"
fi
if [[ -n "$REG_VAULT" && -z "$VAULT" ]]; then
  VAULT="$REG_VAULT"
fi
if [[ -n "$REG_FIELD" && -z "$FIELD" ]]; then
  FIELD="$REG_FIELD"
fi

if [[ -z "$ITEM" ]]; then
  ITEM="threeriversduckclub.com (moo)"
fi
if [[ -z "$VAULT" ]]; then
  VAULT="oc_pedro"
fi
if [[ -z "$FIELD" ]]; then
  FIELD="password"
fi

log "Story start: $SCRIPT_NAME is opening the TRIV credential notebook."
log "Script path: $SCRIPT_PATH"
log "DIL base path: $BASE_DIL"
log "Log file: $LOG_FILE"
log "Registry file: $REGISTRY_FILE"
log "Registry key: $SECRET_KEY"
log "Lookup request: vault='$VAULT' item='$ITEM' field='$FIELD'"

if [[ -n "$ACCOUNT" ]]; then
  log "Checking account context for '$ACCOUNT'."
  if ! op account get "$ACCOUNT" >/dev/null 2>&1; then
    log "Could not find account '$ACCOUNT' in local op profiles."
    echo "ERROR: 1Password account '$ACCOUNT' is unavailable." >&2
    exit 2
  fi
fi

OP_ARGS=()
if [[ -n "$ACCOUNT" ]]; then
  OP_ARGS+=(--account "$ACCOUNT")
fi

# Use the direct field retrieval pattern required for hidden password fields.
VALUE="$(op item get "$ITEM" "${OP_ARGS[@]}" --vault "$VAULT" --field "$FIELD" --reveal 2>/dev/null || true)"

if [[ -z "$VALUE" ]]; then
  log "The helper could not find a value for that item/field."
  echo "ERROR: No value found for vault='$VAULT', item='$ITEM', field='$FIELD'." >&2
  echo "Hint: verify item title + field label with: op item get \"$ITEM\" --vault \"$VAULT\"" >&2
  exit 3
fi

if [[ "$REVEAL" == "1" ]]; then
  log "Explicit reveal requested; printing secret to stdout."
  printf '%s\n' "$VALUE"
else
  MASKED="$(mask_value "$VALUE")"
  log "Secret retrieved successfully (masked output mode)."
  printf 'VALUE_MASKED=%s\n' "$MASKED"
fi

END_TS="$(date +%s)"
ELAPSED="$((END_TS - START_TS))"
log "Story complete in ${ELAPSED}s."
