#!/usr/bin/env python3
"""
create_task.py — Create canonical DIL task files.

Replaces the bash implementation with Python for performance:
- Inline single-file validation instead of full-system validate_tasks.sh (~60s → <1s)
- Lock held only during counter/file/index mutation, not during validation
- Same CLI interface, pipe-delimited output, exit codes

Exit codes: 0=success, 2=validation, 3=duplicate, 4=missing prereq, 5=post-creation validation
"""

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from resolve_base import resolve_dil_base
except ImportError:
    resolve_dil_base = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = {"todo", "assigned", "in_progress", "blocked", "done", "cancelled", "retired"}
VALID_PRIORITIES = {"low", "normal", "medium", "high", "critical"}
VALID_WORK_TYPES = {"feature", "bug", "chore", "research", "infrastructure"}
VALID_TASK_TYPES = {"kanban", "sprint", "epic", "spike"}
VALID_EFFORT_TYPES = {"low", "medium", "high"}

REQUIRED_FRONTMATTER_KEYS = [
    "title", "date", "machine", "assistant", "category", "memoryType",
    "priority", "tags", "updated", "source", "domain", "project",
    "status", "owner", "due", "work_type", "task_type", "effort_type",
    "task_id", "created_by", "model", "created_at", "task_schema",
    "parent_task_id", "agents", "subcategory",
]

SCRIPT_NAME = "create_task"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self):
        self.log_file = None

    def init(self, base, domain):
        log_dir = os.path.join(base, "_shared", "logs", SCRIPT_NAME)
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(log_dir, f"{SCRIPT_NAME}.create.{ts}.log")

    def log(self, msg):
        if self.log_file:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, "a") as f:
                f.write(f"{now} | {msg}\n")


logger = Logger()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def output_ok(task_id, domain, status, path):
    print(f"OK | {task_id} | {domain} | {status} | {path}")


