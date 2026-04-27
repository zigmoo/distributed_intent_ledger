#!/usr/bin/env bash
set -euo pipefail

# x_tool
# Local helper for X/Twitter bookmark workflows backed by Field Theory data.
#
# Workflows covered:
# - refresh bookmarks via ft sync
# - find bookmarks by query
# - list recent bookmarks as one-line summaries
# - add tags to individual bookmark records in bookmarks.jsonl
#
# Data defaults to ~/.ft-bookmarks; override with --data-dir.

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/resolve_base.sh
source "$SCRIPT_DIR/../lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPT_DIR" "${BASE_DIL:-}")"

DEFAULT_DATA_DIR="${HOME}/.ft-bookmarks"
GLOBAL_DATA_DIR="${X_TOOL_DATA_DIR:-$DEFAULT_DATA_DIR}"
LOG_DIR="${X_TOOL_LOG_DIR:-$BASE/_shared/logs/x_tool}"
mkdir -p "$LOG_DIR"
HOSTNAME_SHORT="$(hostname -s | tr '[:upper:]' '[:lower:]')"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${HOSTNAME_SHORT}.x_tool.${TIMESTAMP}.log"

xlog() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG_FILE"
}

usage() {
  cat <<'EOF'
x_tool — Local bookmark workflow helper for Field Theory data

Usage:
  x_tool [global-options] sync [options]
  x_tool [global-options] find <query> [options]
  x_tool [global-options] refresh-find <query> [options]
  x_tool [global-options] recent [options]
  x_tool [global-options] tag (--url URL | --id ID) --tag "tag text" [options]
  x_tool [global-options] status [options]

Global options:
  --data-dir PATH                  Override bookmark data dir for this invocation

Subcommands:
  sync
    Run bookmark sync via ft.
    Options:
      --browser NAME                 Browser for ft sync (default: chromium)
      --agent-browser                Use /home/moo/.config/chromium-agent + Default profile
      --chrome-user-data-dir PATH    Override Chromium user data dir
      --chrome-profile-directory DIR Override Chromium profile directory

  search <query>
    FTS5 full-text search with BM25 ranking (SQLite).
    Options:
      --author HANDLE                Filter by author
      --after DATE                   Synced after (ISO 8601, e.g. 2026-04-01)
      --before DATE                  Synced before
      --limit N                      Max rows (default: 20)
      --json                         JSON output

  list
    List bookmarks with filters (SQLite).
    Options:
      --author HANDLE                Filter by author
      --after DATE                   Synced after
      --before DATE                  Synced before
      --category CAT                 Filter by category
      --domain DOM                   Filter by domain
      --sort-by FIELD                Sort column (default: synced_at)
      --limit N                      Max rows (default: 30)
      --json                         JSON output

  show <id>
    Show full bookmark detail (SQLite).
    Options:
      --json                         JSON output

  stats
    Aggregate statistics.
    Options:
      --json                         JSON output

  categories
    Show category distribution.
    Options:
      --json                         JSON output

  domains
    Show domain distribution.
    Options:
      --json                         JSON output

  find <query>
    (Legacy) Search bookmarks.jsonl by query. Use 'search' instead.
    Options:
      --limit N                      Max rows (default: 30)
      --data-dir PATH                Bookmark data dir (default: ~/.ft-bookmarks)

  refresh-find <query>
    Run sync, then search in one command.
    Accepts sync options plus:
      --limit N

  recent
    Show one-line summaries for bookmarks posted in last N days.
    Options:
      --days N                       Window in days (default: 3)
      --limit N                      Max rows (default: 200)
      --data-dir PATH                Bookmark data dir (default: ~/.ft-bookmarks)

  tag
    Add a tag to one bookmark and rebuild ft index.
    Options:
      --url URL                      Bookmark URL to patch
      --id ID                        Bookmark id/tweetId to patch
      --tag TEXT                     Tag text to add (required)
      --data-dir PATH                Bookmark data dir (default: ~/.ft-bookmarks)
      --no-index                     Skip ft index rebuild

  status
    Print data path and record count from bookmarks.jsonl.
    Options:
      --data-dir PATH                Bookmark data dir (default: ~/.ft-bookmarks)

  compose
    Draft an X post via message_tool nozzle pipeline.
    Options:
      --body TEXT                     Post text (or pipe via stdin, or --file)
      --file PATH                    Read post body from file
      --reply-to ID                  Tweet ID to reply to (stored in draft metadata)

  post
    Dispatch the latest (or specified) draft to clipboard for pasting into X.
    Options:
      --draft ID                     Draft file path or partial ID (default: latest)
      --send                         Paste via CDP + confirm before posting
      --yes                          With --send: skip confirmation, post immediately

  drafts
    List message_tool drafts.
    Options:
      --limit N                      Max rows (default: 10)

Standards:
  - base_dir: resolved with DIL resolver (BASE_DIL -> repo-relative -> ~/Documents/dil_agentic_memory_0001)
  - logs: written to $BASE/_shared/logs/x_tool (override with X_TOOL_LOG_DIR)
  - data_dir: defaults to ~/.ft-bookmarks (override with --data-dir or X_TOOL_DATA_DIR)

Dependencies:
  - Required by command path:
    sync: ft
    find/recent/tag/status: jq
    tag (unless --no-index): ft
    compose/post/drafts: message_tool
  - Also uses: awk, sed, date, mktemp

Examples:
  x_tool sync
  x_tool refresh-find prototown
  x_tool recent --days 3 --limit 50
  x_tool tag --url "https://x.com/..." --tag "dad jokes"
  x_tool compose --body "Interesting thread on agentic memory systems"
  x_tool post
  x_tool drafts
EOF
}

