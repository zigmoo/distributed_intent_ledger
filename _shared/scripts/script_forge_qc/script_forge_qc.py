#!/usr/bin/env python3
"""script_forge_qc.py - query Script Forge QC registry data."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_NAME = "script_forge_qc"
REGISTRY_RELATIVE_PATH = "_shared/data/script_forge_qc/test_runs.csv"
SAFE_FILTER_VALUE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def fail(code: int, message: str) -> None:
    print(f"ERR | {code} | {message}", file=sys.stderr)
    raise SystemExit(code)


def registry_path(base: Path) -> Path:
    return base / REGISTRY_RELATIVE_PATH


def require_duckdb_sql() -> str:
    path = shutil.which("duckdb_sql")
    if not path:
        fail(4, "duckdb_sql not found in PATH")
    return path


def run_duckdb_sql(csv_path: Path, sql: str, *, json_output: bool = False, single_value: bool = False) -> str:
    if not csv_path.exists():
        fail(4, f"QC test run registry not found: {csv_path}")
    command = [require_duckdb_sql(), "-g", "-d", str(csv_path), "-s", sql]
    if json_output:
        command.append("-j")
    if single_value:
        command.append("-S")
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail(result.returncode, (result.stderr or result.stdout).strip())
    return result.stdout.rstrip()


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def cmd_latest(args: argparse.Namespace, csv_path: Path) -> int:
    sql = (
        "SELECT run_ts_utc, suite, tool, status, tests_total, passed, failed, "
        "skipped, rebuilt, mode, single_test, machine, runner, git_commit, "
        "duration_sec, log_path "
        "ORDER BY run_ts_utc DESC "
        f"LIMIT {args.limit}"
    )
    print(run_duckdb_sql(csv_path, sql, json_output=args.json))
    return 0


def cmd_summary(args: argparse.Namespace, csv_path: Path) -> int:
    sql = (
        "SELECT suite, tool, status, COUNT(*) AS runs, MAX(run_ts_utc) AS last_run "
        "GROUP BY suite, tool, status "
        "ORDER BY suite, tool, status"
    )
    print(run_duckdb_sql(csv_path, sql, json_output=args.json))
    return 0


def cmd_last_status(args: argparse.Namespace, csv_path: Path) -> int:
    if args.suite and not SAFE_FILTER_VALUE.match(args.suite):
        fail(2, f"invalid suite filter: {args.suite}")
    suite_filter = f"WHERE suite = '{args.suite}' " if args.suite else ""
    sql = (
        "SELECT status "
        f"{suite_filter}"
        "ORDER BY run_ts_utc DESC "
        "LIMIT 1"
    )
    output = run_duckdb_sql(csv_path, sql, single_value=True)
    print(output or "UNKNOWN")
    return 0


def cmd_path(args: argparse.Namespace, csv_path: Path) -> int:
    print(csv_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Query DIL Script Forge QC registry data",
    )
    parser.add_argument("--base", required=True, help="DIL base path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest = subparsers.add_parser("latest", help="show recent test runs")
    latest.add_argument("--limit", type=int, default=10)
    latest.add_argument("--json", action="store_true")

    summary = subparsers.add_parser("summary", help="summarize runs by suite/tool/status")
    summary.add_argument("--json", action="store_true")

    last_status = subparsers.add_parser("last-status", help="show latest status")
    last_status.add_argument("--suite", default="")

    subparsers.add_parser("path", help="print the test run registry path")

    args = parser.parse_args()
    if hasattr(args, "limit") and args.limit < 1:
        fail(2, "--limit must be >= 1")

    csv_path = registry_path(Path(args.base).expanduser().resolve())
    if args.command == "latest":
        return cmd_latest(args, csv_path)
    if args.command == "summary":
        return cmd_summary(args, csv_path)
    if args.command == "last-status":
        return cmd_last_status(args, csv_path)
    if args.command == "path":
        return cmd_path(args, csv_path)
    fail(2, f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
