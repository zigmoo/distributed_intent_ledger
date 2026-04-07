#!/usr/bin/env python3
"""
list_ingest.py — Query the DIL knowledge registry for ingested items.

Registry-driven (not filesystem-grepping). Filters by status, domain,
source_type, content_tier, actor. Supports human-readable table, JSON,
and pipe-delimited output.

Vanilla Python (stdlib only).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Import registry parser from ingest_source
sys.path.insert(0, os.path.dirname(__file__))
from ingest_source import _parse_registry, KNOWLEDGE_REGISTRY_PATH

STALE_FAILURE_DAYS = 7  # items in failed state longer than this are flagged


def query_registry(filters):
    """Query the registry with filters. Returns list of row dicts."""
    _, rows = _parse_registry()
    results = []
    for _, row in rows:
        if filters.get("status") and row["status"] != filters["status"]:
            continue
        if filters.get("domain") and row["domain"] != filters["domain"]:
            continue
        if filters.get("source_type") and row["source_type"] != filters["source_type"]:
            continue
        if filters.get("content_tier") and row["content_tier"] != filters["content_tier"]:
            continue
        if filters.get("actor") and row["actor"] != filters["actor"]:
            continue
        if filters.get("mime_type") and row["mime_type"] != filters["mime_type"]:
            continue
        results.append(row)
    return results


def _is_stale_failure(row):
    """Check if a failed item is older than STALE_FAILURE_DAYS."""
    if row["status"] not in ("failed", "failed_terminal", "pending_tooling"):
        return False
    ingested_at = row.get("ingested_at", "")
    if not ingested_at:
        return False
    try:
        ts = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        return age > timedelta(days=STALE_FAILURE_DAYS)
    except (ValueError, TypeError):
        return False


def _truncate(s, maxlen):
    """Truncate string with ellipsis if too long."""
    if len(s) <= maxlen:
        return s
    return s[:maxlen - 3] + "..."


def format_table(results):
    """Format results as a human-readable table."""
    if not results:
        return "No items found."

    # Column widths
    cols = [
        ("ingest_id", 28),
        ("domain", 10),
        ("source_type", 8),
        ("title", 35),
        ("status", 18),
        ("content_tier", 8),
        ("mime_type", 25),
        ("ingested_at", 20),
        ("actor", 12),
    ]

    # Header
    header = " | ".join(name.ljust(width) for name, width in cols)
    sep = "-+-".join("-" * width for _, width in cols)
    lines = [header, sep]

    for row in results:
        stale_marker = " [STALE]" if _is_stale_failure(row) else ""
        values = []
        for name, width in cols:
            val = row.get(name, "")
            if name == "status":
                val = val + stale_marker
            values.append(_truncate(val, width).ljust(width))
        lines.append(" | ".join(values))

    # Summary
    lines.append("")
    lines.append(f"Total: {len(results)} items")

    # Count by status
    status_counts = {}
    for row in results:
        s = row["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    if len(status_counts) > 1:
        summary_parts = [f"{s}: {c}" for s, c in sorted(status_counts.items())]
        lines.append(f"By status: {', '.join(summary_parts)}")

    stale_count = sum(1 for r in results if _is_stale_failure(r))
    if stale_count:
        lines.append(f"Stale failures (>{STALE_FAILURE_DAYS} days): {stale_count}")

    return "\n".join(lines)


def format_json(results):
    """Format results as JSON array."""
    # Add stale flag
    for row in results:
        row["stale_failure"] = _is_stale_failure(row)
    return json.dumps(results, indent=2)


def format_pipe(results):
    """Format results as pipe-delimited rows."""
    lines = []
    for row in results:
        cols = [
            row.get("ingest_id", ""),
            row.get("domain", ""),
            row.get("source_type", ""),
            row.get("title", ""),
            row.get("status", ""),
            row.get("content_tier", ""),
            row.get("raw_scope_path", ""),
        ]
        lines.append(" | ".join(cols))
    return "\n".join(lines)


def summary_report():
    """Generate a summary report of all registry items by state."""
    _, rows = _parse_registry()
    if not rows:
        return "Registry is empty."

    total = len(rows)
    by_status = {}
    by_domain = {}
    by_tier = {}
    stale = 0

    for _, row in rows:
        s = row["status"]
        d = row["domain"]
        t = row["content_tier"]
        by_status[s] = by_status.get(s, 0) + 1
        by_domain[d] = by_domain.get(d, 0) + 1
        by_tier[t] = by_tier.get(t, 0) + 1
        if _is_stale_failure(row):
            stale += 1

    lines = [f"Knowledge Registry Summary — {total} items", ""]

    lines.append("By status:")
    for s, c in sorted(by_status.items()):
        lines.append(f"  {s}: {c}")

    lines.append("\nBy domain:")
    for d, c in sorted(by_domain.items()):
        lines.append(f"  {d}: {c}")

    lines.append("\nBy content tier:")
    for t, c in sorted(by_tier.items()):
        lines.append(f"  {t}: {c}")

    if stale:
        lines.append(f"\nStale failures (>{STALE_FAILURE_DAYS} days): {stale}")

    # Action items
    actionable = by_status.get("pending_tooling", 0) + by_status.get("failed", 0) + by_status.get("failed_validation", 0)
    if actionable:
        lines.append(f"\nActionable items requiring triage: {actionable}")
        if by_status.get("pending_tooling", 0):
            lines.append(f"  Run: retry_ingest.sh --state pending_tooling --check-tooling")
        if by_status.get("failed", 0):
            lines.append(f"  Run: list_ingest.sh --state failed")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Query the DIL knowledge registry",
        epilog="Examples:\n"
               "  list_ingest.py --state pending_tooling\n"
               "  list_ingest.py --state failed --domain personal\n"
               "  list_ingest.py --domain work --format json\n"
               "  list_ingest.py --summary\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--state", "--status", default=None,
                        help="Filter by status (e.g., pending_tooling, failed, extracted, duplicate)")
    parser.add_argument("--domain", default=None,
                        help="Filter by domain (e.g., personal, work, triv)")
    parser.add_argument("--source-type", default=None, dest="source_type",
                        help="Filter by source type (e.g., file, url, stdin)")
    parser.add_argument("--tier", default=None, dest="content_tier",
                        help="Filter by content tier (raw, draft, curated)")
    parser.add_argument("--actor", default=None,
                        help="Filter by actor")
    parser.add_argument("--mime-type", default=None, dest="mime_type",
                        help="Filter by MIME type")
    parser.add_argument("--format", default="table", choices=["table", "json", "pipe"],
                        dest="output_format",
                        help="Output format (default: table)")
    parser.add_argument("--summary", action="store_true",
                        help="Show summary report instead of listing items")

    args = parser.parse_args()

    if args.summary:
        print(summary_report())
        return

    filters = {
        "status": args.state,
        "domain": args.domain,
        "source_type": args.source_type,
        "content_tier": args.content_tier,
        "actor": args.actor,
        "mime_type": args.mime_type,
    }
    # Remove None filters
    filters = {k: v for k, v in filters.items() if v is not None}

    results = query_registry(filters)

    if args.output_format == "json":
        print(format_json(results))
    elif args.output_format == "pipe":
        print(format_pipe(results))
    else:
        print(format_table(results))


if __name__ == "__main__":
    main()
