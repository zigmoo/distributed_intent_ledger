#!/usr/bin/env python3
"""Unified task_tool implementation.

Subcommands:
  search   Filter and list tasks from the task index, with active-dir fallback
  review   Show a single task file with key frontmatter and body
  status   Set task status (and optionally owner) with transition validation
  handoff  Create a structured handoff note, append task evidence, optionally set status
  pickup   Read the latest handoff note and optionally claim the task
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


VALID_STATUSES = {"todo", "assigned", "in_progress", "blocked", "done", "cancelled", "retired"}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"assigned", "in_progress", "blocked", "cancelled", "retired"},
    "assigned": {"in_progress", "blocked", "done", "cancelled", "retired"},
    "in_progress": {"blocked", "done", "assigned", "cancelled", "retired"},
    "blocked": {"in_progress", "assigned", "cancelled", "retired"},
    "done": {"retired"},
    "cancelled": {"retired"},
    "retired": {"todo", "in_progress"},
}

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
        if line.startswith(" ") or line.startswith("\t"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in frontmatter:
            frontmatter[key] = value.strip().strip('"')
    return frontmatter, body


def extract_body(text: str) -> str:
    _, body = parse_frontmatter(text)
    return body


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


class DirLock:
    def __init__(self, lock_path: Path, max_retries: int = 50, backoff_s: float = 0.1):
        self.lock_path = lock_path
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.held = False

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self.max_retries):
            try:
                self.lock_path.mkdir()
                self.held = True
                return True
            except FileExistsError:
                time.sleep(self.backoff_s)
        return False

    def release(self) -> None:
        if self.held:
            try:
                self.lock_path.rmdir()
            except OSError:
                pass
            self.held = False

    def __enter__(self) -> "DirLock":
        if not self.acquire():
            fail(4, f"Could not acquire lock: {self.lock_path}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def update_task_frontmatter(task_file: Path, updates: dict[str, str]) -> None:
    text = task_file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    dash_count = 0
    inside = False
    out: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n")
        if stripped == "---":
            dash_count += 1
            inside = dash_count == 1
            out.append(line)
            continue
        if inside:
            key_match = re.match(r"^(\w[\w_-]*):", stripped)
            if key_match and key_match.group(1) in updates:
                key = key_match.group(1)
                out.append(f"{key}: {updates[key]}\n")
                continue
        out.append(line)
    task_file.write_text("".join(out), encoding="utf-8")


def update_index_row(index_file: Path, task_id: str, new_row: str) -> None:
    text = index_file.read_text(encoding="utf-8")
    pattern = re.compile(r"^\|\s*" + re.escape(task_id) + r"\s*\|.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(new_row, text)
    else:
        text = text.rstrip("\n") + "\n" + new_row + "\n"
    index_file.write_text(text, encoding="utf-8")


def append_changelog_rows(changelog_file: Path, rows: list[str]) -> None:
    with changelog_file.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(row + "\n")


def cmd_status(args: argparse.Namespace) -> int:
    task_file = task_file_for_id(args.base, args.task_id)
    frontmatter, _ = parse_frontmatter(task_file.read_text(encoding="utf-8"))
    old_status = frontmatter.get("status", "")
    old_owner = frontmatter.get("owner", "")
    domain = frontmatter.get("domain", "")
    project = frontmatter.get("project", "")
    priority = frontmatter.get("priority", "")
    due = frontmatter.get("due", "")

    new_status = args.status
    new_owner = args.owner if args.owner else old_owner

    if new_status not in VALID_STATUSES:
        fail(2, f"Invalid --status: {new_status}")

    if old_status == new_status and old_owner == new_owner:
        print(f"No changes required for {args.task_id}")
        return 0

    if old_status != new_status:
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            fail(1, f"Invalid status transition: {old_status} -> {new_status}")

    script_dir = Path(__file__).resolve().parent
    actor = detect_assistant(args.actor, script_dir)
    model = detect_model(args.model)
    date_utc = today_date()
    ts_utc = now_utc_iso()
    task_rel = str(task_file.relative_to(args.base))

    if args.dry_run:
        field_parts = []
        if old_status != new_status:
            field_parts.append(f"status: {old_status}->{new_status}")
        if old_owner != new_owner:
            field_parts.append(f"owner: {old_owner}->{new_owner}")
        print("DRY RUN")
        print(f"Task: {args.task_id}")
        print(f"File: {task_file}")
        print(f"Change: {'; '.join(field_parts)}")
        return 0

    index_file = args.base / "_shared" / "_meta" / "task_index.md"
    changelog_file = args.base / "_shared" / "tasks" / "_meta" / "change_log.md"
    lock_path = args.base / "_shared" / "tasks" / "_meta" / ".status_update.lock"

    for req in (index_file, changelog_file):
        if not req.exists():
            fail(4, f"Missing required path: {req}")

    new_row = f"| {args.task_id} | {domain} | {new_status} | {priority} | {new_owner} | {due} | {project} | {task_rel} | {date_utc} |"

    field_parts = []
    if old_status != new_status:
        field_parts.append(f"status: {old_status}->{new_status}")
    if old_owner != new_owner:
        field_parts.append(f"owner: {old_owner}->{new_owner}")
    field_changes = "; ".join(field_parts)
    reason = args.reason

    with DirLock(lock_path):
        update_task_frontmatter(task_file, {
            "status": new_status,
            "owner": new_owner,
            "updated": date_utc,
        })
        update_index_row(index_file, args.task_id, new_row)
        changelog_rows = [
            f"| {ts_utc} | {actor} | {model} | {args.task_id} | update | {field_changes} | {reason} |",
            f"| {ts_utc} | {actor} | {model} | N/A | update | task_index updated {args.task_id} | {reason} |",
        ]
        append_changelog_rows(changelog_file, changelog_rows)

    print(f"Updated task: {args.task_id}")
    print(f"Status: {old_status} -> {new_status}")
    if old_owner != new_owner:
        print(f"Owner: {old_owner} -> {new_owner}")
    return 0


def cmd_append_note(args: argparse.Namespace) -> int:
    if args.task_id and args.file:
        fail(2, "Use only one of --task-id or --file")
    if not args.task_id and not args.file:
        fail(2, "Provide --task-id or --file")

    if args.task_id:
        task_file = task_file_for_id(args.base, args.task_id)
    else:
        task_file = Path(args.file).expanduser().resolve()
        if not task_file.exists():
            fail(2, f"Task file not found: {task_file}")

    if args.content_file:
        content_path = Path(args.content_file).expanduser()
        if not content_path.exists():
            fail(2, f"Content file not found: {content_path}")
        content = content_path.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            fail(2, "No content provided — use --content-file or pipe content via stdin")
        content = sys.stdin.read()

    if not content.strip():
        fail(2, "No content provided")

    timestamp = args.timestamp if args.timestamp else now_utc_iso()
    note_block = format_execution_note(content, timestamp)

    if args.dry_run:
        result = insert_execution_note(task_file, note_block, dry_run=True)
        print(result)
        return 0

    insert_execution_note(task_file, note_block, dry_run=False)
    print(f"Appended execution note to: {task_file}")
    return 0


def cmd_tee_note(args: argparse.Namespace) -> int:
    if args.task_id and args.file:
        fail(2, "Use only one of --task-id or --file")
    if not args.task_id and not args.file:
        fail(2, "Provide --task-id or --file")

    if args.task_id:
        task_file = task_file_for_id(args.base, args.task_id)
    else:
        task_file = Path(args.file).expanduser().resolve()
        if not task_file.exists():
            fail(2, f"Task file not found: {task_file}")

    if sys.stdin.isatty():
        fail(2, "No stdin content — pipe content to tee-note")
    content = sys.stdin.read()
    if not content.strip():
        fail(2, "No stdin content")

    sys.stdout.write(content)

    timestamp = args.timestamp if args.timestamp else now_utc_iso()
    note_block = format_execution_note(content, timestamp)
    insert_execution_note(task_file, note_block, dry_run=False)
    return 0


VALID_PRIORITIES = {"low", "normal", "medium", "high", "critical"}
VALID_WORK_TYPES = {"feature", "bug", "chore", "research", "infrastructure"}
VALID_TASK_TYPES = {"kanban", "sprint", "epic", "spike"}
VALID_EFFORT_TYPES = {"low", "medium", "high"}


def read_counter(counter_file: Path, prefix: str) -> int | None:
    in_section = False
    for line in counter_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            header_text = stripped.lstrip("#").strip()
            in_section = header_text == prefix or header_text.startswith(f"{prefix} ")
            continue
        if in_section:
            check = stripped.lstrip("- ").strip()
            if check.startswith("next_id:"):
                val = check.split(":", 1)[1].strip()
                if val.isdigit():
                    return int(val)
    return None


def update_counter(counter_file: Path, prefix: str, new_next_id: int, actor: str, model: str) -> None:
    lines = counter_file.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            header_text = stripped.lstrip("#").strip()
            in_section = header_text == prefix or header_text.startswith(f"{prefix} ")
            out.append(line)
            continue
        if in_section:
            check = stripped.lstrip("- ").strip()
            indent = "- " if stripped.startswith("- ") else ""
            if check.startswith("next_id:"):
                out.append(f"{indent}next_id: {new_next_id}\n")
                continue
            if check.startswith("last_allocator:"):
                out.append(f"{indent}last_allocator: {actor}\n")
                continue
            if check.startswith("last_model:"):
                out.append(f"{indent}last_model: {model}\n")
                continue
        out.append(line)
    counter_file.write_text("".join(out), encoding="utf-8")


def task_id_in_index(index_file: Path, task_id: str) -> bool:
    pattern = re.compile(r"^\|\s*" + re.escape(task_id) + r"\s*\|")
    for line in index_file.read_text(encoding="utf-8").splitlines():
        if pattern.match(line):
            return True
    return False


def yaml_quote(value: str) -> str:
    if not value:
        return ""
    if any(c in value for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                                 '?', '|', '-', '<', '>', '=', '!', '%',
                                 '@', '`', '"', "'")):
        return f'"{value.replace(chr(34), chr(92)+chr(34))}"'
    if value.lower() in ('true', 'false', 'null', 'yes', 'no'):
        return f'"{value}"'
    return value


def force_quote(value: str) -> str:
    s = str(value) if value else ""
    return f'"{s.replace(chr(34), chr(92)+chr(34))}"'


def validate_task_file_quick(task_path: Path, task_id: str) -> list[str]:
    errors: list[str] = []
    try:
        content = task_path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"Cannot read {task_path}: {e}"]
    if not content.startswith("---"):
        return [f"{task_path}: missing frontmatter"]
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return [f"{task_path}: malformed frontmatter"]
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if m:
            fm[m.group(1).strip()] = m.group(2).strip().strip('"').strip("'")
    required_keys = ["title", "date", "domain", "project", "status", "priority",
                     "owner", "task_id", "created_by", "model", "task_schema"]
    nonempty_keys = ["title", "date", "domain", "status", "priority",
                     "owner", "task_id", "created_by", "model", "task_schema"]
    for key in required_keys:
        if key not in fm:
            errors.append(f"{task_path}: missing required key: {key}")
    for key in nonempty_keys:
        if key in fm and not fm[key]:
            errors.append(f"{task_path}: empty required value: {key}")
    if fm.get("status", "") not in VALID_STATUSES:
        errors.append(f"{task_path}: invalid status '{fm.get('status', '')}'")
    if fm.get("priority", "") not in VALID_PRIORITIES:
        errors.append(f"{task_path}: invalid priority '{fm.get('priority', '')}'")
    if fm.get("task_id", "") != task_id:
        errors.append(f"{task_path}: task_id mismatch (expected {task_id}, got {fm.get('task_id', '')})")
    return errors


def notify_elucubrate(url: str = "http://127.0.0.1:3000") -> None:
    import urllib.request
    import urllib.error
    try:
        urllib.request.urlopen(urllib.request.Request(f"{url}/api/health", method="GET"), timeout=1)
        urllib.request.urlopen(urllib.request.Request(f"{url}/api/cache/refresh", method="POST"), timeout=2)
    except Exception:
        pass


def cmd_create(args: argparse.Namespace) -> int:
    domain_name = (args.domain or "").strip()
    title = (args.title or "").strip()
    project = (args.project or "").strip()

    if not domain_name or not title:
        fail(2, "Missing required args: --domain, --title")

    registry = load_registry(args.base)
    domains = registry.get("domains", {})
    if domain_name not in domains:
        fail(4, f"Unknown domain: {domain_name}")
    domain_conf = domains[domain_name]

    if not project and domain_conf.get("id_mode") != "external":
        fail(2, "Missing required arg: --project (required for auto-ID domains)")

    script_dir = Path(__file__).resolve().parent
    actor = detect_assistant(args.actor, script_dir)
    model = detect_model(args.model)

    status = args.status or "todo"
    priority = args.priority or "normal"
    work_type = args.work_type
    task_type = args.task_type or "kanban"
    effort_type = args.effort_type or "medium"

    if status not in VALID_STATUSES:
        fail(2, f"Invalid --status: {status}")
    if priority not in VALID_PRIORITIES:
        fail(2, f"Invalid --priority: {priority}")
    id_mode = domain_conf.get("id_mode", "auto")
    if not work_type:
        work_type = "feature" if id_mode == "external" else "chore"
    if work_type not in VALID_WORK_TYPES:
        fail(2, f"Invalid --work-type: {work_type}")
    if task_type not in VALID_TASK_TYPES:
        fail(2, f"Invalid --task-type: {task_type}")
    if effort_type not in VALID_EFFORT_TYPES:
        fail(2, f"Invalid --effort-type: {effort_type}")

    owner = args.owner or domain_conf.get("default_owner", "moo")
    due = args.due or ""
    subcategory = args.subcategory or ""
    parent_task_id = (args.parent_task_id or "").strip()
    summary = args.summary or ""
    task_id = (args.task_id or "").strip()

    if parent_task_id and not re.match(r"^[A-Z]+-\d+$", parent_task_id):
        fail(2, f"Invalid --parent-task-id format: {parent_task_id}")

    task_dir = domain_conf.get("task_dir", "")
    task_dir_path = args.base / task_dir if not Path(task_dir).is_absolute() else Path(task_dir)
    active_dir = task_dir_path / "active"

    index_file = args.base / "_shared" / "_meta" / "task_index.md"
    counter_file = args.base / "_shared" / "_meta" / "task_id_counter.md"
    changelog_file = args.base / "_shared" / "tasks" / "_meta" / "change_log.md"

    for req in (index_file, counter_file, changelog_file):
        if not req.exists():
            fail(4, f"Missing required path: {req}")
    if not active_dir.is_dir():
        fail(4, f"Missing active task directory: {active_dir}")

    now_utc = dt.datetime.now(dt.timezone.utc)
    date_utc = now_utc.strftime("%Y-%m-%d")
    ts_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    id_prefix = domain_conf.get("id_prefix", "")

    # Validate parent exists (read-only, before lock)
    if parent_task_id:
        parent_found = False
        for dname, dconf in domains.items():
            td = dconf.get("task_dir", "")
            td_path = args.base / td if not Path(td).is_absolute() else Path(td)
            if (td_path / "active" / f"{parent_task_id}.md").exists():
                parent_found = True
                break
            archived = td_path / "archived"
            if archived.is_dir():
                for match in archived.rglob(f"{parent_task_id}.md"):
                    parent_found = True
                    break
            if parent_found:
                break
        if not parent_found:
            fail(2, f"--parent-task-id not found in canonical tasks: {parent_task_id}")

    # Acquire lock
    lock = None
    lock_path = args.base / "_shared" / "_meta" / "locks" / "create_task.lock"
    if not args.dry_run:
        lock = DirLock(lock_path, max_retries=30)
        if not lock.acquire():
            fail(4, f"Could not acquire create_task lock after {lock.max_retries} attempts")

    try:
        # ID allocation
        next_id = None
        if id_mode == "external":
            if not task_id:
                fail(2, f"--task-id is required for external-ID domain '{domain_name}'")
            if not re.match(r"^[A-Z]+-\d+$", task_id):
                fail(2, f"Invalid task id format for external domain: {task_id}")
        elif id_mode == "auto":
            if task_id:
                fail(2, f"Do not pass --task-id for auto-ID domain '{domain_name}'; it is allocated automatically")
            next_id = read_counter(counter_file, id_prefix)
            if next_id is None:
                fail(4, f"Invalid next_id for prefix {id_prefix} in {counter_file}")
            for bump in range(201):
                task_id = f"{id_prefix}-{next_id}"
                task_path = active_dir / f"{task_id}.md"
                if not task_path.exists() and not task_id_in_index(index_file, task_id):
                    break
                if bump >= 200:
                    fail(4, f"Unable to allocate free task ID for prefix {id_prefix} after 200 bumps")
                next_id += 1

        task_path = active_dir / f"{task_id}.md"
        task_rel = str(task_path.relative_to(args.base))

        if id_mode == "external":
            if task_path.exists():
                fail(3, f"Task file already exists: {task_path}")
            if task_id_in_index(index_file, task_id):
                fail(3, f"Task ID already present in index: {task_id}")

        if parent_task_id and parent_task_id == task_id:
            fail(2, f"--parent-task-id cannot equal task_id ({task_id})")

        # Build task content
        agents_block = f'  - id: {force_quote(owner)}\n    role: accountable\n    responsibility_order: 1'
        if actor != owner and actor and actor != "unknown":
            agents_block += f'\n  - id: {force_quote(actor)}\n    role: responsible\n    responsibility_order: 2'

        summary_line = f"- {summary}" if summary else "-"

        task_content = f"""---