die() {
  xlog "ERROR | $*"
  echo "ERR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

data_file_from_dir() {
  local dir="$1"
  printf '%s/bookmarks.jsonl' "$dir"
}

db_file_from_dir() {
  local dir="$1"
  printf '%s/bookmarks.db' "$dir"
}

require_db() {
  local db
  db="$(db_file_from_dir "$GLOBAL_DATA_DIR")"
  [[ -f "$db" ]] || die "SQLite database not found: $db (run: ft index)"
  printf '%s' "$db"
}

sanitize_fts_query() {
  local q="$1"
  if echo "$q" | grep -qE '(^|\s)(AND|OR|NOT|NEAR)(\s|$)|[(){}:*^"\\+-]'; then
    printf '"%s"' "$(echo "$q" | sed 's/"//g')"
  else
    printf '%s' "$q"
  fi
}

run_sqlite() {
  local db="$1"; shift
  local json_mode="${X_TOOL_JSON:-0}"
  if [[ "$json_mode" -eq 1 ]]; then
    sqlite3 -json "$db" "$@"
  else
    sqlite3 -separator '|' "$db" "$@"
  fi
}

run_sync() {
  local browser="chromium"
  local agent_browser=0
  local chrome_user_data_dir=""
  local chrome_profile_directory=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --browser) browser="$2"; shift 2 ;;
      --agent-browser) agent_browser=1; shift ;;
      --chrome-user-data-dir) chrome_user_data_dir="$2"; shift 2 ;;
      --chrome-profile-directory) chrome_profile_directory="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown sync arg: $1" ;;
    esac
  done

  require_cmd ft
  xlog "sync | browser=$browser | agent_browser=$agent_browser | chrome_user_data_dir=${chrome_user_data_dir:-unset} | chrome_profile_directory=${chrome_profile_directory:-unset}"

  if [[ "$agent_browser" -eq 1 ]]; then
    chrome_user_data_dir="/home/moo/.config/chromium-agent"
    chrome_profile_directory="Default"
  fi

  if [[ -n "$chrome_user_data_dir" || -n "$chrome_profile_directory" ]]; then
    FT_CHROME_USER_DATA_DIR="$chrome_user_data_dir" \
    FT_CHROME_PROFILE_DIRECTORY="$chrome_profile_directory" \
      ft sync --browser "$browser" --yes
    return
  fi

  ft sync --browser "$browser" --yes
}

