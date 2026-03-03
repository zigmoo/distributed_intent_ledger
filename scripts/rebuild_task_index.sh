#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-/home/moo/Documents/dil_agentic_memory_0001}"
WORK_DIR="$BASE/_shared/tasks/work"
PERSONAL_DIR="$BASE/_shared/tasks/personal"
INDEX_FILE="$BASE/_shared/_meta/task_index.md"
COUNTER_FILE="$BASE/_shared/_meta/task_id_counter.md"
TODAY="$(date -u +%Y-%m-%d)"

trim() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
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

tmp_rows="$(mktemp)"

for f in $(find "$WORK_DIR" "$PERSONAL_DIR" -maxdepth 1 -type f -name '*.md' | sort -V); do
  task_id="$(get_key "$f" task_id)"
  domain="$(get_key "$f" domain)"
  status="$(get_key "$f" status)"
  priority="$(get_key "$f" priority)"
  owner="$(get_key "$f" owner)"
  due="$(get_key "$f" due)"
  project="$(get_key "$f" project)"
  updated="$(get_key "$f" updated)"
  rel="_shared/tasks/$domain/$task_id.md"
  printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
    "$task_id" "$domain" "$status" "$priority" "$owner" "$due" "$project" "$rel" "$updated" >> "$tmp_rows"
done

cat > "$INDEX_FILE" <<EOT
---
title: "Shared Task Index"
date: 2026-02-19
machine: shared
assistant: shared
category: system
memoryType: index
priority: critical
tags: [index, tasks, shared]
updated: $TODAY
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Shared Task Index

Scan this file first before reading task notes.

| task_id | domain | status | priority | owner | due | project | path | updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
EOT

cat "$tmp_rows" >> "$INDEX_FILE"
rm -f "$tmp_rows"

# Recompute personal counter from files.
max_personal="$(find "$PERSONAL_DIR" -maxdepth 1 -type f -name 'MOO-*.md' -print | sed -E 's|.*MOO-([0-9]+)\.md|\1|' | sort -n | tail -1)"
if [[ -z "$max_personal" ]]; then
  next_id=1100
else
  next_id=$((max_personal + 1))
fi
sed -i "s/^- next_id: .*/- next_id: $next_id/" "$COUNTER_FILE"
sed -i "s/^- updated: .*/updated: $TODAY/" "$COUNTER_FILE"

echo "Rebuilt index: $INDEX_FILE"
echo "Updated counter next_id: $next_id"
