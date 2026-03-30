#!/usr/bin/env bash
# identify_agent.sh
# Runtime agent identity resolution.
# No hardcoded agent names. All name mappings are user-maintained in:
#   ${XDG_CONFIG_HOME:-~/.config}/dil/agent_aliases.conf
#
# Output: a normalized agent slug on stdout, or UNRESOLVED + exit 1
#
# Usage:
#   ASSISTANT=$(identify_agent.sh) || { echo "Cannot resolve agent identity"; exit 1; }

set -euo pipefail

# ── Helpers ───────────────────────────────────────────────────────────────────

slugify() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9._-]/-/g' \
    | sed 's/--*/-/g; s/^-//; s/-$//'
}

# Generic interpreter names — not agents, just runtimes to look through
GENERIC_RUNTIMES='bash|sh|zsh|fish|dash|ksh|csh|tcsh|node|nodejs|bun|deno|python|python3|ruby|perl|java|go|php'

# ── 1. Load alias map (user-maintained, not hardcoded here) ──────────────────
#
# File format: one mapping per line, from=to
# Lines starting with # are comments. Blank lines ignored.
# Example entries:
#   kilo=opencode
#   cc=claude-code
#   claude=claude-code

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALIAS_MAP_FILE="${DIL_ALIAS_MAP:-$(cd "$SCRIPT_DIR/.." && pwd)/_shared/_meta/agent_aliases.conf}"
declare -A ALIAS_MAP=()

if [[ -f "$ALIAS_MAP_FILE" ]]; then
  while IFS='=' read -r from to; do
    from="${from%%#*}"  # strip inline comments
    from="${from// /}"
    to="${to// /}"
    [[ -z "$from" || -z "$to" ]] && continue
    ALIAS_MAP["$from"]="$to"
  done < "$ALIAS_MAP_FILE"
fi

resolve_alias() {
  local slug="$1"
  echo "${ALIAS_MAP[$slug]:-$slug}"
}

emit() {
  # Final output: apply alias, then print
  local raw
  raw=$(slugify "$1")
  resolve_alias "$raw"
  exit 0
}

# ── 2. Explicit env vars (highest priority) ───────────────────────────────────
#
# Agents or wrappers can set any of these to force identity.

for var in ASSISTANT_ID AGENT_NAME AGENT_ID DIL_AGENT_ID; do
  val="${!var:-}"
  [[ -n "$val" ]] && emit "$val"
done

# Also honor ASSISTANT_ALIAS_MAP env-inline format (DIL compat: "from:to,from:to")
if [[ -n "${ASSISTANT_ALIAS_MAP:-}" ]]; then
  IFS=',' read -r -a _pairs <<< "$ASSISTANT_ALIAS_MAP"
  for pair in "${_pairs[@]}"; do
    _from="${pair%%:*}"
    _to="${pair#*:}"
    ALIAS_MAP["$_from"]="$_to"
  done
fi

# ── 3. Generic env var pattern scan ───────────────────────────────────────────
#
# Look for any env var whose name suggests it carries agent/assistant identity.
# No specific var names are hardcoded — only the semantic suffixes.

identity_pattern='^[A-Z_]*(AGENT|ASSISTANT|BOT|RUNTIME|RUNNER)[A-Z_]*_(ID|NAME|SLUG|LABEL)$'

while IFS='=' read -r varname value; do
  if [[ "$varname" =~ $identity_pattern && -n "$value" ]]; then
    emit "$value"
  fi
done < <(env)

# ── 4. Process tree walk ───────────────────────────────────────────────────────
#
# Walk up the process ancestry from PPID. For each ancestor:
#   a) Try comm directly against alias map
#   b) If comm is a generic runtime, inspect the command line for a
#      more specific binary name and try that
#   c) If comm is non-generic and not in alias map, use it as-is
#
# Stops at PID 1 or after max_depth steps.

walk_process_tree() {
  local pid="${1:-$PPID}"
  local depth=0
  local max_depth=12

  while [[ "$pid" -gt 1 && $depth -lt $max_depth ]]; do
    local comm args
    comm=$(ps -p "$pid" -o comm= 2>/dev/null) || break
    args=$(ps -p "$pid" -o args= 2>/dev/null) || break

    local slug
    slug=$(slugify "$comm")

    # a) Direct alias map hit on comm slug
    if [[ -n "${ALIAS_MAP[$slug]:-}" ]]; then
      echo "${ALIAS_MAP[$slug]}"
      return 0
    fi

    # b) Generic runtime — dig into argv for the actual script/binary
    if echo "$slug" | grep -qE "^($GENERIC_RUNTIMES)$"; then
      # Find first non-generic argv (skip argv[0] if it's the interpreter)
      local -a argv
      read -ra argv <<< "$args"
      for arg in "${argv[@]}"; do
        local arg_slug
        arg_slug=$(slugify "$arg")
        # Skip if it's also a generic runtime
        if ! echo "$arg_slug" | grep -qE "^($GENERIC_RUNTIMES)$"; then
          # Try alias map
          if [[ -n "${ALIAS_MAP[$arg_slug]:-}" ]]; then
            echo "${ALIAS_MAP[$arg_slug]}"
            return 0
          fi
          # Use it as-is if it looks like an agent name (has letters)
          if echo "$arg_slug" | grep -qE '^[a-z]'; then
            echo "$arg_slug"
            return 0
          fi
        fi
      done
    fi

    # c) Non-generic comm — try alias map first, else use comm
    if [[ -n "${ALIAS_MAP[$slug]:-}" ]]; then
      echo "${ALIAS_MAP[$slug]}"
      return 0
    fi

    # If it looks like a meaningful name (not just a random hash-like string), use it
    if echo "$slug" | grep -qE '^[a-z][a-z0-9]{2,}'; then
      echo "$slug"
      return 0
    fi

    # Move to parent
    local ppid
    ppid=$(ps -p "$pid" -o ppid= 2>/dev/null) || break
    pid="$ppid"
    ((depth++))
  done

  return 1
}

# ── 5. Config file signals ─────────────────────────────────────────────────────
#
# Dynamically build config directory checks from alias map values.
# For each canonical agent slug, check for existence of ~/.<slug>/ directory.

check_config_markers() {
  local home="$HOME"
  
  # Extract unique canonical slugs from alias map
  declare -A seen
  local -a slugs=()
  for to in "${ALIAS_MAP[@]}"; do
    [[ -z "${seen[$to]:-}" ]] || continue
    seen[$to]=1
    slugs+=("$to")
  done
  
  # For each canonical slug, check for ~/.<slug>/ directory
  for slug in "${slugs[@]}"; do
    local config_dir="$home/.$slug"
    if [[ -d "$config_dir" ]]; then
      echo "$slug"
      return 0
    fi
  done
  
  return 1
}

# ── Run detection cascade ─────────────────────────────────────────────────────

# Try process tree first (most reliable for running agents)
if walk_process_tree; then
  exit 0
fi

# Fall back to config file markers
if check_config_markers; then
  exit 0
fi

# Nothing resolved
echo "UNRESOLVED" >&2
exit 1