run_find() {
  local query="$1"; shift
  local limit=30
  local data_dir="$GLOBAL_DATA_DIR"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --data-dir) data_dir="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown find arg: $1" ;;
    esac
  done

  require_cmd jq
  local data_file
  data_file="$(data_file_from_dir "$data_dir")"
  [[ -f "$data_file" ]] || die "bookmark file not found: $data_file"
  xlog "find | query=$query | limit=$limit | data_file=$data_file"

  local rendered
  rendered="$(jq -r --arg q "$query" --argjson limit "$limit" '
    def hay:
      ((.text // "") + " " +
       (.url // "") + " " +
       (.authorHandle // "") + " " +
       (.authorName // "") + " " +
       (.quotedTweet.text? // "") + " " +
       ((.tags // []) | join(" ")));
    def norm(s): (s | ascii_downcase | gsub("[^a-z0-9]+"; ""));
    select(
      ((hay | ascii_downcase) | contains($q | ascii_downcase))
      or (norm(hay) | contains(norm($q)))
    )
    | [.postedAt, .url, .authorHandle, ((.text // "") | gsub("[\r\n\t]+"; " "))]
    | @tsv
  ' "$data_file" | awk -F'\t' '
    BEGIN { c=0 }
    {
      c++
      txt=$4
      gsub(/[[:space:]]+/, " ", txt)
      if (length(txt) > 120) txt=substr(txt, 1, 117) "..."
      if (c <= limit) {
        printf("%03d. %s | @%s | %s | %s\n", c, $1, $3, txt, $2)
      }
    }
  ' limit="$limit")"

  if [[ -z "$rendered" ]]; then
    echo "NO_MATCH | query=$query"
    return 0
  fi
  printf '%s\n' "$rendered"
}

run_recent() {
  local days=3
  local limit=200
  local data_dir="$GLOBAL_DATA_DIR"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --days) days="$2"; shift 2 ;;
      --limit) limit="$2"; shift 2 ;;
      --data-dir) data_dir="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown recent arg: $1" ;;
    esac
  done

  require_cmd jq
  local data_file
  data_file="$(data_file_from_dir "$data_dir")"
  [[ -f "$data_file" ]] || die "bookmark file not found: $data_file"
  xlog "recent | days=$days | limit=$limit | data_file=$data_file"

  local now cutoff
  now="$(date -u +%s)"
  cutoff=$((now - days * 24 * 3600))

  jq -r --argjson cutoff "$cutoff" '
    select(((.postedAt // "") | strptime("%a %b %d %H:%M:%S +0000 %Y") | mktime) >= $cutoff)
    | [.postedAt, .url, ((.text // "") | gsub("[\r\n\t]+"; " "))]
    | @tsv
  ' "$data_file" | awk -F'\t' '
    BEGIN { c=0 }
    {
      c++
      txt=$3
      gsub(/https?:\/\/t\.co\/[A-Za-z0-9]+/, "", txt)
      gsub(/[[:space:]]+/, " ", txt)
      sub(/^ /, "", txt)
      if (length(txt) > 110) txt=substr(txt, 1, 107) "..."
      if (c <= limit) {
        printf("%03d. %s | %s | %s\n", c, $1, txt, $2)
      }
    }
  ' limit="$limit"
}

run_tag() {
  local url=""
  local id=""
  local tag=""
  local data_dir="$GLOBAL_DATA_DIR"
  local do_index=1

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --url) url="$2"; shift 2 ;;
      --id) id="$2"; shift 2 ;;
      --tag) tag="$2"; shift 2 ;;
      --data-dir) data_dir="$2"; shift 2 ;;
      --no-index) do_index=0; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown tag arg: $1" ;;
    esac
  done

  [[ -n "$tag" ]] || die "--tag is required"
  if [[ -z "$url" && -z "$id" ]]; then
    die "one of --url or --id is required"
  fi
  if [[ -n "$url" && -n "$id" ]]; then
    die "use either --url or --id, not both"
  fi

  require_cmd jq
  local data_file
  data_file="$(data_file_from_dir "$data_dir")"
  [[ -f "$data_file" ]] || die "bookmark file not found: $data_file"
  xlog "tag | target=${url:-$id} | tag=$tag | data_file=$data_file | do_index=$do_index"

  local match_expr
  if [[ -n "$url" ]]; then
    match_expr='.url == $needle'
  else
    match_expr='(.id == $needle or .tweetId == $needle)'
  fi

  local exists
  exists="$(jq -r --arg needle "${url:-$id}" "select($match_expr) | .id" "$data_file" | head -n 1 || true)"
  [[ -n "$exists" ]] || die "target bookmark not found"

  local backup tmp
  backup="${data_file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$(mktemp)"
  cp "$data_file" "$backup"

  jq --arg needle "${url:-$id}" --arg tag "$tag" "
    if $match_expr
    then .tags = (((.tags // []) + [\$tag]) | unique)
    else .
    end
  " "$data_file" > "$tmp"
  mv "$tmp" "$data_file"

  if [[ "$do_index" -eq 1 ]]; then
    require_cmd ft
    ft index >/dev/null
  fi

  jq -c --arg needle "${url:-$id}" "select($match_expr) | {id,url,tags}" "$data_file"
  echo "OK | backup=$backup"
}

run_status() {
  local data_dir="$GLOBAL_DATA_DIR"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --data-dir) data_dir="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown status arg: $1" ;;
    esac
  done

  local data_file
  data_file="$(data_file_from_dir "$data_dir")"
  [[ -f "$data_file" ]] || die "bookmark file not found: $data_file"
  local count
  count="$(wc -l < "$data_file" | tr -d ' ')"
  xlog "status | data_file=$data_file | count=$count"
  echo "OK | data_dir=$data_dir | file=$data_file | count=$count | base=$BASE | log_file=$LOG_FILE"
}

run_search() {
  local query="$1"; shift
  local limit=20
  local author=""
  local after=""
  local before=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --author) author="$2"; shift 2 ;;
      --after) after="$2"; shift 2 ;;
      --before) before="$2"; shift 2 ;;
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown search arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  local safe_q
  safe_q="$(sanitize_fts_query "$query")"
  xlog "search | query=$query | safe_q=$safe_q | limit=$limit | author=$author | after=$after | before=$before"

  local where="bookmarks_fts MATCH '$safe_q'"
  if [[ -n "$author" ]]; then
    where="$where AND b.author_handle = '${author}' COLLATE NOCASE"
  fi
  if [[ -n "$after" ]]; then
    where="$where AND b.synced_at >= '${after}'"
  fi
  if [[ -n "$before" ]]; then
    where="$where AND b.synced_at <= '${before}'"
  fi

  local sql="SELECT b.id, b.url, replace(replace(b.text, char(10), ' '), char(13), ' '), b.author_handle, b.posted_at, b.like_count, b.view_count, bm25(bookmarks_fts, 5.0, 1.0, 1.0, 3.0) AS rank FROM bookmarks b JOIN bookmarks_fts ON bookmarks_fts.rowid = b.rowid WHERE ${where} ORDER BY rank ASC LIMIT ${limit};"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "SELECT b.id, b.url, b.text, b.author_handle, b.posted_at, b.like_count, b.view_count, bm25(bookmarks_fts, 5.0, 1.0, 1.0, 3.0) AS rank FROM bookmarks b JOIN bookmarks_fts ON bookmarks_fts.rowid = b.rowid WHERE ${where} ORDER BY rank ASC LIMIT ${limit};"
  else
    sqlite3 -separator $'\t' "$db" "$sql" | awk -F'\t' '{
      n++
      text=$3
      if (length(text) > 100) text=substr(text, 1, 97) "..."
      printf "%03d. %s | @%s | %s | %s\n", n, $5, $4, text, $2
    }'
    local count
    count="$(sqlite3 "$db" "SELECT COUNT(*) FROM bookmarks b JOIN bookmarks_fts ON bookmarks_fts.rowid = b.rowid WHERE ${where};")"
    if [[ "$count" -gt "$limit" ]]; then
      echo "--- showing $limit of $count matches ---"
    fi
  fi
}

run_list() {
  local limit=30
  local author=""
  local after=""
  local before=""
  local category=""
  local domain=""
  local sort_by="synced_at"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      --author) author="$2"; shift 2 ;;
      --after) after="$2"; shift 2 ;;
      --before) before="$2"; shift 2 ;;
      --category) category="$2"; shift 2 ;;
      --domain) domain="$2"; shift 2 ;;
      --sort-by) sort_by="$2"; shift 2 ;;
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown list arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  xlog "list | limit=$limit | author=$author | after=$after | before=$before | category=$category | domain=$domain"

  local where_parts=""
  if [[ -n "$author" ]]; then
    where_parts="${where_parts:+$where_parts AND }author_handle = '${author}' COLLATE NOCASE"
  fi
  if [[ -n "$after" ]]; then
    where_parts="${where_parts:+$where_parts AND }synced_at >= '${after}'"
  fi
  if [[ -n "$before" ]]; then
    where_parts="${where_parts:+$where_parts AND }synced_at <= '${before}'"
  fi
  if [[ -n "$category" ]]; then
    where_parts="${where_parts:+$where_parts AND }categories LIKE '%${category}%'"
  fi
  if [[ -n "$domain" ]]; then
    where_parts="${where_parts:+$where_parts AND }domains LIKE '%${domain}%'"
  fi

  local where=""
  if [[ -n "$where_parts" ]]; then
    where="WHERE $where_parts"
  fi

  local order="ORDER BY ${sort_by} DESC"
  local sql="SELECT id, url, replace(replace(text, char(10), ' '), char(13), ' '), author_handle, posted_at, like_count, view_count FROM bookmarks ${where} ${order} LIMIT ${limit};"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "SELECT id, url, text, author_handle, posted_at, like_count, view_count FROM bookmarks ${where} ${order} LIMIT ${limit};"
  else
    sqlite3 -separator $'\t' "$db" "$sql" | awk -F'\t' '{
      n++
      text=$3
      if (length(text) > 100) text=substr(text, 1, 97) "..."
      printf "%03d. %s | @%s | %s | %s\n", n, $5, $4, text, $2
    }'
  fi
}

