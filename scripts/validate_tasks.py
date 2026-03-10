#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VALID_STATUSES = {"todo", "assigned", "in_progress", "blocked", "done", "cancelled", "retired"}
VALID_PRIORITIES = {"low", "normal", "high", "critical"}
VALID_WORK_TYPES = {"feature", "bug", "chore", "research", "infrastructure"}
VALID_TASK_TYPES = {"kanban", "sprint", "epic", "spike"}
VALID_EFFORT_TYPES = {"low", "medium", "high"}

REQUIRED_KEYS = [
    "title",
    "date",
    "machine",
    "assistant",
    "category",
    "memoryType",
    "priority",
    "tags",
    "updated",
    "source",
    "domain",
    "project",
    "status",
    "owner",
    "due",
    "work_type",
    "task_type",
    "effort_type",
    "task_id",
    "created_by",
    "model",
    "created_at",
    "task_schema",
    "parent_task_id",
    "agents",
]

NONEMPTY_KEYS = [
    "title",
    "date",
    "machine",
    "assistant",
    "category",
    "memoryType",
    "priority",
    "tags",
    "updated",
    "source",
    "domain",
    "status",
    "owner",
    "work_type",
    "task_type",
    "effort_type",
    "task_id",
    "created_by",
    "model",
    "created_at",
    "task_schema",
]


def trim_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def valid_transition(old: str, new: str) -> bool:
    if new == "retired":
        return True
    allowed = {
        "todo": {"assigned", "in_progress", "blocked", "cancelled"},
        "assigned": {"in_progress", "blocked", "done", "cancelled"},
        "in_progress": {"blocked", "done", "assigned", "cancelled"},
        "blocked": {"in_progress", "assigned", "cancelled"},
        "retired": {"todo", "in_progress"},
        "done": set(),
        "cancelled": set(),
    }
    return new in allowed.get(old, set())


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    lines = text.splitlines()
    dash_lines = [idx for idx, line in enumerate(lines) if line == "---"]
    if len(dash_lines) < 2 or dash_lines[0] != 0:
        return {}, []

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
                    current_agent = {"id": trim_quotes(stripped.split(":", 1)[1])}
                    agents.append(current_agent)
                    continue
                if current_agent is not None and ":" in stripped:
                    key, value = stripped.split(":", 1)
                    current_agent[key.strip()] = trim_quotes(value)
                    continue
                if in_agents:
                    continue

        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.lstrip()
        data[key] = value
        if key == "agents":
            in_agents = True
            current_agent = None

    return data, agents


def parse_index(index_path: Path) -> tuple[dict[str, str], dict[str, int]]:
    rows: dict[str, str] = {}
    counts: dict[str, int] = {}
    if not index_path.exists():
        return rows, counts

    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*(Path|task_id)\s*\|", line):
            continue
        if re.match(r"^\|\s*---", line):
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if not parts:
            continue
        task_id = parts[0]
        if not task_id:
            continue
        rows.setdefault(task_id, line)
        counts[task_id] = counts.get(task_id, 0) + 1

    return rows, counts