title: {force_quote(title)}
date: {date_utc}
machine: shared
assistant: shared
category: tasks
memoryType: task
priority: {priority}
tags: [task, {domain_name}]
updated: {date_utc}
source: internal
domain: {domain_name}
project: {yaml_quote(project)}
status: {status}
owner: {yaml_quote(owner)}
due: {yaml_quote(due)}
work_type: {work_type}
task_type: {task_type}
effort_type: {effort_type}
task_id: {task_id}
created_by: {yaml_quote(actor)}
model: {yaml_quote(model)}
created_at: {ts_utc}
task_schema: v1
parent_task_id: {force_quote(parent_task_id)}
agents:
{agents_block}
subcategory: {yaml_quote(subcategory)}
---

# {title}

## Summary
{summary_line}

## Links
- Related tasks:
- Related notes:

## Execution Notes
- Created via task_tool create.
"""

        index_row = f"| {task_id} | {domain_name} | {status} | {priority} | {owner} | {due} | {project} | {task_rel} | {date_utc} |"

        if args.dry_run:
            print("DRY RUN")
            print(f"Would create: {task_path}")
            for line in task_content.splitlines()[:32]:
                print(line)
            print(f"Would append to index: {index_row}")
            if id_mode == "auto":
                print(f"Would update counter {id_prefix} next_id: {next_id} -> {next_id + 1}")
            return 0

        # Write task file
        task_path.write_text(task_content, encoding="utf-8")

        # Update index
        with index_file.open("a", encoding="utf-8") as f:
            f.write(index_row + "\n")

        # Update counter
        if id_mode == "auto" and next_id is not None:
            new_next_id = next_id + 1
            update_counter(counter_file, id_prefix, new_next_id, actor, model)

        # Changelog
        cl_rows = [
            f"| {ts_utc} | {actor} | {model} | {task_id} | create | created canonical {domain_name} task | task_tool create |",
            f"| {ts_utc} | {actor} | {model} | N/A | update | task_index appended {task_id} | task_tool create |",
        ]
        if id_mode == "auto" and next_id is not None:
            cl_rows.append(
                f"| {ts_utc} | {actor} | {model} | {task_id} | update | counter {id_prefix} next_id: {next_id}->{new_next_id} | task_tool create |"
            )
        append_changelog_rows(changelog_file, cl_rows)

    finally:
        if lock:
            lock.release()

    # Elucubrate notification (best-effort, outside lock)
    elucubrate_notify = os.environ.get("ELUCUBRATE_NOTIFY", "auto")
    if elucubrate_notify not in ("off", "false", "0"):
        notify_elucubrate(os.environ.get("ELUCUBRATE_URL", "http://127.0.0.1:3000"))

    # Single-file validation (outside lock)
    validation_errors = validate_task_file_quick(task_path, task_id)
    if validation_errors:
        for err in validation_errors:
            eprint(f"VALIDATION ERROR: {err}")
        fail(5, f"Task {task_id} created but has validation errors. File: {task_path}")

    print(f"OK | {task_id} | {domain_name} | created | {task_path}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    task_file = task_file_for_id(args.base, args.task_id)
    frontmatter, _ = parse_frontmatter(task_file.read_text(encoding="utf-8"))
    current_status = frontmatter.get("status", "")
    if not current_status:
        fail(1, f"Task has no status: {task_file}")

    script_dir = Path(__file__).resolve().parent
    actor = detect_assistant(args.actor, script_dir)
    model = detect_model(args.model)

    set_task_status(
        base=args.base,
        task_id=args.task_id,
        status=current_status,
        owner=args.owner,
        reason=args.reason,
        actor=actor,
        model=model,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        print(f"Assigned {args.task_id} to {args.owner}")
    return 0


TERMINAL_STATUSES = {"done", "cancelled", "retired"}


def cmd_archive(args: argparse.Namespace) -> int:
    registry = load_registry(args.base)
    domains = registry.get("domains", {})
    moved = 0
    skipped = 0
    errors = 0

    for domain_name, domain_conf in domains.items():
        archive_conf = domain_conf.get("archive", {})
        after_days = archive_conf.get("after_days")
        if not after_days or after_days <= 0:
            continue

        task_dir = domain_conf.get("task_dir", "")
        task_dir_path = args.base / task_dir if not Path(task_dir).is_absolute() else Path(task_dir)
        active_dir = task_dir_path / "active"
        archived_base = task_dir_path / "archived"

        if not active_dir.is_dir():
            continue

        cutoff_seconds = after_days * 86400

        task_files = sorted(active_dir.glob("*.md"))
        task_files = [f for f in task_files if f.name != "index.md"]

        if not task_files:
            continue

        newest_epoch = 0
        file_data: list[tuple[Path, dict[str, str], float]] = []

        for f in task_files:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            updated = fm.get("updated", "")
            try:
                epoch = dt.datetime.strptime(updated, "%Y-%m-%d").replace(
                    tzinfo=dt.timezone.utc
                ).timestamp()
            except (ValueError, TypeError):
                epoch = 0.0
            if epoch > newest_epoch:
                newest_epoch = epoch
            file_data.append((f, fm, epoch))

        for f, fm, epoch in file_data:
            status = fm.get("status", "")
            if status not in TERMINAL_STATUSES:
                continue

            updated = fm.get("updated", "")
            if epoch == 0.0:
                skipped += 1
                continue

            age_from_newest = newest_epoch - epoch
            if age_from_newest < cutoff_seconds:
                continue

            year = updated[:4]
            dest_dir = archived_base / year
            fname = f.name

            if args.dry_run:
                print(f"[DRY RUN] ARCHIVE {f} -> {dest_dir}/{fname} (status={status}, updated={updated}, age={int(age_from_newest)}s)")
                moved += 1
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                f.rename(dest_dir / fname)
                moved += 1
            except OSError as e:
                eprint(f"ERROR: failed to move {f}: {e}")
                errors += 1

        if not args.dry_run and archived_base.is_dir():
            for year_dir in sorted(archived_base.iterdir()):
                if not year_dir.is_dir():
                    continue
                year = year_dir.name
                index_file = year_dir / "index.md"
                lines = [
                    "---",
                    f'title: "{domain_name} archived tasks {year}"',
                    f"date: {today_date()}",
                    "category: system",
                    "memoryType: index",
                    f"domain: {domain_name}",
                    "status: active",
                    "---",
                    "",
                    f"# {domain_name} archived tasks — {year}",
                    "",
                    "| task_id | title | status | updated | archived_date |",
                    "| --- | --- | --- | --- | --- |",
                ]
                for af in sorted(year_dir.glob("*.md")):
                    if af.name == "index.md":
                        continue
                    afm, _ = parse_frontmatter(af.read_text(encoding="utf-8"))
                    lines.append(
                        f"| {afm.get('task_id', af.stem)} | {afm.get('title', '')} | {afm.get('status', '')} | {afm.get('updated', '')} | {today_date()} |"
                    )
                index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("")
    print("=== Archive summary ===")
    print(f"Archived: {moved}")
    print(f"Skipped (missing date): {skipped}")
    print(f"Errors: {errors}")

    if args.dry_run:
        print("")
        print("[DRY RUN] No files were moved.")
        return 0

    if moved > 0:
        print("")
        print("Rebuilding task index...")
        cmd_rebuild_index_impl(args.base)

    return 1 if errors > 0 else 0


def cmd_list_archived(args: argparse.Namespace) -> int:
    registry = load_registry(args.base)
    domains = registry.get("domains", {})
    if args.domain:
        if args.domain not in domains:
            fail(2, f"Unknown domain: {args.domain}")
        scan_domains = {args.domain: domains[args.domain]}
    else:
        scan_domains = domains

    results: list[dict[str, str]] = []
    for domain_name, domain_conf in scan_domains.items():
        task_dir = domain_conf.get("task_dir", "")
        task_dir_path = args.base / task_dir if not Path(task_dir).is_absolute() else Path(task_dir)
        archived_base = task_dir_path / "archived"
        if not archived_base.is_dir():
            continue

        for year_dir in sorted(archived_base.iterdir()):
            if not year_dir.is_dir():
                continue
            year = year_dir.name
            if args.year and year != args.year:
                continue

            for f in sorted(year_dir.glob("*.md")):
                if f.name == "index.md":
                    continue
                fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
                task_id = fm.get("task_id", f.stem)
                title = fm.get("title", "")
                status = fm.get("status", "")
                updated = fm.get("updated", "")
                project = fm.get("project", "")

                if args.status and status != args.status:
                    continue
                if args.grep:
                    search_text = f"{task_id} {title} {project}".lower()
                    if args.grep.lower() not in search_text:
                        continue

                results.append({
                    "task_id": task_id, "domain": domain_name, "year": year,
                    "status": status, "title": title, "project": project, "updated": updated,
                })

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    if not results:
        print("No archived tasks found matching filters.")
        return 0

    for r in results:
        print(f"| {r['task_id']} | {r['domain']} | {r['year']} | {r['status']} | {r['title']} | {r['updated']} |")
    print(f"\n{len(results)} archived task(s) found.")
    return 0


def cmd_rebuild_index_impl(base: Path) -> None:
    registry = load_registry(base)
    domains = registry.get("domains", {})
    index_file = base / "_shared" / "_meta" / "task_index.md"
    counter_file = base / "_shared" / "_meta" / "task_id_counter.md"
    date_utc = today_date()

    task_dirs: list[Path] = []
    for domain_conf in domains.values():
        td = domain_conf.get("task_dir", "")
        td_path = base / td if not Path(td).is_absolute() else Path(td)
        active = td_path / "active"
        if active.is_dir():
            task_dirs.append(active)
        elif td_path.is_dir():
            task_dirs.append(td_path)
        archived = td_path / "archived"
        if archived.is_dir():
            for year_dir in sorted(archived.iterdir()):
                if year_dir.is_dir():
                    task_dirs.append(year_dir)

    rows: list[str] = []
    max_dil = 1099
    for d in task_dirs:
        for f in sorted(d.glob("*.md")):
            if f.name == "index.md":
                continue
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            rel = str(f.relative_to(base))
            rows.append(
                f"| {fm.get('task_id', f.stem)} | {fm.get('domain', '')} | {fm.get('status', '')} "
                f"| {fm.get('priority', '')} | {fm.get('owner', '')} | {fm.get('due', '')} "
                f"| {fm.get('project', '')} | {rel} | {fm.get('updated', '')} |"
            )
            m = re.match(r"^DIL-(\d+)$", fm.get("task_id", ""))
            if m:
                n = int(m.group(1))
                if n > max_dil:
                    max_dil = n

    header = f"""---