run_show() {
  local id="$1"; shift || die "show requires <id>"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown show arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  xlog "show | id=$id"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "SELECT * FROM bookmarks WHERE id = '${id}';"
  else
    local row
    local json_row
    json_row="$(sqlite3 -json "$db" "SELECT * FROM bookmarks WHERE id = '${id}';")"
    [[ "$json_row" != "[]" ]] || die "bookmark not found: $id"

    echo "$json_row" | python3 -c "
import sys, json
rows = json.load(sys.stdin)
if not rows:
    print('Not found'); sys.exit(1)
b = rows[0]
print(f'ID:         {b[\"id\"]}')
print(f'URL:        {b[\"url\"]}')
print(f'Author:     @{b.get(\"author_handle\",\"\")} ({b.get(\"author_name\",\"\")})')
print(f'Posted:     {b.get(\"posted_at\",\"\")}')
print(f'Bookmarked: {b.get(\"bookmarked_at\",\"\")}')
print(f'Language:   {b.get(\"language\",\"\")}')
print(f'Category:   {b.get(\"primary_category\",\"\") or \"unclassified\"}')
print(f'Domain:     {b.get(\"primary_domain\",\"\") or \"unclassified\"}')
print()
likes = b.get('like_count') or 0
reposts = b.get('repost_count') or 0
replies = b.get('reply_count') or 0
quotes = b.get('quote_count') or 0
views = b.get('view_count') or 0
print('Engagement:')
print(f'  Likes: {likes} | Reposts: {reposts} | Replies: {replies} | Quotes: {quotes} | Views: {views}')
print()
print('Text:')
print(b.get('text',''))
qt = b.get('quoted_tweet_json')
if qt:
    try:
        d = json.loads(qt)
        print(f'\nQuoted tweet:')
        print(f'  @{d.get(\"authorHandle\",\"?\")} — {d.get(\"text\",\"\")[:200]}')
    except: pass
links = b.get('links_json')
if links:
    try:
        urls = json.loads(links)
        if urls:
            print('\nLinks:')
            for u in urls: print(f'  {u}')
    except: pass
tags = b.get('tags_json')
if tags:
    try:
        t = json.loads(tags)
        if t: print(f'\nTags: {t}')
    except: pass
"
  fi
}

