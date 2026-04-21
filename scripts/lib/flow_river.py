#!/usr/bin/env python3
"""
flow_river.py — Harvest, persist, and visualize DIL operational activity.

Subcommands:
  render    Scan logs and generate the Flow River HTML visualization (default)
  harvest   Scan logs and emit a portable JSON data file with metadata

Exit codes: 0=success, 1=error
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from resolve_base import resolve_dil_base
except ImportError:
    resolve_dil_base = None

SCRIPT_NAME = "flow_river"
DATA_FORMAT_VERSION = 1


def resolve_base(script_dir: str | None = None) -> str:
    if resolve_dil_base:
        return resolve_dil_base(script_dir)
    base = os.environ.get("BASE_DIL") or os.environ.get("DIL_BASE") or os.environ.get("CLAWVAULT_BASE")
    if base:
        return str(Path(base).expanduser())
    legacy = Path.home() / "Documents" / "dil_agentic_memory_0001"
    if (legacy / "_shared").is_dir():
        return str(legacy)
    raise RuntimeError("Could not resolve DIL base. Set BASE_DIL.")


# ---------------------------------------------------------------------------
# Log harvesting
# ---------------------------------------------------------------------------

def get_log_dirs(base_path: Path, extra_dirs: list[str] | None = None) -> list[tuple[Path, str]]:
    log_dirs: list[tuple[Path, str]] = [(base_path / "_shared" / "logs", "DIL")]
    az_logs = Path("/az/talend/logs")
    if az_logs.is_dir():
        log_dirs.append((az_logs, "Work"))
    if extra_dirs:
        for d in extra_dirs:
            label = Path(d).name or "Custom"
            log_dirs.append((Path(d), label))
    return log_dirs


def harvest_log_filenames(log_dirs: list[tuple[Path, str]], max_depth: int = 3) -> list[dict]:
    entries = []
    for d, domain in log_dirs:
        if not d.is_dir():
            continue
        for root, _, files in os.walk(d):
            depth = len(Path(root).relative_to(d).parts)
            if depth > max_depth:
                continue
            for f in files:
                if f.endswith(".log"):
                    entries.append({"file": f, "domain": domain})
    return entries


def parse_log_filename(filename: str) -> dict | None:
    basename = filename.rsplit("/", 1)[-1].removesuffix(".log")
    m = re.match(r"^([^.]+)\.([^.]+)\.([^.]+)\.(\d{8}_\d{6})$", basename)
    if m:
        return {"machine": m.group(1), "tool": m.group(2), "action": m.group(3), "ts": parse_ts(m.group(4))}

    m = re.match(r"^([^.]+)\.([^.]+)\.(\d{8}_\d{6})$", basename)
    if m:
        return {"tool": m.group(1), "action": m.group(2), "ts": parse_ts(m.group(3))}

    m = re.match(r"^(.+?)_(\d{8})-(\d{6})$", basename)
    if m:
        return {"tool": m.group(1), "action": "run", "ts": parse_ts(m.group(2) + "_" + m.group(3))}

    m = re.search(r"(\d{8}_\d{6})$", basename)
    if m:
        prefix = re.sub(r"\.?\d{8}_\d{6}$", "", basename)
        parts = prefix.split(".")
        action = parts.pop() if len(parts) > 1 else "run"
        tool = ".".join(parts) or "unknown"
        return {"tool": tool, "action": action, "ts": parse_ts(m.group(1))}

    return None


def parse_ts(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}Z"


# ---------------------------------------------------------------------------
# Git / DIL version info
# ---------------------------------------------------------------------------

def get_dil_version(base_path: Path) -> dict:
    info: dict = {"commit": None, "branch": None, "commit_date": None, "dirty": None, "remote_url": None}

    git_dir = base_path
    # DIL might not be a git repo (Obsidian-synced), check for .git
    if not (git_dir / ".git").exists():
        # Check if the template repo is available as a reference
        template = Path.home() / "projects" / "ai_projects" / "distributed_intent_ledger"
        if (template / ".git").exists():
            git_dir = template
        else:
            return info

    try:
        def git(*args: str) -> str:
            r = subprocess.run(
                ["git", "-C", str(git_dir)] + list(args),
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else ""

        info["commit"] = git("rev-parse", "--short", "HEAD") or None
        info["branch"] = git("rev-parse", "--abbrev-ref", "HEAD") or None
        info["commit_date"] = git("log", "-1", "--format=%aI") or None
        info["dirty"] = bool(git("status", "--porcelain"))
        info["remote_url"] = git("remote", "get-url", "origin") or None

        behind = git("rev-list", "--count", "HEAD..@{u}")
        info["behind_remote"] = int(behind) if behind.isdigit() else None
    except (subprocess.TimeoutExpired, OSError):
        pass

    return info


def get_machine_info() -> dict:
    try:
        hostname = subprocess.run(
            ["hostname", "-s"], capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip().lower()
    except (subprocess.TimeoutExpired, OSError):
        hostname = "unknown"

    return {
        "hostname": hostname,
        "user": os.environ.get("USER", "unknown"),
    }


# ---------------------------------------------------------------------------
# harvest subcommand
# ---------------------------------------------------------------------------

def cmd_harvest(args: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(str(script_dir))
    base_path = Path(base)

    log_dirs = get_log_dirs(base_path, args.log_dir)
    raw_entries = harvest_log_filenames(log_dirs)

    events = []
    for entry in raw_entries:
        parsed = parse_log_filename(entry["file"])
        if not parsed:
            continue
        event = {
            "tool": parsed["tool"],
            "action": parsed["action"],
            "ts": parsed["ts"],
            "domain": entry["domain"],
        }
        if "machine" in parsed:
            event["machine"] = parsed["machine"]
        events.append(event)

    events.sort(key=lambda e: e["ts"])

    machine_info = get_machine_info()
    dil_version = get_dil_version(base_path)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = {
        "version": DATA_FORMAT_VERSION,
        "harvested_at": now,
        "machine": machine_info["hostname"],
        "user": machine_info["user"],
        "dil": dil_version,
        "event_count": len(events),
        "domain_counts": {},
        "tool_counts": {},
        "events": events,
    }

    for e in events:
        data["domain_counts"][e["domain"]] = data["domain_counts"].get(e["domain"], 0) + 1
        data["tool_counts"][e["tool"]] = data["tool_counts"].get(e["tool"], 0) + 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print(f"Harvest complete: {output_path}")
    print(f"Events: {len(events)} | Domains: {len(data['domain_counts'])} | Tools: {len(data['tool_counts'])}")
    print(f"Machine: {machine_info['hostname']} | User: {machine_info['user']}")
    if dil_version["commit"]:
        behind = dil_version.get("behind_remote")
        behind_str = f" ({behind} commits behind)" if behind else ""
        print(f"DIL version: {dil_version['commit']} ({dil_version['branch']}){behind_str}")
    return 0


# ---------------------------------------------------------------------------
# render subcommand
# ---------------------------------------------------------------------------

def cmd_render(args: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(str(script_dir))
    base_path = Path(base)

    default_template = script_dir.parent / "flow_river.html"
    template_path = Path(args.template) if args.template else default_template

    if not template_path.is_file():
        print(f"Error: template not found: {template_path}", file=sys.stderr)
        return 1

    if args.data_file:
        data = json.loads(Path(args.data_file).read_text(encoding="utf-8"))
        log_entries = [{"file": f"{e['tool']}.{e['action']}.{e['ts'].replace('-','').replace(':','').replace('T','_')[:15]}.log", "domain": e["domain"]} for e in data["events"]]
    else:
        log_dirs = get_log_dirs(base_path, args.log_dir)
        log_entries = harvest_log_filenames(log_dirs)

    template = template_path.read_text(encoding="utf-8")
    html = template.replace("__LOG_DATA__", json.dumps(log_entries))

    output_path = Path(args.output)
    output_path.write_text(html, encoding="utf-8")

    print(f"Flow River generated: {output_path}")
    print(f"Events: {len(log_entries)}")

    if not args.no_open:
        import shutil
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, str(output_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flow_river",
        description="Harvest, persist, and visualize DIL operational activity.",
    )
    sub = parser.add_subparsers(dest="command")

    # -- render (default) --
    p_render = sub.add_parser("render", help="Generate the Flow River HTML visualization")
    p_render.add_argument("--output", "-o", default="/tmp/flow_river_live.html", help="Output HTML path")
    p_render.add_argument("--template", default="", help="HTML template path")
    p_render.add_argument("--data-file", default="", help="Load from a harvest JSON file instead of scanning logs")
    p_render.add_argument("--log-dir", action="append", default=None, help="Additional log directories")
    p_render.add_argument("--no-open", action="store_true", help="Don't open in browser")

    # -- harvest --
    p_harvest = sub.add_parser("harvest", help="Scan logs and emit a portable JSON data file")
    p_harvest.add_argument("--output", "-o", default="", help="Output JSON path (default: /tmp/flow_river_<hostname>_<timestamp>.json)")
    p_harvest.add_argument("--log-dir", action="append", default=None, help="Additional log directories")

    return parser


def main() -> int:
    # If first arg isn't a known subcommand, default to render
    known = {"render", "harvest", "-h", "--help"}
    if len(sys.argv) < 2 or sys.argv[1] not in known:
        sys.argv.insert(1, "render")

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "render":
        return cmd_render(args)
    elif args.command == "harvest":
        if not args.output:
            hostname = get_machine_info()["hostname"]
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            args.output = f"/tmp/flow_river_{hostname}_{ts}.json"
        return cmd_harvest(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
