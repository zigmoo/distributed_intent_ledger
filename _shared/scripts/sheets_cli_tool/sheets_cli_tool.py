#!/usr/bin/env python3
"""sheets_cli_tool.py — Deterministic Ben workbook updater for Sheets"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base

try:
    from tool_forge_log import ToolForgeLogger
except ImportError:
    ToolForgeLogger = None

SCRIPT_NAME = "sheets_cli_tool"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sheets_cli_tool",
        description="Deterministic Ben workbook updater for Sheets",
    )
    parser.add_argument("--base", required=True, help="DIL base path")
    parser.add_argument("--dry-run", action="store_true", help="preview without side effects")
    arguments = parser.parse_args()

    base = Path(arguments.base).expanduser().resolve()

    log = ToolForgeLogger(SCRIPT_NAME, "run", str(base)) if ToolForgeLogger else None

    if log:
        log.section("Initialization")
        log.info(f"base: {base}")
        log.info(f"dry_run: {arguments.dry_run}")

    if log:
        log.section("Processing")

    # --- your logic here ---

    if log:
        log.section("Result")
        log.info("done")
        log.close()

    print(f"OK | {SCRIPT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
