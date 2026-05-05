#!/usr/bin/env bash
# git_tool - DIL-compliant, agent-safe wrapper for common Git operations.
#
# Direct-use script for humans and agents. It intentionally exposes a narrow
# allowlist of Git operations and refuses destructive actions by design.

set -euo pipefail

SCRIPT_NAME="git_tool"
SCRIPT_VERSION="2026-04-15"
SCRIPT_AUTHOR="codex"
SCRIPT_MODEL="gpt-5.4"
SCRIPT_OWNER="moo"
IMPLEMENTATION_TASK_ID="DIL-1453"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_NAME"

# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
# shellcheck source=lib/domains.sh
source "$SCRIPT_DIR/../lib/domains.sh"

BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"
resolve_domain personal

ACTION="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

OUTPUT_MODE="text"
REPO_INPUT=""
ASSUME_YES=0
MESSAGE=""
MAX_COUNT="10"
DIFF_MODE="full"
REMOTE=""
BRANCH=""
START_POINT=""
MERGE_MODE="ff-only"
FILES=()

START_TS="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
START_US="$(date -u +%s%6N)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
HOSTNAME_SHORT="$(hostname -s | tr '[:upper:]' '[:lower:]')"

LOG_ROOT="$LOG_DIR/$SCRIPT_NAME"
DATA_ROOT="$DATA_DIR/$SCRIPT_NAME"
mkdir -p "$LOG_ROOT" "$DATA_ROOT"

LOG_FILE="$LOG_ROOT/${SCRIPT_NAME}.${ACTION}.${STAMP}.$$.log"
DATA_FILE="$DATA_ROOT/${SCRIPT_NAME}.${ACTION}.${STAMP}.$$.json"
LATEST_DATA_FILE="$DATA_ROOT/${SCRIPT_NAME}.${ACTION}.latest.json"
TMP_OUT="$(mktemp)"
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_OUT" "$TMP_ERR"' EXIT

usage() {
  cat <<'EOF'
git_tool - DIL-compliant, agent-safe wrapper for common Git operations

Usage:
  git_tool <subcommand> [options]

Read-only subcommands:
  status              Show porcelain and branch status
  summary             Repo summary: branch, head, upstream, dirty files, remotes
  diff                Show diff; supports --stat, --name-only, --cached
  log                 Show recent commits
  branch              Show branch information
  remotes             Show configured remotes
  files-changed       List changed files
  is-clean            Exit 0 if clean, 1 if dirty
  root                Print repository root

Guarded write subcommands:
  add -- FILE...       Stage files
  commit -m MESSAGE    Commit staged changes
  pull                 Pull from upstream
  push                 Push current branch
  branch-create NAME   Create a branch
  branch-switch NAME   Switch branches using git switch
  branch-delete NAME   Delete a fully merged local branch; requires --yes
  merge BRANCH         Merge a branch; defaults to --ff-only and requires --yes

Options:
  --repo PATH          Repository path. Defaults to current directory.
  --json               Emit JSON artifact content to stdout.
  --max N              Commit count for log. Default: 10.
  --stat               For diff, show diff stat.
  --name-only          For diff, show changed names only.
  --cached             For diff, show staged diff.
  -m, --message TEXT   Commit message.
  --yes                Required for pull and push.
  --remote NAME        Remote for pull/push. Default: upstream/default remote.
  --branch NAME        Branch for pull/push. Default: current branch.
  --start-point REF    Start point for branch-create.
  --ff-only            Merge only if fast-forward is possible. Default for merge.
  --no-ff              Allow a non-fast-forward merge commit. Requires clean tree.
  -h, --help           Show help.

Refused by design:
  reset --hard, clean, force push, checkout/restore file reverts, rebase.
EOF
}

die() {
  local code="${2:-1}"
  echo "ERROR: $1" >&2
  exit "$code"
}

log_line() {
  local level="$1"
  shift
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  printf '[%s] [%s] [%s] %s\n' "$ts" "$SCRIPT_NAME" "$level" "$*" >> "$LOG_FILE"
}

