#!/usr/bin/env python3
"""morning_brief.py — Generate daily task briefing with urgency escalation.

Reads task data from task_tool, hot state, signals, and recurring reminders.
Renders a briefing and prepends to _shared/reminders.md.

Features:
  - Domains from domain_registry.json (display_order, briefing_label)
  - Checkbox items (- [ ]) for Obsidian tracking
  - Carry-forward of unchecked items from previous briefing
  - URGENT escalation: critical priority, due-date lead times, overdue, recurring
  - Effort-based lead times: low=3d, medium=14d, high=30d
  - Storybook logging via sf_log
  - JSON data artifact per run
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
    from sf_log import SFLogger
except ImportError:
    SFLogger = None

SCRIPT_NAME = "morning_brief"
STALE_DAYS = 7
LEAD_TIMES = {"low": 3, "medium": 14, "high": 30}
TERMINAL_STATUSES = {"done", "cancelled", "retired"}


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}
    fm: dict[str, str] = {}
    for line in parts[0].splitlines()[1:]:
        if line.startswith(" ") or line.startswith("\t"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in fm:
            fm[key] = value.strip().strip('"')
    return fm


def days_between(date_str: str, today: dt.date) -> int | None:
    try:
        d = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        return (today - d).days
    except (ValueError, TypeError):
        return None


def days_until(date_str: str, today: dt.date) -> int | None:
    try:
        d = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d - today).days
    except (ValueError, TypeError):
        return None


def load_registry(base: Path) -> dict:
    reg = base / "_shared" / "_meta" / "domain_registry.json"
    if not reg.exists():
        return {}
    return json.loads(reg.read_text(encoding="utf-8"))


def load_recurring(base: Path, today: dt.date) -> list[str]:
    recurring_file = base / "_shared" / "recurring_reminders.md"
    if not recurring_file.exists():
        return []

    items: list[str] = []
    current_year = today.year
    for line in recurring_file.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "reminder" in line.lower():
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 5:
            continue
        reminder, trigger_date, lead_days_str, last_completed, notes = parts[0], parts[1], parts[2], parts[3], parts[4] if len(parts) > 4 else ""
        if not reminder or not trigger_date:
            continue
        if last_completed == str(current_year):
            continue
        try:
            lead = int(lead_days_str)
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


def truncate(s: str, maxlen: int = 80) -> str:
    return s[:maxlen - 3] + "..." if len(s) > maxlen else s


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate morning task briefing")
    parser.add_argument("--base", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = Path(args.base).expanduser().resolve()
    today = dt.date.today()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    today_str = today.strftime("%Y-%m-%d")

    log = SFLogger(SCRIPT_NAME, "run", str(base)) if SFLogger else None

    if log:
        log.section("Initialization")
        log.info(f"base: {base}")
        log.info(f"today: {today_str}")
        log.info(f"dry_run: {args.dry_run}")
        log.info(f"stale_days: {STALE_DAYS}")
        log.info(f"lead_times: {LEAD_TIMES}")

    registry = load_registry(base)
    domains_conf = registry.get("domains", {})

    domain_order = sorted(
        domains_conf.items(),
        key=lambda x: x[1].get("display_order", 999),
    )
    primary_domain = domain_order[0][0] if domain_order else ""

    if log:
        log.section("Domain Scan")
        log.info(f"domains: {[d[0] for d in domain_order]}")
        log.info(f"primary: {primary_domain}")

    # Carry forward
    carried = extract_carryforward(base)
    if log:
        log.info(f"carried_forward items: {len(carried)}")

    # Recurring
    recurring = load_recurring(base, today)
    if log:
        log.info(f"recurring reminders triggered: {len(recurring)}")

    # Scan all domains
    urgent_items: list[str] = []
    domain_sections: list[tuple[int, str, str]] = []
    seen_ids: set[str] = set()
    fresh_ids: set[str] = set()
    stats: dict[str, dict[str, int]] = {}

    for domain_name, domain_conf in domain_order:
        td = domain_conf.get("task_dir", "")
        td_path = base / td if not Path(td).is_absolute() else Path(td)
        active_dir = td_path / "active"
        if not active_dir.is_dir():
            continue

        label = domain_conf.get("briefing_label", domain_conf.get("name", domain_name))
        order = domain_conf.get("display_order", 999)

        blocked: list[str] = []
        in_progress: list[str] = []
        due_soon: list[str] = []
        stale: list[str] = []
        new_todo: list[str] = []
        domain_stats = {"blocked": 0, "in_progress": 0, "due_soon": 0, "stale": 0, "new_todo": 0, "urgent": 0, "skipped_terminal": 0}

        for f in sorted(active_dir.glob("*.md")):
            if f.name == "index.md":
                continue
            fm = parse_frontmatter(f.read_text(encoding="utf-8"))
            task_id = fm.get("task_id", f.stem)
            title = truncate(fm.get("title", task_id))
            status = fm.get("status", "")
            priority = fm.get("priority", "normal")
            updated = fm.get("updated", "")
            due = fm.get("due", "")
            project = fm.get("project", "")
            effort = fm.get("effort_type", "medium")

            if status in TERMINAL_STATUSES:
                domain_stats["skipped_terminal"] += 1
                continue

            fresh_ids.add(task_id)
            line = f"- [ ] **{task_id}** ({priority}) — {title} [{project}]"

            # Urgency checks
            is_urgent = False
            urgent_reason = ""

            if priority == "critical" and domain_name != primary_domain:
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
                        urgent_reason = f"DUE TODAY" if remaining == 0 else f"due in {remaining} day(s) ({effort} effort, {lead}d lead)"

            if is_urgent:
                urgent_items.append(f"{line} — **{urgent_reason}**")
                seen_ids.add(task_id)
                domain_stats["urgent"] += 1
                continue

            # Standard categorization
            placed = False

            if due and not placed:
                remaining = days_until(due, today)
                if remaining is not None and remaining <= 7:
                    if remaining < 0:
                        due_soon.append(f"{line} — **OVERDUE by {abs(remaining)} day(s)**")
                    elif remaining == 0:
                        due_soon.append(f"{line} — **DUE TODAY**")
                    else:
                        due_soon.append(f"{line} — due in {remaining} day(s)")
                    placed = True
                    domain_stats["due_soon"] += 1

            if status == "blocked" and not placed:
                blocked.append(line)
                placed = True
                domain_stats["blocked"] += 1

            if status in ("in_progress", "assigned") and not placed:
                age = days_between(updated, today)
                if age is not None and age >= STALE_DAYS:
                    stale.append(f"{line} — last updated {age} day(s) ago")
                    domain_stats["stale"] += 1
                else:
                    in_progress.append(line)
                    domain_stats["in_progress"] += 1
                placed = True

            if status == "todo" and not placed:
                created = fm.get("date", "")
                age = days_between(created, today)
                if age is not None and age <= 3:
                    new_todo.append(line)
                    domain_stats["new_todo"] += 1
                    placed = True

            if placed:
                seen_ids.add(task_id)

        # Build domain section
        section_parts: list[str] = []
        if blocked:
            section_parts.append("#### Blocked / Waiting\n" + "\n".join(blocked))
        if due_soon:
            section_parts.append("#### Due Soon / Overdue\n" + "\n".join(due_soon))
        if in_progress:
            section_parts.append("#### In Progress\n" + "\n".join(in_progress))
        if stale:
            section_parts.append(f"#### Stale (no update in {STALE_DAYS}+ days)\n" + "\n".join(stale))
        if new_todo:
            section_parts.append("#### New (created in last 3 days, still todo)\n" + "\n".join(new_todo))

        if section_parts:
            active_count = domain_stats["blocked"] + domain_stats["in_progress"] + domain_stats["due_soon"] + domain_stats["new_todo"]
            header = f"### {label} ({active_count} active, {domain_stats['stale']} stale)\n"
            domain_sections.append((order, domain_name, header + "\n" + "\n\n".join(section_parts) + "\n"))

        stats[domain_name] = domain_stats

        if log:
            log.info(f"  {domain_name}: {domain_stats}")

    # Carry-forward: orphaned items go to URGENT
    carried_to_urgent: list[str] = []
    for cline in carried:
        m = re.search(r"\*\*([A-Z]+-[0-9]+)\*\*", cline)
        if m and m.group(1) in fresh_ids:
            continue
        if "RECURRING" in cline:
            reminder_m = re.search(r"RECURRING\*\* — (.*?) —", cline)
            if reminder_m and any(reminder_m.group(1) in r for r in recurring):
                continue
        clean = re.sub(r"\s*\*\(carried\)\*", "", cline).rstrip()
        carried_to_urgent.append(f"{clean} *(carried)*")

    # Build briefing
    briefing_parts: list[str] = [f"## Morning Briefing — {now_str}\n"]

    all_urgent = urgent_items + recurring + carried_to_urgent
    if all_urgent:
        briefing_parts.append(f"### URGENT ({len(all_urgent)} items)")
        briefing_parts.append("\n".join(all_urgent))
        briefing_parts.append("")

    domain_sections.sort(key=lambda x: x[0])
    for _, _, section in domain_sections:
        briefing_parts.append(section)

    total_urgent = len(all_urgent)
    total_carried = len(carried_to_urgent)
    briefing_parts.append("### Summary")
    briefing_parts.append(f"Urgent: {total_urgent} ({total_carried} carried) | Lead times: low={LEAD_TIMES['low']}d med={LEAD_TIMES['medium']}d high={LEAD_TIMES['high']}d")
    briefing_parts.append("\n---\n")

    briefing = "\n".join(briefing_parts) + "\n"

    if log:
        log.section("Briefing Assembled")
        log.info(f"urgent_items: {len(urgent_items)}")
        log.info(f"recurring_triggered: {len(recurring)}")
        log.info(f"carried_forward: {len(carried)} (orphaned to urgent: {total_carried})")
        log.info(f"domain_sections: {len(domain_sections)}")
        log.info(f"total_urgent: {total_urgent}")
        log.info(f"briefing_length: {len(briefing)} chars")

    if args.dry_run:
        print(briefing)
        if log:
            log.section("Result")
            log.info("DRY RUN — briefing printed to stdout, not written to reminders.md")
            log.close()
        return 0

    # Write
    reminders_file = base / "_shared" / "reminders.md"

    if reminders_file.exists():
        existing = reminders_file.read_text(encoding="utf-8")
        if existing.startswith("---"):
            m = re.match(r"^(---\n.*?\n---\n)(.*)", existing, re.DOTALL)
            if m:
                reminders_file.write_text(m.group(1) + "\n" + briefing + m.group(2), encoding="utf-8")
            else:
                reminders_file.write_text(briefing + existing, encoding="utf-8")
        else:
            reminders_file.write_text(briefing + existing, encoding="utf-8")
    else:
        header = f"""---
title: "Daily Reminders & Briefings"
date: {today_str}
machine: shared
assistant: shared
category: system
memoryType: reference
priority: notable
tags: [reminders, briefing, daily]
updated: {today_str}
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

    # Data artifact
    data_dir = base / "_shared" / "data" / SCRIPT_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    data_file = data_dir / f"{SCRIPT_NAME}.run.{ts}.json"
    artifact = {
        "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output_file": str(reminders_file),
        "total_urgent": total_urgent,
        "total_carried": total_carried,
        "recurring_triggered": len(recurring),
        "domain_stats": stats,
        "briefing_length": len(briefing),
    }
    data_file.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    if log:
        log.section("Result")
        log.info(f"Written to: {reminders_file}")
        log.info(f"Data artifact: {data_file}")
        log.info(f"Urgent: {total_urgent} ({total_carried} carried)")
        for dn, ds in stats.items():
            log.info(f"  {dn}: {ds}")
        log.close()

    print(f"Briefing written to {reminders_file}")
    print(f"Urgent: {total_urgent} | Carried: {total_carried} | Lead times: low={LEAD_TIMES['low']}d med={LEAD_TIMES['medium']}d high={LEAD_TIMES['high']}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
