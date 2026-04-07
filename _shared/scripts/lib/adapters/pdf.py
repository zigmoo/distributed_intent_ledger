"""
DIL ingestion adapter for PDF files.

Two-stage extraction:
1. pdftotext (fast, handles text-based PDFs)
2. If text extraction yields little/no content: pdftoppm + tesseract OCR (for scanned PDFs)

Requires system packages (not pip):
- poppler-utils (pdftotext, pdftoppm)
- tesseract (tesseract-ocr)

All calls via subprocess — vanilla Python stdlib only.
"""

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

# Minimum extracted text length to consider pdftotext successful
MIN_TEXT_LENGTH = 50

# Maximum pages to OCR (prevents runaway on huge scanned docs)
MAX_OCR_PAGES = 50


def check_tooling():
    """Check if required system tools are available for PDF extraction.
    Called by retry_ingest --check-tooling to verify host dependencies.
    Requires pdftotext (text PDFs) and pdftoppm + tesseract (scanned PDFs).
    Returns True only when the full toolchain is present, since we cannot
    distinguish text vs scanned PDFs at triage time."""
    has_pdftotext = shutil.which("pdftotext") is not None
    has_ocr = shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None
    return has_pdftotext and has_ocr


def _yaml_scalar(value):
    if value is None:
        return "null"
    s = str(value)
    if any(c in s for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                             '?', '|', '-', '<', '>', '=', '!', '%',
                             '@', '`', '"', "'")):
        return f'"{s.replace(chr(34), chr(92)+chr(34))}"'
    if s in ('', 'true', 'false', 'null', 'yes', 'no'):
        return f'"{s}"'
    return s


def _check_tool(name):
    """Check if a system tool is available."""
    return shutil.which(name) is not None


def _run(cmd, timeout=60):
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", -1
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", -1


def _get_page_count(raw_path):
    """Get PDF page count using pdfinfo or pdftotext."""
    stdout, _, rc = _run(["pdfinfo", raw_path], timeout=10)
    if rc == 0:
        for line in stdout.split("\n"):
            if line.startswith("Pages:"):
                try:
                    return int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
    # Fallback: try pdftotext and count form feeds
    stdout, _, rc = _run(["pdftotext", "-q", raw_path, "-"], timeout=30)
    if rc == 0:
        return stdout.count("\f") + 1
    return 0


def _extract_text_pdf(raw_path):
    """Extract text using pdftotext. Returns (text, method) or (None, error)."""
    stdout, stderr, rc = _run(["pdftotext", "-q", "-layout", raw_path, "-"], timeout=30)
    if rc != 0:
        return None, f"pdftotext failed: {stderr.strip()}"

    text = stdout.strip()
    if len(text) < MIN_TEXT_LENGTH:
        return None, "pdftotext returned insufficient text (likely scanned PDF)"

    return text, "pdftotext"