title: "Shared Task Index"
date: 2026-02-19
machine: shared
assistant: shared
category: system
memoryType: index
priority: critical
tags: [index, tasks, shared]
updated: {date_utc}
source: internal
domain: operations
project: dil
status: active
owner: shared
due:
---

# Shared Task Index

Scan this file first before reading task notes.

| task_id | domain | status | priority | owner | due | project | path | updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""
    index_file.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")

    next_id = max_dil + 1
    if counter_file.exists():
        text = counter_file.read_text(encoding="utf-8")
        text = re.sub(r"^(- next_id: ).*$", f"\\g<1>{next_id}", text, flags=re.MULTILINE)
        text = re.sub(r"^(- updated: ).*$", f"\\g<1>{date_utc}", text, flags=re.MULTILINE)
        counter_file.write_text(text, encoding="utf-8")

    print(f"Rebuilt index: {index_file}")
    print(f"Updated counter next_id: {next_id}")


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    cmd_rebuild_index_impl(args.base)
    return 0



def parse_frontmatter_full(text: str) -> tuple[dict[str, str], list[dict[str, str]], bool]:
    lines = text.splitlines()
    dash_lines = [idx for idx, line in enumerate(lines) if line == "---"]
    if len(dash_lines) < 2 or dash_lines[0] != 0:
        return {}, [], False
    fm_lines = lines[dash_lines[0] + 1 : dash_lines[1]]
    data: dict[str, str] = {}
    agents: list[dict[str, str]] = []
    in_agents = False
    current_agent: dict[str, str] | None = None
    for raw_line in fm_lines:
        if in_agents:
            if raw_line and not raw_line.startswith(" "):
                in_agents = False
                current_agent = None
            else:
                stripped = raw_line.strip()
                if stripped.startswith("- id:"):
                    current_agent = {"id": stripped.split(":", 1)[1].strip().strip('"')}
                    agents.append(current_agent)
                    continue
                if current_agent is not None and ":" in stripped:
                    key, value = stripped.split(":", 1)
                    current_agent[key.strip()] = value.strip().strip('"')
                    continue
                continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        data[key.strip()] = value.lstrip()
        if key.strip() == "agents":
            in_agents = True
            current_agent = None
    return data, agents, True


