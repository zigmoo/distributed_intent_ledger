#!/usr/bin/env python3
"""Render ticket resultsets for console output.

Input is a JSON array of objects with keys such as:
ticket, status, priority, owner, updated, summary.
Output is fixed-width text with OSC 8 hyperlinks for ticket IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import jinja2
except ImportError:
    jinja2 = None


def resolve_base() -> Path:
    for env_name in ("BASE_DIL", "DIL_BASE", "CLAWVAULT_BASE"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser()
    return Path.home() / "Documents" / "dil_agentic_memory_0001"


def resolve_url_tool(base: Path) -> Path | None:
    candidates = [
        base / "_shared" / "scripts" / "bin" / "url_tool",
        base / "_shared" / "scripts" / "url_tool" / "url_tool.bash",
        Path("/org/platform/scripts/bin/url_tool"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ticket_url(base: Path, ticket: str) -> str:
    url_tool = resolve_url_tool(base)
    if url_tool is None:
        return ""
    env = os.environ.copy()
    env["URL_TOOL_REGISTRY"] = str(base / "_shared" / "_meta" / "domain_registry.json")
    proc = subprocess.run(
        [str(url_tool), "--plain", "ticket", ticket],
        capture_output=True,
        text=True,
        env=env,
    )
    url = proc.stdout.strip() if proc.returncode == 0 else ""
    if not re.match(r"^https?://", url):
        return ""
    return url


def osc8(label: str, url: str) -> str:
    if not url:
        return label
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def normalize_row(base: Path, row: dict[str, Any]) -> dict[str, str]:
    ticket = str(row.get("ticket") or row.get("task_id") or row.get("key") or "")
    url = ticket_url(base, ticket) if ticket else ""
    return {
        "ticket": ticket,
        "link": osc8(ticket, url),
        "ticket_pad": " " * max(0, 14 - len(ticket)),
        "status": str(row.get("status") or ""),
        "priority": str(row.get("priority") or ""),
        "owner": str(row.get("owner") or row.get("assignee") or ""),
        "updated": str(row.get("updated") or "")[:10],
        "summary": str(row.get("summary") or row.get("title") or ""),
    }


def render_rows(template_path: Path, rows: list[dict[str, str]]) -> str:
    if jinja2 is None:
        lines = [
            f"{row['link']}{row['ticket_pad']}  {row['status']:<13}  {row['priority']:<8}  {row['owner']:<20}  {row['updated']:<10}  {row['summary']}"
            for row in rows
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    return environment.get_template(template_path.name).render(rows=rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render ticket resultsets for console output.")
    parser.add_argument("--template", default="", help="Jinja2 template path")
    parser.add_argument("--base", default="", help="DIL base path")
    args = parser.parse_args()

    base = Path(args.base).expanduser() if args.base else resolve_base()
    template_path = (
        Path(args.template).expanduser()
        if args.template
        else Path("")
    )
    if not template_path.is_file():
        print("ERROR: --template is required and must point to a Jinja2 template file", file=sys.stderr)
        return 2

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON input: {exc}", file=sys.stderr)
        return 2

    if not isinstance(payload, list):
        print("ERROR: expected a JSON array of result rows", file=sys.stderr)
        return 2

    rows = [normalize_row(base, row) for row in payload if isinstance(row, dict)]
    print(render_rows(template_path, rows), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