def output_error(code, msg):
    print(f"ERR | {code} | {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Environment resolution
# ---------------------------------------------------------------------------

def resolve_actor(explicit=None):
    if explicit:
        return explicit
    for var in ("ACTOR", "ASSISTANT_ID", "AGENT_NAME", "AGENT_ID"):
        val = os.environ.get(var, "")
        if val:
            return val
    # Try identify_agent.sh
    script_dir = os.path.dirname(os.path.abspath(__file__))
    agent_script = os.path.join(script_dir, "..", "identify_agent.sh")
    if os.path.isfile(agent_script) and os.access(agent_script, os.X_OK):
        try:
            result = subprocess.run([agent_script], capture_output=True, text=True, timeout=5)
            resolved = result.stdout.strip()
            if resolved and resolved != "UNRESOLVED":
                return resolved
        except Exception:
            pass
    return "unknown"


def resolve_model(explicit=None):
    if explicit:
        return explicit
    for var in ("MODEL", "AGENT_MODEL"):
        val = os.environ.get(var, "")
        if val:
            return val
    if os.environ.get("CLAUDECODE") == "1":
        return "claude"
    return "unknown"


# ---------------------------------------------------------------------------
# Domain registry
# ---------------------------------------------------------------------------

def load_domain_registry(base):
    reg_path = os.path.join(base, "_shared", "_meta", "domain_registry.json")
    if not os.path.isfile(reg_path):
        output_error(4, f"Domain registry not found: {reg_path}")
    with open(reg_path, "r") as f:
        return json.load(f)


def resolve_domain(registry, domain_name, base):
    domains = registry.get("domains", {})
    if domain_name not in domains:
        return None
    d = domains[domain_name]
    # Resolve paths
    task_dir = d.get("task_dir", "")
    if not task_dir.startswith("/"):
        task_dir = os.path.join(base, task_dir)
    log_dir = d.get("log_dir", "")
    if not log_dir.startswith("/"):
        log_dir = os.path.join(base, log_dir)
    data_dir = d.get("data_dir", "")
    if not data_dir.startswith("/"):
        data_dir = os.path.join(base, data_dir)
    return {
        "name": domain_name,
        "task_dir": task_dir,
        "log_dir": log_dir,
        "data_dir": data_dir,
        "id_prefix": d.get("id_prefix", ""),
        "id_mode": d.get("id_mode", "auto"),
        "default_owner": d.get("default_owner", "moo"),
    }


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

class TaskLock:
    def __init__(self, base, actor, model, max_retries=30,
                 min_backoff_ms=700, max_backoff_ms=1600):
        self.lock_dir = os.path.join(base, "_shared", "_meta", "locks")
        self.lock_path = os.path.join(self.lock_dir, "create_task.lock")
        self.actor = actor
        self.model = model
        self.max_retries = max_retries
        self.min_backoff_ms = min_backoff_ms
        self.max_backoff_ms = max_backoff_ms
        self.held = False

    def acquire(self):
        os.makedirs(self.lock_dir, exist_ok=True)
        for attempt in range(1, self.max_retries + 1):
            try:
                os.mkdir(self.lock_path)
                self.held = True
                # Write holder info
                holder_path = os.path.join(self.lock_path, "holder")
                now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(holder_path, "w") as f:
                    f.write(f"pid={os.getpid()}\nactor={self.actor}\nmodel={self.model}\nts={now}\n")
                logger.log(f"Acquired create_task lock on attempt {attempt}")
                return True
            except FileExistsError:
                delay = random.randint(self.min_backoff_ms, self.max_backoff_ms) / 1000.0
                logger.log(f"Lock busy (attempt {attempt}/{self.max_retries}); backing off {delay:.3f}s")
                time.sleep(delay)
        return False

    def release(self):
        if self.held and os.path.isdir(self.lock_path):
            holder = os.path.join(self.lock_path, "holder")
            if os.path.exists(holder):
                os.remove(holder)
            try:
                os.rmdir(self.lock_path)
            except OSError:
                pass
        self.held = False


# ---------------------------------------------------------------------------
# Counter management
# ---------------------------------------------------------------------------

def read_counter(counter_file, prefix):
    """Read next_id for a given prefix from the multi-prefix counter file."""
    in_section = False
    with open(counter_file, "r") as f:
        for line in f:
            if line.startswith("### "):
                in_section = line.startswith(f"### {prefix} ")
                continue
            if in_section and line.strip().startswith("- next_id:"):
                val = line.split(":", 1)[1].strip()
                if val.isdigit():
                    return int(val)
    return None


def update_counter(counter_file, prefix, new_next_id, actor, model):
    """Update next_id, last_allocator, last_model for a given prefix."""
    with open(counter_file, "r") as f:
        lines = f.readlines()

    in_section = False
    out = []
    for line in lines:
        if line.startswith("### "):
            in_section = line.startswith(f"### {prefix} ")
            out.append(line)
            continue
        if in_section:
            if line.strip().startswith("- next_id:"):
                out.append(f"- next_id: {new_next_id}\n")
                continue
            if line.strip().startswith("- last_allocator:"):
                out.append(f"- last_allocator: {actor}\n")
                continue
            if line.strip().startswith("- last_model:"):
                out.append(f"- last_model: {model}\n")
                continue
        out.append(line)

    with open(counter_file, "w") as f:
        f.writelines(out)


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

def task_id_in_index(index_file, task_id):
    """Check if task_id already has a row in the index."""
    pattern = re.compile(r"^\|\s*" + re.escape(task_id) + r"\s*\|")
    with open(index_file, "r") as f:
        for line in f:
            if pattern.match(line):
                return True
    return False


def append_index_row(index_file, row):
    with open(index_file, "a") as f:
        f.write(row + "\n")


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------

def append_changelog(changelog_path, entries):
    """Append multiple changelog rows. Each entry is a tuple of fields."""
    with open(changelog_path, "a") as f:
        for fields in entries:
            row = "| " + " | ".join(str(x) for x in fields) + " |"
            f.write(row + "\n")


# ---------------------------------------------------------------------------
# Single-file validation
# ---------------------------------------------------------------------------

def validate_task_file(task_path, task_id):
    """Validate a single task file's frontmatter. Returns list of errors."""
    errors = []
    try:
        with open(task_path, "r") as f:
            content = f.read()
    except OSError as e:
        return [f"Cannot read {task_path}: {e}"]

    if not content.startswith("---"):
        return [f"{task_path}: missing frontmatter"]

    # Extract frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return [f"{task_path}: malformed frontmatter"]

    fm = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if m:
            fm[m.group(1).strip()] = m.group(2).strip().strip('"').strip("'")

    # Check required keys
    for key in ["title", "date", "domain", "project", "status", "priority",
                "owner", "task_id", "created_by", "model", "task_schema"]:
        if key not in fm:
            errors.append(f"{task_path}: missing required key: {key}")
        elif not fm[key]:
            errors.append(f"{task_path}: empty required value: {key}")

    # Validate values
    if fm.get("status", "") not in VALID_STATUSES:
        errors.append(f"{task_path}: invalid status '{fm.get('status', '')}'")
    if fm.get("priority", "") not in VALID_PRIORITIES:
        errors.append(f"{task_path}: invalid priority '{fm.get('priority', '')}'")
    if fm.get("task_id", "") != task_id:
        errors.append(f"{task_path}: task_id mismatch (expected {task_id}, got {fm.get('task_id', '')})")

    return errors


# ---------------------------------------------------------------------------
# YAML quoting
# ---------------------------------------------------------------------------

def yaml_quote(value):
    """Quote a YAML string value if it contains special chars."""
    if value is None:
        return ""
    s = str(value)
    if not s:
        return ""
    # Quote if contains special yaml chars or looks like a boolean/null
    if any(c in s for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                             '?', '|', '-', '<', '>', '=', '!', '%',
                             '@', '`', '"', "'")):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    if s.lower() in ('true', 'false', 'null', 'yes', 'no'):
        return f'"{s}"'
    return s