format_duration() {
  local total_us="$1"
  local hours=$((total_us / 3600000000))
  local rem=$((total_us % 3600000000))
  local mins=$((rem / 60000000))
  rem=$((rem % 60000000))
  local secs=$((rem / 1000000))
  local frac=$(((rem % 1000000) / 100))
  printf '%02dh%02dm%02d.%04ds' "$hours" "$mins" "$secs" "$frac"
}

parse_common_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo)
        REPO_INPUT="${2:-}"
        [[ -n "$REPO_INPUT" ]] || die "--repo requires a path" 2
        shift 2
        ;;
      --json)
        OUTPUT_MODE="json"
        shift
        ;;
      --max)
        MAX_COUNT="${2:-}"
        [[ "$MAX_COUNT" =~ ^[0-9]+$ ]] || die "--max requires an integer" 2
        shift 2
        ;;
      --stat)
        DIFF_MODE="stat"
        shift
        ;;
      --name-only)
        DIFF_MODE="name-only"
        shift
        ;;
      --cached)
        if [[ "$DIFF_MODE" == "full" ]]; then
          DIFF_MODE="cached"
        else
          DIFF_MODE="${DIFF_MODE}-cached"
        fi
        shift
        ;;
      -m|--message)
        MESSAGE="${2:-}"
        [[ -n "$MESSAGE" ]] || die "--message requires text" 2
        shift 2
        ;;
      --yes)
        ASSUME_YES=1
        shift
        ;;
      --remote)
        REMOTE="${2:-}"
        [[ -n "$REMOTE" ]] || die "--remote requires a name" 2
        shift 2
        ;;
      --branch)
        BRANCH="${2:-}"
        [[ -n "$BRANCH" ]] || die "--branch requires a name" 2
        shift 2
        ;;
      --start-point)
        START_POINT="${2:-}"
        [[ -n "$START_POINT" ]] || die "--start-point requires a ref" 2
        shift 2
        ;;
      --ff-only)
        MERGE_MODE="ff-only"
        shift
        ;;
      --no-ff)
        MERGE_MODE="no-ff"
        shift
        ;;
      --)
        shift
        FILES+=("$@")
        break
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        FILES+=("$1")
        shift
        ;;
    esac
  done
}

resolve_repo() {
  local candidate="${REPO_INPUT:-$PWD}"
  [[ -d "$candidate" ]] || die "Repository path is not a directory: $candidate" 2
  git -C "$candidate" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Not inside a Git worktree: $candidate" 2
  git -C "$candidate" rev-parse --show-toplevel
}

git_capture() {
  local repo="$1"
  shift
  git -C "$repo" "$@"
}

write_artifact() {
  local repo="$1"
  local status="$2"
  local exit_code="$3"
  local stdout_file="$4"
  local stderr_file="$5"
  local end_ts end_us duration_us duration_human branch head dirty_count
  end_ts="$(date -u +%Y-%m-%dT%H:%M:%S.%6NZ)"
  end_us="$(date -u +%s%6N)"
  duration_us=$((end_us - START_US))
  duration_human="$(format_duration "$duration_us")"
  branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  head="$(git -C "$repo" rev-parse HEAD 2>/dev/null || true)"
  dirty_count="$(git -C "$repo" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"

  jq -n \
    --arg script_name "$SCRIPT_NAME" \
    --arg script_version "$SCRIPT_VERSION" \
    --arg implementation_task_id "$IMPLEMENTATION_TASK_ID" \
    --arg action "$ACTION" \
    --arg status "$status" \
    --argjson exit_code "$exit_code" \
    --arg hostname_short "$HOSTNAME_SHORT" \
    --arg start_ts_utc "$START_TS" \
    --arg end_ts_utc "$end_ts" \
    --arg duration_human "$duration_human" \
    --arg repo "$repo" \
    --arg branch "$branch" \
    --arg head "$head" \
    --argjson dirty_count "$dirty_count" \
    --arg log_file "$LOG_FILE" \
    --arg data_file "$DATA_FILE" \
    --rawfile stdout "$stdout_file" \
    --rawfile stderr "$stderr_file" \
    '{
      script_name: $script_name,
      script_version: $script_version,
      implementation_task_id: $implementation_task_id,
      action: $action,
      status: $status,
      exit_code: $exit_code,
      hostname_short: $hostname_short,
      start_ts_utc: $start_ts_utc,
      end_ts_utc: $end_ts_utc,
      duration_human: $duration_human,
      repo: $repo,
      branch: $branch,
      head: $head,
      dirty_count: $dirty_count,
      log_file: $log_file,
      data_file: $data_file,
      stdout: $stdout,
      stderr: $stderr
    }' > "$DATA_FILE"
  cp "$DATA_FILE" "$LATEST_DATA_FILE"
}