run_stats_cmd() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown stats arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  xlog "stats"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "
      SELECT
        (SELECT COUNT(*) FROM bookmarks) as total,
        (SELECT COUNT(DISTINCT author_handle) FROM bookmarks) as unique_authors,
        (SELECT MIN(synced_at) FROM bookmarks) as earliest_sync,
        (SELECT MAX(synced_at) FROM bookmarks) as latest_sync;
    "
  else
    local total authors earliest latest
    total="$(sqlite3 "$db" "SELECT COUNT(*) FROM bookmarks;")"
    authors="$(sqlite3 "$db" "SELECT COUNT(DISTINCT author_handle) FROM bookmarks;")"
    earliest="$(sqlite3 "$db" "SELECT MIN(synced_at) FROM bookmarks;")"
    latest="$(sqlite3 "$db" "SELECT MAX(synced_at) FROM bookmarks;")"

    echo "Bookmarks:      $total"
    echo "Unique authors: $authors"
    echo "Synced range:   $earliest → $latest"
    echo ""
    echo "Top authors:"
    sqlite3 -separator '|' "$db" "SELECT author_handle, COUNT(*) as c FROM bookmarks GROUP BY author_handle ORDER BY c DESC LIMIT 10;" | awk -F'|' '{ printf "  @%-20s %s\n", $1, $2 }'
    echo ""
    echo "Languages:"
    sqlite3 -separator '|' "$db" "SELECT language, COUNT(*) as c FROM bookmarks WHERE language IS NOT NULL GROUP BY language ORDER BY c DESC LIMIT 10;" | awk -F'|' '{ printf "  %-5s %s\n", $1, $2 }'
  fi
}

