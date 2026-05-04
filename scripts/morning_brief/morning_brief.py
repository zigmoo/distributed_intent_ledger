#!/usr/bin/env python3
"""morning_brief.py — Generate daily task briefing with urgency escalation.

Reads task data from task_index.csv via DuckDB, hot state, signals, and recurring reminders.
Renders a briefing via J2 template and prepends to _shared/reminders.md.

Architecture: CSV-primary (Standard #11) — task_index.csv is the data source,
DuckDB provides the query layer, J2 template renders the output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import jinja2
except ImportError:
    jinja2 = None

SCRIPT_NAME = "morning_brief"
STALE_DAYS = 7
LEAD_TIMES = {"low": 3, "medium": 14, "high": 30}
TERMINAL_STATUSES = ("done", "cancelled", "retired")


def days_between(date_string: str, today: dt.date) -> int | None:
    try:
        parsed_date = dt.datetime.strptime(date_string, "%Y-%m-%d").date()
        return (today - parsed_date).days
    except (ValueError, TypeError):
        return None


def days_until(date_string: str, today: dt.date) -> int | None:
    try:
        parsed_date = dt.datetime.strptime(date_string, "%Y-%m-%d").date()
        return (parsed_date - today).days
    except (ValueError, TypeError):
        return None


def load_registry(base: Path) -> dict:
    registry_path = base / "_shared" / "_meta" / "domain_registry.json"
    if not registry_path.exists():
        return {}
    return json.loads(registry_path.read_text(encoding="utf-8"))


def load_active_tasks_from_csv(base: Path) -> list[dict]:
    csv_path = base / "_shared" / "_meta" / "task_index.csv"
    if not csv_path.exists():
        return []
    connection = duckdb.connect(":memory:")
    connection.execute(f"CREATE VIEW data AS SELECT * FROM read_csv_auto('{csv_path}')")
    terminal_list = ", ".join(f"'{status}'" for status in TERMINAL_STATUSES)
    result = connection.execute(f"SELECT * FROM data WHERE status NOT IN ({terminal_list})")
    column_names = [description[0] for description in result.description]
    rows = []
    for raw_row in result.fetchall():
        row = dict(zip(column_names, raw_row))
        for key in row:
            if row[key] is None:
                row[key] = ""
            else:
                row[key] = str(row[key])
        rows.append(row)
    connection.close()
    return rows


def load_hot_state(base: Path) -> dict:
    """Load _hot.md and extract session context and pending items."""
    hot_file = base / "_shared" / "_hot.md"
    if not hot_file.exists():
        return {"exists": False, "pending_lines": [], "agent": "", "machine": "", "updated": ""}

    text = hot_file.read_text(encoding="utf-8")

    frontmatter: dict[str, str] = {}
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            for line in parts[0].splitlines()[1:]:
                if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip()

    pending_lines: list[str] = []
    in_pending_section = False
    for line in text.splitlines():
        if re.match(r"^##\s+Pending", line, re.IGNORECASE) or re.match(r"^##\s+Next", line, re.IGNORECASE):
            in_pending_section = True
            continue
        if in_pending_section and line.startswith("## "):
            break
        if in_pending_section and line.strip():
            pending_lines.append(line)

    return {
        "exists": True,
        "pending_lines": pending_lines,
        "agent": frontmatter.get("session_agent", ""),
        "machine": frontmatter.get("session_machine", ""),
        "updated": frontmatter.get("updated", ""),
    }


def load_recurring(base: Path, today: dt.date) -> list[str]:
    recurring_file = base / "_shared" / "recurring_reminders.md"
    if not recurring_file.exists():
        return []

    items: list[str] = []
    current_year = today.year
    for line in recurring_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "reminder" in line.lower():
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) < 5:
            continue
        reminder, trigger_date, lead_days_string, last_completed = parts[0], parts[1], parts[2], parts[3]
        notes = parts[4] if len(parts) > 4 else ""
        if not reminder or not trigger_date:
            continue
        if last_completed == str(current_year):
            continue
        try:
            lead = int(lead_days_string)
        except (ValueError, TypeError):
            lead = 14
        remaining = days_until(f"{current_year}-{trigger_date}", today)
        if remaining is None:
            continue
        if remaining <= lead:
            if remaining < 0:
                items.append(f"- [ ] **RECURRING** — {reminder} — **OVERDUE by {abs(remaining)} day(s)** [{notes}]")
            elif remaining == 0:
                items.append(f"- [ ] **RECURRING** — {reminder} — **DUE TODAY** [{notes}]")
            else:
                items.append(f"- [ ] **RECURRING** — {reminder} — due in {remaining} day(s) [{notes}]")
    return items


def extract_carryforward(base: Path) -> list[str]:
    reminders_file = base / "_shared" / "reminders.md"
    if not reminders_file.exists():
        return []
    text = reminders_file.read_text(encoding="utf-8")
    in_briefing = False
    items: list[str] = []
    for line in text.splitlines():
        if line.startswith("## Morning Briefing"):
            in_briefing = True
            continue
        if in_briefing and line == "---":
            break
        if in_briefing and line.startswith("- [ ]"):
            items.append(line)
    return items


def truncate(text: str, maximum_length: int = 80) -> str:
    return text[:maximum_length - 3] + "..." if len(text) > maximum_length else text


def categorize_tasks(tasks: list[dict], today: dt.date, primary_domain: str) -> dict:
    """Categorize tasks into urgent, blocked, in_progress, due_soon, stale, new_todo by domain."""
    urgent_items: list[str] = []
    domain_buckets: dict[str, dict[str, list[str]]] = {}
    domain_stats: dict[str, dict[str, int]] = {}
    seen_task_ids: set[str] = set()
    fresh_task_ids: set[str] = set()

    for task in tasks:
        task_id = task.get("task_id", "")
        title = truncate(task.get("title", task_id))
        status = task.get("status", "")
        priority = task.get("priority", "normal")
        updated = task.get("updated", "")
        due = task.get("due", "")
        project = task.get("project", "")
        effort = task.get("effort_type", "medium")
        domain = task.get("domain", "")

        fresh_task_ids.add(task_id)
        line = f"- [ ] **{task_id}** ({priority}) — {title} [{project}]"

        is_urgent = False
        urgent_reason = ""

        if priority == "critical" and domain != primary_domain:
            is_urgent = True
            urgent_reason = "critical priority"

        if due:
            remaining = days_until(due, today)
            if remaining is not None:
                lead = LEAD_TIMES.get(effort, 14)
                if remaining < 0:
                    is_urgent = True
                    urgent_reason = f"OVERDUE by {abs(remaining)} day(s)"
                elif remaining <= lead:
                    is_urgent = True
                    urgent_reason = "DUE TODAY" if remaining == 0 else f"due in {remaining} day(s) ({effort} effort, {lead}d lead)"

        if is_urgent:
            urgent_items.append(f"{line} — **{urgent_reason}**")
            seen_task_ids.add(task_id)
            domain_stats.setdefault(domain, {}).setdefault("urgent", 0)
            domain_stats[domain]["urgent"] += 1
            continue

        if domain not in domain_buckets:
            domain_buckets[domain] = {"blocked": [], "due_soon": [], "in_progress": [], "stale": [], "new_todo": []}
            domain_stats[domain] = {"blocked": 0, "in_progress": 0, "due_soon": 0, "stale": 0, "new_todo": 0, "urgent": 0}

        placed = False

        if due and not placed:
            remaining = days_until(due, today)
            if remaining is not None and remaining <= 7:
                if remaining < 0:
                    domain_buckets[domain]["due_soon"].append(f"{line} — **OVERDUE by {abs(remaining)} day(s)**")
                elif remaining == 0:
                    domain_buckets[domain]["due_soon"].append(f"{line} — **DUE TODAY**")
                else:
                    domain_buckets[domain]["due_soon"].append(f"{line} — due in {remaining} day(s)")
                placed = True
                domain_stats[domain]["due_soon"] += 1

        if status == "blocked" and not placed:
            domain_buckets[domain]["blocked"].append(line)
            placed = True
            domain_stats[domain]["blocked"] += 1

        if status in ("in_progress", "assigned") and not placed:
            age = days_between(updated, today)
            if age is not None and age >= STALE_DAYS:
                domain_buckets[domain]["stale"].append(f"{line} — last updated {age} day(s) ago")
                domain_stats[domain]["stale"] += 1
            else:
                domain_buckets[domain]["in_progress"].append(line)
                domain_stats[domain]["in_progress"] += 1
            placed = True

        if status == "todo" and not placed:
            created = task.get("date", updated)
            age = days_between(created, today)
            if age is not None and age <= 3:
                domain_buckets[domain]["new_todo"].append(line)
                domain_stats[domain]["new_todo"] += 1
                placed = True

        if placed:
            seen_task_ids.add(task_id)

    return {
        "urgent_items": urgent_items,
        "domain_buckets": domain_buckets,
        "domain_stats": domain_stats,
        "fresh_task_ids": fresh_task_ids,
    }


def render_briefing(
    categorized: dict,
    domain_order: list[tuple[str, dict]],
    recurring: list[str],
    carried: list[str],
    now_string: str,
    hot_state: dict | None = None,
) -> str:
    urgent_items = categorized["urgent_items"]
    domain_buckets = categorized["domain_buckets"]
    domain_stats = categorized["domain_stats"]
    fresh_task_ids = categorized["fresh_task_ids"]

    carried_to_urgent: list[str] = []
    for carried_line in carried:
        match = re.search(r"\*\*([A-Z]+-[0-9]+)\*\*", carried_line)
        if match and match.group(1) in fresh_task_ids:
            continue
        if "RECURRING" in carried_line:
            reminder_match = re.search(r"RECURRING\*\* — (.*?) —", carried_line)
            if reminder_match and any(reminder_match.group(1) in reminder for reminder in recurring):
                continue
        clean = re.sub(r"\s*\*\(carried\)\*", "", carried_line).rstrip()
        carried_to_urgent.append(f"{clean} *(carried)*")

    briefing_parts: list[str] = [f"## Morning Briefing — {now_string}\n"]

    all_urgent = urgent_items + recurring + carried_to_urgent
    if all_urgent:
        briefing_parts.append(f"### URGENT ({len(all_urgent)} items)")
        briefing_parts.append("\n".join(all_urgent))
        briefing_parts.append("")

    if hot_state and hot_state.get("exists") and hot_state.get("pending_lines"):
        hot_header = "### Last Session — Pending"
        if hot_state.get("agent") or hot_state.get("machine"):
            hot_header += f" (from {hot_state.get('agent', '?')} on {hot_state.get('machine', '?')}, {hot_state.get('updated', '?')})"
        briefing_parts.append(hot_header)
        briefing_parts.append("\n".join(hot_state["pending_lines"]))
        briefing_parts.append("")

    for domain_name, domain_configuration in domain_order:
        buckets = domain_buckets.get(domain_name, {})
        stats = domain_stats.get(domain_name, {})
        section_parts: list[str] = []
        label = domain_configuration.get("briefing_label", domain_configuration.get("name", domain_name))

        if buckets.get("blocked"):
            section_parts.append("#### Blocked / Waiting\n" + "\n".join(buckets["blocked"]))
        if buckets.get("due_soon"):
            section_parts.append("#### Due Soon / Overdue\n" + "\n".join(buckets["due_soon"]))
        if buckets.get("in_progress"):
            section_parts.append("#### In Progress\n" + "\n".join(buckets["in_progress"]))
        if buckets.get("stale"):
            section_parts.append(f"#### Stale (no update in {STALE_DAYS}+ days)\n" + "\n".join(buckets["stale"]))
        if buckets.get("new_todo"):
            section_parts.append("#### New (created in last 3 days, still todo)\n" + "\n".join(buckets["new_todo"]))

        if section_parts:
            active_count = stats.get("blocked", 0) + stats.get("in_progress", 0) + stats.get("due_soon", 0) + stats.get("new_todo", 0)
            header = f"### {label} ({active_count} active, {stats.get('stale', 0)} stale)\n"
            briefing_parts.append(header + "\n" + "\n\n".join(section_parts) + "\n")

    total_urgent = len(all_urgent)
    total_carried = len(carried_to_urgent)
    briefing_parts.append("### Summary")
    briefing_parts.append(f"Urgent: {total_urgent} ({total_carried} carried) | Lead times: low={LEAD_TIMES['low']}d med={LEAD_TIMES['medium']}d high={LEAD_TIMES['high']}d")
    briefing_parts.append("\n---\n")

    return "\n".join(briefing_parts) + "\n", total_urgent, total_carried


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate morning task briefing")
    parser.add_argument("--base", required=True)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    base = Path(arguments.base).expanduser().resolve()
    today = dt.date.today()
    now_string = dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    today_string = today.strftime("%Y-%m-%d")

    log = ToolForgeLogger(SCRIPT_NAME, "run", str(base)) if ToolForgeLogger else None

    if log:
        log.section("Initialization")
        log.info(f"base: {base}")
        log.info(f"today: {today_string}")
        log.info(f"dry_run: {arguments.dry_run}")
        log.info(f"data_source: task_index.csv (CSV-primary, DuckDB queries)")

    registry = load_registry(base)
    domains_configuration = registry.get("domains", {})

    domain_order = sorted(
        domains_configuration.items(),
        key=lambda entry: entry[1].get("display_order", 999),
    )
    primary_domain = domain_order[0][0] if domain_order else ""

    if log:
        log.section("Data Loading")
        log.info(f"domains: {[entry[0] for entry in domain_order]}")
        log.info(f"primary: {primary_domain}")

    active_tasks = load_active_tasks_from_csv(base)
    if log:
        log.info(f"active tasks from CSV: {len(active_tasks)}")

    hot_state = load_hot_state(base)
    if log:
        log.info(f"hot state exists: {hot_state['exists']}")
        if hot_state["exists"]:
            log.info(f"  agent: {hot_state['agent']}, machine: {hot_state['machine']}, updated: {hot_state['updated']}")
            log.info(f"  pending items: {len(hot_state['pending_lines'])}")

    carried = extract_carryforward(base)
    recurring = load_recurring(base, today)
    if log:
        log.info(f"carried_forward items: {len(carried)}")
        log.info(f"recurring reminders triggered: {len(recurring)}")

    if log:
        log.section("Categorization")

    categorized = categorize_tasks(active_tasks, today, primary_domain)

    if log:
        for domain_name, stats in categorized["domain_stats"].items():
            log.info(f"  {domain_name}: {stats}")

    briefing, total_urgent, total_carried = render_briefing(
        categorized, domain_order, recurring, carried, now_string, hot_state,
    )

    if log:
        log.section("Briefing Assembled")
        log.info(f"total_urgent: {total_urgent}")
        log.info(f"total_carried: {total_carried}")
        log.info(f"briefing_length: {len(briefing)} chars")

    if arguments.dry_run:
        print(briefing)
        if log:
            log.section("Result")
            log.info("DRY RUN — briefing printed to stdout, not written to reminders.md")
            log.close()
        return 0

    reminders_file = base / "_shared" / "reminders.md"

    if reminders_file.exists():
        existing = reminders_file.read_text(encoding="utf-8")
        if existing.startswith("---"):
            frontmatter_match = re.match(r"^(---\n.*?\n---\n)(.*)", existing, re.DOTALL)
            if frontmatter_match:
                reminders_file.write_text(frontmatter_match.group(1) + "\n" + briefing + frontmatter_match.group(2), encoding="utf-8")
            else:
                reminders_file.write_text(briefing + existing, encoding="utf-8")
        else:
            reminders_file.write_text(briefing + existing, encoding="utf-8")
    else:
        header = f"""---
