#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-/home/moo/Documents/dil_agentic_memory_0001}"
REGISTRY="$BASE/_shared/_meta/domain_registry.json"
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

# Collect all task directories from registry + legacy fallback
declare -a task_dirs=()

if [[ -f "$REGISTRY" ]] && command -v jq >/dev/null 2>&1; then
  while IFS= read -r dname; do
    raw_task_dir=$(jq -r --arg d "$dname" '.domains[$d].task_dir' "$REGISTRY")
    if [[ "$raw_task_dir" == /* ]]; then
      resolved="$raw_task_dir"
    else
      resolved="$BASE/$raw_task_dir"
    fi
    # Add active/ subdir if it exists, otherwise flat dir
    if [[ -d "$resolved/active" ]]; then
      task_dirs+=("$resolved/active")
    elif [[ -d "$resolved" ]]; then
      task_dirs+=("$resolved")
    fi
    # Add archived year subdirs
    if [[ -d "$resolved/archived" ]]; then
      while IFS= read -r year_dir; do
        task_dirs+=("$year_dir")
      done < <(find "$resolved/archived" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
    fi
  done < <(jq -r '.domains | keys[]' "$REGISTRY")
fi

# Also check legacy paths (coexist during migration)
for legacy_dir in "$BASE/_shared/tasks/work" "$BASE/_shared/tasks/personal"; do
  if [[ -d "$legacy_dir" ]]; then
    # Avoid duplicates
    already=0
    for existing in "${task_dirs[@]}"; do
      [[ "$existing" == "$legacy_dir" ]] && already=1
    done
    (( already )) || task_dirs+=("$legacy_dir")
  fi
done

tmp_rows="$(mktemp)"

for dir in "${task_dirs[@]}"; do
  [[ -d "$dir" ]] || continue
  for f in $(find "$dir" -maxdepth 1 -type f -name '*.md' ! -name 'index.md' | sort -V); do
    task_id="$(get_key "$f" task_id)"
    domain="$(get_key "$f" domain)"
    status="$(get_key "$f" status)"
    priority="$(get_key "$f" priority)"
    owner="$(get_key "$f" owner)"
    due="$(get_key "$f" due)"
    project="$(get_key "$f" project)"
    updated="$(get_key "$f" updated)"
    # Compute relative path from BASE
    rel="${f#$BASE/}"
    printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
      "$task_id" "$domain" "$status" "$priority" "$owner" "$due" "$project" "$rel" "$updated" >> "$tmp_rows"
  done
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
max_dil=1099
for dir in "${task_dirs[@]}"; do
  [[ -d "$dir" ]] || continue
  while IFS= read -r tf; do
    fname="$(basename "$tf" .md)"
    if [[ "$fname" =~ ^DIL-([0-9]+)$ ]]; then
      n="${BASH_REMATCH[1]}"
      if (( n > max_dil )); then
        max_dil="$n"
      fi
    fi
  done < <(find "$dir" -maxdepth 1 -type f -name 'DIL-*.md' 2>/dev/null)
done
next_id=$((max_dil + 1))
sed -i "s/^- next_id: .*/- next_id: $next_id/" "$COUNTER_FILE"
sed -i "s/^- updated: .*/- updated: $TODAY/" "$COUNTER_FILE"

echo "Rebuilt index: $INDEX_FILE"
echo "Updated counter next_id: $next_id"
