#!/usr/bin/env python3
"""
ingest_source.py — DIL Universal Inbox Ingestion Pipeline (Core)

Vanilla Python (stdlib only). No pip install required.
Accepts file path, URL, or stdin. Auto-detects source type, MIME, size, hash.

Exit codes: 0=success, 2=input validation, 3=duplicate, 4=missing prereq, 5=post-validation failure
Output: pipe-delimited (OK | ingest_id | domain | status | path) or (ERR | code | message)
"""

import argparse
import datetime
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from resolve_base import resolve_dil_base

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIL = resolve_dil_base(
    script_dir=Path(__file__).resolve().parent,
    explicit=(os.environ.get("BASE_DIL") or os.environ.get("DIL_BASE") or os.environ.get("CLAWVAULT_BASE")),
)
DOMAIN_REGISTRY_PATH = os.path.join(BASE_DIL, "_shared/_meta/domain_registry.json")
KNOWLEDGE_REGISTRY_PATH = os.path.join(BASE_DIL, "_shared/_meta/knowledge_registry_active.md")
UNIFIED_CHANGELOG_PATH = os.path.join(BASE_DIL, "_shared/knowledge/_meta/change_log.md")

SENSITIVITY_LEVELS = ("public", "private", "internal", "restricted")

# MIME -> adapter module name
ADAPTER_MAP = {
    "text/plain": "txt_md",
    "text/markdown": "txt_md",
    "text/x-markdown": "txt_md",
    "text/csv": "txt_md",
    "text/tab-separated-values": "txt_md",
    "application/json": "txt_md",
    "application/xml": "txt_md",
    "text/xml": "txt_md",
    "text/html": "txt_md",
    "text/x-python": "txt_md",
    "text/x-script.python": "txt_md",
    "text/x-shellscript": "txt_md",
    "text/x-c": "txt_md",
    "text/x-c++src": "txt_md",
    "text/x-java-source": "txt_md",
    "text/javascript": "txt_md",
    "application/javascript": "txt_md",
    "application/x-yaml": "txt_md",
    "text/yaml": "txt_md",
    "application/pdf": "pdf",
    "_default": "unknown",
}

# Source type overrides (checked before MIME routing)
SOURCE_TYPE_ADAPTER_MAP = {
    "url": "url",
}


# ---------------------------------------------------------------------------
# YAML frontmatter helpers (no pyyaml needed)
# ---------------------------------------------------------------------------