def trim_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


REQUIRED_KEYS = [
    "title", "date", "machine", "assistant", "category", "memoryType",
    "priority", "tags", "updated", "source", "domain", "project",
    "status", "owner", "due", "work_type", "task_type", "effort_type",
    "task_id", "created_by", "model", "created_at", "task_schema",
    "parent_task_id", "agents",
]

NONEMPTY_KEYS = [
    "title", "date", "machine", "assistant", "category", "memoryType",
    "priority", "tags", "updated", "source", "domain", "status", "owner",
    "work_type", "task_type", "effort_type", "task_id", "created_by",
    "model", "created_at", "task_schema",
]


def parse_index_rows_full(index_file: Path) -> tuple[dict[str, str], dict[str, int]]:
    rows: dict[str, str] = {}
    counts: dict[str, int] = {}
    if not index_file.exists():
        return rows, counts
    for line in index_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*(Path|task_id)\s*\|", line):
            continue
        if re.match(r"^\|\s*---", line):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if not parts or not parts[0]:
            continue
        task_id = parts[0]
        rows.setdefault(task_id, line)
        counts[task_id] = counts.get(task_id, 0) + 1
    return rows, counts


def parse_change_log_full(change_log_path: Path) -> tuple[bool, dict[str, str]]:
    if not change_log_path.exists():
        return False, {}
    header_ok = False
    log_last_status: dict[str, str] = {}
    pattern = re.compile(r"status:\s*([a-z_]+)\->([a-z_]+)")
    for line in change_log_path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\|\s*timestamp\s*\|\s*actor\s*\|\s*model\s*\|", line):
            header_ok = True
            continue
        if not line.startswith("|") or re.match(r"^\|\s*---", line):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        task_id = parts[3]
        match = pattern.search(parts[5])
        if match:
            old_s, new_s = match.groups()
            allowed = VALID_TRANSITIONS.get(old_s, set())
            if new_s not in allowed:
                raise ValueError(f"Invalid status transition in log for '{task_id}': {old_s}->{new_s}")
            log_last_status[task_id] = new_s
    return header_ok, log_last_status


