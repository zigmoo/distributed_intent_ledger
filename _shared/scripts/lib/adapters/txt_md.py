"""
DIL ingestion adapter for plain text and markdown files.

Reads a .txt or .md source file, produces an extraction note with
YAML frontmatter and a content preview.
"""

import os
import datetime


def _yaml_scalar(value):
    """Quote a YAML scalar value if it contains characters that need quoting."""
    if value is None:
        return "null"
    s = str(value)
    if any(c in s for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                             '?', '|', '-', '<', '>', '=', '!', '%',
                             '@', '`', '"', "'")):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    if s in ('', 'true', 'false', 'null', 'yes', 'no'):
        return f'"{s}"'
    return s


def extract(raw_path: str, manifest: dict, output_dir: str) -> dict:
    """
    Extract content from a plain-text or markdown file and write an
    extraction note.

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
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return {
            "status": "failed",
            "notes": [],
            "error": f"Failed to read {raw_path}: {exc}",
        }

    lines = content.splitlines()
    line_count = len(lines)
    word_count = len(content.split())

    preview_lines = lines[:50]
    preview = "\n".join(preview_lines)
    truncated = line_count > 50

    ingest_id = manifest.get("ingest_id", "unknown")
    raw_scope_path = manifest.get("raw_scope_path", "")
    original_source = manifest.get("original_source", "")
    title = manifest.get("title", os.path.basename(raw_path))
    date = manifest.get("date", datetime.date.today().isoformat())

    note_filename = f"{ingest_id}_extraction.md"
    note_path = os.path.join(output_dir, note_filename)

    os.makedirs(output_dir, exist_ok=True)

    frontmatter = (
        "---\n"
        f"title: {_yaml_scalar(title)}\n"
        f"date: {_yaml_scalar(date)}\n"
        f"source_type: extraction_note\n"
        f"raw_scope_path: {_yaml_scalar(raw_scope_path)}\n"
        f"original_source: {_yaml_scalar(original_source)}\n"
        f"ingest_id: {_yaml_scalar(ingest_id)}\n"
        f"content_tier: draft\n"
        "---\n"
    )

    truncation_note = " (first 50 lines)" if truncated else ""

    body = (
        f"\n## Content Preview{truncation_note}\n"
        f"\n```\n{preview}\n```\n"
        f"\n- **Word count:** {word_count}\n"
        f"- **Line count:** {line_count}\n"
        f"\n## Provenance\n"
        f"\n- **raw_scope_path:** {raw_scope_path}\n"
        f"- **original_source:** {original_source}\n"
    )

    try:
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write(body)
    except Exception as exc:
        return {
            "status": "failed",
            "notes": [],
            "error": f"Failed to write extraction note {note_path}: {exc}",
        }

    return {
        "status": "extracted",
        "notes": [note_path],
        "error": None,
    }
