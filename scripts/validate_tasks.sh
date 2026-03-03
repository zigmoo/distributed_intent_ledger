#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-/home/moo/Documents/dil_agentic_memory_0001}"
WORK_DIR="$BASE/_shared/tasks/work"
PERSONAL_DIR="$BASE/_shared/tasks/personal"
INDEX_FILE="$BASE/_shared/_meta/task_index.md"
COUNTER_FILE="$BASE/_shared/_meta/task_id_counter.md"
CHANGE_LOG="$BASE/_shared/tasks/_meta/change_log.md"

errors=0
warnings=0

declare -A seen_task_ids
declare -A seen_task_domains
declare -A declared_status
declare -A parent_of

declare -A log_last_status

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
    low|normal|high|critical) return 0 ;;
    *) return 1 ;;
  esac
}

valid_work_type() {
  case "$1" in
    feature|bug|chore|research|infrastructure) return 0 ;;
    *) return 1 ;;
  esac
}

valid_task_type() {
  case "$1" in
    kanban|sprint|epic|spike) return 0 ;;
    *) return 1 ;;
  esac
}

valid_effort_type() {
  case "$1" in
    low|medium|high) return 0 ;;
    *) return 1 ;;
  esac
}

valid_transition() {
  local old="$1"
  local new="$2"
  # Any status can transition to retired
  if [[ "$new" == "retired" ]]; then
    return 0
  fi
  case "$old" in
    todo) [[ "$new" =~ ^(assigned|in_progress|blocked|cancelled)$ ]] ;;
    assigned) [[ "$new" =~ ^(in_progress|blocked|done|cancelled)$ ]] ;;
    in_progress) [[ "$new" =~ ^(blocked|done|assigned|cancelled)$ ]] ;;
    blocked) [[ "$new" =~ ^(in_progress|assigned|cancelled)$ ]] ;;
    retired) [[ "$new" =~ ^(todo|in_progress)$ ]] ;;
    done|cancelled) return 1 ;;
    *) return 1 ;;
  esac
}

required_keys=(
  title date machine assistant category memoryType priority tags updated source
  domain project status owner due work_type task_type effort_type task_id created_by model created_at
  task_schema parent_task_id agents
)

nonempty_keys=(
  title date machine assistant category memoryType priority tags updated source
  domain status owner work_type task_type effort_type task_id created_by model created_at task_schema
)

mapfile -t task_files < <(
  find "$WORK_DIR" "$PERSONAL_DIR" -maxdepth 1 -type f -name '*.md' 2>/dev/null | sort
)

if [[ ${#task_files[@]} -eq 0 ]]; then
  err "No canonical task files found in $WORK_DIR or $PERSONAL_DIR"
fi

for f in "${task_files[@]}"; do
  domain_expected=""
  case "$f" in
    "$WORK_DIR"/*) domain_expected="work" ;;
    "$PERSONAL_DIR"/*) domain_expected="personal" ;;
  esac

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
  work_type="$(get_key "$f" work_type || true)"
  task_type="$(get_key "$f" task_type || true)"
  effort_type="$(get_key "$f" effort_type || true)"
  parent="$(get_key "$f" parent_task_id || true)"
  schema="$(get_key "$f" task_schema || true)"

  if [[ -z "$task_id" ]]; then
    err "$f has empty task_id; cannot complete validation for this file"
    continue
  fi

  if [[ "$domain" != "$domain_expected" ]]; then
    err "$f domain '$domain' does not match directory domain '$domain_expected'"
  fi

  if [[ "$domain" == "work" ]]; then
    if [[ ! "$task_id" =~ ^[A-Z]+-[0-9]+$ ]]; then
      err "$f work task_id must match ^[A-Z]+-[0-9]+$: got '$task_id'"
    fi
  fi
  if [[ "$domain" == "personal" ]]; then
    if [[ ! "$task_id" =~ ^DIL-[0-9]+$ ]]; then
      err "$f personal task_id must match ^DIL-[0-9]+$: got '$task_id'"
    fi
  fi

  if ! valid_status "$status"; then
    err "$f has invalid status '$status'"
  fi

  if ! valid_priority "$priority"; then
    err "$f has invalid priority '$priority'"
  fi

  if ! valid_work_type "$work_type"; then
    err "$f has invalid work_type '$work_type'"
  fi

  if ! valid_task_type "$task_type"; then
    err "$f has invalid task_type '$task_type'"
  fi

  if ! valid_effort_type "$effort_type"; then
    err "$f has invalid effort_type '$effort_type'"
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

  # Exact index row check catches malformed column order.
  rel="_shared/tasks/$domain/$task_id.md"
  expected_row="| $task_id | $domain | $status | $priority | $owner | $due | $project | $rel | $updated |"
  if ! grep -Fxq "$expected_row" "$INDEX_FILE"; then
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