def parse_change_log(change_log_path: Path) -> tuple[bool, dict[str, str]]:
    if not change_log_path.exists():
        return False, {}

    header_ok = False
    log_last_status: dict[str, str] = {}
    pattern = re.compile(r"status:\s*([a-z_]+)\->([a-z_]+)")

    for line in change_log_path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\|\s*timestamp\s*\|\s*actor\s*\|\s*model\s*\|", line):
            header_ok = True
            continue
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*---", line):
            continue

        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) < 6:
            continue

        task_id = parts[3]
        field_changes = parts[5]
        match = pattern.search(field_changes)
        if match:
            old_status, new_status = match.groups()
            if not valid_transition(old_status, new_status):
                raise ValueError(f"Invalid status transition in log for '{task_id}': {old_status}->{new_status}")
            log_last_status[task_id] = new_status

    return header_ok, log_last_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical DIL task files and indexes.")
    parser.add_argument("base", nargs="?", default="/home/moo/Documents/dil_agentic_memory_0001")
    args = parser.parse_args()

    base = Path(args.base)
    work_dir = base / "_shared" / "tasks" / "work"
    personal_dir = base / "_shared" / "tasks" / "personal"
    index_file = base / "_shared" / "_meta" / "task_index.md"
    counter_file = base / "_shared" / "_meta" / "task_id_counter.md"
    change_log = base / "_shared" / "tasks" / "_meta" / "change_log.md"

    errors = 0
    warnings = 0

    def err(message: str) -> None:
        nonlocal errors
        print(f"ERROR: {message}")
        errors += 1

    task_files = sorted(work_dir.glob("*.md")) + sorted(personal_dir.glob("*.md"))
    if not task_files:
        err(f"No canonical task files found in {work_dir} or {personal_dir}")

    index_rows, index_counts = parse_index(index_file)

    seen_task_ids: dict[str, Path] = {}
    declared_status: dict[str, str] = {}
    parent_of: dict[str, str] = {}

    for task_file in task_files:
        domain_expected = "work" if task_file.parent == work_dir else "personal"
        data, agents = parse_frontmatter(task_file.read_text(encoding="utf-8"))

        for key in REQUIRED_KEYS:
            if key not in data:
                err(f"{task_file} missing required key: {key}")

        for key in NONEMPTY_KEYS:
            value = trim_quotes(data.get(key, ""))
            if not value:
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
            err(f"{task_file} has empty task_id; cannot complete validation for this file")
            continue

        if domain != domain_expected:
            err(f"{task_file} domain '{domain}' does not match directory domain '{domain_expected}'")

        if domain == "work" and not re.match(r"^[A-Z]+-[0-9]+$", task_id):
            err(f"{task_file} work task_id must match ^[A-Z]+-[0-9]+$: got '{task_id}'")
        if domain == "personal" and not re.match(r"^DIL-[0-9]+$", task_id):
            err(f"{task_file} personal task_id must match ^DIL-[0-9]+$: got '{task_id}'")

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

        if task_id in seen_task_ids:
            err(f"Duplicate task_id '{task_id}' in {task_file} and {seen_task_ids[task_id]}")
        else:
            seen_task_ids[task_id] = task_file

        if len(agents) < 1:
            err(f"{task_file} must include at least one agent in agents list")
        else:
            first_agent = agents[0]
            first_role = trim_quotes(first_agent.get("role", ""))
            first_order = trim_quotes(first_agent.get("responsibility_order", ""))
            first_id = trim_quotes(first_agent.get("id", ""))

            if first_role != "accountable":
                err(f"{task_file} first agent role must be accountable (got '{first_role}')")
            if first_order != "1":
                err(f"{task_file} first agent responsibility_order must be 1 (got '{first_order}')")
            if first_id and owner != first_id:
                err(f"{task_file} owner must match accountable agent id (owner='{owner}', accountable='{first_id}')")

            for agent in agents:
                if trim_quotes(agent.get("id", "")) == "columbus":
                    role = trim_quotes(agent.get("role", ""))
                    if role not in {"reviewer", "accountable"}:
                        err(f"{task_file} columbus role must be reviewer (or accountable when first)")

        if parent:
            if parent == task_id:
                err(f"{task_file} parent_task_id cannot self-reference ({task_id})")
            if not re.match(r"^(DIL-[0-9]+|[A-Z]+-[0-9]+)$", parent):
                err(f"{task_file} invalid parent_task_id format '{parent}'")
            parent_of[task_id] = parent

        rel = f"_shared/tasks/{domain}/{task_id}.md"
        expected_row = f"| {task_id} | {domain} | {status} | {priority} | {owner} | {due} | {project} | {rel} | {updated} |"
        if index_rows.get(task_id) != expected_row:
            err(f"{index_file} missing exact row for {task_id}")
        if index_counts.get(task_id, 0) != 1:
            err(f"{index_file} should contain exactly one row for {task_id} (found {index_counts.get(task_id, 0)})")

        declared_status[task_id] = status

    for task_id, parent in parent_of.items():
        if parent not in seen_task_ids:
            err(f"Task {task_id} references missing parent_task_id {parent}")

    for task_id in list(parent_of):
        current = task_id
        seen_chain: set[str] = set()
        while current in parent_of:
            nxt = parent_of[current]
            if nxt == task_id or nxt in seen_chain:
                err(f"Cycle detected in parent_task_id chain starting at {task_id}")
                break
            seen_chain.add(nxt)
            current = nxt

    if counter_file.exists():
        next_id = ""
        for line in counter_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("- next_id:"):
                next_id = line.split(":", 1)[1].strip()
                break
        if not re.match(r"^[0-9]+$", next_id):
            err(f"Invalid or missing next_id in {counter_file}")
        else:
            max_personal = 1099
            for task_id in seen_task_ids:
                match = re.match(r"^DIL-([0-9]+)$", task_id)
                if match:
                    max_personal = max(max_personal, int(match.group(1)))
            expected_next = max_personal + 1
            if int(next_id) != expected_next:
                err(f"Counter mismatch in {counter_file}: next_id={next_id} expected={expected_next}")
    else:
        err(f"Missing counter file: {counter_file}")

    try:
        header_ok, log_last_status = parse_change_log(change_log)
        if not header_ok:
            err(f"Change log header must include model column: {change_log}")
    except ValueError as exc:
        err(str(exc))
        log_last_status = {}
    except FileNotFoundError:
        err(f"Missing change log: {change_log}")
        log_last_status = {}

    for task_id, status in log_last_status.items():
        if task_id in declared_status and declared_status[task_id] != status:
            err(f"Status mismatch for {task_id}: file={declared_status[task_id]} log_last={status}")

    if errors > 0:
        print(f"Validation failed: {errors} error(s), {warnings} warning(s)")
        return 1

    print(f"Validation passed: {len(task_files)} task(s), {warnings} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
