#!/usr/bin/env bash
# registry.sh — Bash shim for parsing DIL markdown table registries
# Source this file, then call registry_* functions.
# Parses header rows dynamically — column additions never break callers.
# Compatible with set -euo pipefail.

_REGISTRY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve_base.sh
source "$_REGISTRY_LIB_DIR/resolve_base.sh"
_REGISTRY_BASE="$(resolve_dil_base_or_die "$_REGISTRY_LIB_DIR" "${BASE_DIL:-}")"
_PROJECT_REGISTRY="${_REGISTRY_BASE}/_shared/_meta/project_registry.md"

# Internal: populated by registry_parse_header, read by other functions.
# Using module-level arrays instead of namerefs for set -e compatibility.
declare -gA _REG_COL_MAP=()
declare -ga _REG_COL_ORDER=()

# Parse a markdown table header into the module-level column map.
# After calling this, use registry_get_col and registry_build_row.
#
# Usage:
#   registry_parse_header "/path/to/file.md"
#   echo "slug is column ${_REG_COL_MAP[slug]}"
#
# Args:
#   $1 — path to the markdown file
#
# Returns 0 on success, 1 if no header found.
registry_parse_header() {
  local file="$1"
  _REG_COL_MAP=()
  _REG_COL_ORDER=()

  local header_line
  header_line=$(grep -m1 '^| slug ' "$file" 2>/dev/null) || header_line=$(grep -m1 '^|[^-]' "$file" 2>/dev/null) || true

  if [[ -z "$header_line" ]]; then
    echo "ERROR: no table header found in $file" >&2
    return 1
  fi

  local idx=0
  local col_name
  local IFS='|'
  local -a parts
  read -ra parts <<< "$header_line"
  for part in "${parts[@]}"; do
    col_name=$(echo "$part" | xargs) || true  # trim whitespace
    if [[ -n "$col_name" ]]; then
      _REG_COL_MAP["$col_name"]=$idx
      _REG_COL_ORDER+=("$col_name")
      (( idx++ )) || true
    fi
  done
  return 0
}

# Extract a column value from a pipe-delimited row by column name.
#
# Usage:
#   registry_parse_header "/path/to/file.md"
#   value=$(registry_get_col "$row" "slug")
#
# Args:
#   $1 — the full pipe-delimited row string
#   $2 — column name
#
# Prints the trimmed value. Empty string if column not found.
registry_get_col() {
  local row="$1"
  local col_name="$2"

  if [[ ! -v _REG_COL_MAP[$col_name] ]]; then
    return 0
  fi
  local col_idx="${_REG_COL_MAP[$col_name]}"

  local IFS='|'
  local -a row_parts
  read -ra row_parts <<< "$row"
  # +1 because leading | creates empty element at [0]
  local raw="${row_parts[$((col_idx + 1))]:-}"
  echo "$raw" | xargs || true
}

# Build a pipe-delimited row from an associative array of values.
# Columns not provided get empty values. Column order matches the
# header parsed by registry_parse_header.
#
# Usage:
#   registry_parse_header "/path/to/file.md"
#   registry_build_row slug="my-project" domain="personal" name="My Project"
#
# Args:
#   key=value pairs for each column to populate
#
# Prints the formatted row string.
registry_build_row() {
  # Parse key=value args into a local associative array
  local -A vals=()
  local arg
  for arg in "$@"; do
    local key="${arg%%=*}"
    local value="${arg#*=}"
    vals["$key"]="$value"
  done

  local row="|"
  local col val
  for col in "${_REG_COL_ORDER[@]}"; do
    if [[ -v vals[$col] ]]; then
      val="${vals[$col]}"
    else
      val=""
    fi
    row+=" ${val} |"
  done

  echo "$row"
}

# Check if a slug exists in the project registry.
#
# Usage:
#   if registry_slug_exists "my-project"; then ...
#
# Args:
#   $1 — slug to check
#   $2 — (optional) path to registry file, defaults to $_PROJECT_REGISTRY
registry_slug_exists() {
  local slug="$1"
  local file="${2:-$_PROJECT_REGISTRY}"
  grep -qP "^\|\s*${slug}\s*\|" "$file" 2>/dev/null
}
