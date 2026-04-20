#!/bin/bash
set -euo pipefail
# url_tool — Zero-inference URL formatter using domain_registry ticket_systems templates
#
# Reads ticket_systems[].url_templates from domain_registry.json and outputs
# clickable formatted links for Jira tickets, Jira comments, SMAX requests,
# GitLab MRs, GitLab pipelines, and any future SaaS entity types.
#
# Subcommands:
#   ticket         Format a ticket URL (auto-detects system by prefix)
#   comment        Format a Jira comment URL (requires ticket ID + comment ID)
#   smax           Format an SMAX request URL
#   mr             Format a GitLab merge request URL
#   pipeline       Format a GitLab pipeline URL
#   systems        List configured ticket systems and their entity types
#
# Usage:
#   url_tool ticket DMDI-12050
#   url_tool comment DMDI-12050 1492390
#   url_tool smax 83736206
#   url_tool mr 42 --repo it/data-management/Talend/projects/scripts
#   url_tool pipeline 98765 --repo it/data-management/Talend/projects/scripts
#   url_tool systems
#
# Output modes:
#   --md       Markdown link (default)
#   --plain    Bare URL only
#   --json     JSON object {display, url, type, system}
#
# Contract:
#   This tool and DMDeployinator's Tickets screen are co-consumers of the
#   ticket_systems[].url_templates schema in domain_registry.json.
#
# Exit codes:
#   0  Success
#   1  General error
#   2  Invalid input / missing required argument
#   3  No matching ticket system found
#   4  Registry file not found or unparseable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve registry (first existing file wins):
#   1. $URL_TOOL_REGISTRY env var (explicit override)
#   2. Repo-relative via resolve_base.sh (DIL-portable)
#   3. /az/talend/data/url_tool/domain_registry.json (scripts library — remote servers)
_resolve_registry() {
    if [[ -n "${URL_TOOL_REGISTRY:-}" ]]; then echo "$URL_TOOL_REGISTRY"; return; fi
    if [[ -f "$SCRIPT_DIR/lib/resolve_base.sh" ]]; then
        # shellcheck source=lib/resolve_base.sh
        source "$SCRIPT_DIR/lib/resolve_base.sh"
        local dil_base
        dil_base="$(resolve_dil_base "$SCRIPT_DIR" "${BASE_DIL:-}" 2>/dev/null)" || true
        if [[ -n "$dil_base" && -f "$dil_base/_shared/_meta/domain_registry.json" ]]; then
            echo "$dil_base/_shared/_meta/domain_registry.json"; return
        fi
    fi
    local scripts_lib="/az/talend/data/url_tool/domain_registry.json"
    if [[ -f "$scripts_lib" ]]; then echo "$scripts_lib"; return; fi
    echo "NOT_FOUND"
}
REGISTRY="$(_resolve_registry)"
OUTPUT_MODE="md"

# --- helpers ---

die() { echo "ERROR: $*" >&2; exit "${2:-1}"; }
usage() {
    cat <<'EOF'
url_tool — Zero-inference URL formatter

Usage:
  url_tool ticket <TICKET_ID>                              # auto-detect by prefix
  url_tool comment <TICKET_ID> <COMMENT_ID>                # Jira comment
  url_tool smax <REQUEST_ID>                               # SMAX request
  url_tool mr <MR_ID> --repo <REPO_PATH>                   # GitLab MR
  url_tool pipeline <PIPELINE_ID> --repo <REPO_PATH>       # GitLab pipeline
  url_tool systems                                         # list configured systems

Options:
  --md        Markdown link output (default)
  --plain     Bare URL output
  --json      JSON object output
  --registry  Override registry file path
  -h, --help  Show this help
EOF
    exit 0
}

check_deps() {
    command -v jq >/dev/null 2>&1 || die "jq is required but not found" 4
    [[ -f "$REGISTRY" ]] || die "Registry not found: $REGISTRY" 4
}

