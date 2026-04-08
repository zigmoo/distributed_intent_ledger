#!/usr/bin/env python3
"""Unified task_tool implementation.

Subcommands:
  search   Filter and list tasks from the task index, with active-dir fallback
  review   Show a single task file with key frontmatter and body
  handoff  Create a structured handoff note, append task evidence, optionally set status
  pickup   Read the latest handoff note and optionally claim the task
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DISPLAY_KEYS = [
    "task_id",
    "title",
    "date",
    "domain",
    "status",
    "priority",
    "owner",
    "due",
    "project",
    "work_type",
    "task_type",
    "effort_type",
    "created_by",
    "created_at",
    "parent_task_id",
    "subcategory",
]


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def fail(code: int, msg: str) -> None:
    eprint(f"ERR | {code} | {msg}")
    raise SystemExit(code)


def run_cmd(cmd: list[str], dry_run: bool = False) -> tuple[int, str, str]:
    if dry_run:
        return 0, f"DRY_RUN: {' '.join(shlex.quote(x) for x in cmd)}", ""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_date() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def load_registry(base: Path) -> dict[str, Any]:
    registry_path = base / "_shared" / "_meta" / "domain_registry.json"
    if not registry_path.exists():
        fail(4, f"Missing domain registry: {registry_path}")
    return json.loads(registry_path.read_text(encoding="utf-8"))


def domain_map(base: Path) -> dict[str, Any]:
    return load_registry(base).get("domains", {})


def resolve_registered_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else base / path


def resolve_domain_task_dir(base: Path, domain: str) -> Path:
    domains = domain_map(base)
    if domain not in domains:
        fail(2, f"unknown domain: {domain}")
    task_dir = domains[domain].get("task_dir")
    if not task_dir:
        fail(4, f"Domain missing task_dir: {domain}")
    return resolve_registered_path(base, task_dir)


def resolve_domain_io_dirs(base: Path, domain: str, script_name: str = "task_tool") -> tuple[Path, Path]:
    domains = domain_map(base)
    if domain not in domains:
        fail(4, f"Domain not found in registry: {domain}")
    entry = domains[domain]
    log_dir = resolve_registered_path(base, entry.get("log_dir", f"_shared/domains/{domain}/logs"))
    data_dir = resolve_registered_path(base, entry.get("data_dir", f"_shared/domains/{domain}/data"))
    return log_dir / script_name, data_dir / script_name


def write_run_artifacts(
    *,
    base: Path,
    domain: str,
    subcmd: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> tuple[Path, Path]:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_dir, data_dir = resolve_domain_io_dirs(base, domain)
    log_path = log_dir / f"task_tool.{subcmd}.{ts}.log"
    data_path = data_dir / f"task_tool.{subcmd}.{ts}.json"
    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"timestamp_utc={payload.get('timestamp_utc', '')}",
            f"task_id={payload.get('task_id', '')}",
            f"subcommand={subcmd}",
            f"domain={domain}",
            f"actor={payload.get('actor', '')}",
            f"model={payload.get('model', '')}",
            "result=ok",
        ]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return log_path, data_path


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    frontmatter_lines = parts[0].splitlines()[1:]
    body = parts[1]
    frontmatter: dict[str, str] = {}
    for line in frontmatter_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip('"')
    return frontmatter, body


def detect_machine(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    try:
        return subprocess.check_output(["hostname", "-s"], text=True).strip().lower()
    except Exception:
        return "unknown"


def detect_assistant(explicit: str | None, script_dir: Path) -> str:
    if explicit:
        return explicit
    for env_var in ("ACTOR", "ASSISTANT_ID", "AGENT_NAME", "AGENT_ID"):
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    identify_script = script_dir / "identify_agent.sh"
    if identify_script.exists() and os.access(identify_script, os.X_OK):
        try:
            proc = subprocess.run([str(identify_script)], capture_output=True, text=True, timeout=5)
            output = proc.stdout.strip()
            if output and output != "UNRESOLVED":
                return output
        except Exception:
            pass
    return "unknown"


def detect_model(explicit: str | None) -> str:
    if explicit:
        return explicit
    for env_var in ("MODEL", "AGENT_MODEL"):
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return "unknown"


def parse_index_rows(index_file: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not index_file.exists():
        return rows
    for line in index_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        if "task_id" in line and "domain" in line and "status" in line:
            continue
        if re.match(r"^\|\s*-", line):
            continue
        cols = [col.strip() for col in line.strip().strip("|").split("|")]
        if len(cols) != 9:
            continue
        rows.append(
            {
                "task_id": cols[0],
                "domain": cols[1],
                "status": cols[2],
                "priority": cols[3],
                "owner": cols[4],
                "due": cols[5],
                "project": cols[6],
                "path": cols[7],
                "updated": cols[8],
            }
        )
    return rows


def fallback_index_rows(base: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for domain in sorted(domain_map(base)):
        active_dir = resolve_domain_task_dir(base, domain) / "active"
        if not active_dir.exists():
            continue
        for task_file in sorted(active_dir.glob("*.md")):
            text = task_file.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(text)
            rel_path = str(task_file.relative_to(base))
            rows.append(
                {
                    "task_id": frontmatter.get("task_id", task_file.stem),
                    "domain": frontmatter.get("domain", domain),
                    "status": frontmatter.get("status", ""),
                    "priority": frontmatter.get("priority", ""),
                    "owner": frontmatter.get("owner", ""),
                    "due": frontmatter.get("due", ""),
                    "project": frontmatter.get("project", ""),
                    "path": rel_path,
                    "updated": frontmatter.get("updated", ""),
                }
            )
    return rows


def index_rows(base: Path) -> list[dict[str, str]]:
    index_file = base / "_shared" / "_meta" / "task_index.md"
    rows = parse_index_rows(index_file)
    return rows if rows else fallback_index_rows(base)


def task_file_for_id(base: Path, task_id: str) -> Path:
    matches: list[Path] = []
    for domain in sorted(domain_map(base)):
        candidate = resolve_domain_task_dir(base, domain) / "active" / f"{task_id}.md"
        if candidate.exists():
            matches.append(candidate)
    if len(matches) != 1:
        fail(2, f"Expected exactly one active task file for {task_id}, found {len(matches)}")
    return matches[0]


def task_summary(task_file: Path) -> dict[str, str]:
    frontmatter, _ = parse_frontmatter(task_file.read_text(encoding="utf-8"))
    return {
        "task_id": frontmatter.get("task_id", task_file.stem),
        "title": frontmatter.get("title", task_file.stem),
        "status": frontmatter.get("status", ""),
        "owner": frontmatter.get("owner", ""),
        "domain": frontmatter.get("domain", ""),
        "project": frontmatter.get("project", ""),
    }


def filtered_rows(args: argparse.Namespace, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed_statuses = {status.strip() for status in args.status.split(",")} if args.status else None
    result: list[dict[str, str]] = []
    for row in rows:
        if allowed_statuses and row["status"] not in allowed_statuses:
            continue
        if args.project and row["project"] != args.project:
            continue
        if args.domain and row["domain"] != args.domain:
            continue
        result.append(row)
    result.sort(key=lambda row: row["updated"], reverse=True)
    if args.latest and len(result) > args.latest:
        result = result[: args.latest]
    return result


def ticket_url(base: Path, task_id: str) -> str:
    script_dir = Path(__file__).resolve().parent
    url_tool = script_dir / "url_tool.sh"
    if not url_tool.exists():
        return ""
    env = os.environ.copy()
    env["URL_TOOL_REGISTRY"] = str(base / "_shared" / "_meta" / "domain_registry.json")
    proc = subprocess.run(
        [str(url_tool), "ticket", task_id, "--plain"],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def linkify_task_id(base: Path, task_id: str) -> str:
    if not sys.stdout.isatty():
        return task_id
    url = ticket_url(base, task_id)
    if not url:
        return task_id
    return f"\033]8;;{url}\033\\{task_id}\033]8;;\033\\"


def cmd_search(args: argparse.Namespace) -> int:
    if args.domain:
        resolve_domain_task_dir(args.base, args.domain)

    rows = filtered_rows(args, index_rows(args.base))
    if args.count:
        if args.json:
            print(json.dumps({"ok": True, "count": len(rows)}))
        else:
            print(len(rows))
        return 0

    if args.json:
        print(json.dumps({"ok": True, "count": len(rows), "data": rows}, indent=2))
        return 0

    for row in rows:
        task_id = row["task_id"]
        display_id = linkify_task_id(args.base, task_id)
        if sys.stdout.isatty():
            print(
                " | ".join(
                    [
                        display_id,
                        row["domain"],
                        row["status"],
                        row["priority"],
                        row["owner"],
                        row["due"],
                        row["project"],
                        row["updated"],
                    ]
                )
            )
        else:
            print(
                " | ".join(
                    [
                        task_id,
                        row["domain"],
                        row["status"],
                        row["priority"],
                        row["owner"],
                        row["due"],
                        row["project"],
                        row["path"],
                        row["updated"],
                    ]
                )
            )
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    task_file = task_file_for_id(args.base, args.task_id)
    frontmatter, body = parse_frontmatter(task_file.read_text(encoding="utf-8"))
    if args.json:
        data = {key: frontmatter.get(key, "") for key in DISPLAY_KEYS}
        data["body"] = body
        print(json.dumps({"ok": True, "data": data}, indent=2))
        return 0
    for key in DISPLAY_KEYS:
        print(f"{key}: {frontmatter.get(key, '')}")
    print("---")
    print(body.rstrip("\n"))
    return 0


def write_handoff_note(
    *,
    base: Path,
    task: dict[str, str],
    from_machine: str,
    from_assistant: str,
    to_machine: str,
    to_assistant: str,
    pending_steps: list[str],
    referenced_files: list[str],
    permitted_paths: list[str],
    allowed_actions: list[str],
    expiry: str,
    details: str,
    dry_run: bool,
) -> Path:
    ts = now_utc_iso()
    slug_ts = ts.replace(":", "").replace("-", "")
    out_dir = base / to_machine / to_assistant / "handoffs"
    out_path = out_dir / f"{task['task_id']}-handoff-{slug_ts}.md"
    if not pending_steps:
        pending_steps = ["Review latest execution note and proceed with next actionable step."]
    if not permitted_paths:
        permitted_paths = [str(base / to_machine / to_assistant)]
    if not allowed_actions:
        allowed_actions = ["create", "append", "update"]

    body_lines: list[str] = [
        f"# Handoff: {task['task_id']}",
        "",
        "## Summary",
        f"- task_id: {task['task_id']}",
        f"- task_title: {task['title']}",
        f"- from: {from_machine}/{from_assistant}",
        f"- to: {to_machine}/{to_assistant}",
        f"- created_at_utc: {ts}",
        "",
        "## Authorization",
        f"- requesting_actor: {from_assistant}",
        "- permitted_paths:",
    ]
    for path in permitted_paths:
        body_lines.append(f"  - {path}")
    body_lines.append("- allowed_actions:")
    for action in allowed_actions:
        body_lines.append(f"  - {action}")
    body_lines.extend(
        [
            f"- expiry: {expiry}",
            "",
            "## Pending Steps",
        ]
    )
    for step in pending_steps:
        body_lines.append(f"- {step}")
    body_lines.extend(["", "## Referenced Files"])
    if referenced_files:
        for ref in referenced_files:
            body_lines.append(f"- {ref}")
    else:
        body_lines.append("- (none)")
    body_lines.append("")
    if details.strip():
        body_lines.append("## Context")
        body_lines.extend(details.rstrip("\n").splitlines())
        body_lines.append("")

    frontmatter_lines = [
        "---",
        f'title: "{task["task_id"]} handoff to {to_machine}/{to_assistant}"',
        f"date: {today_date()}",
        f"machine: {to_machine}",
        f"assistant: {to_assistant}",
        "category: handoff",
        "memoryType: handoff",
        "priority: high",
        f"tags: [handoff, {task['task_id']}]",
        f"updated: {today_date()}",
        "source: internal",
        "domain: operations",
        "project: dil",
        "status: active",
        f"owner: {to_assistant}",
        "due:",
        f"task_id: {task['task_id']}",
        f"from_scope: {from_machine}/{from_assistant}",
        f"to_scope: {to_machine}/{to_assistant}",
        f"created_at: {ts}",
        "---",
        "",
    ]
    content = "\n".join(frontmatter_lines + body_lines) + "\n"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
    return out_path


def append_task_note(base: Path, task_file: Path, content: str, dry_run: bool) -> None:
    append_script = base / "_shared" / "scripts" / "append_task_execution_note.sh"
    if not append_script.exists():
        fail(4, f"Missing required script: {append_script}")
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(content)
        temp_path = temp_file.name
    try:
        cmd = [str(append_script), "--file", str(task_file), "--content-file", temp_path, "--base", str(base)]
        rc, out, err = run_cmd(cmd, dry_run)
        if rc != 0:
            fail(5, err or out or "append_task_execution_note.sh failed")
    finally:
        if not dry_run:
            Path(temp_path).unlink(missing_ok=True)


def set_task_status(
    base: Path,
    task_id: str,
    status: str,
    owner: str | None,
    reason: str,
    actor: str,
    model: str,
    dry_run: bool,
) -> None:
    status_script = base / "_shared" / "scripts" / "set_task_status.sh"
    if not status_script.exists():
        fail(4, f"Missing required script: {status_script}")
    cmd = [
        str(status_script),
        "--task-id",
        task_id,
        "--status",
        status,
        "--reason",
        reason,
        "--actor",
        actor,
        "--model",
        model,
        "--base",
        str(base),
    ]
    if owner:
        cmd.extend(["--owner", owner])
    rc, out, err = run_cmd(cmd, dry_run)
    if rc != 0:
        fail(5, err or out or "set_task_status.sh failed")


def gather_handoff_notes(base: Path, task_id: str) -> list[Path]:
    notes: list[Path] = []
    for note_path in base.glob("*/*/handoffs/*.md"):
        if note_path.name == "change_log.md":
            continue
        try:
            text = note_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if task_id in text:
            notes.append(note_path)
    notes.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return notes


def summarize_handoff(path: Path, task_id: str) -> dict[str, Any]:
    frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    pending_steps: list[str] = []
    referenced_files: list[str] = []
    section = ""
    for line in body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if section == "pending steps":
            pending_steps.append(item)
        elif section == "referenced files":
            referenced_files.append(item)
    return {
        "task_id": task_id,
        "path": str(path),
        "from_scope": frontmatter.get("from_scope", ""),
        "to_scope": frontmatter.get("to_scope", ""),
        "created_at": frontmatter.get("created_at", ""),
        "pending_steps": pending_steps,
        "referenced_files": referenced_files,
        "title": frontmatter.get("title", ""),
    }


def cmd_handoff(args: argparse.Namespace) -> int:
    task_file = task_file_for_id(args.base, args.task_id)
    task = task_summary(task_file)
    script_dir = Path(__file__).resolve().parent
    actor = detect_assistant(args.actor, script_dir)
    model = detect_model(args.model)
    from_machine = detect_machine(args.from_machine)
    from_assistant = args.from_assistant or actor
    to_machine = args.to_machine or from_machine
    to_assistant = args.to_assistant or from_assistant

    details = ""
    if args.content_file:
        content_file = Path(args.content_file).expanduser()
        if not content_file.exists():
            fail(2, f"--content-file not found: {content_file}")
        details = content_file.read_text(encoding="utf-8")
    elif args.note:
        details = args.note + "\n"

    handoff_path = write_handoff_note(
        base=args.base,
        task=task,
        from_machine=from_machine,
        from_assistant=from_assistant,
        to_machine=to_machine,
        to_assistant=to_assistant,
        pending_steps=args.pending_step or [],
        referenced_files=args.ref_file or [],
        permitted_paths=args.permitted_path or [],
        allowed_actions=args.allowed_action or [],
        expiry=args.expiry,
        details=details,
        dry_run=args.dry_run,
    )

    if not args.no_status:
        set_task_status(
            base=args.base,
            task_id=args.task_id,
            status=args.status,
            owner=None,
            reason=args.reason,
            actor=actor,
            model=model,
            dry_run=args.dry_run,
        )

    note = (
        f"Handoff created: {handoff_path}\n"
        f"- from: {from_machine}/{from_assistant}\n"
        f"- to: {to_machine}/{to_assistant}\n"
        f"- status_set: {args.status if not args.no_status else 'skipped'}\n"
    )
    append_task_note(args.base, task_file, note, args.dry_run)
    payload = {
        "ok": True,
        "timestamp_utc": now_utc_iso(),
        "task_id": args.task_id,
        "domain": task.get("domain", ""),
        "actor": actor,
        "model": model,
        "handoff_path": str(handoff_path),
        "from_scope": f"{from_machine}/{from_assistant}",
        "to_scope": f"{to_machine}/{to_assistant}",
        "status_set": None if args.no_status else args.status,
        "dry_run": args.dry_run,
    }
    log_path, data_path = write_run_artifacts(
        base=args.base,
        domain=task.get("domain", ""),
        subcmd="handoff",
        payload=payload,
        dry_run=args.dry_run,
    )
    if args.json:
        output = dict(payload)
        output["log_path"] = str(log_path)
        output["data_path"] = str(data_path)
        print(json.dumps(output, indent=2))
    else:
        print(f"OK | {args.task_id} | handoff | {handoff_path}")
    return 0


def cmd_pickup(args: argparse.Namespace) -> int:
    task_file = task_file_for_id(args.base, args.task_id)
    task = task_summary(task_file)
    notes = gather_handoff_notes(args.base, args.task_id)
    if not notes:
        fail(2, f"No handoff note found for {args.task_id}")
    latest = notes[0]
    summary = summarize_handoff(latest, args.task_id)
    script_dir = Path(__file__).resolve().parent
    actor = detect_assistant(args.actor, script_dir)
    model = detect_model(args.model)

    if args.claim:
        claim_owner = args.owner or actor
        set_task_status(
            base=args.base,
            task_id=args.task_id,
            status=args.status,
            owner=claim_owner,
            reason=args.reason,
            actor=actor,
            model=model,
            dry_run=args.dry_run,
        )
        claim_note = (
            f"Pickup acknowledged from {summary['path']}\n"
            f"- claimed_by: {claim_owner}\n"
            f"- status_set: {args.status}\n"
        )
        append_task_note(args.base, task_file, claim_note, args.dry_run)

    payload = {
        "ok": True,
        "timestamp_utc": now_utc_iso(),
        "task_id": args.task_id,
        "domain": task.get("domain", ""),
        "actor": actor,
        "model": model,
        "latest_handoff": summary,
        "claim_applied": bool(args.claim),
        "claim_owner": (args.owner or actor) if args.claim else None,
        "claim_status": args.status if args.claim else None,
        "dry_run": args.dry_run,
    }
    log_path, data_path = write_run_artifacts(
        base=args.base,
        domain=task.get("domain", ""),
        subcmd="pickup",
        payload=payload,
        dry_run=args.dry_run,
    )
    if args.json:
        output = dict(payload)
        output["log_path"] = str(log_path)
        output["data_path"] = str(data_path)
        print(json.dumps(output, indent=2))
    else:
        print(f"OK | {args.task_id} | pickup | {summary['path']}")
        print(f"from: {summary.get('from_scope', '')}")
        print(f"to: {summary.get('to_scope', '')}")
        if summary.get("pending_steps"):
            print("pending_steps:")
            for step in summary["pending_steps"][:10]:
                print(f"- {step}")
        if summary.get("referenced_files"):
            print("referenced_files:")
            for path in summary["referenced_files"][:10]:
                print(f"- {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="task_tool",
        description="Fast task discovery, review, and handoff tooling",
    )
    parser.add_argument("--base", required=True, help="Resolved DIL base path from task_tool.sh")
    parser.add_argument("--json", action="store_true", help="Emit JSON output where supported")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search the task index")
    search.add_argument("--status", help="Comma-separated status filter")
    search.add_argument("--project", help="Exact project slug")
    search.add_argument("--domain", help="Registered domain name")
    search.add_argument("--latest", type=int, default=0, help="Limit to latest N tasks by updated date")
    search.add_argument("--count", action="store_true", help="Print count only")
    search.set_defaults(func=cmd_search)

    review = subparsers.add_parser("review", help="Review a single task")
    review.add_argument("task_id")
    review.set_defaults(func=cmd_review)

    handoff = subparsers.add_parser("handoff", help="Create a task handoff note")
    handoff.add_argument("--task-id", required=True)
    handoff.add_argument("--to-machine")
    handoff.add_argument("--to-assistant")
    handoff.add_argument("--from-machine")
    handoff.add_argument("--from-assistant")
    handoff.add_argument("--status", default="in_progress")
    handoff.add_argument("--reason", default="task_tool handoff")
    handoff.add_argument("--note")
    handoff.add_argument("--content-file")
    handoff.add_argument("--pending-step", action="append")
    handoff.add_argument("--ref-file", action="append")
    handoff.add_argument("--permitted-path", action="append")
    handoff.add_argument("--allowed-action", action="append")
    handoff.add_argument("--expiry", default="")
    handoff.add_argument("--no-status", action="store_true")
    handoff.add_argument("--actor")
    handoff.add_argument("--model")
    handoff.add_argument("--dry-run", action="store_true")
    handoff.set_defaults(func=cmd_handoff)

    pickup = subparsers.add_parser("pickup", help="Read latest handoff note and optionally claim")
    pickup.add_argument("--task-id", required=True)
    pickup.add_argument("--claim", action="store_true")
    pickup.add_argument("--owner")
    pickup.add_argument("--status", default="in_progress")
    pickup.add_argument("--reason", default="task_tool pickup")
    pickup.add_argument("--actor")
    pickup.add_argument("--model")
    pickup.add_argument("--dry-run", action="store_true")
    pickup.set_defaults(func=cmd_pickup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.base = Path(args.base).expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