run_categories() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown categories arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  xlog "categories"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "SELECT primary_category as category, COUNT(*) as count FROM bookmarks GROUP BY primary_category ORDER BY count DESC;"
  else
    sqlite3 -separator '|' "$db" "SELECT primary_category, COUNT(*) as c FROM bookmarks GROUP BY primary_category ORDER BY c DESC;" | awk -F'|' '{ printf "  %-20s %s\n", $1, $2 }'
  fi
}

run_domains() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) X_TOOL_JSON=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown domains arg: $1" ;;
    esac
  done

  local db
  db="$(require_db)"
  xlog "domains"

  if [[ "${X_TOOL_JSON:-0}" -eq 1 ]]; then
    sqlite3 -json "$db" "SELECT primary_domain as domain, COUNT(*) as count FROM bookmarks WHERE primary_domain IS NOT NULL AND primary_domain != '' GROUP BY primary_domain ORDER BY count DESC;"
  else
    local result
    result="$(sqlite3 -separator '|' "$db" "SELECT primary_domain, COUNT(*) as c FROM bookmarks WHERE primary_domain IS NOT NULL AND primary_domain != '' GROUP BY primary_domain ORDER BY c DESC;")"
    if [[ -z "$result" ]]; then
      echo "No domains found. Run: x_tool classify-domains"
    else
      echo "$result" | awk -F'|' '{ printf "  %-20s %s\n", $1, $2 }'
    fi
  fi
}

