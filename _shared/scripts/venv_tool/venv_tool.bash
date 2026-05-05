#!/usr/bin/env bash
# venv_tool — validate and bootstrap Python venvs for Tool Forge drawers
# Uses uv when available, falls back to pip.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

usage() {
  cat <<'EOF'
venv_tool — validate and bootstrap Python virtual environments

Usage:
  venv_tool ensure <drawer_path>    Create venv and install deps if needed
  venv_tool status <drawer_path>    Check venv health without modifying
  venv_tool rebuild <drawer_path>   Remove and recreate venv from scratch
  venv_tool engine                  Show which engine (uv or pip) would be used

Arguments:
  drawer_path    Path to a tool drawer containing requirements.txt
                 The venv is created at <drawer_path>/venv/

Options:
  -q, --quiet    Suppress all output (for use in wrappers)
  -h, --help     Show this help
EOF
}

QUIET=false
ACTION=""
DRAWER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -q|--quiet) QUIET=true; shift ;;
    -h|--help) usage; exit 0 ;;
    ensure|status|rebuild|engine) ACTION="$1"; shift ;;
    *) DRAWER="$1"; shift ;;
  esac
done

log() { $QUIET || echo "$*" >&2; }

has_uv() { command -v uv >/dev/null 2>&1; }

engine() {
  if has_uv; then echo "uv"; else echo "pip"; fi
}

do_ensure() {
  local drawer="$1"
  local req="$drawer/requirements.txt"
  local venv="$drawer/venv"

  if [[ ! -f "$req" ]] || [[ ! -s "$req" ]]; then
    log "OK: no requirements.txt (stdlib-only tool)"
    return 0
  fi

  if [[ -f "$venv/bin/activate" ]]; then
    log "OK: venv exists at $venv"
    return 0
  fi

  log "Creating venv at $venv..."
  if has_uv; then
    uv venv "$venv" -q 2>/dev/null
    VIRTUAL_ENV="$venv" uv pip install -q -r "$req" -p "$venv/bin/python" 2>/dev/null
  else
    python3 -m venv "$venv" 2>/dev/null
    "$venv/bin/pip" install --quiet --disable-pip-version-check -r "$req" 2>/dev/null
  fi
  log "OK: venv created ($(engine))"
}

do_status() {
  local drawer="$1"
  local req="$drawer/requirements.txt"
  local venv="$drawer/venv"

  echo "drawer: $drawer"
  echo "engine: $(engine)"

  if [[ ! -f "$req" ]] || [[ ! -s "$req" ]]; then
    echo "requirements: none (stdlib-only)"
    echo "venv: not needed"
    return 0
  fi

  echo "requirements: $(wc -l < "$req") lines"

  if [[ -f "$venv/bin/activate" ]]; then
    echo "venv: present"
    echo "python: $("$venv/bin/python" --version 2>&1)"
    local installed
    installed=$("$venv/bin/pip" list --format=columns 2>/dev/null | tail -n +3 | wc -l)
    echo "packages: $installed installed"
  else
    echo "venv: MISSING (run: venv_tool ensure $drawer)"
  fi
}

do_rebuild() {
  local drawer="$1"
  local venv="$drawer/venv"

  if [[ -d "$venv" ]]; then
    log "Removing $venv..."
    rm -rf "$venv"
  fi
  do_ensure "$drawer"
}

case "${ACTION:-}" in
  ensure)
    [[ -n "$DRAWER" ]] || { echo "ERR: drawer path required" >&2; exit 2; }
    do_ensure "$DRAWER"
    ;;
  status)
    [[ -n "$DRAWER" ]] || { echo "ERR: drawer path required" >&2; exit 2; }
    do_status "$DRAWER"
    ;;
  rebuild)
    [[ -n "$DRAWER" ]] || { echo "ERR: drawer path required" >&2; exit 2; }
    do_rebuild "$DRAWER"
    ;;
  engine)
    engine
    ;;
  *)
    usage
    exit 1
    ;;
esac