def _extract_ocr_pdf(raw_path, page_count):
    """Extract text via OCR: pdftoppm → tesseract. Returns (text, method) or (None, error)."""
    if not _check_tool("pdftoppm"):
        return None, "pdftoppm not available (install poppler-utils)"
    if not _check_tool("tesseract"):
        return None, "tesseract not available (install tesseract-ocr)"

    ocr_pages = min(page_count, MAX_OCR_PAGES)
    workdir = tempfile.mkdtemp(prefix="dil_pdf_ocr_")

    try:
        # Convert PDF pages to images
        _, stderr, rc = _run(
            ["pdftoppm", "-png", "-r", "300", "-l", str(ocr_pages), raw_path,
             os.path.join(workdir, "page")],
            timeout=120
        )
        if rc != 0:
            return None, f"pdftoppm failed: {stderr.strip()}"

        # Collect page images in order
        images = sorted([
            os.path.join(workdir, f) for f in os.listdir(workdir)
            if f.endswith(".png")
        ])

        if not images:
            return None, "pdftoppm produced no images"

        # OCR each page
        all_text = []
        for img_path in images:
            stdout, stderr, rc = _run(
                ["tesseract", img_path, "stdout", "-l", "eng", "--psm", "1"],
                timeout=30
            )
            if rc == 0 and stdout.strip():
                all_text.append(stdout.strip())

        if not all_text:
            return None, "tesseract produced no text from any page"

        text = "\n\n---\n\n".join(all_text)
        method = f"pdftoppm+tesseract (OCR, {len(images)} pages)"
        return text, method

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def extract(raw_path, manifest, output_dir):
    """
    Extract content from a PDF file.

    Strategy:
    1. Try pdftotext (fast, text-based PDFs)
    2. If insufficient text: fall back to pdftoppm + tesseract OCR
    3. If neither tool available: return pending_tooling

    Args:
        raw_path:   absolute path to the raw PDF file
        manifest:   the full manifest dict
        output_dir: directory for extraction notes

    Returns:
        {"status": "extracted"|"pending_tooling"|"failed", "notes": [...], "error": ...}
    """
    ingest_id = manifest.get("ingest_id", "unknown")
    raw_scope_path = manifest.get("raw_scope_path", "")
    original_source = manifest.get("original_source", "")
    title = manifest.get("title", os.path.basename(raw_path))

    # Check basic tooling
    if not _check_tool("pdftotext"):
        return {
            "status": "pending_tooling",
            "notes": [],
            "error": "pdftotext not available (install poppler-utils)",
        }

    # Get page count
    page_count = _get_page_count(raw_path)

    # Stage 1: try pdftotext
    text, method = _extract_text_pdf(raw_path)

    # Stage 2: if pdftotext failed, try OCR
    if text is None:
        if page_count == 0:
            return {
                "status": "failed",
                "notes": [],
                "error": f"Cannot determine PDF page count: {method}",
            }
        text, method = _extract_ocr_pdf(raw_path, page_count)

    # If both stages failed
    if text is None:
        if "not available" in (method or ""):
            return {"status": "pending_tooling", "notes": [], "error": method}
        return {"status": "failed", "notes": [], "error": method}

    # Build extraction note
    lines = text.splitlines()
    line_count = len(lines)
    word_count = len(text.split())

    # Preview: first 100 lines or all
    preview_lines = lines[:100]
    preview = "\n".join(preview_lines)
    truncated = line_count > 100

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_filename = f"{ingest_id}_extraction.md"
    note_path = os.path.join(output_dir, note_filename)
    os.makedirs(output_dir, exist_ok=True)

    truncation_note = " (first 100 lines)" if truncated else ""

    frontmatter = (
        "---\n"
        f"title: {_yaml_scalar(title)}\n"
        f"date: {date_str}\n"
        f"source_type: extraction_note\n"
        f"raw_scope_path: {_yaml_scalar(raw_scope_path)}\n"
        f"original_source: {_yaml_scalar(original_source)}\n"
        f"ingest_id: {_yaml_scalar(ingest_id)}\n"
        f"content_tier: draft\n"
        f"extraction_method: {_yaml_scalar(method)}\n"
        f"pdf_pages: {page_count}\n"
        "---\n"
    )

    body = (
        f"\n## Content Preview{truncation_note}\n"
        f"\n```\n{preview}\n```\n"
        f"\n- **Word count:** {word_count}\n"
        f"- **Line count:** {line_count}\n"
        f"- **Pages:** {page_count}\n"
        f"- **Extraction method:** {method}\n"
        f"\n## Provenance\n"
        f"\n- **raw_scope_path:** `{raw_scope_path}`\n"
        f"- **original_source:** `{original_source}`\n"
    )

    try:
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(frontmatter)
            f.write(body)
    except Exception as e:
        return {"status": "failed", "notes": [], "error": f"Failed to write note: {e}"}

    return {
        "status": "extracted",
        "notes": [note_path],
        "error": None,
    }