def cmd_validate(args: argparse.Namespace) -> int:
    base = args.base
    index_file = base / "_shared" / "_meta" / "task_index.md"
    counter_file = base / "_shared" / "_meta" / "task_id_counter.md"
    change_log = base / "_shared" / "tasks" / "_meta" / "change_log.md"
    project_registry = base / "_shared" / "_meta" / "project_registry.md"

    error_list: list[str] = []
    warning_list: list[str] = []
    skipped_files: list[str] = []
    json_mode = args.json

    def err(msg: str) -> None:
        error_list.append(msg)
        if not json_mode:
            print(f"ERROR: {msg}")

    def warn(msg: str) -> None:
        warning_list.append(msg)
        if not json_mode:
            print(f"WARNING: {msg}")

    registry = load_registry(base) if (base / "_shared" / "_meta" / "domain_registry.json").exists() else {}
    domains_conf = registry.get("domains", {})

    domain_dirs: dict[str, list[Path]] = {}
    for dname, dconf in domains_conf.items():
        td = dconf.get("task_dir", "")
        td_path = base / td if not Path(td).is_absolute() else Path(td)
        dirs: list[Path] = []
        active = td_path / "active"
        if active.is_dir():
            dirs.append(active)
        elif td_path.is_dir():
            dirs.append(td_path)
        archived = td_path / "archived"
        if archived.is_dir():
            for yd in sorted(archived.iterdir()):
                if yd.is_dir():
                    dirs.append(yd)
        if dirs:
            domain_dirs[dname] = dirs

    for legacy_name, legacy_sub in [("work", "work"), ("personal", "personal")]:
        lp = base / "_shared" / "tasks" / legacy_sub
        if lp.is_dir():
            domain_dirs.setdefault(legacy_name, [])
            if lp not in domain_dirs[legacy_name]:
                domain_dirs[legacy_name].append(lp)

    id_rules: dict[str, tuple[str, str]] = {}
    for dname, dconf in domains_conf.items():
        id_rules[dname] = (dconf.get("id_prefix", ""), dconf.get("id_mode", ""))
    id_rules.setdefault("work", ("DMDI", "external"))
    id_rules.setdefault("personal", ("DIL", "auto"))

    registered_projects: set[str] = set()
    if project_registry.exists():
        col_map: dict[str, int] = {}
        for line in project_registry.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or re.match(r"^\|\s*---", line):
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if not col_map:
                col_map = {name: idx for idx, name in enumerate(parts)}
                continue
            slug_idx = col_map.get("slug", 0)
            if slug_idx < len(parts) and parts[slug_idx]:
                registered_projects.add(parts[slug_idx])
    else:
        warn(f"Project registry not found: {project_registry}")

    task_files: list[tuple[Path, str]] = []
    for dname, dirs in domain_dirs.items():
        for d in dirs:
            for tf in sorted(d.glob("*.md")):
                if tf.name == "index.md":
                    continue
                task_files.append((tf, dname))

    if not task_files:
        err("No canonical task files found in any registered domain directory")

    idx_rows, idx_counts = parse_index_rows_full(index_file)
    seen_task_ids: dict[str, Path] = {}
    declared_status: dict[str, str] = {}
    parent_of: dict[str, str] = {}

    for task_file, domain_expected in task_files:
        data, agents, fm_valid = parse_frontmatter_full(task_file.read_text(encoding="utf-8"))
        if not fm_valid:
            err(f"{task_file} has malformed or missing frontmatter (no valid --- boundaries); skipping file")
            skipped_files.append(str(task_file))
            continue

        for key in REQUIRED_KEYS:
            if key not in data:
                err(f"{task_file} missing required key: {key}")
        for key in NONEMPTY_KEYS:
            v = trim_quotes(data.get(key, ""))
            if not v:
                err(f"{task_file} has empty required value: {key}")

        task_id = trim_quotes(data.get("task_id", ""))
        domain = trim_quotes(data.get("domain", ""))
        status = trim_quotes(data.get("status", ""))
        owner = trim_quotes(data.get("owner", ""))
        priority = trim_quotes(data.get("priority", ""))
        due = trim_quotes(data.get("due", ""))
        project = trim_quotes(data.get("project", ""))
        updated = trim_quotes(data.get("updated", ""))
        work_type = trim_quotes(data.get("work_type", ""))
        task_type = trim_quotes(data.get("task_type", ""))
        effort_type = trim_quotes(data.get("effort_type", ""))
        parent = trim_quotes(data.get("parent_task_id", ""))
        schema = trim_quotes(data.get("task_schema", ""))

        if not task_id:
            err(f"{task_file} has empty task_id; cannot complete validation")
            continue

        if domain != domain_expected:
            err(f"{task_file} domain '{domain}' does not match directory domain '{domain_expected}'")

        id_prefix, id_mode = id_rules.get(domain, ("", ""))
        if id_mode == "external":
            if not re.match(r"^[A-Z]+-[0-9]+$", task_id):
                err(f"{task_file} {domain} task_id must match ^[A-Z]+-[0-9]+$: got '{task_id}'")
        elif id_mode == "auto" and id_prefix:
            if not re.match(rf"^{re.escape(id_prefix)}-[0-9]+$", task_id):
                err(f"{task_file} {domain} task_id must match ^{id_prefix}-[0-9]+$: got '{task_id}'")

        if status not in VALID_STATUSES:
            err(f"{task_file} has invalid status '{status}'")
        if priority not in VALID_PRIORITIES:
            err(f"{task_file} has invalid priority '{priority}'")
        if work_type not in VALID_WORK_TYPES:
            err(f"{task_file} has invalid work_type '{work_type}'")
        if task_type not in VALID_TASK_TYPES:
            err(f"{task_file} has invalid task_type '{task_type}'")
        if effort_type not in VALID_EFFORT_TYPES:
            err(f"{task_file} has invalid effort_type '{effort_type}'")
        if schema != "v1":
            err(f"{task_file} task_schema must be v1, got '{schema}'")

        if registered_projects and project and project not in registered_projects:
            warn(f"{task_file} project '{project}' not in project registry")

        if task_id in seen_task_ids:
            err(f"Duplicate task_id '{task_id}' in {task_file} and {seen_task_ids[task_id]}")
        else:
            seen_task_ids[task_id] = task_file

        if len(agents) < 1:
            err(f"{task_file} must include at least one agent in agents list")
        else:
            first = agents[0]
            if first.get("role", "") != "accountable":
                err(f"{task_file} first agent role must be accountable (got '{first.get('role', '')}')")
            if first.get("responsibility_order", "") != "1":
                err(f"{task_file} first agent responsibility_order must be 1 (got '{first.get('responsibility_order', '')}')")
            if first.get("id", "") and owner != first["id"]:
                err(f"{task_file} owner must match accountable agent id (owner='{owner}', accountable='{first['id']}')")

        if parent:
            if parent == task_id:
                err(f"{task_file} parent_task_id cannot self-reference ({task_id})")
            if not re.match(r"^(DIL-[0-9]+|TRIV-[0-9]+|[A-Z]+-[0-9]+)$", parent):
                err(f"{task_file} invalid parent_task_id format '{parent}'")
            parent_of[task_id] = parent

        rel_old = f"_shared/tasks/{domain}/{task_id}.md"
        rel_new = f"_shared/domains/{domain}/tasks/active/{task_id}.md"
        expected_old = f"| {task_id} | {domain} | {status} | {priority} | {owner} | {due} | {project} | {rel_old} | {updated} |"
        expected_new = f"| {task_id} | {domain} | {status} | {priority} | {owner} | {due} | {project} | {rel_new} | {updated} |"

        found_row = idx_rows.get(task_id) in (expected_old, expected_new)
        if not found_row and task_id in idx_rows and f"_shared/domains/{domain}/tasks/archived/" in idx_rows[task_id]:
            found_row = True
        if not found_row:
            err(f"{index_file} missing exact row for {task_id}")
        if idx_counts.get(task_id, 0) != 1:
            err(f"{index_file} should contain exactly one row for {task_id} (found {idx_counts.get(task_id, 0)})")

        declared_status[task_id] = status

    for tid, parent in parent_of.items():
        if parent not in seen_task_ids:
            err(f"Task {tid} references missing parent_task_id {parent}")

    for tid in list(parent_of):
        current = tid
        seen_chain: set[str] = set()
        while current in parent_of:
            nxt = parent_of[current]
            if nxt == tid or nxt in seen_chain:
                err(f"Cycle detected in parent_task_id chain starting at {tid}")
                break
            seen_chain.add(nxt)
            current = nxt

    if counter_file.exists():
        next_id_str = ""
        for line in counter_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("- next_id:"):
                next_id_str = line.split(":", 1)[1].strip()
                break
        if not re.match(r"^[0-9]+$", next_id_str):
            err(f"Invalid or missing next_id in {counter_file}")
        else:
            max_personal = 1099
            for tid in seen_task_ids:
                m = re.match(r"^DIL-(\d+)$", tid)
                if m:
                    max_personal = max(max_personal, int(m.group(1)))
            expected_next = max_personal + 1
            if int(next_id_str) != expected_next:
                err(f"Counter mismatch in {counter_file}: next_id={next_id_str} expected={expected_next}")
    else:
        err(f"Missing counter file: {counter_file}")

    try:
        header_ok, log_last_status = parse_change_log_full(change_log)
        if not header_ok:
            err(f"Change log header must include model column: {change_log}")
    except ValueError as exc:
        err(str(exc))
        log_last_status = {}
    except FileNotFoundError:
        err(f"Missing change log: {change_log}")
        log_last_status = {}

    for tid, log_status in log_last_status.items():
        if tid in declared_status and declared_status[tid] != log_status:
            err(f"Status mismatch for {tid}: file={declared_status[tid]} log_last={log_status}")

    errors = len(error_list)
    warnings = len(warning_list)

    if json_mode:
        result = {
            "ok": errors == 0,
            "tasks": len(task_files),
            "errors": errors,
            "warnings": warnings,
            "skipped_files": skipped_files,
            "error_messages": error_list,
            "warning_messages": warning_list,
        }
        print(json.dumps(result, indent=2))
        return 0 if errors == 0 else 1

    if errors > 0:
        print(f"Validation failed: {errors} error(s), {warnings} warning(s)")
        return 1

    print(f"Validation passed: {len(task_files)} task(s), {warnings} warning(s)")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    registry = load_registry(args.base)
    domains_conf = registry.get("domains", {})
    today_str = today_date()

    task_dirs: list[Path] = []
    for dconf in domains_conf.values():
        td = dconf.get("task_dir", "")
        td_path = args.base / td if not Path(td).is_absolute() else Path(td)
        active = td_path / "active"
        if active.is_dir():
            task_dirs.append(active)
        elif td_path.is_dir():
            task_dirs.append(td_path)

    for legacy in ["_shared/tasks/work", "_shared/tasks/personal"]:
        lp = args.base / legacy
        if lp.is_dir() and lp not in task_dirs:
            task_dirs.append(lp)

    changed = 0
    checked = 0

    for task_dir in task_dirs:
        for path in sorted(task_dir.glob("*.md")):
            if path.name == "index.md":
                continue
            task_id = path.stem

            if args.min_id is not None or args.max_id is not None:
                m = re.match(r"^DIL-(\d+)$", task_id)
                if m:
                    n = int(m.group(1))
                    if args.min_id and n < args.min_id:
                        continue
                    if args.max_id and n > args.max_id:
                        continue

            checked += 1
            text = path.read_text(encoding="utf-8")
            data, agents_list, fm_valid = parse_frontmatter_full(text)
            if not fm_valid:
                continue

            needs_fix = False
            if "task_schema" not in data or trim_quotes(data.get("task_schema", "")) != "v1":
                needs_fix = True
            if "agents" not in data:
                needs_fix = True

            if needs_fix:
                changed += 1
                print(f"MIGRATE {task_id}: {path}")
                if args.apply:
                    if "task_schema" not in data:
                        update_task_frontmatter(path, {"task_schema": "v1"})
                    if not agents_list:
                        owner = trim_quotes(data.get("owner", "moo")) or "moo"
                        agents_block = f'agents:\n  - id: "{owner}"\n    role: accountable\n    responsibility_order: 1'
                        content = path.read_text(encoding="utf-8")
                        content = content.replace("\n---\n", f"\n{agents_block}\n---\n", 1)
                        path.write_text(content, encoding="utf-8")

    print(f"CHECKED={checked} CHANGED={changed} APPLY={args.apply}")
    return 0


