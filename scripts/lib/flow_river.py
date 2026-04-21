#!/usr/bin/env python3
"""
flow_river.py — Harvest DIL + work log filenames and generate the Flow River visualization.

Usage:
  flow_river.py [--output PATH] [--template PATH] [--log-dir PATH ...]

Scans log directories for .log files, parses timestamps and tool names from
filenames, injects the data as JSON into the HTML template, and writes the result.
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from resolve_base import resolve_dil_base
except ImportError:
    resolve_dil_base = None


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


def harvest_logs(log_dirs: list[Path], max_depth: int = 3) -> list[str]:
    filenames = []
    for d in log_dirs:
        if not d.is_dir():
            continue
        for root, _, files in os.walk(d):
            depth = len(Path(root).relative_to(d).parts)
            if depth > max_depth:
                continue
            for f in files:
                if f.endswith(".log"):
                    filenames.append(f)
    return filenames


def build_html(template_path: Path, log_filenames: list[str]) -> str:
    template = template_path.read_text(encoding="utf-8")
    data_json = json.dumps(log_filenames)
    return template.replace("__LOG_DATA__", data_json)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(str(script_dir))
    base_path = Path(base)

    default_template = script_dir.parent / "flow_river.html"
    default_output = Path("/tmp/flow_river_live.html")

    parser = argparse.ArgumentParser(
        prog="flow_river",
        description="Generate the DIL Flow River visualization from log files.",
    )
    parser.add_argument("--output", "-o", default=str(default_output), help="Output HTML path")
    parser.add_argument("--template", default=str(default_template), help="HTML template path")
    parser.add_argument("--log-dir", action="append", default=None, help="Additional log directories to scan")
    parser.add_argument("--no-open", action="store_true", help="Don't open in browser")
    args = parser.parse_args()

    log_dirs = [base_path / "_shared" / "logs"]

    az_logs = Path("/az/talend/logs")
    if az_logs.is_dir():
        log_dirs.append(az_logs)

    if args.log_dir:
        log_dirs.extend(Path(d) for d in args.log_dir)

    filenames = harvest_logs(log_dirs)

    template_path = Path(args.template)
    if not template_path.is_file():
        print(f"Error: template not found: {template_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    html = build_html(template_path, filenames)
    output_path.write_text(html, encoding="utf-8")

    print(f"Flow River generated: {output_path}")
    print(f"Events harvested: {len(filenames)}")

    if not args.no_open:
        import subprocess
        import shutil
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, str(output_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return 0


if __name__ == "__main__":
    sys.exit(main())