def _yaml_value(v):
    """Format a Python value as a YAML scalar."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Quote if contains special chars
    if any(c in s for c in (":", "#", "[", "]", "{", "}", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "\n")):
        return '"%s"' % s.replace('"', '\\"')
    return s


def write_frontmatter_md(path, fields, body=""):
    """Write a .md file with YAML frontmatter and body content."""
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {_yaml_value(v)}")
    lines.append("---")
    lines.append("")
    if body:
        lines.append(body)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Domain registry
# ---------------------------------------------------------------------------

def load_domain_registry():
    with open(DOMAIN_REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_domain_config(registry, domain_name):
    domains = registry.get("domains", {})
    if domain_name not in domains:
        return None
    return domains[domain_name]


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def is_url(source):
    parsed = urllib.parse.urlparse(source)
    return parsed.scheme in ("http", "https", "ftp", "ftps")


def detect_mime(file_path):
    """Detect MIME type using mimetypes + file command fallback."""
    mime, _ = mimetypes.guess_type(file_path)
    if mime:
        return mime
    # Fallback to file command
    try:
        result = subprocess.run(
            ["file", "--mime-type", "-b", file_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "application/octet-stream"


def compute_sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_actor():
    for var in ("ACTOR", "ASSISTANT_ID", "AGENT_NAME", "AGENT_ID"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    # Try identify_agent.sh
    script = os.path.join(BASE_DIL, "_shared/scripts/identify_agent.sh")
    if os.path.isfile(script) and os.access(script, os.X_OK):
        try:
            result = subprocess.run([script], capture_output=True, text=True, timeout=5)
            resolved = result.stdout.strip()
            if resolved and resolved != "UNRESOLVED":
                return resolved
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return "unknown"


# ---------------------------------------------------------------------------
# Ingest ID allocation
# ---------------------------------------------------------------------------

def allocate_ingest_id():
    """Generate a unique ingest ID using timestamp + short hash."""
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    # Add microseconds for uniqueness
    micro = now.strftime("%f")[:4]
    return f"KI-{ts}_{micro}"


# ---------------------------------------------------------------------------
# Registry table parser (column-aware)
# ---------------------------------------------------------------------------

# Column indices in the registry table (0-based, after splitting on |)
# Split produces: ['', col0, col1, ..., ''] so actual data starts at index 1
_REG_COLS = {
    "ingest_id": 1, "domain": 2, "source_type": 3, "title": 4,
    "raw_scope_path": 5, "original_source": 6, "sensitivity": 7,
    "visibility": 8, "access_policy": 9, "status": 10, "content_tier": 11,
    "duplicate_of": 12, "sha256": 13, "mime_type": 14, "size_bytes": 15,
    "ingested_at": 16, "actor": 17,
}


def _escape_pipe(value):
    """Escape pipe characters in cell values to prevent column misalignment."""
    return str(value).replace("|", "\\|")


def _unescape_pipe(value):
    """Unescape pipe characters in cell values."""
    return value.replace("\\|", "|")


def _parse_registry_row(line):
    """Parse a registry table row into a dict. Returns None for non-data rows."""
    stripped = line.strip()
    if not stripped or not stripped.startswith("|"):
        return None
    # Split on unescaped pipes: use regex to split on | not preceded by \
    raw_cols = re.split(r'(?<!\\)\|', stripped)
    cols = [_unescape_pipe(c.strip()) for c in raw_cols]
    # Skip header and separator rows
    if len(cols) < 18:
        return None
    if cols[1] == "ingest_id" or stripped.startswith("|---"):
        return None
    return {name: cols[idx] if idx < len(cols) else "" for name, idx in _REG_COLS.items()}


def _parse_registry():
    """Parse the entire registry into a list of (line_index, row_dict) tuples."""
    if not os.path.isfile(KNOWLEDGE_REGISTRY_PATH):
        return [], []
    try:
        with open(KNOWLEDGE_REGISTRY_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return [], []
    rows = []
    for i, line in enumerate(lines):
        parsed = _parse_registry_row(line)
        if parsed is not None:
            rows.append((i, parsed))
    return lines, rows


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------

def check_duplicate(sha256_hash, domain):
    """Check if sha256 already exists in the registry for the given domain.
    Dedup is domain-scoped to preserve domain boundaries.
    Returns (canonical_ingest_id, canonical_raw_scope_path) or (None, None)."""
    _, rows = _parse_registry()
    for _, row in rows:
        if row["sha256"] == sha256_hash and row["domain"] == domain and not row["duplicate_of"]:
            return row["ingest_id"], row["raw_scope_path"]
    return None, None


# ---------------------------------------------------------------------------
# Registry and changelog writes
# ---------------------------------------------------------------------------

def _format_registry_row(manifest):
    """Format a manifest dict as a registry table row. Escapes pipe chars in values."""
    cols = [
        manifest.get("ingest_id", ""),
        manifest.get("domain", ""),
        manifest.get("source_type", ""),
        manifest.get("title", ""),
        manifest.get("raw_scope_path", ""),
        manifest.get("original_source", ""),
        manifest.get("sensitivity", ""),
        manifest.get("visibility", ""),
        manifest.get("access_policy", ""),
        manifest.get("status", ""),
        manifest.get("content_tier", ""),
        manifest.get("duplicate_of", ""),
        manifest.get("sha256", ""),
        manifest.get("mime_type", ""),
        str(manifest.get("size_bytes", "")),
        manifest.get("ingested_at", ""),
        manifest.get("actor", ""),
    ]
    return "| " + " | ".join(_escape_pipe(c) for c in cols) + " |"


def append_registry_row(manifest):
    """Append a row to knowledge_registry_active.md."""
    row = _format_registry_row(manifest)
    with open(KNOWLEDGE_REGISTRY_PATH, "a", encoding="utf-8") as f:
        f.write(row + "\n")


def update_registry_row(manifest):
    """Update an existing registry row in-place by ingest_id (column-aware)."""
    ingest_id = manifest.get("ingest_id", "")
    if not ingest_id:
        return
    new_row = _format_registry_row(manifest)
    lines, rows = _parse_registry()
    if not lines:
        return
    updated = False
    for line_idx, row in rows:
        if row["ingest_id"] == ingest_id:
            lines[line_idx] = new_row + "\n"
            updated = True
            break
    if updated:
        with open(KNOWLEDGE_REGISTRY_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)


def append_changelog(ingest_id, previous_state, new_state, command, manifest_path, actor):
    """Append a row to the unified changelog."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = f"| {now} | {actor} | {ingest_id} | {previous_state} | {new_state} | {command} | {manifest_path} |"
    with open(UNIFIED_CHANGELOG_PATH, "a", encoding="utf-8") as f:
        f.write(row + "\n")