def cmd_validate_range(args: argparse.Namespace) -> int:
    if args.fix:
        ns = argparse.Namespace(
            base=args.base, min_id=args.min_id, max_id=args.max_id, apply=True, json=False
        )
        rc = cmd_migrate(ns)
        if rc != 0:
            return rc
        cmd_rebuild_index_impl(args.base)

    ns = argparse.Namespace(base=args.base, json=False)
    return cmd_validate(ns)


def cmd_test(args: argparse.Namespace) -> int:
    test_script = Path(__file__).resolve().parent / "task_tool_test_script.bash"
    if not test_script.exists():
        fail(4, f"Test script not found: {test_script}")
    result = subprocess.run(["bash", str(test_script)], cwd=str(test_script.parent))
    return result.returncode


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


def insert_execution_note(task_file: Path, note_block: str, dry_run: bool) -> None:
    text = task_file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_exec = False
    inserted = False

    for line in lines:
        stripped = line.rstrip("\n")
        if re.match(r"^## Execution Notes\s*$", stripped):
            in_exec = True
            out.append(line)
            continue
        if in_exec and not inserted and stripped.startswith("## "):
            out.append("\n")
            out.append(note_block)
            out.append("\n\n")
            inserted = True
            in_exec = False
        out.append(line)

    if not inserted:
        if not in_exec:
            out.append("\n## Execution Notes\n")
        out.append("\n")
        out.append(note_block)
        out.append("\n")

    result = "".join(out)
    if not dry_run:
        task_file.write_text(result, encoding="utf-8")
    return result


