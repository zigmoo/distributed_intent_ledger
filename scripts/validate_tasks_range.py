#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate task range; optionally migrate to contract v1 before validation.")
    ap.add_argument("--min-id", type=int, required=True, help="Minimum MOO numeric id")
    ap.add_argument("--max-id", type=int, default=999999, help="Maximum MOO numeric id")
    ap.add_argument("--base", default="/home/moo/Documents/dil_agentic_memory_0001")
    ap.add_argument("--fix", action="store_true", help="Migrate selected range to contract v1 before validation")
    args = ap.parse_args()

    base = Path(args.base)
    scripts = base / "_shared" / "tasks" / "_meta" / "scripts"

    migrate = scripts / "migrate_task_contract_v1.py"
    rebuild = scripts / "rebuild_task_index.sh"
    validate = scripts / "validate_tasks.sh"

    if args.fix:
        rc = run([
            str(migrate),
            "--base", str(base),
            "--min-id", str(args.min_id),
            "--max-id", str(args.max_id),
            "--apply",
        ])
        if rc != 0:
            return rc

        rc = run([str(rebuild), str(base)])
        if rc != 0:
            return rc

    return run([str(validate), str(base)])


if __name__ == "__main__":
    raise SystemExit(main())