def _parse_frontmatter(content):
    """Parse YAML frontmatter from file content.
    Returns (fields_as_ordered_list_of_tuples, body_text) or (None, None) on failure.
    Fields are returned as [(key, raw_value_string), ...] to preserve order and formatting."""
    if not content.startswith("---"):
        return None, None

    # Find the closing --- by scanning lines, not substring matching.
    # This avoids false matches on --- in the body (e.g., markdown horizontal rules).
    lines = content.split("\n")
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close_idx = i
            break

    if close_idx is None:
        return None, None

    # Parse frontmatter fields — handle first colon as delimiter only.
    # Values may contain colons (URLs, timestamps, etc.)
    fields = []
    for line in lines[1:close_idx]:
        if not line.strip():
            continue
        colon_pos = line.find(":")
        if colon_pos == -1:
            continue
        key = line[:colon_pos].strip()
        val = line[colon_pos + 1:].strip()
        fields.append((key, val))

    # Body is everything after the closing ---
    body = "\n".join(lines[close_idx + 1:])

    return fields, body


def rewrite_manifest_frontmatter(manifest_path, updated_fields):
    """Rewrite YAML frontmatter fields in a manifest file, preserving the body.
    Uses line-scanning parser that handles values with colons and avoids
    false --- matches in body content."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError):
        return

    fields, body = _parse_frontmatter(content)
    if fields is None:
        return

    # Build a key->index map for existing fields
    key_indices = {}
    for i, (k, _) in enumerate(fields):
        if k not in key_indices:
            key_indices[k] = i

    # Update existing fields or append new ones
    for k, v in updated_fields.items():
        formatted = _yaml_value(v)
        if k in key_indices:
            fields[key_indices[k]] = (k, formatted)
        else:
            fields.append((k, formatted))

    # Rewrite
    out_lines = ["---"]
    for k, v in fields:
        out_lines.append(f"{k}: {v}")
    out_lines.append("---")
    out_lines.append(body)

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))


def append_state_history(manifest_path, timestamp, actor, previous_state, new_state, command):
    """Append to the ## State History section of a manifest file."""
    entry = f"| {timestamp} | {actor} | {previous_state} | {new_state} | {command} |"
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


# ---------------------------------------------------------------------------
# Adapter loading and dispatch
# ---------------------------------------------------------------------------