title: "Daily Reminders & Briefings"
date: {today_string}
machine: shared
assistant: shared
category: system
memoryType: reference
priority: notable
tags: [reminders, briefing, daily]
updated: {today_string}
source: internal
domain: operations
project: dil-active
status: active
owner: shared
due:
---

# Daily Reminders & Briefings

Generated by `morning_brief`. Newest briefing appears first.
Check items with `[x]` to mark complete — unchecked items carry forward.
Tasks escalate to URGENT based on effort-based lead times.

"""
        reminders_file.write_text(header + briefing, encoding="utf-8")

    data_directory = base / "_shared" / "data" / SCRIPT_NAME
    data_directory.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    data_file = data_directory / f"{SCRIPT_NAME}.run.{timestamp}.json"
    artifact = {
        "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_file": str(reminders_file),
        "data_source": "task_index.csv",
        "active_tasks_queried": len(active_tasks),
        "total_urgent": total_urgent,
        "total_carried": total_carried,
        "recurring_triggered": len(recurring),
        "domain_stats": categorized["domain_stats"],
        "briefing_length": len(briefing),
    }
    data_file.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    if log:
        log.section("Result")
        log.info(f"Written to: {reminders_file}")
        log.info(f"Data artifact: {data_file}")
        log.info(f"Urgent: {total_urgent} ({total_carried} carried)")
        for domain_name, stats in categorized["domain_stats"].items():
            log.info(f"  {domain_name}: {stats}")
        log.close()

    print(f"Briefing written to {reminders_file}")
    print(f"Urgent: {total_urgent} | Carried: {total_carried} | Lead times: low={LEAD_TIMES['low']}d med={LEAD_TIMES['medium']}d high={LEAD_TIMES['high']}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
