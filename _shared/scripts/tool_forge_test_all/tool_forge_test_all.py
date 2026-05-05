#!/usr/bin/env python3
"""tool_forge_test_all.py — Run all Tool Forge test suites in a single pass.

Discovers *_test_script.bash files under _shared/scripts/, runs each with
--quiet, captures exit codes and summary lines, and reports aggregate results.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base

SCRIPT_NAME = "tool_forge_test_all"

INFRA_DEPENDENT = {
    "llm_matrix_tool": {"max_test": 2, "reason": "tests 3+ need LM Studio running"},
}


def discover_test_suites(scripts_dir: Path) -> list[dict]:
    suites = []
    for path in sorted(scripts_dir.rglob("*_test_script.bash")):
        if "venv" in str(path) or "__pycache__" in str(path):
            continue
        if path.name == f"{SCRIPT_NAME}_test_script.bash":
            continue
        drawer = path.parent.name
        tool_name = path.stem.replace("_test_script", "")
        suites.append({
            "path": str(path),
            "drawer": drawer,
            "tool_name": tool_name,
        })
    return suites


def run_suite(suite: dict, timeout_sec: int = 120, rebuild: bool = False,
              single_test: str | None = None) -> dict:
    cmd = ["bash", suite["path"]]
    if rebuild:
        cmd.append("--rebuild")
    else:
        cmd.append("--quiet")
    if single_test:
        cmd.extend(["--test", single_test])

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        elapsed = time.time() - start
        output = result.stdout + result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        elapsed = timeout_sec
        output = ""
        exit_code = -1

    passed = failed = skipped = total = 0
    summary_line = ""
    for line in output.splitlines():
        if "PASSED=" in line and "FAILED=" in line:
            summary_line = line.strip()
            for part in summary_line.split():
                if part.startswith("PASSED="):
                    passed = int(part.split("=")[1])
                elif part.startswith("FAILED="):
                    failed = int(part.split("=")[1])
                elif part.startswith("SKIPPED="):
                    skipped = int(part.split("=")[1])
                elif part.startswith("TOTAL="):
                    total = int(part.split("=")[1])
        elif "ALL PASSED:" in line:
            summary_line = line.strip().lstrip("= ").rstrip("= ")
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "passed,":
                    passed = int(parts[i - 1])
                elif p == "failed,":
                    failed = int(parts[i - 1])
                elif p == "skipped":
                    skipped = int(parts[i - 1])
            total = passed + failed + skipped

    if total == 0 and exit_code == 0:
        total = passed = 1

    return {
        "tool_name": suite["tool_name"],
        "drawer": suite["drawer"],
        "exit_code": exit_code,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "elapsed": round(elapsed, 1),
        "summary": summary_line,
        "status": "TIMEOUT" if exit_code == -1
                  else "PASS" if exit_code == 0
                  else "FAIL",
    }


def main():
    parser = argparse.ArgumentParser(
        description="tool_forge_test_all — run all Tool Forge test suites"
    )
    parser.add_argument("--base", default="", help="DIL base path override")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all golden files")
    parser.add_argument("--timeout", type=int, default=120, help="Per-suite timeout in seconds")
    parser.add_argument("--skip", action="append", default=[], help="Skip suite by tool name")
    parser.add_argument("--only", action="append", default=[], help="Run only these suites")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    base = args.base or resolve_dil_base(str(SCRIPTS_DIR))
    if not base:
        print("ERROR: Cannot resolve DIL base", file=sys.stderr)
        sys.exit(1)

    scripts_dir = Path(base) / "_shared" / "scripts"
    suites = discover_test_suites(scripts_dir)

    if args.only:
        suites = [s for s in suites if s["tool_name"] in args.only]
    if args.skip:
        suites = [s for s in suites if s["tool_name"] not in args.skip]

    if not suites:
        print("No test suites found.")
        sys.exit(0)

    results = []
    total_passed = total_failed = total_timeout = 0
    total_tests = 0

    if not args.json:
        print("=" * 70)
        print("  TOOL FORGE — FULL TEST RUN")
        print("=" * 70)
        print()

    for suite in suites:
        tool = suite["tool_name"]
        infra = INFRA_DEPENDENT.get(tool)

        if infra:
            max_test = infra["max_test"]
            combined = None
            for t in range(1, max_test + 1):
                r = run_suite(suite, timeout_sec=args.timeout, rebuild=args.rebuild, single_test=str(t))
                if combined is None:
                    combined = r
                else:
                    combined["passed"] += r["passed"]
                    combined["total"] += r["total"]
                    combined["elapsed"] += r["elapsed"]
                    if r["exit_code"] != 0:
                        combined["status"] = "FAIL"
                        combined["exit_code"] = r["exit_code"]
            combined["summary"] = f"tests 1-{max_test} only ({infra['reason']})"
            result = combined
        else:
            result = run_suite(suite, timeout_sec=args.timeout, rebuild=args.rebuild)

        results.append(result)
        total_tests += result["total"]

        if result["status"] == "PASS":
            total_passed += 1
        elif result["status"] == "TIMEOUT":
            total_timeout += 1
        else:
            total_failed += 1

        if not args.json:
            icon = {"PASS": "PASS", "FAIL": "FAIL", "TIMEOUT": "TIME"}[result["status"]]
            print(f"  {icon}  {result['drawer']:<35} "
                  f"{result['passed']:>3}/{result['total']:<3} "
                  f"{result['elapsed']:>5.1f}s  {result['summary']}")

    if args.json:
        print(json.dumps({
            "suites": results,
            "summary": {
                "total_suites": len(results),
                "passed": total_passed,
                "failed": total_failed,
                "timeout": total_timeout,
                "total_tests": total_tests,
            }
        }, indent=2))
    else:
        print()
        print("=" * 70)
        print(f"  SUITES: {len(results)}  "
              f"PASSED: {total_passed}  "
              f"FAILED: {total_failed}  "
              f"TIMEOUT: {total_timeout}  "
              f"TESTS: {total_tests}")
        print("=" * 70)

    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