# ---------------------------------------------------------------------------
# Elucubrate notification
# ---------------------------------------------------------------------------

def notify_elucubrate(url="http://127.0.0.1:3000"):
    """Best-effort Elucubrate cache refresh."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"{url}/api/health", method="GET")
        with urllib.request.urlopen(req, timeout=1):
            pass
        req = urllib.request.Request(f"{url}/api/cache/refresh", method="POST")
        with urllib.request.urlopen(req, timeout=2):
            pass
        logger.log("Elucubrate cache refreshed")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# JSON sidecar mode
# ---------------------------------------------------------------------------

def load_json_manifest(manifest_path):
    """Load a JSON manifest and return as a dict of CLI-equivalent args."""
    with open(manifest_path, "r") as f:
        data = json.load(f)

    field_map = {
        "domain": "domain", "task_id": "task_id", "title": "title",
        "project": "project", "summary": "summary", "subcategory": "subcategory",
        "parent_task_id": "parent_task_id", "priority": "priority",
        "status": "status", "work_type": "work_type", "task_type": "task_type",
        "effort_type": "effort_type", "owner": "owner", "due": "due",
        "actor": "actor", "model": "model",
    }
    args = {}
    for json_key, arg_key in field_map.items():
        val = data.get(json_key)
        if val:
            args[arg_key] = str(val)
    return args, data


# ---------------------------------------------------------------------------
# Main creation logic
# ---------------------------------------------------------------------------

def create_task(args, base):
    domain_name = (args.domain or "").strip()
    title = (args.title or "").strip()
    project = (args.project or "").strip()

    if not domain_name or not title or not project:
        output_error(2, "Missing required args: --domain, --title, --project")

    # Load domain registry
    registry = load_domain_registry(base)
    domain = resolve_domain(registry, domain_name, base)
    if not domain:
        output_error(4, f"Unknown domain: {domain_name}")

    # Resolve actor/model
    actor = resolve_actor(args.actor)
    model = resolve_model(args.model)

    # Init logging
    logger.init(base, domain_name)
    logger.log(f"=== {SCRIPT_NAME} create started ===")
    logger.log(f"Host: {os.uname().nodename}")
    logger.log(f"Actor: {actor}")
    logger.log(f"Model: {model}")
    logger.log(f"Domain: {domain_name}")
    logger.log(f"Title: {title}")
    logger.log(f"Project: {project}")

    # Apply defaults for fields that may come from JSON overlay
    status = args.status if args.status else "todo"
    priority = args.priority if args.priority else "normal"
    work_type = args.work_type
    task_type = args.task_type if args.task_type else "kanban"
    effort_type = args.effort_type if args.effort_type else "medium"

    if status not in VALID_STATUSES:
        output_error(2, f"Invalid --status: {status}")
    if priority not in VALID_PRIORITIES:
        output_error(2, f"Invalid --priority: {priority}")
    if not work_type:
        work_type = "feature" if domain["id_mode"] == "external" else "chore"
    if work_type not in VALID_WORK_TYPES:
        output_error(2, f"Invalid --work-type: {work_type}")
    if task_type not in VALID_TASK_TYPES:
        output_error(2, f"Invalid --task-type: {task_type}")
    if effort_type not in VALID_EFFORT_TYPES:
        output_error(2, f"Invalid --effort-type: {effort_type}")

    owner = args.owner or domain["default_owner"]
    due = args.due or ""
    subcategory = args.subcategory or ""
    parent_task_id = (args.parent_task_id or "").strip()
    summary = args.summary or ""
    task_id = (args.task_id or "").strip()

    # Validate parent_task_id format
    if parent_task_id:
        if not re.match(r"^[A-Z]+-\d+$", parent_task_id):
            output_error(2, f"Invalid --parent-task-id format: {parent_task_id}")

    # Paths
    index_file = os.path.join(base, "_shared", "_meta", "task_index.md")
    counter_file = os.path.join(base, "_shared", "_meta", "task_id_counter.md")
    changelog = os.path.join(base, "_shared", "tasks", "_meta", "change_log.md")
    active_dir = os.path.join(domain["task_dir"], "active")

    for req_path in (index_file, counter_file, changelog):
        if not os.path.exists(req_path):
            output_error(4, f"Missing required path: {req_path}")

    if not os.path.isdir(active_dir):
        output_error(4, f"Missing active task directory: {active_dir}")

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    date_utc = now_utc.strftime("%Y-%m-%d")
    ts_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    id_mode = domain["id_mode"]
    id_prefix = domain["id_prefix"]

    # --- Validate parent exists (read-only, before lock) ---
    if parent_task_id:
        parent_found = False
        for dname, dconf in registry.get("domains", {}).items():
            td = dconf.get("task_dir", "")
            if not td.startswith("/"):
                td = os.path.join(base, td)
            if os.path.isfile(os.path.join(td, "active", f"{parent_task_id}.md")):
                parent_found = True
                break
            archived = os.path.join(td, "archived")
            if os.path.isdir(archived):
                for root, dirs, files in os.walk(archived):
                    if f"{parent_task_id}.md" in files:
                        parent_found = True
                        break
                if parent_found:
                    break
        if not parent_found:
            output_error(2, f"--parent-task-id not found in canonical tasks: {parent_task_id}")

    # --- Acquire lock (only for mutation phase) ---
    lock = None
    if not args.dry_run:
        lock = TaskLock(
            base, actor, model,
            max_retries=int(os.environ.get("CREATE_TASK_LOCK_RETRIES", "30")),
            min_backoff_ms=int(os.environ.get("CREATE_TASK_LOCK_MIN_BACKOFF_MS", "700")),
            max_backoff_ms=int(os.environ.get("CREATE_TASK_LOCK_MAX_BACKOFF_MS", "1600")),
        )
        if not lock.acquire():
            output_error(4, f"Could not acquire create_task lock after {lock.max_retries} attempts")

    try:
        # --- ID allocation ---
        next_id = None
        if id_mode == "external":
            if not task_id:
                output_error(2, f"--task-id is required for external-ID domain '{domain_name}'")
            if not re.match(r"^[A-Z]+-\d+$", task_id):
                output_error(2, f"Invalid task id format for external domain: {task_id}")
        elif id_mode == "auto":
            if task_id:
                output_error(2, f"Do not pass --task-id for auto-ID domain '{domain_name}'; it is allocated automatically")
            next_id = read_counter(counter_file, id_prefix)
            if next_id is None:
                output_error(4, f"Invalid next_id for prefix {id_prefix} in {counter_file}")

            # Bump past collisions
            max_bumps = 200
            for bump in range(max_bumps + 1):
                task_id = f"{id_prefix}-{next_id}"
                task_path = os.path.join(active_dir, f"{task_id}.md")
                if not os.path.exists(task_path) and not task_id_in_index(index_file, task_id):
                    break
                if bump >= max_bumps:
                    output_error(4, f"Unable to allocate free task ID for prefix {id_prefix} after {max_bumps} bumps")
                logger.log(f"ID collision on {task_id}; bumping counter candidate")
                next_id += 1

        task_path = os.path.join(active_dir, f"{task_id}.md")
        task_rel = os.path.relpath(task_path, base)

        # Check for duplicates (external mode)
        if id_mode == "external":
            if os.path.exists(task_path):
                output_error(3, f"Task file already exists: {task_path}")
            if task_id_in_index(index_file, task_id):
                output_error(3, f"Task ID already present in index: {task_id}")

        # Parent self-reference check (needs task_id which is allocated above)
        if parent_task_id and parent_task_id == task_id:
            output_error(2, f"--parent-task-id cannot equal task_id ({task_id})")

        # --- Build task content ---
        def _force_quote(v):
            """Always double-quote a value for YAML, matching bash q() behavior."""
            s = str(v) if v else ""
            return f'"{s.replace(chr(34), chr(92)+chr(34))}"'

        agents_block = f'  - id: {_force_quote(owner)}\n    role: accountable\n    responsibility_order: 1'
        if actor != owner and actor and actor != "unknown":
            agents_block += f'\n  - id: {_force_quote(actor)}\n    role: responsible\n    responsibility_order: 2'

        summary_line = f"- {summary}" if summary else "-"

        task_content = f"""---
