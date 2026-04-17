#!/usr/bin/env bash
# domains.sh — Bash shim for DIL domain registry
# Source this file, then call resolve_domain <domain_name>
# Requires: jq

_DOMAINS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_base.sh
source "$_DOMAINS_LIB_DIR/resolve_base.sh"
_BASE_DIL="$(resolve_dil_base_or_die "$_DOMAINS_LIB_DIR" "${BASE_DIL:-}")"
_DOMAIN_REGISTRY="${DOMAIN_REGISTRY:-${_BASE_DIL}/_shared/_meta/domain_registry.json}"

_domains_require_jq() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: domains.sh requires jq" >&2
    return 1
  fi
}

_domains_resolve_path() {
  local raw_path="$1"
  local path_type="$2"
  if [[ "$raw_path" == /* ]]; then
    printf '%s' "$raw_path"
  else
    printf '%s/%s' "$_BASE_DIL" "$raw_path"
  fi
}

# List all registered domain keys
list_domains() {
  _domains_require_jq || return 1
  jq -r '.domains | keys[]' "$_DOMAIN_REGISTRY"
}

# Check if a domain exists in the registry
domain_exists() {
  local domain="$1"
  _domains_require_jq || return 1
  jq -e --arg d "$domain" '.domains[$d] // empty' "$_DOMAIN_REGISTRY" >/dev/null 2>&1
}

# Resolve a domain — sets exported variables for the caller
# Usage: resolve_domain <domain_name>
# Exports: DOMAIN_NAME, TASK_DIR, LOG_DIR, DATA_DIR, ID_PREFIX, ID_MODE,
#          DEFAULT_OWNER, PATH_TYPE, DOMAIN_STATUS,
#          LOG_PRUNE_STRATEGY, LOG_PRUNE_WINDOW_DAYS,
#          ARCHIVE_AFTER_DAYS, ARCHIVE_YEAR_KEY, ARCHIVE_STRATEGY
resolve_domain() {
  local domain="$1"

  _domains_require_jq || return 1

  if [[ -z "$domain" ]]; then
    echo "ERROR: resolve_domain requires a domain name" >&2
    return 1
  fi

  if [[ ! -f "$_DOMAIN_REGISTRY" ]]; then
    echo "ERROR: domain registry not found: $_DOMAIN_REGISTRY" >&2
    return 1
  fi

  if ! domain_exists "$domain"; then
    echo "ERROR: unknown domain '$domain' — registered domains: $(list_domains | tr '\n' ' ')" >&2
    return 1
  fi

  local json
  json=$(jq -c --arg d "$domain" '.domains[$d]' "$_DOMAIN_REGISTRY")

  DOMAIN_NAME=$(printf '%s' "$json" | jq -r '.name')
  PATH_TYPE=$(printf '%s' "$json" | jq -r '.path_type')

  local raw_task_dir raw_log_dir raw_data_dir
  raw_task_dir=$(printf '%s' "$json" | jq -r '.task_dir')
  raw_log_dir=$(printf '%s' "$json" | jq -r '.log_dir')
  raw_data_dir=$(printf '%s' "$json" | jq -r '.data_dir')

  TASK_DIR=$(_domains_resolve_path "$raw_task_dir" "$PATH_TYPE")
  LOG_DIR=$(_domains_resolve_path "$raw_log_dir" "$PATH_TYPE")
  DATA_DIR=$(_domains_resolve_path "$raw_data_dir" "$PATH_TYPE")

  ID_PREFIX=$(printf '%s' "$json" | jq -r '.id_prefix')
  ID_MODE=$(printf '%s' "$json" | jq -r '.id_mode')
  DEFAULT_OWNER=$(printf '%s' "$json" | jq -r '.default_owner')
  DOMAIN_STATUS=$(printf '%s' "$json" | jq -r '.status')

  LOG_PRUNE_STRATEGY=$(printf '%s' "$json" | jq -r '.log_prune.strategy')
  LOG_PRUNE_WINDOW_DAYS=$(printf '%s' "$json" | jq -r '.log_prune.window_days')

  ARCHIVE_AFTER_DAYS=$(printf '%s' "$json" | jq -r '.archive.after_days')
  ARCHIVE_YEAR_KEY=$(printf '%s' "$json" | jq -r '.archive.year_key')
  ARCHIVE_STRATEGY=$(printf '%s' "$json" | jq -r '.archive.strategy')

  export DOMAIN_NAME TASK_DIR LOG_DIR DATA_DIR ID_PREFIX ID_MODE DEFAULT_OWNER
  export PATH_TYPE DOMAIN_STATUS
  export LOG_PRUNE_STRATEGY LOG_PRUNE_WINDOW_DAYS
  export ARCHIVE_AFTER_DAYS ARCHIVE_YEAR_KEY ARCHIVE_STRATEGY
}
