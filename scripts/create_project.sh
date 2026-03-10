#!/usr/bin/env bash
set -euo pipefail

BASE="/home/moo/Documents/dil_agentic_memory_0001"
SLUG=""
NAME=""
DOMAIN=""
STATUS="active"
PARENT=""
OWNER="moo"
DESCRIPTION=""
NOTES=""
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  create_project.sh --slug "my-project" --name "My Project" --domain personal [options]

Required:
  --slug TEXT           URL-safe project identifier (lowercase, hyphens)
  --name TEXT           Human-readable project name
  --domain personal|work

Options:
  --status TEXT         Default: active (active|paused|done|retired)
  --parent TEXT         Parent project slug (must already exist in registry)
  --owner TEXT          Default: moo
  --description TEXT    One-line description
  --notes TEXT          Initial notes entry
  --base PATH           Default: /home/moo/Documents/dil_agentic_memory_0001
  --dry-run             Show what would be done without writing
  -h, --help            Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --parent) PARENT="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

REGISTRY="$BASE/_shared/_meta/project_registry.md"

# --- Validate required fields ---
if [[ -z "$SLUG" ]]; then
  echo "ERROR: --slug is required" >&2
  exit 1
fi
if [[ -z "$NAME" ]]; then
  echo "ERROR: --name is required" >&2
  exit 1
fi
if [[ -z "$DOMAIN" ]]; then
  echo "ERROR: --domain is required (personal|work)" >&2
  exit 1
fi

# --- Validate slug format ---
if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
  echo "ERROR: slug must be lowercase alphanumeric with hyphens/dots/underscores: got '$SLUG'" >&2
  exit 1
fi

# --- Validate domain ---
case "$DOMAIN" in
  personal|work) ;;
  *) echo "ERROR: domain must be personal or work, got '$DOMAIN'" >&2; exit 1 ;;
esac

# --- Validate status ---
case "$STATUS" in
  active|paused|done|retired) ;;
  *) echo "ERROR: status must be active|paused|done|retired, got '$STATUS'" >&2; exit 1 ;;
esac

# --- Check registry exists ---
if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: project registry not found: $REGISTRY" >&2
  exit 1
fi

# --- Check for duplicate slug ---
if grep -qP "^\| ${SLUG} \|" "$REGISTRY"; then
  echo "ERROR: project slug '$SLUG' already exists in registry" >&2
  exit 1
fi

# --- Validate parent exists if specified ---
if [[ -n "$PARENT" ]]; then
  if ! grep -qP "^\| ${PARENT} \|" "$REGISTRY"; then
    echo "ERROR: parent project '$PARENT' not found in registry" >&2
    exit 1
  fi
fi

# --- Build the row ---
ROW="| ${SLUG} | ${NAME} | ${DOMAIN} | ${STATUS} | ${PARENT} | ${OWNER} | ${DESCRIPTION} | ${NOTES} |"

if (( DRY_RUN == 1 )); then
  echo "DRY RUN — would append to $REGISTRY:"
  echo "$ROW"
  exit 0
fi

# --- Append to registry ---
echo "$ROW" >> "$REGISTRY"

echo "Created project: $SLUG"
echo "Registry: $REGISTRY"
