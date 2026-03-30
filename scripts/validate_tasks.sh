#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIL_BASE="${1:-${DIL_BASE:-$(cd "$SCRIPT_DIR/.." && pwd)}}"
REGISTRY="$DIL_BASE/_shared/_meta/domain_registry.json"
INDEX_FILE="$DIL_BASE/_shared/_meta/task_index.md"
COUNTER_FILE="$DIL_BASE/_shared/_meta/task_id_counter.md"
CHANGE_LOG="$DIL_BASE/_shared/tasks/_meta/change_log.md"

errors=0
warnings=0

declare -A seen_task_ids
declare -A seen_task_domains
declare -A declared_status
declare -A parent_of
declare -A log_last_status

# Domain-to-directory mapping: populated from registry + legacy fallback
declare -A domain_dirs
declare -A domain_id_prefix
declare -A domain_id_mode

# Load domains from registry if available
if [[ -f "$REGISTRY" ]] && command -v jq >/dev/null 2>&1; then
  while IFS= read -r dname; do
    raw_task_dir=$(jq -r --arg d "$dname" '.domains[$d].task_dir' "$REGISTRY")
    if [[ "$raw_task_dir" == /* ]]; then
      resolved="$raw_task_dir"
    else
      resolved="$DIL_BASE/$raw_task_dir"
    fi
    # Support both active/ subdir (new) and flat dir (legacy)
    if [[ -d "$resolved/active" ]]; then
      domain_dirs["$dname"]="$resolved/active"
    elif [[ -d "$resolved" ]]; then
      domain_dirs["$dname"]="$resolved"
    fi
    # Also scan archived dirs
    if [[ -d "$resolved/archived" ]]; then
      while IFS= read -r year_dir; do
        domain_dirs["${dname}__archived__$(basename "$year_dir")"]="$year_dir"
      done < <(find "$resolved/archived" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    fi
    domain_id_prefix["$dname"]=$(jq -r --arg d "$dname" '.domains[$d].id_prefix' "$REGISTRY")
    domain_id_mode["$dname"]=$(jq -r --arg d "$dname" '.domains[$d].id_mode' "$REGISTRY")
  done < <(jq -r '.domains | keys[]' "$REGISTRY")
fi

# Also check legacy paths (coexist during migration)
if [[ -d "$DIL_BASE/_shared/tasks/work" ]]; then
  domain_dirs[work__legacy]="$DIL_BASE/_shared/tasks/work"
  domain_id_prefix[work]="${domain_id_prefix[work]:-DMDI}"
  domain_id_mode[work]="${domain_id_mode[work]:-external}"
fi
if [[ -d "$DIL_BASE/_shared/tasks/personal" ]]; then
  domain_dirs[personal__legacy]="$DIL_BASE/_shared/tasks/personal"
  domain_id_prefix[personal]="${domain_id_prefix[personal]:-DIL}"
  domain_id_mode[personal]="${domain_id_mode[personal]:-auto}"
fi

trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

err() {
  echo "ERROR: $*"
  errors=$((errors + 1))
}

warn() {
  echo "WARN: $*"
  warnings=$((warnings + 1))
}

has_key() {
  local file="$1"
  local key="$2"
  awk -v k="$key" '
    BEGIN {dash=0; inside=0}
    $0=="---" {dash++; if (dash==1) {inside=1; next} if (dash==2) {inside=0}}
    inside && $0 ~ ("^" k ":") {found=1}
    END {exit(found?0:1)}
  ' "$file"
}

get_key() {
  local file="$1"
  local key="$2"
  awk -v k="$key" '
    BEGIN {dash=0; inside=0}
    $0=="---" {dash++; if (dash==1) {inside=1; next} if (dash==2) {inside=0}}
    inside && $0 ~ ("^" k ":") {
      sub("^" k ":[[:space:]]*", "", $0)
      print $0
      exit
    }
  ' "$file" | trim | sed -e 's/^"//' -e 's/"$//'
}

frontmatter_block() {
  local file="$1"
  awk '
    BEGIN {dash=0; inside=0}
    $0=="---" {
      dash++
      if (dash==1) {inside=1; next}
      if (dash==2) {inside=0; exit}
    }
    inside {print}
  ' "$file"
}

valid_status() {
  case "$1" in
    todo|assigned|in_progress|blocked|done|cancelled|retired) return 0 ;;
    *) return 1 ;;
  esac
}

valid_priority() {
  case "$1" in
    low|normal|medium|high|critical) return 0 ;;
    *) return 1 ;;
  esac
}

valid_transition() {
  local old="$1"
  local new="$2"
  case "$old" in
    todo) [[ "$new" =~ ^(assigned|in_progress|blocked|cancelled|retired)$ ]] ;;
    assigned) [[ "$new" =~ ^(in_progress|blocked|done|cancelled|retired)$ ]] ;;
    in_progress) [[ "$new" =~ ^(blocked|done|assigned|cancelled|retired)$ ]] ;;
    blocked) [[ "$new" =~ ^(in_progress|assigned|cancelled|retired)$ ]] ;;
    done|cancelled) [[ "$new" =~ ^(retired)$ ]] ;;
    retired) [[ "$new" =~ ^(todo|in_progress)$ ]] ;;
    *) return 1 ;;
  esac
}

required_keys=(
  title date machine assistant category memoryType priority tags updated source
  domain project status owner due task_id created_by model created_at
  task_schema parent_task_id agents
)

nonempty_keys=(
  title date machine assistant category memoryType priority tags updated source
  domain status owner task_id created_by model created_at task_schema
)

# Collect all task files across all domain directories
mapfile -t task_files < <(
  for dir_key in "${!domain_dirs[@]}"; do
    dir="${domain_dirs[$dir_key]}"
    if [[ -d "$dir" ]]; then
      find "$dir" -maxdepth 1 -type f -name '*.md' ! -name 'index.md' 2>/dev/null
    fi
  done | sort
)

if [[ ${#task_files[@]} -eq 0 ]]; then
  err "No canonical task files found in any registered domain directory"
fi

# Build reverse map: directory -> domain name (for domain_expected resolution)
declare -A dir_to_domain
for dir_key in "${!domain_dirs[@]}"; do
  # Strip __archived__YYYY or __legacy suffix to get base domain
  base_domain="${dir_key%%__*}"
  dir_to_domain["${domain_dirs[$dir_key]}"]="$base_domain"
done

for f in "${task_files[@]}"; do
  parent_dir="$(dirname "$f")"
  domain_expected="${dir_to_domain[$parent_dir]:-}"

  if [[ -z "$domain_expected" ]]; then
    warn "$f is in an unrecognized directory; skipping domain check"
  fi

  for k in "${required_keys[@]}"; do
    if ! has_key "$f" "$k"; then
      err "$f missing required key: $k"
    fi
  done

  for k in "${nonempty_keys[@]}"; do
    v="$(get_key "$f" "$k" || true)"
    if [[ -z "$v" ]]; then
      err "$f has empty required value: $k"
    fi
  done

  task_id="$(get_key "$f" task_id || true)"
  domain="$(get_key "$f" domain || true)"
  status="$(get_key "$f" status || true)"
  owner="$(get_key "$f" owner || true)"
  priority="$(get_key "$f" priority || true)"
  due="$(get_key "$f" due || true)"
  project="$(get_key "$f" project || true)"
  updated="$(get_key "$f" updated || true)"
  parent="$(get_key "$f" parent_task_id || true)"
  schema="$(get_key "$f" task_schema || true)"

  if [[ -z "$task_id" ]]; then
    err "$f has empty task_id; cannot complete validation for this file"
    continue
  fi

  if [[ -n "$domain_expected" && "$domain" != "$domain_expected" ]]; then
    err "$f domain '$domain' does not match directory domain '$domain_expected'"
  fi

  # Validate task_id format based on domain's id_mode
  id_mode="${domain_id_mode[$domain]:-}"
  id_prefix="${domain_id_prefix[$domain]:-}"
  if [[ "$id_mode" == "external" ]]; then
    if [[ ! "$task_id" =~ ^[A-Z]+-[0-9]+$ ]]; then
      err "$f $domain task_id must match ^[A-Z]+-[0-9]+$: got '$task_id'"
    fi
  elif [[ "$id_mode" == "auto" && -n "$id_prefix" ]]; then
    if [[ ! "$task_id" =~ ^${id_prefix}-[0-9]+$ ]]; then
      err "$f $domain task_id must match ^${id_prefix}-[0-9]+\$: got '$task_id'"
    fi
  fi

  if ! valid_status "$status"; then
    err "$f has invalid status '$status'"
  fi

  if ! valid_priority "$priority"; then
    err "$f has invalid priority '$priority'"
  fi

  if [[ "$schema" != "v1" ]]; then
    err "$f task_schema must be v1, got '$schema'"
  fi

  if [[ -n "${seen_task_ids[$task_id]:-}" ]]; then
    err "Duplicate task_id '$task_id' in $f and ${seen_task_ids[$task_id]}"
  else
    seen_task_ids["$task_id"]="$f"
    seen_task_domains["$task_id"]="$domain"
  fi

  fm="$(frontmatter_block "$f")"

  # Agent checks: must have at least one, first must be accountable with order 1.
  agent_count="$(printf '%s\n' "$fm" | awk '/^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {c++} END{print c+0}')"
  if [[ "$agent_count" -lt 1 ]]; then
    err "$f must include at least one agent in agents list"
  else
    first_role="$(printf '%s\n' "$fm" | awk '
      BEGIN{in_agents=0; idx=0; role=""}
      /^agents:/ {in_agents=1; next}
      in_agents && /^[^[:space:]]/ {in_agents=0}
      in_agents && /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {idx++; next}
      in_agents && idx==1 && /^[[:space:]]*role:[[:space:]]*/ {sub(/^[[:space:]]*role:[[:space:]]*/,""); print; exit}
    ' | trim)"
    first_order="$(printf '%s\n' "$fm" | awk '
      BEGIN{in_agents=0; idx=0}
      /^agents:/ {in_agents=1; next}
      in_agents && /^[^[:space:]]/ {in_agents=0}
      in_agents && /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {idx++; next}
      in_agents && idx==1 && /^[[:space:]]*responsibility_order:[[:space:]]*/ {sub(/^[[:space:]]*responsibility_order:[[:space:]]*/,""); print; exit}
    ' | trim)"
    first_id="$(printf '%s\n' "$fm" | awk '
      BEGIN{in_agents=0}
      /^agents:/ {in_agents=1; next}
      in_agents && /^[^[:space:]]/ {in_agents=0}
      in_agents && /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {sub(/^[[:space:]]*-[[:space:]]*id:[[:space:]]*/,""); print; exit}
    ' | trim | sed -e 's/^"//' -e 's/"$//')"

    if [[ "$first_role" != "accountable" ]]; then
      err "$f first agent role must be accountable (got '$first_role')"
    fi
    if [[ "$first_order" != "1" ]]; then
      err "$f first agent responsibility_order must be 1 (got '$first_order')"
    fi
    if [[ -n "$first_id" && "$owner" != "$first_id" ]]; then
      err "$f owner must match accountable agent id (owner='$owner', accountable='$first_id')"
    fi

    # Ensure columbus, if present, is reviewer.
    columbus_bad="$(printf '%s\n' "$fm" | awk '
      BEGIN{in_agents=0; current=""; bad=0}
      /^agents:/ {in_agents=1; next}
      in_agents && /^[^[:space:]]/ {in_agents=0}
      in_agents && /^[[:space:]]*-[[:space:]]*id:[[:space:]]*/ {current=$0; sub(/^[[:space:]]*-[[:space:]]*id:[[:space:]]*/,"",current); gsub(/^"|"$/,"",current); next}
      in_agents && current=="columbus" && /^[[:space:]]*role:[[:space:]]*/ {role=$0; sub(/^[[:space:]]*role:[[:space:]]*/,"",role); if (role!="reviewer" && role!="accountable") bad=1}
      END{print bad}
    ')"
    if [[ "$columbus_bad" == "1" ]]; then
      err "$f columbus role must be reviewer (or accountable when first)"
    fi
  fi

  if [[ -n "$parent" ]]; then
    if [[ "$parent" == "$task_id" ]]; then
      err "$f parent_task_id cannot self-reference ($task_id)"
    fi
    if [[ ! "$parent" =~ ^(DIL-[0-9]+|[A-Z]+-[0-9]+)$ ]]; then
      err "$f invalid parent_task_id format '$parent'"
    fi
    parent_of["$task_id"]="$parent"
  fi

  # Index row check: accept both old (_shared/tasks/) and new (_shared/domains/) path formats
  rel_old="_shared/tasks/$domain/$task_id.md"
  rel_new="_shared/domains/$domain/tasks/active/$task_id.md"
  rel_archived_prefix="_shared/domains/$domain/tasks/archived/"
  expected_row_old="| $task_id | $domain | $status | $priority | $owner | $due | $project | $rel_old | $updated |"
  expected_row_new="| $task_id | $domain | $status | $priority | $owner | $due | $project | $rel_new | $updated |"

  found_row=0
  if grep -Fxq "$expected_row_old" "$INDEX_FILE" 2>/dev/null; then
    found_row=1
  elif grep -Fxq "$expected_row_new" "$INDEX_FILE" 2>/dev/null; then
    found_row=1
  elif grep -q "| $task_id |.*${rel_archived_prefix}" "$INDEX_FILE" 2>/dev/null; then
    # Archived task — check it has the right non-path fields
    found_row=1
  fi

  if [[ "$found_row" -eq 0 ]]; then
    err "$INDEX_FILE missing exact row for $task_id"
  fi

  row_count="$(grep -Ec "^\|[[:space:]]*$task_id[[:space:]]*\|" "$INDEX_FILE" || true)"
  if [[ "$row_count" != "1" ]]; then
    err "$INDEX_FILE should contain exactly one row for $task_id (found $row_count)"
  fi

  declared_status["$task_id"]="$status"
done

# Parent existence and cycle checks.
for tid in "${!parent_of[@]}"; do
  pid="${parent_of[$tid]}"
  if [[ -z "${seen_task_ids[$pid]:-}" ]]; then
    err "Task $tid references missing parent_task_id $pid"
  fi
done

for tid in "${!parent_of[@]}"; do
  current="$tid"
  seen_chain=""
  while :; do
    next="${parent_of[$current]:-}"
    [[ -n "$next" ]] || break
    if [[ "$next" == "$tid" ]]; then
      err "Cycle detected in parent_task_id chain starting at $tid"
      break
    fi
    if [[ ",$seen_chain," == *",$next,"* ]]; then
      err "Cycle detected in parent_task_id chain involving $tid"
      break
    fi
    seen_chain="${seen_chain}${seen_chain:+,}$next"
    current="$next"
  done
done

# Counter validation: check all auto-mode domain counters
if [[ -f "$COUNTER_FILE" ]]; then
  next_id="$(awk -F: '/^- next_id:/ {gsub(/ /, "", $2); print $2; exit}' "$COUNTER_FILE")"
  if [[ -z "$next_id" || ! "$next_id" =~ ^[0-9]+$ ]]; then
    err "Invalid or missing next_id in $COUNTER_FILE"
  else
    max_personal=1099
    for task_id in "${!seen_task_ids[@]}"; do
      if [[ "$task_id" =~ ^DIL-([0-9]+)$ ]]; then
        n="${BASH_REMATCH[1]}"
        if (( n > max_personal )); then
          max_personal="$n"
        fi
      fi
    done
    expected_next=$((max_personal + 1))
    if (( next_id != expected_next )); then
      err "Counter mismatch in $COUNTER_FILE: next_id=$next_id expected=$expected_next"
    fi
  fi
else
  err "Missing counter file: $COUNTER_FILE"
fi

if [[ -f "$CHANGE_LOG" ]]; then
  if ! rg -q "^\|[[:space:]]*timestamp[[:space:]]*\|[[:space:]]*actor[[:space:]]*\|[[:space:]]*model[[:space:]]*\|" "$CHANGE_LOG"; then
    err "Change log header must include model column: $CHANGE_LOG"
  fi

  while IFS= read -r line; do
    [[ "$line" =~ ^\| ]] || continue
    [[ "$line" =~ ^\|[[:space:]]*--- ]] && continue
    [[ "$line" =~ ^\|[[:space:]]*timestamp[[:space:]]*\| ]] && continue

    IFS='|' read -r _ c1 c2 c3 c4 c5 c6 c7 _ <<< "$line"
    task_id="$(printf '%s' "$c4" | trim)"
    field_changes="$(printf '%s' "$c6" | trim)"

    if [[ "$field_changes" =~ status:[[:space:]]*([a-z_]+)\-\>([a-z_]+) ]]; then
      old_status="${BASH_REMATCH[1]}"
      new_status="${BASH_REMATCH[2]}"
      if ! valid_transition "$old_status" "$new_status"; then
        err "Invalid status transition in log for '$task_id': $old_status->$new_status"
      fi
      log_last_status["$task_id"]="$new_status"
    fi
  done < "$CHANGE_LOG"
else
  err "Missing change log: $CHANGE_LOG"
fi

for task_id in "${!log_last_status[@]}"; do
  if [[ -n "${declared_status[$task_id]:-}" ]]; then
    if [[ "${declared_status[$task_id]}" != "${log_last_status[$task_id]}" ]]; then
      err "Status mismatch for $task_id: file=${declared_status[$task_id]} log_last=${log_last_status[$task_id]}"
    fi
  fi
done

if (( errors > 0 )); then
  echo "Validation failed: $errors error(s), $warnings warning(s)"
  exit 1
fi

echo "Validation passed: ${#task_files[@]} task(s), $warnings warning(s)"
