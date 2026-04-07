#!/usr/bin/env python3
"""
retry_ingest.py — DIL Ingestion Pipeline Retry Tool (Core)

Retries failed/pending ingestion items, abandons hopeless ones, or force-promotes.
Vanilla Python (stdlib only). Imports helpers from ingest_source.py.

Exit codes: 0=success, 2=input validation, 4=missing prereq
Output: pipe-delimited (OK | ingest_id | action | new_state | path) or (ERR | code | message)
"""

import argparse
import datetime
import os
import subprocess
import sys
import urllib.request
import urllib.error

# Import helpers from sibling module
sys.path.insert(0, os.path.dirname(__file__))
from ingest_source import (
    BASE_DIL,
    KNOWLEDGE_REGISTRY_PATH,
    _parse_registry,
    _parse_frontmatter,
    _format_registry_row,
    update_registry_row,
    append_changelog,
    append_state_history,
    rewrite_manifest_frontmatter,
    load_adapter,
    route_adapter,
    resolve_actor,
    _yaml_value,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETRYABLE_STATES = ("pending_tooling", "failed", "failed_validation")

# Max retry counts per state (pending_tooling is unlimited)
RETRY_LIMITS = {
    "pending_tooling": None,   # unlimited
    "failed": 3,
    "failed_validation": 3,
}

CDP_VERSION_URL = "http://localhost:9222/json/version"


# ---------------------------------------------------------------------------
# Manifest discovery and parsing
# ---------------------------------------------------------------------------

def find_manifest_path(ingest_id, raw_scope_path):
    """Derive manifest path from the registry row's raw_scope_path.

    The manifest is {ingest_id}_manifest.md in the same directory as the
    raw_scope_path file.
    """
    raw_abs = os.path.join(BASE_DIL, raw_scope_path)
    manifest_dir = os.path.dirname(raw_abs)
    manifest_path = os.path.join(manifest_dir, f"{ingest_id}_manifest.md")
    if os.path.isfile(manifest_path):
        return manifest_path
    return None


def read_manifest_frontmatter(manifest_path):
    """Read and parse manifest frontmatter into a dict."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError):
        return None

    fields, _ = _parse_frontmatter(content)
    if fields is None:
        return None

    result = {}
    for k, v in fields:
        # Strip surrounding quotes if present
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        result[k] = v
    return result


def get_int_field(manifest_fields, key, default=0):
    """Get an integer field from manifest, with fallback."""
    val = manifest_fields.get(key, str(default))
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Tooling availability checks
# ---------------------------------------------------------------------------

def check_cdp_available():
    """Check if Chrome DevTools Protocol is available at localhost:9222."""
    try:
        req = urllib.request.Request(CDP_VERSION_URL, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_adapter_available(mime_type, source_type=None):
    """Check if a real (non-fallback) adapter exists for the given MIME/source type.
    Returns False if routing falls through to 'unknown' — that means
    tooling is still unavailable, not that extraction will succeed."""
    adapter_name = route_adapter(mime_type, source_type)
    if adapter_name == "unknown":
        return False  # unknown adapter is the fallback, not real tooling
    adapter_module = load_adapter(adapter_name)
    return adapter_module is not None


def check_tooling(source_type, mime_type):
    """Check if required tooling is available for a given source.

    Returns True if tooling is available, False otherwise.
    """
    if source_type == "url":
        # URL adapter needs CDP for browser-rendered sites
        if not check_adapter_available(mime_type, source_type):
            return False
        return check_cdp_available()
    else:
        return check_adapter_available(mime_type, source_type)


# ---------------------------------------------------------------------------
# Resolve output directory (same logic as ingest_source.py)
# ---------------------------------------------------------------------------

def resolve_output_dir():
    """Resolve the agent-scoped output directory for adapter extraction."""
    machine = os.environ.get("DIL_MACHINE", "")
    if not machine:
        try:
            result = subprocess.run(
                ["hostname", "-s"], capture_output=True, text=True, timeout=5
            )
            machine = result.stdout.strip().lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            machine = "shared"

    assistant = resolve_actor()
    if assistant == "unknown":
        assistant = "shared"

    output_dir = os.path.join(BASE_DIL, machine, assistant, "knowledge", "drafts")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


# ---------------------------------------------------------------------------
# Core retry operations
# ---------------------------------------------------------------------------

def do_retry(ingest_id, registry_row, manifest_path, manifest_fields, adapter_override=None):
    """Re-run adapter extraction on a single item.

    Returns (exit_code, message_string).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = resolve_actor()

    current_status = manifest_fields.get("status", "")
    extraction_status = manifest_fields.get("extraction_status", "")
    retry_count = get_int_field(manifest_fields, "retry_count", 0)
    mime_type = manifest_fields.get("mime_type", "application/octet-stream")
    source_type = manifest_fields.get("source_type", "file")

    # Determine the retryable state (use extraction_status if status is still ingested_raw)
    retry_state = extraction_status if extraction_status in RETRYABLE_STATES else current_status
    if retry_state not in RETRYABLE_STATES:
        return 2, f"ERR | 2 | {ingest_id} is in state '{current_status}' (extraction: {extraction_status}), not retryable"

    # Check retry limits
    limit = RETRY_LIMITS.get(retry_state)
    if limit is not None and retry_count >= limit:
        # Over limit — transition to failed_terminal
        return do_abandon(ingest_id, registry_row, manifest_path, manifest_fields,
                          reason=f"retry limit ({limit}) exceeded")

    # Resolve adapter
    if adapter_override:
        adapter_name = adapter_override
    else:
        adapter_name = route_adapter(mime_type, source_type)

    adapter_module = load_adapter(adapter_name)
    if adapter_module is None:
        # Try unknown fallback
        adapter_module = load_adapter("unknown")
        if adapter_module is None:
            return 4, f"ERR | 4 | No adapter available for {mime_type} (tried: {adapter_name}, unknown)"

    # Find the raw file to extract from
    raw_scope_path = registry_row.get("raw_scope_path", "")
    raw_file = os.path.join(BASE_DIL, raw_scope_path)
    if not os.path.isfile(raw_file):
        return 2, f"ERR | 2 | Raw file not found: {raw_file}"

    # Build manifest dict for adapter (merge registry row + frontmatter fields)
    manifest_dict = dict(manifest_fields)
    manifest_dict.update({
        k: registry_row[k] for k in registry_row if registry_row[k]
    })

    # Resolve output directory
    output_dir = resolve_output_dir()

    # Run extraction
    prev_status = current_status
    try:
        extract_result = adapter_module.extract(raw_file, manifest_dict, output_dir)
    except Exception as e:
        extract_result = {"status": "failed", "notes": [], "error": str(e)}

    new_extraction_status = extract_result.get("status", "failed")
    new_retry_count = retry_count + 1

    # Determine new manifest state based on extraction result
    if new_extraction_status == "extracted":
        new_status = "extracted"
        new_content_tier = "draft"
        action = "retry_extracted"
    elif new_extraction_status == "pending_tooling":
        new_status = "pending_tooling"
        new_content_tier = manifest_fields.get("content_tier", "raw")
        action = "retry_still_pending"
    else:
        new_status = "failed"
        new_content_tier = manifest_fields.get("content_tier", "raw")
        action = "retry_failed"

    # Update manifest frontmatter
    rewrite_manifest_frontmatter(manifest_path, {
        "status": new_status,
        "extraction_status": new_extraction_status,
        "content_tier": new_content_tier,
        "retry_count": new_retry_count,
        "last_retry_at": timestamp,
    })

    # Update registry row
    manifest_dict["status"] = new_status
    manifest_dict["content_tier"] = new_content_tier
    update_registry_row(manifest_dict)

    # Append state history and changelog
    cmd = f"retry_ingest:adapter:{adapter_name}"
    append_state_history(manifest_path, timestamp, actor, prev_status, new_status, cmd)
    append_changelog(ingest_id, prev_status, new_status, cmd, manifest_path, actor)

    return 0, f"OK | {ingest_id} | {action} | {new_status} | {manifest_path}"


def do_abandon(ingest_id, registry_row, manifest_path, manifest_fields, reason="abandoned"):
    """Mark an item as failed_terminal.

    Returns (exit_code, message_string).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = resolve_actor()

    prev_status = manifest_fields.get("status", "")

    # Update manifest
    rewrite_manifest_frontmatter(manifest_path, {
        "status": "failed_terminal",
        "extraction_status": "failed_terminal",
    })

    # Update registry
    manifest_dict = dict(manifest_fields)
    manifest_dict.update({
        k: registry_row[k] for k in registry_row if registry_row[k]
    })
    manifest_dict["status"] = "failed_terminal"
    update_registry_row(manifest_dict)

    # State history and changelog
    cmd = f"retry_ingest:abandon:{reason}"
    append_state_history(manifest_path, timestamp, actor, prev_status, "failed_terminal", cmd)
    append_changelog(ingest_id, prev_status, "failed_terminal", cmd, manifest_path, actor)

    return 0, f"OK | {ingest_id} | abandon | failed_terminal | {manifest_path}"


def do_force_promote(ingest_id, registry_row, manifest_path, manifest_fields):
    """Force-promote an item to curated/promoted_shared.

    Returns (exit_code, message_string).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = resolve_actor()

    prev_status = manifest_fields.get("status", "")

    # Update manifest
    rewrite_manifest_frontmatter(manifest_path, {
        "status": "promoted_shared",
        "content_tier": "curated",
    })

    # Update registry
    manifest_dict = dict(manifest_fields)
    manifest_dict.update({
        k: registry_row[k] for k in registry_row if registry_row[k]
    })
    manifest_dict["status"] = "promoted_shared"
    manifest_dict["content_tier"] = "curated"
    update_registry_row(manifest_dict)

    # State history and changelog
    cmd = "retry_ingest:force_promote"
    append_state_history(manifest_path, timestamp, actor, prev_status, "promoted_shared", cmd)
    append_changelog(ingest_id, prev_status, "promoted_shared", cmd, manifest_path, actor)

    return 0, f"OK | {ingest_id} | force_promote | promoted_shared | {manifest_path}"


# ---------------------------------------------------------------------------
# Batch operations (--state filtering)
# ---------------------------------------------------------------------------

def find_items_by_state(target_state, domain_filter=None):
    """Find registry rows matching a target state (and optional domain).

    Checks both the registry status column and manifest extraction_status.
    Returns list of (ingest_id, registry_row) tuples.
    """
    _, rows = _parse_registry()
    matches = []
    for _, row in rows:
        # Match on registry status column
        status_match = row.get("status", "") == target_state
        if not status_match:
            # Also check if the extraction_status in the manifest matches
            # (items stuck in ingested_raw with extraction_status=pending_tooling)
            # We'll load manifests later; for now, include ingested_raw items too
            if target_state in ("pending_tooling", "failed", "failed_validation"):
                if row.get("status", "") == "ingested_raw":
                    status_match = True  # candidate, will verify via manifest

        if not status_match:
            continue

        if domain_filter and row.get("domain", "") != domain_filter:
            continue

        matches.append((row["ingest_id"], row))

    return matches


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DIL Ingestion Pipeline Retry Tool",
        epilog="Examples:\n"
               "  retry_ingest.py KI-20260401_120000_1234              # retry single\n"
               "  retry_ingest.py --state pending_tooling              # retry all pending\n"
               "  retry_ingest.py --state failed --domain personal     # retry failed in domain\n"
               "  retry_ingest.py KI-20260401_120000_1234 --abandon    # mark terminal\n"
               "  retry_ingest.py KI-20260401_120000_1234 --force-promote --yes\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("ingest_id", nargs="?", default=None,
                        help="Ingest ID to retry (omit for batch --state mode)")
    parser.add_argument("--state", default=None,
                        choices=list(RETRYABLE_STATES),
                        help="Retry all items in this state")
    parser.add_argument("--domain", default=None,
                        help="Filter by domain (used with --state)")
    parser.add_argument("--check-tooling", action="store_true",
                        help="Only retry items where tooling is now available")
    parser.add_argument("--abandon", action="store_true",
                        help="Mark item as failed_terminal")
    parser.add_argument("--force-promote", action="store_true",
                        help="Skip validation and promote to curated (requires --yes)")
    parser.add_argument("--yes", action="store_true",
                        help="Confirm destructive operations (required for --force-promote)")
    parser.add_argument("--adapter", default=None,
                        help="Override adapter selection (e.g., txt_md, url)")

    args = parser.parse_args()

    # Validate argument combinations
    if not args.ingest_id and not args.state:
        print("ERR | 2 | Must specify either <ingest_id> or --state")
        sys.exit(2)

    if args.force_promote and not args.yes:
        print("ERR | 2 | --force-promote requires --yes flag")
        sys.exit(2)

    if args.abandon and args.force_promote:
        print("ERR | 2 | Cannot use --abandon and --force-promote together")
        sys.exit(2)

    if args.state and (args.abandon or args.force_promote):
        print("ERR | 2 | --abandon and --force-promote require a specific ingest_id")
        sys.exit(2)

    # --- Single item mode ---
    if args.ingest_id:
        ingest_id = args.ingest_id
        _, rows = _parse_registry()

        # Find the registry row
        registry_row = None
        for _, row in rows:
            if row["ingest_id"] == ingest_id:
                registry_row = row
                break

        if registry_row is None:
            print(f"ERR | 2 | Ingest ID not found in registry: {ingest_id}")
            sys.exit(2)

        # Find and read manifest
        manifest_path = find_manifest_path(ingest_id, registry_row["raw_scope_path"])
        if manifest_path is None:
            print(f"ERR | 2 | Manifest file not found for {ingest_id}")
            sys.exit(2)

        manifest_fields = read_manifest_frontmatter(manifest_path)
        if manifest_fields is None:
            print(f"ERR | 2 | Cannot parse manifest frontmatter: {manifest_path}")
            sys.exit(2)

        # Dispatch to action
        if args.abandon:
            exit_code, msg = do_abandon(ingest_id, registry_row, manifest_path, manifest_fields)
        elif args.force_promote:
            exit_code, msg = do_force_promote(ingest_id, registry_row, manifest_path, manifest_fields)
        else:
            if args.check_tooling:
                source_type = manifest_fields.get("source_type", "file")
                mime_type = manifest_fields.get("mime_type", "application/octet-stream")
                if not check_tooling(source_type, mime_type):
                    print(f"ERR | 4 | Tooling not available for {ingest_id} (source_type={source_type}, mime={mime_type})")
                    sys.exit(4)
            exit_code, msg = do_retry(ingest_id, registry_row, manifest_path, manifest_fields,
                                      adapter_override=args.adapter)

        print(msg)
        sys.exit(exit_code)

    # --- Batch mode (--state) ---
    candidates = find_items_by_state(args.state, domain_filter=args.domain)

    if not candidates:
        print(f"OK | - | no_matches | {args.state} | -")
        sys.exit(0)

    results = []
    exit_code = 0

    for ingest_id, registry_row in candidates:
        manifest_path = find_manifest_path(ingest_id, registry_row["raw_scope_path"])
        if manifest_path is None:
            results.append(f"ERR | 2 | Manifest not found for {ingest_id}")
            continue

        manifest_fields = read_manifest_frontmatter(manifest_path)
        if manifest_fields is None:
            results.append(f"ERR | 2 | Cannot parse manifest: {manifest_path}")
            continue

        # Verify the extraction_status actually matches the target state
        extraction_status = manifest_fields.get("extraction_status", "")
        manifest_status = manifest_fields.get("status", "")
        if extraction_status != args.state and manifest_status != args.state:
            continue  # skip — registry was a candidate but manifest doesn't match

        # Tooling check
        if args.check_tooling:
            source_type = manifest_fields.get("source_type", "file")
            mime_type = manifest_fields.get("mime_type", "application/octet-stream")
            if not check_tooling(source_type, mime_type):
                continue  # skip — tooling not available

        code, msg = do_retry(ingest_id, registry_row, manifest_path, manifest_fields,
                             adapter_override=args.adapter)
        results.append(msg)
        if code != 0:
            exit_code = code

    if not results:
        print(f"OK | - | no_actionable | {args.state} | -")
    else:
        for r in results:
            print(r)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
