"""
Fallback adapter for the DIL ingestion pipeline.

Handles any file type that lacks a dedicated adapter by creating a pointer
note that signals the file exists but real extraction requires tooling
that is not yet available.
"""

import os
from datetime import datetime, timezone


def extract(raw_path: str, manifest: dict, output_dir: str) -> dict:
    """
    Args:
        raw_path:   absolute path to the raw file (read-only, never modify)
        manifest:   the full frontmatter dict (all fields populated)
        output_dir: directory where extraction notes should be written

    Returns:
        {
            "status": "extracted" | "pending_tooling" | "failed",
            "notes": ["path/to/note1.md", ...],
            "error": None | "human-readable reason"
        }
    """
    ingest_id = manifest["ingest_id"]
    filename = os.path.basename(raw_path)
    note_filename = f"{ingest_id}_pointer.md"
    note_path = os.path.join(output_dir, note_filename)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    mime_type = manifest.get("mime_type", "unknown")
    file_size = manifest.get("size_bytes", "unknown")
    sha256 = manifest.get("sha256", "unknown")
    raw_scope_path = manifest.get("raw_scope_path", "unknown")
    original_source = manifest.get("original_source", "unknown")

    note_content = f"""---
title: "{filename} — pointer note"
date: {date_str}
source_type: pointer_note
raw_scope_path: "{raw_scope_path}"
original_source: "{original_source}"
ingest_id: "{ingest_id}"
content_tier: draft
extraction_status: pending_tooling
---

This file type does not have a dedicated adapter yet. Real extraction
requires tooling that is not currently available.

- **MIME type:** `{mime_type}`
- **File size:** {file_size}
- **SHA-256:** `{sha256}`

## Provenance

- **raw_scope_path:** `{raw_scope_path}`
- **original_source:** `{original_source}`
"""

    os.makedirs(output_dir, exist_ok=True)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(note_content)

    return {
        "status": "pending_tooling",
        "notes": [note_path],
        "error": None,
    }
