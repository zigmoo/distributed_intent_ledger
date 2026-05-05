#!/usr/bin/env bash
# resolve_base.sh — Canonical DIL base path resolver for scripts.
# Resolution order:
#   1) Explicit override arg / BASE_DIL / DIL_BASE / CLAWVAULT_BASE
#   2) Repo-relative from script location
#   3) Legacy fallback: $HOME/Documents/dil_agentic_memory_0001

resolve_dil_base() {
  local script_dir="${1:-}"
  local explicit="${2:-${BASE_DIL:-${DIL_BASE:-${CLAWVAULT_BASE:-}}}}"

  if [[ -n "$explicit" ]]; then
    printf '%s\n' "$explicit"
    return 0
  fi

  if [[ -n "$script_dir" ]]; then
    local cursor
    cursor="$(cd "$script_dir" 2>/dev/null && pwd || true)"
    while [[ -n "$cursor" && "$cursor" != "/" ]]; do
      if [[ -d "$cursor/_shared/_meta" ]]; then
        printf '%s\n' "$cursor"
        return 0
      fi
      cursor="$(dirname "$cursor")"
    done
  fi

  local legacy_base="$HOME/Documents/dil_agentic_memory_0001"
  if [[ -d "$legacy_base/_shared" ]]; then
    printf '%s\n' "$legacy_base"
    return 0
  fi

  echo "ERR | 3 | Could not resolve DIL base. Set BASE_DIL to your vault path." >&2
  return 3
}

resolve_dil_base_or_die() {
  local script_dir="${1:-}"
  local explicit="${2:-}"
  local base
  if ! base="$(resolve_dil_base "$script_dir" "$explicit")"; then
    exit 3
  fi
  printf '%s\n' "$base"
}