run_git_command() {
  local repo="$1"
  shift
  log_line INFO "command: git -C $repo $*"
  set +e
  git_capture "$repo" "$@" >"$TMP_OUT" 2>"$TMP_ERR"
  local rc=$?
  set -e
  if [[ -s "$TMP_ERR" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      log_line STDERR "$line"
    done < "$TMP_ERR"
  fi
  if [[ -s "$TMP_OUT" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      log_line STDOUT "$line"
    done < "$TMP_OUT"
  fi
  return "$rc"
}

emit_output() {
  if [[ "$OUTPUT_MODE" == "json" ]]; then
    cat "$DATA_FILE"
  elif [[ -s "$TMP_OUT" ]]; then
    cat "$TMP_OUT"
  fi
}

require_clean_for_pull() {
  local repo="$1"
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    die "Refusing pull with local changes. Commit/stash first." 3
  fi
}

require_clean_worktree() {
  local repo="$1"
  local reason="$2"
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    die "Refusing $reason with local changes. Commit/stash first." 3
  fi
}

require_branch_name() {
  local name="$1"
  [[ -n "$name" ]] || die "branch name is required" 2
  case "$name" in
    -*|*..*|*~*|*^*|*:*|*\\*|*'?'*|*'['*|*' '*)
      die "Unsafe branch/ref name: $name" 2
      ;;
  esac
}

require_yes() {
  local action_label="$1"
  [[ "$ASSUME_YES" -eq 1 ]] || die "$action_label requires --yes" 2
}

parse_common_args "$@"

case "$ACTION" in
  help|-h|--help)
    usage
    exit 0
    ;;
  reset|clean|rebase|checkout|restore)
    die "Refusing destructive or high-risk git action: $ACTION" 4
    ;;
esac

command -v git >/dev/null 2>&1 || die "git is required but not found" 127
command -v jq >/dev/null 2>&1 || die "jq is required but not found" 127

REPO="$(resolve_repo)"

log_line INFO "script_name: $SCRIPT_NAME"
log_line INFO "script_version: $SCRIPT_VERSION"
log_line INFO "script_author: $SCRIPT_AUTHOR"
log_line INFO "script_model: $SCRIPT_MODEL"
log_line INFO "script_owner: $SCRIPT_OWNER"
log_line INFO "implementation_task_id: $IMPLEMENTATION_TASK_ID"
log_line INFO "hostname_short: $HOSTNAME_SHORT"
log_line INFO "pid: $$"
log_line INFO "start_ts_utc: $START_TS"
log_line INFO "base_dil: $BASE"
log_line INFO "script_path: $SCRIPT_PATH"
log_line INFO "repo: $REPO"
log_line INFO "log_file: $LOG_FILE"
log_line INFO "data_file: $DATA_FILE"
log_line INFO "latest_data_file: $LATEST_DATA_FILE"

RC=0
case "$ACTION" in
  root)
    printf '%s\n' "$REPO" > "$TMP_OUT"
    ;;
  status)
    run_git_command "$REPO" status --short --branch || RC=$?
    ;;
  summary)
    {
      echo "repo: $REPO"
      echo "branch: $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
      echo "head: $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || true)"
      echo "upstream: $(git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
      echo "dirty_count: $(git -C "$REPO" status --porcelain | wc -l | tr -d ' ')"
      echo "changed_files:"
      git -C "$REPO" status --porcelain | sed 's/^/  /'
      echo "remotes:"
      git -C "$REPO" remote -v | sed 's/^/  /'
    } > "$TMP_OUT"
    ;;
  diff)
    case "$DIFF_MODE" in
      stat) run_git_command "$REPO" diff --stat || RC=$? ;;
      name-only) run_git_command "$REPO" diff --name-only || RC=$? ;;
      cached) run_git_command "$REPO" diff --cached || RC=$? ;;
      stat-cached) run_git_command "$REPO" diff --cached --stat || RC=$? ;;
      name-only-cached) run_git_command "$REPO" diff --cached --name-only || RC=$? ;;
      full) run_git_command "$REPO" diff || RC=$? ;;
      *) die "Unsupported diff mode: $DIFF_MODE" 2 ;;
    esac
    ;;
  log)
    run_git_command "$REPO" log "--max-count=$MAX_COUNT" --decorate --oneline --graph || RC=$?
    ;;
  branch)
    run_git_command "$REPO" branch -vv || RC=$?
    ;;
  branch-create)
    target="${FILES[0]:-${BRANCH:-}}"
    require_branch_name "$target"
    if [[ -n "$START_POINT" ]]; then
      run_git_command "$REPO" branch "$target" "$START_POINT" || RC=$?
    else
      run_git_command "$REPO" branch "$target" || RC=$?
    fi
    ;;
  branch-switch)
    target="${FILES[0]:-${BRANCH:-}}"
    require_branch_name "$target"
    require_clean_worktree "$REPO" "branch switch"
    run_git_command "$REPO" switch "$target" || RC=$?
    ;;
  branch-delete)
    require_yes "branch-delete"
    target="${FILES[0]:-${BRANCH:-}}"
    require_branch_name "$target"
    current_branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
    [[ "$target" != "$current_branch" ]] || die "Refusing to delete current branch: $target" 3
    run_git_command "$REPO" branch -d "$target" || RC=$?
    ;;
  remotes)
    run_git_command "$REPO" remote -v || RC=$?
    ;;
  files-changed)
    run_git_command "$REPO" status --porcelain || RC=$?
    ;;
  is-clean)
    if [[ -z "$(git -C "$REPO" status --porcelain)" ]]; then
      echo "clean" > "$TMP_OUT"
      RC=0
    else
      echo "dirty" > "$TMP_OUT"
      RC=1
    fi
    ;;
  add)
    [[ "${#FILES[@]}" -gt 0 ]] || die "add requires files after --" 2
    run_git_command "$REPO" add -- "${FILES[@]}" || RC=$?
    ;;
  commit)
    [[ -n "$MESSAGE" ]] || die "commit requires -m/--message" 2
    if [[ -z "$(git -C "$REPO" diff --cached --name-only)" ]]; then
      die "Refusing empty commit: no staged changes" 3
    fi
    run_git_command "$REPO" commit -m "$MESSAGE" || RC=$?
    ;;
  pull)
    require_yes "pull"
    require_clean_for_pull "$REPO"
    if [[ -n "$REMOTE" && -n "$BRANCH" ]]; then
      run_git_command "$REPO" pull --ff-only "$REMOTE" "$BRANCH" || RC=$?
    else
      run_git_command "$REPO" pull --ff-only || RC=$?
    fi
    ;;
  push)
    require_yes "push"
    if [[ -n "$REMOTE" && -n "$BRANCH" ]]; then
      run_git_command "$REPO" push "$REMOTE" "$BRANCH" || RC=$?
    else
      run_git_command "$REPO" push || RC=$?
    fi
    ;;
  merge)
    require_yes "merge"
    target="${FILES[0]:-${BRANCH:-}}"
    require_branch_name "$target"
    require_clean_worktree "$REPO" "merge"
    if [[ "$MERGE_MODE" == "no-ff" ]]; then
      run_git_command "$REPO" merge --no-ff "$target" || RC=$?
    else
      run_git_command "$REPO" merge --ff-only "$target" || RC=$?
    fi
    ;;
  *)
    die "Unknown subcommand: $ACTION" 2
    ;;
esac

if [[ "$ACTION" == "root" || "$ACTION" == "summary" || "$ACTION" == "is-clean" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    log_line STDOUT "$line"
  done < "$TMP_OUT"
fi

write_artifact "$REPO" "$([[ "$RC" -eq 0 ]] && echo ok || echo error)" "$RC" "$TMP_OUT" "$TMP_ERR"
emit_output
exit "$RC"