title: {_force_quote(title)}
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
parent_task_id: {_force_quote(parent_task_id)}
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
- Created via create_task.sh.
"""

        index_row = f"| {task_id} | {domain_name} | {status} | {priority} | {owner} | {due} | {project} | {task_rel} | {date_utc} |"

        # --- Dry run ---
        if args.dry_run:
            print("DRY RUN")
            print(f"Would create: {task_path}")
            for line in task_content.splitlines()[:32]:
                print(line)
            print(f"Would append to index: {index_row}")
            if id_mode == "auto":
                print(f"Would update counter {id_prefix} next_id: {next_id} -> {next_id + 1}")
            print("Would append change-log entries for create/index/counter")
            return

        # --- Write task file ---
        logger.log(f"Creating task file: {task_path}")
        with open(task_path, "w") as f:
            f.write(task_content)

        # --- Update index ---
        append_index_row(index_file, index_row)

        # --- Update counter ---
        if id_mode == "auto":
            new_next_id = next_id + 1
            update_counter(counter_file, id_prefix, new_next_id, actor, model)
            logger.log(f"Counter updated: {id_prefix} next_id {next_id} -> {new_next_id}")

        # --- Changelog ---
        entries = [
            (ts_utc, actor, model, task_id, "create", f"created canonical {domain_name} task", SCRIPT_NAME),
            (ts_utc, actor, model, "N/A", "update", f"task_index appended {task_id}", SCRIPT_NAME),
        ]
        if id_mode == "auto":
            entries.append(
                (ts_utc, actor, model, task_id, "update",
                 f"counter {id_prefix} next_id: {next_id}->{new_next_id}", SCRIPT_NAME)
            )
        append_changelog(changelog, entries)

    finally:
        # --- Release lock BEFORE validation ---
        if lock:
            lock.release()

    # --- Elucubrate notification (best-effort, outside lock) ---
    elucubrate_notify = os.environ.get("ELUCUBRATE_NOTIFY", "auto")
    if elucubrate_notify not in ("off", "false", "0"):
        notify_elucubrate(os.environ.get("ELUCUBRATE_URL", "http://127.0.0.1:3000"))

    # --- Single-file validation (outside lock, fast) ---
    logger.log("Running single-file validation...")
    validation_errors = validate_task_file(task_path, task_id)
    if validation_errors:
        logger.log(f"VALIDATION FAILED for {task_id}: {validation_errors}")
        for err in validation_errors:
            print(f"VALIDATION ERROR: {err}", file=sys.stderr)
        output_error(5, f"Task {task_id} created but has validation errors. File: {task_path}")

    logger.log(f"Task created successfully: {task_id} at {task_path}")
    output_ok(task_id, domain_name, "created", task_path)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="Create canonical DIL task files")
    parser.add_argument("--base", help="DIL base path")
    parser.add_argument("--domain", help="Registered domain (e.g., personal, work, triv)")
    parser.add_argument("--task-id", dest="task_id", help="Task ID (required for external-ID domains)")
    parser.add_argument("--title", help="Task title")
    parser.add_argument("--project", help="Project slug")
    parser.add_argument("--summary", help="Populate Summary section")
    parser.add_argument("--subcategory", help="Subcategory")
    parser.add_argument("--parent-task-id", dest="parent_task_id", help="Parent task ID")
    parser.add_argument("--priority", default=None, help="low|normal|medium|high|critical")
    parser.add_argument("--status", default=None, help="Task status")
    parser.add_argument("--work-type", dest="work_type", help="feature|bug|chore|research|infrastructure")
    parser.add_argument("--task-type", dest="task_type", default=None, help="kanban|sprint|epic|spike")
    parser.add_argument("--effort-type", dest="effort_type", default=None, help="low|medium|high")
    parser.add_argument("--owner", help="Task owner")
    parser.add_argument("--due", help="Due date")
    parser.add_argument("--actor", help="Creating actor")
    parser.add_argument("--model", help="Creating model")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Preview without writing")
    # JSON sidecar mode
    parser.add_argument("--json-manifest", dest="json_manifest", help="Path to JSON manifest file")
    return parser


def main():
    # Handle "json <manifest>" subcommand for backwards compatibility
    if len(sys.argv) >= 2 and sys.argv[1] == "json":
        if len(sys.argv) < 3:
            print("Usage: create_task.py json <manifest.json>", file=sys.stderr)
            sys.exit(4)
        sys.argv = [sys.argv[0], "--json-manifest", sys.argv[2]] + sys.argv[3:]

    parser = build_parser()
    args = parser.parse_args()

    # Resolve base
    base = args.base
    if not base:
        base = os.environ.get("BASE_DIL", "")
    if not base and resolve_dil_base:
        base = resolve_dil_base()
    if not base:
        fallback = os.path.join(os.path.expanduser("~"), "Documents", "dil_agentic_memory_0001")
        if os.path.isdir(fallback):
            base = fallback
    if not base or not os.path.isdir(base):
        output_error(4, "Could not resolve DIL base. Set BASE_DIL to your vault path.")

    # JSON sidecar mode
    if args.json_manifest:
        manifest_path = args.json_manifest
        if not os.path.isfile(manifest_path):
            output_error(4, f"Manifest file not found: {manifest_path}")
        json_args, raw_data = load_json_manifest(manifest_path)
        # Overlay JSON values onto args (CLI args take precedence)
        for key, val in json_args.items():
            if not getattr(args, key, None):
                setattr(args, key, val)
        # Create the task
        create_task(args, base)
        # Archive manifest
        domain_name = args.domain or raw_data.get("domain", "personal")
        registry = load_domain_registry(base)
        domain_info = resolve_domain(registry, domain_name, base)
        if domain_info:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_dir = os.path.join(domain_info["data_dir"], SCRIPT_NAME)
            os.makedirs(archive_dir, exist_ok=True)
            import shutil
            shutil.copy2(manifest_path, os.path.join(archive_dir, f"{SCRIPT_NAME}.create.{ts}.json"))
            logger.log(f"Manifest archived to {archive_dir}")
    else:
        create_task(args, base)


if __name__ == "__main__":
    main()