def format_execution_note(content: str, timestamp: str) -> str:
    indented = "\n".join("  " + line for line in content.splitlines())
    return f"- {timestamp} Execution detail:\n{indented}\n"


def append_task_note(base: Path, task_file: Path, content: str, dry_run: bool) -> None:
    note_block = format_execution_note(content, now_utc_iso())
    insert_execution_note(task_file, note_block, dry_run)


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
    task_file = task_file_for_id(base, task_id)
    frontmatter, _ = parse_frontmatter(task_file.read_text(encoding="utf-8"))
    old_status = frontmatter.get("status", "")
    old_owner = frontmatter.get("owner", "")
    domain = frontmatter.get("domain", "")
    project = frontmatter.get("project", "")
    priority = frontmatter.get("priority", "")
    due = frontmatter.get("due", "")

    new_owner = owner if owner else old_owner

    if old_status != status:
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if status not in allowed:
            fail(1, f"Invalid status transition: {old_status} -> {status}")

    if old_status == status and old_owner == new_owner:
        return

    if dry_run:
        return

    date_utc = today_date()
    ts_utc = now_utc_iso()
    task_rel = str(task_file.relative_to(base))
    index_file = base / "_shared" / "_meta" / "task_index.md"
    changelog_file = base / "_shared" / "tasks" / "_meta" / "change_log.md"
    lock_path = base / "_shared" / "tasks" / "_meta" / ".status_update.lock"
    new_row = f"| {task_id} | {domain} | {status} | {priority} | {new_owner} | {due} | {project} | {task_rel} | {date_utc} |"

    field_parts = []
    if old_status != status:
        field_parts.append(f"status: {old_status}->{status}")
    if old_owner != new_owner:
        field_parts.append(f"owner: {old_owner}->{new_owner}")
    field_changes = "; ".join(field_parts)

    with DirLock(lock_path):
        update_task_frontmatter(task_file, {"status": status, "owner": new_owner, "updated": date_utc})
        update_index_row(index_file, task_id, new_row)
        append_changelog_rows(changelog_file, [
            f"| {ts_utc} | {actor} | {model} | {task_id} | update | {field_changes} | {reason} |",
            f"| {ts_utc} | {actor} | {model} | N/A | update | task_index updated {task_id} | {reason} |",
        ])


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

    create = subparsers.add_parser("create", help="Create a canonical DIL task file")
    create.add_argument("--domain", help="Registered domain (e.g., personal, work)")
    create.add_argument("--title", help="Task title")
    create.add_argument("--project", help="Project slug")
    create.add_argument("--task-id", dest="task_id", help="Task ID (required for external-ID domains)")
    create.add_argument("--summary", help="Populate Summary section")
    create.add_argument("--subcategory")
    create.add_argument("--parent-task-id", dest="parent_task_id")
    create.add_argument("--priority", help="low|normal|medium|high|critical")
    create.add_argument("--status", help="Task status (default: todo)")
    create.add_argument("--work-type", dest="work_type", help="feature|bug|chore|research|infrastructure")
    create.add_argument("--task-type", dest="task_type", help="kanban|sprint|epic|spike")
    create.add_argument("--effort-type", dest="effort_type", help="low|medium|high")
    create.add_argument("--owner")
    create.add_argument("--due")
    create.add_argument("--actor")
    create.add_argument("--model")
    create.add_argument("--dry-run", action="store_true")
    create.set_defaults(func=cmd_create)

    assign = subparsers.add_parser("assign", help="Reassign task owner")
    assign.add_argument("--task-id", required=True)
    assign.add_argument("--owner", required=True)
    assign.add_argument("--reason", default="task_tool assign")
    assign.add_argument("--actor")
    assign.add_argument("--model")
    assign.add_argument("--dry-run", action="store_true")
    assign.set_defaults(func=cmd_assign)

    archive = subparsers.add_parser("archive", help="Archive terminal tasks past their domain's trailing window")
    archive.add_argument("--dry-run", action="store_true")
    archive.set_defaults(func=cmd_archive)

    list_archived = subparsers.add_parser("list-archived", help="Search and list archived tasks")
    list_archived.add_argument("--domain", help="Filter by domain")
    list_archived.add_argument("--year", help="Filter by archive year")
    list_archived.add_argument("--grep", help="Filter by pattern in task_id/title/project")
    list_archived.add_argument("--status", help="Filter by status (done, cancelled, retired)")
    list_archived.set_defaults(func=cmd_list_archived)

    rebuild_index = subparsers.add_parser("rebuild-index", help="Regenerate task_index.md from task files")
    rebuild_index.set_defaults(func=cmd_rebuild_index)

    validate = subparsers.add_parser("validate", help="Validate task files, index, and changelog")
    validate.set_defaults(func=cmd_validate)

    migrate = subparsers.add_parser("migrate", help="Migrate task files to contract v1")
    migrate.add_argument("--min-id", type=int, dest="min_id")
    migrate.add_argument("--max-id", type=int, dest="max_id")
    migrate.add_argument("--apply", action="store_true")
    migrate.set_defaults(func=cmd_migrate)

    validate_range = subparsers.add_parser("validate-range", help="Optionally migrate then validate")
    validate_range.add_argument("--min-id", type=int, required=True, dest="min_id")
    validate_range.add_argument("--max-id", type=int, default=999999, dest="max_id")
    validate_range.add_argument("--fix", action="store_true")
    validate_range.set_defaults(func=cmd_validate_range)

    test = subparsers.add_parser("test", help="Run the task_tool test suite")
    test.set_defaults(func=cmd_test)

    review = subparsers.add_parser("review", help="Review a single task")
    review.add_argument("task_id")
    review.set_defaults(func=cmd_review)

    status = subparsers.add_parser("status", help="Set task status with transition validation")
    status.add_argument("--task-id", required=True)
    status.add_argument("--status", required=True, help="Target status")
    status.add_argument("--owner", help="Optional owner update")
    status.add_argument("--reason", default="task_tool status")
    status.add_argument("--actor")
    status.add_argument("--model")
    status.add_argument("--dry-run", action="store_true")
    status.set_defaults(func=cmd_status)

    append_note = subparsers.add_parser("append-note", help="Append execution note to task file")
    append_note.add_argument("--task-id", dest="task_id")
    append_note.add_argument("--file", help="Explicit task file path")
    append_note.add_argument("--content-file", dest="content_file", help="Read note from file (default: stdin)")
    append_note.add_argument("--timestamp", help="Override timestamp (default: current UTC)")
    append_note.add_argument("--dry-run", action="store_true")
    append_note.set_defaults(func=cmd_append_note)

    tee_note = subparsers.add_parser("tee-note", help="Echo stdin to stdout and append as execution note")
    tee_note.add_argument("--task-id", dest="task_id")
    tee_note.add_argument("--file", help="Explicit task file path")
    tee_note.add_argument("--timestamp", help="Override timestamp (default: current UTC)")
    tee_note.set_defaults(func=cmd_tee_note)

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
