#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
SLUG=""
NAME=""
DOMAIN=""
STATUS="active"
PARENT=""
ANCHOR_TASK=""
REPO_PATH=""
ALIASES=""
OWNER="moo"
DESCRIPTION=""
DRY_RUN=0

usage() {
  cat << 'USAGE'
Usage:
  create_project.sh --slug "my-project" --name "My Project" --domain personal [options]

Required:
  --slug TEXT           URL-safe project identifier (lowercase, hyphens)
  --name TEXT           Human-readable project name
  --domain TEXT         Registered domain (e.g., personal, work, triv)

Options:
  --status TEXT         Default: active (active|paused|done|retired)
  --parent TEXT         Parent project slug (must already exist in registry)
  --anchor-task TEXT    DIL task ID that groups related tasks (e.g., PRJ-100)
  --repo-path TEXT      Primary filesystem path(s) for this project
  --aliases TEXT        Comma-separated shorthand names for this project
  --owner TEXT          Default: moo
  --description TEXT    One-line description
  --base PATH           Default: auto-detected from script location
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
    --anchor-task) ANCHOR_TASK="$2"; shift 2 ;;
    --repo-path) REPO_PATH="$2"; shift 2 ;;
    --aliases) ALIASES="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --base) DIL_BASE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

REGISTRY="$DIL_BASE/_shared/_meta/project_registry.md"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the registry library
source "$SCRIPT_DIR/lib/registry.sh"

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
  echo "ERROR: --domain is required" >&2
  exit 1
fi

# --- Validate slug format ---
if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
  echo "ERROR: slug must be lowercase alphanumeric with hyphens/dots/underscores: got '$SLUG'" >&2
  exit 1
fi

# --- Validate domain against domain_registry.json ---
DOMAIN_REGISTRY_JSON="$DIL_BASE/_shared/_meta/domain_registry.json"
if [[ -f "$DOMAIN_REGISTRY_JSON" ]] && command -v jq >/dev/null 2>&1; then
  if ! jq -e ".domains[\"$DOMAIN\"]" "$DOMAIN_REGISTRY_JSON" >/dev/null 2>&1; then
    echo "ERROR: domain '$DOMAIN' not found in domain_registry.json" >&2
    echo "Registered domains: $(jq -r '.domains | keys | join(", ")' "$DOMAIN_REGISTRY_JSON")" >&2
    exit 1
  fi
fi

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
if registry_slug_exists "$SLUG" "$REGISTRY"; then
  echo "ERROR: project slug '$SLUG' already exists in registry" >&2
  exit 1
fi

# --- Validate parent exists if specified ---
if [[ -n "$PARENT" ]]; then
  if ! registry_slug_exists "$PARENT" "$REGISTRY"; then
    echo "ERROR: parent project '$PARENT' not found in registry" >&2
    exit 1
  fi
fi

# --- Parse header to build row dynamically ---
registry_parse_header "$REGISTRY"

ROW=$(registry_build_row \
  slug="$SLUG" \
  aliases="$ALIASES" \
  domain="$DOMAIN" \
  name="$NAME" \
  status="$STATUS" \
  parent="$PARENT" \
  anchor_task="$ANCHOR_TASK" \
  repo_path="$REPO_PATH" \
  owner="$OWNER" \
  description="$DESCRIPTION" \
)

if (( DRY_RUN == 1 )); then
  echo "DRY RUN — would append to $REGISTRY:"
  echo "$ROW"
  exit 0
fi

# --- Append to registry ---
# Insert before the Column Definitions section if it exists, otherwise append
if grep -q "^## Column Definitions" "$REGISTRY"; then
  # Find the last data row (last line starting with |) before Column Definitions
  # and append after it
  sed -i "/^## Column Definitions/i\\${ROW}" "$REGISTRY"
else
  echo "$ROW" >> "$REGISTRY"
fi

echo "Created project: $SLUG"
echo "Registry: $REGISTRY"
