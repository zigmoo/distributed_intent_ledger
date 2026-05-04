#!/usr/bin/env python3
r"""whats_hot_tool.py — Deterministic _hot.md prepend-only manager with sentinel separation and indexed retrieval

Design goals:
- Zero-inference parsing: every entry bounded by machine-greppable sentinels.
- Prepend-only writes: old entries never modified; new entries inserted after frontmatter.
- Indexed retrieval: --latest, -N, --date, --all with deterministic extraction.
- Legacy compatible: content before the first sentinel is treated as a legacy entry.

Storage format (_shared/_hot.md):

---
title: Session Hot State
updated: 2026-04-28T22:10:00-05:00
---

<!-- === HOT_ENTRY: 2026-04-28T22:10:00-05:00 | opencode@framemoowork | kimi-k2.6 === -->

## Hot Entry 2026-04-28T22:10:00-05:00

[content ...]

<!-- === HOT_ENTRY: 2026-04-28T21:58:00-05:00 | opencode@framemoowork | kimi-k2.6 === -->

[content ...]

Sentinel regex: ^<!-- === HOT_ENTRY: (.+?) \| (.+?) \| (.+?) === -->$
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base  # noqa: E402

try:
    from tool_forge_log import ToolForgeLogger  # noqa: E402
except ImportError:
    ToolForgeLogger = None

SCRIPT_NAME = "whats_hot_tool"
SENTINEL_RE = re.compile(
    r"^<!-- === HOT_ENTRY:\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*=== -->$"
)
SENTINEL_TEMPLATE = "<!-- === HOT_ENTRY: {timestamp} | {identity} | {model} === -->"
DEFAULT_TITLE = "Session Hot State"


def resolve_machine() -> str:
    try:
        return (
            subprocess.check_output(["hostname", "-s"], text=True, timeout=2)
            .strip()
            .lower()
        )
    except Exception:
        return os.uname().nodename.split(".")[0].lower()


def resolve_agent() -> str:
    agent = (
        os.environ.get("ASSISTANT_ID")
        or os.environ.get("AGENT_NAME")
        or os.environ.get("AGENT_ID")
        or ""
    )
    if agent:
        return agent
    # fallback: try to read from agent_aliases.conf mapping of process name
    try:
        me = Path(f"/proc/{os.getpid()}/comm").read_text().strip()
    except Exception:
        me = ""
    if not me:
        try:
            me = subprocess.check_output(
                ["ps", "-p", str(os.getppid()), "-o", "comm="],
                text=True,
                timeout=2,
            ).strip()
        except Exception:
            me = ""
    if me:
        aliases_path = (
            Path.home()
            / "Documents"
            / "dil_agentic_memory_0001"
            / "_shared"
            / "_meta"
            / "agent_aliases.conf"
        )
        if aliases_path.exists():
            for line in aliases_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    alias_from, alias_to = line.split("=", 1)
                    if alias_from.strip().lower() == me.lower():
                        return alias_to.strip()
    return "unknown"


def resolve_model() -> str:
    return os.environ.get("AGENT_MODEL") or "unknown"


def parse_hot_file(path: Path) -> tuple[str, list[dict]]:
    """Parse _hot.md into (frontmatter_block, [entries]).

    Each entry dict:
        - timestamp: str
        - identity: str   (agent@machine)
        - model: str
        - body: str       (raw markdown content)
    """
    if not path.exists():
        return _default_frontmatter(), []

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Extract YAML frontmatter: first --- ... --- block
    if lines and lines[0].strip() == "---":
        fm_end = 1
        while fm_end < len(lines) and lines[fm_end].strip() != "---":
            fm_end += 1
        fm_end += 1  # include closing ---
        frontmatter = "".join(lines[:fm_end])
        body_lines = lines[fm_end:]
    else:
        frontmatter = _default_frontmatter()
        body_lines = lines

    # Scan body for sentinels
    entries: list[dict] = []
    current_entry: dict | None = None
    current_body_lines: list[str] = []

    for line in body_lines:
        m = SENTINEL_RE.match(line.strip())
        if m:
            # Finalize previous entry
            if current_entry is not None:
                current_entry["body"] = "".join(current_body_lines).strip("\n")
                entries.append(current_entry)
            elif current_body_lines:
                # Content before first sentinel: legacy entry (only if non-empty)
                body = "".join(current_body_lines).strip("\n")
                if body:
                    legacy_identity = f"{resolve_agent()}@{resolve_machine()}"
                    entries.append(
                        {
                            "timestamp": "legacy",
                            "identity": legacy_identity,
                            "model": "legacy",
                            "body": body,
                        }
                    )
            # Start new entry
            current_entry = {
                "timestamp": m.group(1).strip(),
                "identity": m.group(2).strip(),
                "model": m.group(3).strip(),
                "body": "",
            }
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # Finalize last entry
    if current_entry is not None:
        current_entry["body"] = "".join(current_body_lines).strip("\n")
        entries.append(current_entry)
    elif current_body_lines:
        # Trailing legacy content
        legacy_identity = f"{resolve_agent()}@{resolve_machine()}"
        entries.append(
            {
                "timestamp": "legacy",
                "identity": legacy_identity,
                "model": "legacy",
                "body": "".join(current_body_lines).strip("\n"),
            }
        )

    return frontmatter, entries


def _default_frontmatter() -> str:
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    return f"---\ntitle: {DEFAULT_TITLE}\nupdated: {now}\n---\n"


def update_frontmatter_timestamp(frontmatter: str) -> str:
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    lines = frontmatter.splitlines()
    out = []
    for line in lines:
        if line.strip().startswith("updated:"):
            out.append(f"updated: {now}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def build_hot_file(frontmatter: str, entries: list[dict]) -> str:
    parts = [frontmatter]
    first = True
    for entry in entries:
        sentinel = SENTINEL_TEMPLATE.format(
            timestamp=entry["timestamp"],
            identity=entry["identity"],
            model=entry["model"],
        )
        if first:
            parts.append("\n\n")
            first = False
        else:
            parts.append("\n\n")
        parts.append(sentinel)
        parts.append("\n\n")
        parts.append(entry["body"])
    parts.append("\n\n")
    return "".join(parts)


def do_write(
    hot_path: Path,
    content: str,
    title: str | None,
    agent: str,
    machine: str,
    model: str,
    dry_run: bool,
    log: ToolForgeLogger | None,
) -> int:
    frontmatter, entries = parse_hot_file(hot_path)
    frontmatter = update_frontmatter_timestamp(frontmatter)

    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    identity = f"{agent}@{machine}"

    # Wrap content with optional title
    body = content
    if title:
        body = f"## {title}\n\n{body}"
    else:
        body = f"## Hot Entry {now}\n\n{body}"

    new_entry = {
        "timestamp": now,
        "identity": identity,
        "model": model,
        "body": body.strip("\n"),
    }

    # Prepend: new entry first, then existing entries
    entries = [new_entry] + entries

    output = build_hot_file(frontmatter, entries)

    if dry_run:
        print("--- DRY RUN ---")
        print(output)
        print("--- END DRY RUN ---")
        print(f"OK | write | {now} | {identity} | dry_run")
        return 0

    hot_path.parent.mkdir(parents=True, exist_ok=True)
    hot_path.write_text(output, encoding="utf-8")

    if log:
        log.info(f"wrote entry {now} {identity}")
        log.info(f"total entries: {len(entries)}")

    print(f"OK | write | {now} | {identity} | entries:{len(entries)}")
    return 0


def do_read(
    hot_path: Path,
    latest: bool,
    n_prev: int | None,
    date_filter: str | None,
    all_entries: bool,
    raw: bool,
    log: ToolForgeLogger | None,
) -> int:
    frontmatter, entries = parse_hot_file(hot_path)

    if not entries:
        print("ERR | 3 | no entries found in _hot.md")
        return 3

    selected: list[dict] = []

    if all_entries:
        selected = entries
    elif latest or n_prev == 0:
        selected = [entries[0]]
    elif n_prev is not None:
        if n_prev < 0:
            print("ERR | 2 | -N must be non-negative")
            return 2
        if n_prev >= len(entries):
            print(f"ERR | 3 | only {len(entries)} entries available, -N {n_prev} out of range")
            return 3
        selected = [entries[n_prev]]
    elif date_filter:
        found = False
        for entry in entries:
            if entry["timestamp"].startswith(date_filter):
                selected = [entry]
                found = True
                break
        if not found:
            print(f"ERR | 3 | no entry found for date {date_filter}")
            return 3
    else:
        print("ERR | 2 | specify --latest, -N, --date, or --all")
        return 2

    if log:
        log.info(f"read selected {len(selected)} entries from {len(entries)} total")

    for entry in selected:
        if not raw:
            print(f"--- HOT_ENTRY: {entry['timestamp']} | {entry['identity']} | {entry['model']} ---")
        print(entry["body"])
        if not raw and len(selected) > 1:
            print("\n")

    return 0


def do_status(hot_path: Path, log: ToolForgeLogger | None) -> int:
    frontmatter, entries = parse_hot_file(hot_path)

    # Extract updated timestamp from frontmatter
    updated = "unknown"
    for line in frontmatter.splitlines():
        if line.strip().startswith("updated:"):
            updated = line.split(":", 1)[1].strip()
            break

    latest_identity = entries[0]["identity"] if entries else "none"
    latest_time = entries[0]["timestamp"] if entries else "none"

    print(f"OK | status | entries:{len(entries)} | updated:{updated} | latest:{latest_identity}@{latest_time}")

    if log:
        log.info(f"status: {len(entries)} entries, latest {latest_identity}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Deterministic _hot.md prepend-only manager with sentinel separation and indexed retrieval",
    )
    parser.add_argument("--base", default="", help="DIL base path (default: auto-resolve)")
    parser.add_argument("--dry-run", action="store_true", help="preview without side effects")
    parser.add_argument(
        "--hot-path",
        default="",
        help="override path to _hot.md (default: {base}/_shared/_hot.md)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # write
    write_p = subparsers.add_parser("write", help="prepend a new hot entry")
    write_p.add_argument("--content", default="", help="inline markdown content")
    write_p.add_argument("--content-file", default="", help="path to file containing content")
    write_p.add_argument("--stdin", action="store_true", help="read content from stdin")
    write_p.add_argument("--title", default="", help="entry title (default: auto-generated)")
    write_p.add_argument("--agent", default=resolve_agent(), help="agent identity")
    write_p.add_argument("--machine", default=resolve_machine(), help="machine identity")
    write_p.add_argument("--model", default=resolve_model(), help="model identity")

    # read
    read_p = subparsers.add_parser("read", help="retrieve one or more hot entries")
    read_p.add_argument("--latest", action="store_true", help="read the most recent entry")
    read_p.add_argument("-N", type=int, dest="n_prev", default=None, help="read Nth previous entry (0=latest)")
    read_p.add_argument("--date", dest="date_filter", default="", help="read first entry matching date prefix (YYYY-MM-DD)")
    read_p.add_argument("--all", action="store_true", dest="all_entries", help="output all entries")
    read_p.add_argument("--raw", action="store_true", help="output body only, no metadata wrapper")

    # status
    status_p = subparsers.add_parser("status", help="show _hot.md summary")

    arguments = parser.parse_args()

    # Resolve base
    if arguments.base:
        base = Path(arguments.base).expanduser().resolve()
    else:
        try:
            base = Path(resolve_dil_base(str(SCRIPT_DIR)))
        except RuntimeError:
            base = Path.home() / "Documents" / "dil_agentic_memory_0001"

    hot_path = Path(arguments.hot_path) if arguments.hot_path else base / "_shared" / "_hot.md"

    log = None
    if ToolForgeLogger:
        log = ToolForgeLogger(SCRIPT_NAME, str(arguments.command), str(base))
        log.section("Configuration")
        log.info(f"base: {base}")
        log.info(f"hot_path: {hot_path}")
        log.info(f"command: {arguments.command}")
        if arguments.dry_run:
            log.info("dry_run: true")

    if log:
        log.section("Processing")

    rc = 0
    if arguments.command == "write":
        content = ""
        if arguments.stdin:
            content = sys.stdin.read()
        elif arguments.content_file:
            content = Path(arguments.content_file).read_text(encoding="utf-8")
        elif arguments.content:
            content = arguments.content
        else:
            print("ERR | 2 | provide --content, --content-file, or --stdin")
            return 2

        rc = do_write(
            hot_path,
            content,
            arguments.title or None,
            arguments.agent,
            arguments.machine,
            arguments.model,
            arguments.dry_run,
            log,
        )

    elif arguments.command == "read":
        rc = do_read(
            hot_path,
            arguments.latest,
            arguments.n_prev,
            arguments.date_filter or None,
            arguments.all_entries,
            arguments.raw,
            log,
        )

    elif arguments.command == "status":
        rc = do_status(hot_path, log)

    if log:
        log.section("Result")
        log.info(f"exit_code: {rc}")
        log.close()

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
