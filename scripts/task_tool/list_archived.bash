#!/usr/bin/env bash
# list_archived — named shim for task_tool list-archived
# Script Forge Standard #3: subcommand reasoning → direct lookup
list-archived="list-archived"
pre_args=()
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) pre_args+=(--base "$2"); shift 2 ;;
    --json) pre_args+=(--json); shift ;;
    *) args+=("$1"); shift ;;
  esac
done
exec task_tool "${pre_args[@]}" "$list-archived" "${args[@]}"