# Read a url_template for a given system type and entity type from the registry
# Args: $1=system_type (jira, smax, gitlab), $2=entity_type (ticket, comment, mr, pipeline)
get_template() {
    local sys_type="$1" entity_type="$2"
    jq -r --arg st "$sys_type" --arg et "$entity_type" '
        [.domains[].ticket_systems[]? | select(.type == $st)] | first |
        if . == null then "NOT_FOUND"
        else .url_templates[$et] // "NOT_FOUND"
        end
    ' "$REGISTRY"
}

# Read a field from a ticket_system entry
# Args: $1=system_type, $2=field_name
get_sys_field() {
    local sys_type="$1" field="$2"
    jq -r --arg st "$sys_type" --arg f "$field" '
        [.domains[].ticket_systems[]? | select(.type == $st)] | first | .[$f] // ""
    ' "$REGISTRY"
}

# Find which system type owns a given ticket prefix
# Args: $1=prefix (e.g. "DMDI")
find_system_by_prefix() {
    local prefix="$1"
    jq -r --arg p "$prefix" '
        [.domains[].ticket_systems[]? | select(.prefixes[]? == $p)] | first | .type // "NOT_FOUND"
    ' "$REGISTRY"
}

# Interpolate a template string with key=value pairs
# Args: $1=template, remaining args are key=value pairs
interpolate() {
    local result="$1"; shift
    while [[ $# -gt 0 ]]; do
        local key="${1%%=*}" val="${1#*=}"
        result="${result//\{$key\}/$val}"
        shift
    done
    echo "$result"
}

# Format output based on mode
# Args: $1=display_text, $2=url, $3=entity_type, $4=system_name
format_output() {
    local display="$1" url="$2" etype="$3" sys="$4"
    case "$OUTPUT_MODE" in
        md)    echo "[$display]($url)" ;;
        plain) echo "$url" ;;
        json)  jq -n --arg d "$display" --arg u "$url" --arg t "$etype" --arg s "$sys" \
                   '{display: $d, url: $u, type: $t, system: $s}' ;;
    esac
}

# --- subcommands ---