resolve_message_tool() {
  local candidates=(
    "$BASE/_shared/scripts/message_tool"
  )
  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]]; then
      printf '%s' "$c"
      return 0
    fi
  done
  die "message_tool not found (checked: ${candidates[*]})"
}

run_compose() {
  local body=""
  local file=""
  local reply_to=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --body) body="$2"; shift 2 ;;
      --file) file="$2"; shift 2 ;;
      --reply-to) reply_to="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown compose arg: $1" ;;
    esac
  done

  local mt
  mt="$(resolve_message_tool)"

  local mt_args=("compose" "--to" "x-post" "--channel" "x-post")

  if [[ -n "$body" ]]; then
    mt_args+=("--body" "$body")
  elif [[ -n "$file" ]]; then
    mt_args+=("--file" "$file")
  fi

  if [[ -n "$reply_to" ]]; then
    mt_args+=("--subject" "reply-to:${reply_to}")
  fi

  xlog "compose | body_len=${#body} | file=${file:-none} | reply_to=${reply_to:-none}"
  "$mt" "${mt_args[@]}"
}

run_post() {
  local draft=""
  local send=0
  local yes=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --draft) draft="$2"; shift 2 ;;
      --send) send=1; shift ;;
      --yes) yes=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown post arg: $1" ;;
    esac
  done

  local mt
  mt="$(resolve_message_tool)"

  local x_mode="preview"
  if [[ "$send" -eq 1 && "$yes" -eq 1 ]]; then
    x_mode="auto"
  elif [[ "$send" -eq 1 ]]; then
    x_mode="confirm"
  fi

  local mt_args=("send" "--channel" "x-post" "--x-mode" "$x_mode")
  if [[ -n "$draft" ]]; then
    mt_args+=("$draft")
  fi

  xlog "post | draft=${draft:-latest} | mode=$x_mode"
  "$mt" "${mt_args[@]}"
}

run_drafts() {
  local limit=10

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown drafts arg: $1" ;;
    esac
  done

  local mt
  mt="$(resolve_message_tool)"

  xlog "drafts | limit=$limit"
  "$mt" list --limit "$limit"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir)
      GLOBAL_DATA_DIR="$2"
      shift 2
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

xlog "start | args=$* | base=$BASE | data_dir=$GLOBAL_DATA_DIR"
subcommand="$1"
shift

case "$subcommand" in
  sync)
    run_sync "$@"
    ;;
  search)
    [[ $# -ge 1 ]] || die "search requires <query>"
    query="$1"; shift
    run_search "$query" "$@"
    ;;
  list)
    run_list "$@"
    ;;
  show)
    [[ $# -ge 1 ]] || die "show requires <id>"
    run_show "$@"
    ;;
  stats)
    run_stats_cmd "$@"
    ;;
  categories)
    run_categories "$@"
    ;;
  domains)
    run_domains "$@"
    ;;
  find)
    [[ $# -ge 1 ]] || die "find requires <query>"
    query="$1"; shift
    run_find "$query" "$@"
    ;;
  refresh-find)
    [[ $# -ge 1 ]] || die "refresh-find requires <query>"
    query="$1"; shift

    # Parse combined args: sync options + find options.
    sync_args=()
    find_args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --browser|--chrome-user-data-dir|--chrome-profile-directory)
          sync_args+=("$1" "$2"); shift 2 ;;
        --agent-browser)
          sync_args+=("$1"); shift ;;
        --limit|--data-dir)
          find_args+=("$1" "$2"); shift 2 ;;
        *)
          die "unknown refresh-find arg: $1" ;;
      esac
    done

    run_sync "${sync_args[@]}"
    run_search "$query" "${find_args[@]}"
    ;;
  recent)
    run_recent "$@"
    ;;
  tag)
    run_tag "$@"
    ;;
  status)
    run_status "$@"
    ;;
  compose)
    run_compose "$@"
    ;;
  post)
    run_post "$@"
    ;;
  drafts)
    run_drafts "$@"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    die "unknown subcommand: $subcommand"
    ;;
esac
