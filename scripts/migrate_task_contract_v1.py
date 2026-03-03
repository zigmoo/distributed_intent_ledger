#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

REQ_ORDER = [
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
    "task_id",
    "created_by",
    "model",
    "created_at",
    "task_schema",
    "parent_task_id",
    "agents",
    "subcategory",
]

STATUS_SET = {"todo", "assigned", "in_progress", "blocked", "done", "cancelled"}
PRIO_SET = {"low", "normal", "high", "critical"}


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    data = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*-\s+id:\s*", line):
            i += 1
            continue
        if re.match(r"^\s+role:\s*", line) or re.match(r"^\s+responsibility_order:\s*", line) or re.match(r"^\s+status:\s*", line):
            i += 1
            continue
        if line.startswith("agents:"):
            i += 1
            while i < len(lines) and (lines[i].startswith("  - ") or lines[i].startswith("    ")):
                i += 1
            data["agents"] = "<parsed-separately>"
            continue
        m2 = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m2:
            k, v = m2.group(1), m2.group(2).strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            data[k] = v
        i += 1
    return data, body


def q(v: str) -> str:
    return v.replace('"', '\\"')


def parse_existing_agents(text: str):
    ids = []
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm_match:
        return ids
    fm = fm_match.group(1).splitlines()
    in_agents = False
    for line in fm:
        if line.startswith("agents:"):
            in_agents = True
            continue
        if in_agents and re.match(r"^[^\s]", line):
            in_agents = False
        if in_agents:
            m = re.match(r"^\s*-\s+id:\s*(.+)$", line)
            if m:
                aid = m.group(1).strip().strip('"').strip("'").lower()
                if aid:
                    ids.append(aid)
    return ids


def normalize_agents(owner: str, existing_ids: list[str]) -> list[str]:
    out = []
    for candidate in [owner.lower(), *existing_ids, "columbus"]:
        c = candidate.strip().lower()
        if c and c not in out:
            out.append(c)
    if not out:
        out = ["moo", "columbus"]
    return out


def role_for(agent_id: str, idx: int) -> str:
    if idx == 0:
        return "accountable"
    if agent_id == "columbus":
        return "reviewer"
    return "contributor"


def canonical_frontmatter(data: dict[str, str], path: Path, task_id: str, body: str, today: str) -> str:
    domain = data.get("domain") or ("work" if "/work/" in str(path) else "personal")
    owner = (data.get("owner") or "moo").strip() or "moo"
    title = (data.get("title") or task_id).strip() or task_id

    status = (data.get("status") or "todo").strip()
    if status not in STATUS_SET:
        status = "todo"
    priority = (data.get("priority") or "normal").strip()
    if priority not in PRIO_SET:
        priority = "normal"

    created_at = (data.get("created_at") or f"{today}T00:00:00Z").strip()
    date = (data.get("date") or created_at[:10] or today).strip()
    updated = (data.get("updated") or today).strip()

    project = data.get("project", "")
    due = data.get("due", "")
    subcategory = data.get("subcategory", "")
    parent_task_id = data.get("parent_task_id", "")

    machine = data.get("machine", "shared")
    assistant = data.get("assistant", "shared")
    category = data.get("category", "tasks")
    memory_type = data.get("memoryType", "task")
    source = data.get("source", "internal")
    created_by = data.get("created_by", "codex")
    model = data.get("model", "gpt-5")
    tags = data.get("tags") or f"[task, {domain}]"

    existing_agents = parse_existing_agents(path.read_text(encoding="utf-8", errors="ignore"))
    agent_ids = normalize_agents(owner, existing_agents)
    owner = agent_ids[0]

    lines = ["---"]
    lines.append(f"title: \"{q(title)}\"")
    lines.append(f"date: {date}")
    lines.append(f"machine: {machine}")
    lines.append(f"assistant: {assistant}")
    lines.append(f"category: {category}")
    lines.append(f"memoryType: {memory_type}")
    lines.append(f"priority: {priority}")
    lines.append(f"tags: {tags}")
    lines.append(f"updated: {updated}")
    lines.append(f"source: {source}")
    lines.append(f"domain: {domain}")
    lines.append(f"project: \"{q(project)}\"")
    lines.append(f"status: {status}")
    lines.append(f"owner: \"{q(owner)}\"")
    lines.append(f"due: \"{q(due)}\"")
    lines.append(f"task_id: {task_id}")
    lines.append(f"created_by: \"{q(created_by)}\"")
    lines.append(f"model: \"{q(model)}\"")
    lines.append(f"created_at: {created_at}")
    lines.append("task_schema: v1")
    lines.append(f"parent_task_id: \"{q(parent_task_id)}\"")
    lines.append("agents:")

    for idx, aid in enumerate(agent_ids):
        lines.append(f"  - id: {aid}")
        lines.append(f"    role: {role_for(aid, idx)}")
        lines.append(f"    responsibility_order: {idx + 1}")
        lines.append("    status: active")

    lines.append(f"subcategory: \"{q(subcategory)}\"")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def in_scope(task_id: str, min_id: int, max_id: int, include_work: bool) -> bool:
    m = re.match(r"^MOO-(\d+)$", task_id)
    if not m:
        return include_work
    n = int(m.group(1))
    return min_id <= n <= max_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate task files to task contract v1")
    ap.add_argument("--base", default="/home/moo/Documents/dil_agentic_memory_0001")
    ap.add_argument("--min-id", type=int, default=0)
    ap.add_argument("--max-id", type=int, default=999999)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-work", action="store_true", help="Also migrate non-MOO task ids (work tasks)")
    args = ap.parse_args()

    base = Path(args.base)
    task_dirs = [base / "_shared" / "tasks" / "work", base / "_shared" / "tasks" / "personal"]
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")

    changed = 0
    checked = 0

    for task_dir in task_dirs:
        for path in sorted(task_dir.glob("*.md")):
            task_id = path.stem
            if not in_scope(task_id, args.min_id, args.max_id, args.include_work):
                continue

            checked += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            data, body = parse_frontmatter(text)
            new_text = canonical_frontmatter(data, path, task_id, body, today)
            if new_text != text:
                changed += 1
                print(f"MIGRATE {task_id}: {path}")
                if args.apply:
                    path.write_text(new_text, encoding="utf-8")

    print(f"CHECKED={checked} CHANGED={changed} APPLY={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