cmd_ticket() {
    [[ $# -ge 1 ]] || die "Usage: url_tool ticket <TICKET_ID>" 2
    local ticket_id="$1"
    local prefix="${ticket_id%%-*}"

    local sys_type
    sys_type=$(find_system_by_prefix "$prefix")
    [[ "$sys_type" != "NOT_FOUND" ]] || die "No ticket system found for prefix '$prefix'" 3

    local template
    template=$(get_template "$sys_type" "ticket")
    [[ "$template" != "NOT_FOUND" ]] || die "No 'ticket' url_template for system type '$sys_type'" 3

    local base_url
    base_url=$(get_sys_field "$sys_type" "base_url")

    local url
    url=$(interpolate "$template" "base_url=$base_url" "ticket_id=$ticket_id")

    format_output "$ticket_id" "$url" "ticket" "$sys_type"
}

cmd_comment() {
    [[ $# -ge 2 ]] || die "Usage: url_tool comment <TICKET_ID> <COMMENT_ID>" 2
    local ticket_id="$1" comment_id="$2"
    local prefix="${ticket_id%%-*}"

    local sys_type
    sys_type=$(find_system_by_prefix "$prefix")
    [[ "$sys_type" != "NOT_FOUND" ]] || die "No ticket system found for prefix '$prefix'" 3

    local template
    template=$(get_template "$sys_type" "comment")
    [[ "$template" != "NOT_FOUND" ]] || die "No 'comment' url_template for system type '$sys_type'" 3

    local base_url
    base_url=$(get_sys_field "$sys_type" "base_url")

    local url
    url=$(interpolate "$template" "base_url=$base_url" "ticket_id=$ticket_id" "comment_id=$comment_id")

    format_output "comment $comment_id" "$url" "comment" "$sys_type"
}

cmd_smax() {
    [[ $# -ge 1 ]] || die "Usage: url_tool smax <REQUEST_ID>" 2
    local request_id="$1"

    local template
    template=$(get_template "smax" "ticket")
    [[ "$template" != "NOT_FOUND" ]] || die "No 'ticket' url_template for SMAX" 3

    local base_url
    base_url=$(get_sys_field "smax" "base_url")

    local url
    url=$(interpolate "$template" "base_url=$base_url" "ticket_id=$request_id")

    format_output "SMAX $request_id" "$url" "ticket" "smax"
}

cmd_mr() {
    [[ $# -ge 1 ]] || die "Usage: url_tool mr <MR_ID> --repo <REPO_PATH>" 2
    local mr_id="$1"
    local repo_path=""

    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo) repo_path="$2"; shift 2 ;;
            *) die "Unknown option: $1" 2 ;;
        esac
    done
    [[ -n "$repo_path" ]] || die "url_tool mr requires --repo <REPO_PATH>" 2

    local template
    template=$(get_template "gitlab" "mr")
    [[ "$template" != "NOT_FOUND" ]] || die "No 'mr' url_template for GitLab" 3

    local base_url group_path
    base_url=$(get_sys_field "gitlab" "base_url")
    group_path=$(get_sys_field "gitlab" "group_path")

    local url
    url=$(interpolate "$template" "base_url=$base_url" "group_path=$group_path" "repo_path=$repo_path" "mr_id=$mr_id")

    format_output "MR !$mr_id" "$url" "mr" "gitlab"
}

cmd_pipeline() {
    [[ $# -ge 1 ]] || die "Usage: url_tool pipeline <PIPELINE_ID> --repo <REPO_PATH>" 2
    local pipeline_id="$1"
    local repo_path=""

    shift
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo) repo_path="$2"; shift 2 ;;
            *) die "Unknown option: $1" 2 ;;
        esac
    done
    [[ -n "$repo_path" ]] || die "url_tool pipeline requires --repo <REPO_PATH>" 2

    local template
    template=$(get_template "gitlab" "pipeline")
    [[ "$template" != "NOT_FOUND" ]] || die "No 'pipeline' url_template for GitLab" 3

    local base_url group_path
    base_url=$(get_sys_field "gitlab" "base_url")
    group_path=$(get_sys_field "gitlab" "group_path")

    local url
    url=$(interpolate "$template" "base_url=$base_url" "group_path=$group_path" "repo_path=$repo_path" "pipeline_id=$pipeline_id")

    format_output "pipeline $pipeline_id" "$url" "pipeline" "gitlab"
}

cmd_systems() {
    jq -r '
        [.domains[] | .ticket_systems[]? | {name, type, base_url, entities: (.url_templates // {} | keys)}] |
        if length == 0 then "No ticket systems configured."
        else .[] | "\(.name) (\(.type)) — \(.base_url)\n  entities: \(.entities | join(", "))"
        end
    ' "$REGISTRY"
}

# --- main ---

main() {
    # Parse global options first
    local args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --md)       OUTPUT_MODE="md"; shift ;;
            --plain)    OUTPUT_MODE="plain"; shift ;;
            --json)     OUTPUT_MODE="json"; shift ;;
            --registry) REGISTRY="$2"; shift 2 ;;
            -h|--help)  usage ;;
            *)          args+=("$1"); shift ;;
        esac
    done
    set -- "${args[@]}"

    [[ $# -ge 1 ]] || usage
    check_deps

    local cmd="$1"; shift
    case "$cmd" in
        ticket)   cmd_ticket "$@" ;;
        comment)  cmd_comment "$@" ;;
        smax)     cmd_smax "$@" ;;
        mr)       cmd_mr "$@" ;;
        pipeline) cmd_pipeline "$@" ;;
        systems)  cmd_systems ;;
        -h|--help) usage ;;
        *)        die "Unknown subcommand: $cmd. Run 'url_tool --help' for usage." 2 ;;
    esac
}

main "$@"