def load_adapter(adapter_name):
    """Load an adapter module from the adapters directory."""
    adapters_dir = os.path.join(os.path.dirname(__file__), "adapters")
    adapter_path = os.path.join(adapters_dir, f"{adapter_name}.py")
    if not os.path.isfile(adapter_path):
        return None

    import importlib.util
    spec = importlib.util.spec_from_file_location(f"adapters.{adapter_name}", adapter_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route_adapter(mime_type, source_type=None):
    """Return adapter module name for a given MIME type and source type.
    Source type overrides take precedence over MIME routing."""
    if source_type and source_type in SOURCE_TYPE_ADAPTER_MAP:
        return SOURCE_TYPE_ADAPTER_MAP[source_type]
    if mime_type in ADAPTER_MAP:
        return ADAPTER_MAP[mime_type]
    return ADAPTER_MAP["_default"]


# ---------------------------------------------------------------------------
# Visibility / access policy derivation
# ---------------------------------------------------------------------------

def derive_visibility(sensitivity):
    """Derive visibility from sensitivity level."""
    return {
        "public": "public",
        "private": "internal",
        "internal": "domain-gated",
        "restricted": "domain-gated",
    }.get(sensitivity, "internal")


def derive_access_policy(domain, sensitivity):
    """Derive access policy from domain + sensitivity."""
    if sensitivity == "public":
        return "open"
    if sensitivity == "restricted":
        return f"{domain}-restricted"
    return f"{domain}-default"


# ---------------------------------------------------------------------------
# Source acquisition
# ---------------------------------------------------------------------------

def acquire_source(source, workdir):
    """Acquire source content into a local file. Returns (local_path, original_source, source_type)."""
    if source == "-":
        # Stdin
        tmp = tempfile.NamedTemporaryFile(dir=workdir, delete=False, prefix="stdin_")
        with tmp:
            shutil.copyfileobj(sys.stdin.buffer, tmp)
        return tmp.name, "stdin", "stdin"

    if is_url(source):
        # URL fetch
        parsed = urllib.parse.urlparse(source)
        filename = os.path.basename(parsed.path) or "downloaded"
        local_path = os.path.join(workdir, filename)
        try:
            urllib.request.urlretrieve(source, local_path)
        except Exception as e:
            return None, source, f"url_fetch_failed: {e}"
        return local_path, source, "url"

    # Local file path
    source = os.path.expanduser(source)
    if not os.path.isfile(source):
        return None, source, f"file_not_found: {source}"
    return source, source, "file"


# ---------------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------------

def ingest(source, domain="personal", sensitivity_override=None, source_type_override=None):
    """Run the ingestion pipeline. Returns (exit_code, message)."""

    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    actor = resolve_actor()

    # Load domain config
    try:
        registry = load_domain_registry()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return 4, f"ERR | 4 | Cannot load domain registry: {e}"

    domain_config = get_domain_config(registry, domain)
    if domain_config is None:
        return 2, f"ERR | 2 | Unknown domain: {domain}"

    # Resolve sensitivity
    sensitivity = sensitivity_override or domain_config.get("default_sensitivity", "private")
    if sensitivity not in SENSITIVITY_LEVELS:
        return 2, f"ERR | 2 | Invalid sensitivity: {sensitivity}"

    # Acquire source
    workdir = tempfile.mkdtemp(prefix="dil_ingest_")
    try:
        local_path, original_source, detected_type = acquire_source(source, workdir)
        if local_path is None:
            return 2, f"ERR | 2 | {detected_type}"

        source_type = source_type_override or detected_type

        # Detect properties
        mime_type = detect_mime(local_path)
        size_bytes = os.path.getsize(local_path)
        sha256 = compute_sha256(local_path)
        extension = os.path.splitext(local_path)[1].lstrip(".")
        title = os.path.basename(local_path)

        # Allocate ingest ID
        ingest_id = allocate_ingest_id()

        # Dedup check (domain-scoped to preserve domain boundaries)
        canonical_id, canonical_raw_path = check_duplicate(sha256, domain)
        duplicate_of = canonical_id or ""
        is_duplicate = bool(canonical_id)

        # Determine raw storage path
        raw_subdir = {"url": "urls", "file": "files", "stdin": "files"}.get(source_type, "files")
        raw_dir = os.path.join(BASE_DIL, f"_shared/domains/{domain}/knowledge/raw/{raw_subdir}")
        os.makedirs(raw_dir, exist_ok=True)

        if is_duplicate:
            # Point to the canonical item's raw file, not a phantom new path
            raw_scope_path = canonical_raw_path
            raw_dest = os.path.join(BASE_DIL, canonical_raw_path)
        else:
            raw_dest = os.path.join(raw_dir, f"{ingest_id}_{title}")
            raw_scope_path = os.path.relpath(raw_dest, BASE_DIL)

        # Build manifest
        visibility = derive_visibility(sensitivity)
        access_policy = derive_access_policy(domain, sensitivity)

        manifest = {
            "ingest_id": ingest_id,
            "title": title,
            "date": now.strftime("%Y-%m-%d"),
            "source_type": source_type,
            "source_uri_or_path": original_source,
            "raw_scope_path": raw_scope_path,
            "original_source": original_source,
            "mime_type": mime_type,
            "extension": extension,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "ingested_at": timestamp,
            "actor": actor,
            "status": "duplicate" if is_duplicate else "received",
            "extraction_status": "not_started",
            "sensitivity": sensitivity,
            "visibility": visibility,
            "access_policy": access_policy,
            "content_tier": "raw",
            "duplicate_of": duplicate_of,
            "domain": domain,
            "category": "knowledge",
            "memoryType": "manifest",
            "priority": "normal",
            "tags": ["knowledge", "ingestion", domain],
            "updated": now.strftime("%Y-%m-%d"),
            "source": "ingest_source",
            "project": "dil-ingestion-pipe",
            "owner": actor,
            "due": "",
            "machine": "shared",
            "assistant": "shared",
        }

        # Write to global registry immediately (Tier 1)
        append_registry_row(manifest)

        if is_duplicate:
            # Record the event but don't copy the file again
            manifest_dir = os.path.join(BASE_DIL, f"_shared/domains/{domain}/knowledge/raw/{raw_subdir}")
            manifest_path = os.path.join(manifest_dir, f"{ingest_id}_manifest.md")

            # Build manifest body
            body = f"# {title} (Duplicate)\n\n"
            body += f"This item is a duplicate of [[{canonical_id}]].\n\n"
            body += f"## Provenance\n\n"
            body += f"- raw_scope_path: {raw_scope_path}\n"
            body += f"- original_source: {original_source}\n"
            body += f"- duplicate_of: {canonical_id}\n\n"
            body += "## State History\n\n"
            body += "| timestamp | actor | previous_state | new_state | command |\n"
            body += "|---|---|---|---|---|\n"
            body += f"| {timestamp} | {actor} | - | duplicate | ingest_source |\n"

            write_frontmatter_md(manifest_path, manifest, body)
            append_changelog(ingest_id, "-", "duplicate", "ingest_source", manifest_path, actor)

            return 3, f"OK | {ingest_id} | {domain} | duplicate | {manifest_path}"

        # Copy raw file to domain-scoped storage (Tier 2)
        if local_path != raw_dest:
            shutil.copy2(local_path, raw_dest)

        # Update status
        manifest["status"] = "ingested_raw"

        # Write manifest file
        manifest_path = os.path.join(raw_dir, f"{ingest_id}_manifest.md")

        body = f"# {title}\n\n"
        body += f"## Summary\n\n"
        body += f"- Ingested from: {original_source}\n"
        body += f"- MIME type: {mime_type}\n"
        body += f"- Size: {size_bytes} bytes\n"
        body += f"- SHA256: {sha256}\n\n"
        body += f"## Provenance\n\n"
        body += f"- raw_scope_path: {raw_scope_path}\n"
        body += f"- original_source: {original_source}\n\n"
        body += "## State History\n\n"
        body += "| timestamp | actor | previous_state | new_state | command |\n"
        body += "|---|---|---|---|---|\n"
        body += f"| {timestamp} | {actor} | received | ingested_raw | ingest_source |\n"

        write_frontmatter_md(manifest_path, manifest, body)

        # Changelog entries
        append_changelog(ingest_id, "-", "received", "ingest_source", manifest_path, actor)
        append_changelog(ingest_id, "received", "ingested_raw", "ingest_source", manifest_path, actor)

        # --- Adapter extraction ---
        adapter_name = route_adapter(mime_type, source_type)
        adapter_module = load_adapter(adapter_name)

        if adapter_module is None:
            # No adapter available — use unknown fallback
            adapter_module = load_adapter("unknown")

        if adapter_module is not None:
            # Resolve output_dir for extraction (agent-scoped)
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

            try:
                extract_result = adapter_module.extract(raw_dest, manifest, output_dir)
            except Exception as e:
                extract_result = {"status": "failed", "notes": [], "error": str(e)}

            extraction_status = extract_result.get("status", "failed")
            extraction_notes = extract_result.get("notes", [])

            if extraction_status == "extracted":
                manifest["status"] = "extracted"
                manifest["extraction_status"] = "extracted"
                manifest["content_tier"] = "draft"
                append_state_history(manifest_path, timestamp, actor, "ingested_raw", "extracted", "adapter:" + adapter_name)
                append_changelog(ingest_id, "ingested_raw", "extracted", "adapter:" + adapter_name, manifest_path, actor)
            elif extraction_status == "pending_tooling":
                manifest["status"] = "pending_tooling"
                manifest["extraction_status"] = "pending_tooling"
                append_state_history(manifest_path, timestamp, actor, "ingested_raw", "pending_tooling", "adapter:" + adapter_name + ":pending_tooling")
                append_changelog(ingest_id, "ingested_raw", "pending_tooling", "adapter:" + adapter_name + ":pending_tooling", manifest_path, actor)
            else:
                manifest["status"] = "failed"
                manifest["extraction_status"] = "failed"
                error_msg = extract_result.get("error", "unknown error")
                append_state_history(manifest_path, timestamp, actor, "ingested_raw", "failed", f"adapter:{adapter_name}:failed:{error_msg}")
                append_changelog(ingest_id, "ingested_raw", "failed", f"adapter:{adapter_name}:failed", manifest_path, actor)

            # Fix #1: Update registry row to reflect final state
            update_registry_row(manifest)
            # Fix #2: Rewrite manifest frontmatter to reflect final state
            rewrite_manifest_frontmatter(manifest_path, {
                "status": manifest["status"],
                "extraction_status": manifest["extraction_status"],
                "content_tier": manifest["content_tier"],
            })

        return 0, f"OK | {ingest_id} | {domain} | {manifest.get('status', 'ingested_raw')} | {manifest_path}"

    finally:
        # Clean up temp workdir
        if os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DIL Universal Inbox Ingestion Pipeline",
        epilog="Examples:\n"
               "  ingest_source.py /path/to/file.pdf\n"
               "  ingest_source.py https://example.com/doc.html\n"
               "  cat file | ingest_source.py -\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", help="File path, URL, or - for stdin")
    parser.add_argument("--domain", default="personal", help="Target domain (default: personal)")
    parser.add_argument("--sensitivity", default=None, choices=SENSITIVITY_LEVELS,
                        help="Override domain default sensitivity")
    parser.add_argument("--source-type", default=None, dest="source_type",
                        help="Override auto-detected source type")

    args = parser.parse_args()

    exit_code, message = ingest(
        source=args.source,
        domain=args.domain,
        sensitivity_override=args.sensitivity,
        source_type_override=args.source_type,
    )

    print(message)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
