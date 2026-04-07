#!/usr/bin/env python3
"""
dil_search.py — Hybrid search engine for DIL memory/task/preference files.

Scoring model (inspired by MemPalace hybrid scoring, adapted for file-first DIL):
  fused_score = keyword_relevance * temporal_boost * status_weight

  - keyword_relevance: fraction of query terms found + exact phrase bonus
  - temporal_boost: exponential decay from file mtime (recent files score higher)
  - status_weight: active > in_progress > todo/assigned > blocked > done/cancelled/retired

Stdlib-only, no external dependencies.
"""

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from resolve_base import resolve_dil_base

# --- Scoring constants ---
TEMPORAL_HALF_LIFE_DAYS = 30  # score halves every 30 days of staleness
EXACT_PHRASE_BONUS = 0.5      # bonus when all query terms appear consecutively
STATUS_WEIGHTS = {
    "active": 1.0,
    "in_progress": 0.95,
    "todo": 0.9,
    "assigned": 0.9,
    "blocked": 0.7,
    "done": 0.4,
    "cancelled": 0.3,
    "retired": 0.2,
}
DEFAULT_STATUS_WEIGHT = 0.6

# --- Scope → directory mappings ---
# memory scope: machine-scoped dirs + _shared top-level .md files + _shared/_meta/
# (excludes _shared/domains/ to prevent task leakage)
SCOPE_DIRS = {
    "memory": ["__machine__/*/"],
    "memory_shared": ["_shared/_meta/", "_shared/preferences/", "_shared/policies/",
                       "_shared/rules/", "_shared/lessons/"],
    "tasks": ["_shared/domains/*/tasks/"],
    "preferences": ["_shared/preferences/", "_shared/policies/", "_shared/rules/"],
    "recall": [],
}


def parse_frontmatter(text):
    """Extract frontmatter fields from markdown text. Returns dict."""
    fm = {}
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return fm
    for line in match.group(1).splitlines():
        m = re.match(r"^(\w[\w_-]*):\s*(.*)", line)
        if m:
            fm[m.group(1).strip()] = m.group(2).strip().strip('"').strip("'")
    return fm


def resolve_machine():
    """Resolve machine name from hostname, matching DIL convention."""
    import subprocess
    try:
        result = subprocess.run(
            ["hostname", "-s"], capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip().lower()
    except Exception:
        return None


def _resolve_scope_patterns(scope, machine):
    """Return list of directory patterns for a scope, resolving __machine__."""
    patterns = list(SCOPE_DIRS.get(scope, []))
    # For memory scope, also include shared memory dirs
    if scope == "memory":
        patterns.extend(SCOPE_DIRS.get("memory_shared", []))
    # Recall scope: memory + shared memory + tasks + preferences
    if scope == "recall":
        patterns.extend(SCOPE_DIRS.get("memory", []))
        patterns.extend(SCOPE_DIRS.get("memory_shared", []))
        patterns.extend(SCOPE_DIRS.get("tasks", []))
        patterns.extend(SCOPE_DIRS.get("preferences", []))
    resolved = []
    for p in patterns:
        if "__machine__" in p:
            if machine:
                resolved.append(p.replace("__machine__", machine))
        else:
            resolved.append(p)
    return resolved


def gather_files(base, scope, domain, status_filter, machine=None):
    """Walk the DIL tree and yield (path, mtime) for files matching scope/domain filters."""
    base = Path(base)
    candidates = []

    if scope == "all":
        # Walk everything under base, skip .git and archived
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", ".obsidian", "archived")]
            for f in files:
                if f.endswith(".md"):
                    candidates.append(Path(root) / f)
    elif scope in SCOPE_DIRS or scope == "memory":
        patterns = _resolve_scope_patterns(scope, machine)
        for pattern in patterns:
            if "*" in pattern:
                for p in base.glob(pattern + "**/*.md"):
                    if "archived" not in str(p) and ".git" not in str(p):
                        candidates.append(p)
            else:
                d = base / pattern
                if d.is_dir():
                    for p in d.rglob("*.md"):
                        if "archived" not in str(p):
                            candidates.append(p)
    else:
        print(f"Unknown scope: {scope}", file=sys.stderr)
        sys.exit(2)

    # Domain filter
    if domain != "all":
        filtered = []
        for p in candidates:
            rel = str(p.relative_to(base))
            # Include if: in the domain's task dir, OR not in any domain task dir
            if f"domains/{domain}/" in rel:
                filtered.append(p)
            elif "domains/" not in rel:
                filtered.append(p)
        candidates = filtered

    # Deduplicate
    seen = set()
    results = []
    for p in candidates:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            try:
                mtime = rp.stat().st_mtime
            except OSError:
                continue
            results.append((rp, mtime))

    return results


def score_file(filepath, mtime, query_terms, query_lower, now):
    """Score a single file against the query. Returns (score, matches) or None."""
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    text_lower = text.lower()

    # --- Keyword relevance ---
    terms_found = 0
    match_positions = []
    for term in query_terms:
        pos = text_lower.find(term)
        if pos != -1:
            terms_found += 1
            match_positions.append(pos)

    if terms_found == 0:
        return None

    keyword_score = terms_found / len(query_terms)

    # Exact phrase bonus: all terms appear as a consecutive substring
    if len(query_terms) > 1 and query_lower in text_lower:
        keyword_score += EXACT_PHRASE_BONUS

    # Title/frontmatter boost: terms in title or filename get a bonus
    filename_lower = filepath.name.lower()
    fm = parse_frontmatter(text)
    title_lower = fm.get("title", "").lower()
    title_hits = sum(1 for t in query_terms if t in title_lower or t in filename_lower)
    if title_hits > 0:
        keyword_score += 0.3 * (title_hits / len(query_terms))

    # --- Temporal boost ---
    age_days = max((now - mtime) / 86400, 0.01)
    temporal_boost = math.pow(0.5, age_days / TEMPORAL_HALF_LIFE_DAYS)

    # --- Status weight ---
    status = fm.get("status", "active").lower()
    status_weight = STATUS_WEIGHTS.get(status, DEFAULT_STATUS_WEIGHT)

    # --- Fused score ---
    fused = keyword_score * temporal_boost * status_weight

    # --- Collect match context lines ---
    lines = text.splitlines()
    match_lines = []
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(t in line_lower for t in query_terms):
            match_lines.append((i + 1, line.rstrip()))

    return {
        "score": fused,
        "keyword_score": keyword_score,
        "temporal_boost": temporal_boost,
        "status_weight": status_weight,
        "status": status,
        "title": fm.get("title", filepath.stem),
        "match_lines": match_lines,
    }


def apply_recall_task_boost(result, relpath, scope):
    """Boost non-terminal task files in recall mode to favor short-term work memory."""
    if scope != "recall" or "/tasks/" not in relpath:
        return

    status = result["status"]
    if status in ("active", "in_progress", "todo", "assigned", "blocked"):
        result["score"] *= 1.2
    elif status in ("done", "cancelled", "retired"):
        result["score"] *= 0.8


def format_result_text(filepath, result, base, context_lines, use_color):
    """Format a single result for terminal display."""
    rel = str(filepath.relative_to(base)) if str(filepath).startswith(str(base)) else str(filepath)

    # Colors
    if use_color:
        C_FILE = "\033[1;36m"   # bold cyan
        C_SCORE = "\033[1;33m"  # bold yellow
        C_LINE = "\033[0;90m"   # gray
        C_MATCH = "\033[1;31m"  # bold red
        C_TITLE = "\033[1;37m"  # bold white
        C_RESET = "\033[0m"
    else:
        C_FILE = C_SCORE = C_LINE = C_MATCH = C_TITLE = C_RESET = ""

    lines = []
    score_str = f"{result['score']:.3f}"
    lines.append(f"{C_FILE}{rel}{C_RESET}  {C_SCORE}[{score_str}]{C_RESET}  {C_TITLE}{result['title']}{C_RESET}")

    # Show up to context_lines matching lines
    shown = 0
    for lineno, line_text in result["match_lines"]:
        if shown >= context_lines + 2:  # show a few matches
            remaining = len(result["match_lines"]) - shown
            if remaining > 0:
                lines.append(f"  {C_LINE}... +{remaining} more matches{C_RESET}")
            break
        lines.append(f"  {C_LINE}{lineno:>4}:{C_RESET} {line_text[:120]}")
        shown += 1

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="DIL hybrid search")
    parser.add_argument("--base", default=None, help="DIL base directory")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--scope", default="all", help="Search scope (all|memory|tasks|preferences|recall)")
    parser.add_argument("--domain", default="all", help="Domain filter")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--context", type=int, default=1, help="Context lines")
    parser.add_argument("--status", default="active", help="Status filter")
    parser.add_argument("--no-color", action="store_true", help="Disable color")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    base_path = args.base or resolve_dil_base(script_dir=Path(__file__).resolve().parent)
    base = Path(base_path).resolve()
    if not base.is_dir():
        print(f"ERR | 3 | Base directory not found: {base}", file=sys.stderr)
        sys.exit(3)

    query_lower = args.query.lower()
    query_terms = query_lower.split()
    if not query_terms:
        print("ERR | 2 | Empty query", file=sys.stderr)
        sys.exit(2)

    now = time.time()
    use_color = not args.no_color and sys.stdout.isatty()
    machine = resolve_machine()

    # Gather candidate files
    files = gather_files(base, args.scope, args.domain, args.status, machine=machine)

    # Score all files
    results = []
    for filepath, mtime in files:
        result = score_file(filepath, mtime, query_terms, query_lower, now)
        if result is None:
            continue

        rel = str(filepath.relative_to(base))
        apply_recall_task_boost(result, rel, args.scope)

        # Status filter (applies to task files only)
        if "/tasks/" in rel and args.status != "all":
            file_status = result["status"]
            if args.status == "active":
                # "active" means non-terminal statuses
                if file_status in ("done", "cancelled", "retired"):
                    continue
            elif file_status != args.status:
                # Exact status match requested
                continue

        results.append((filepath, result))

    # Sort by fused score descending
    results.sort(key=lambda x: x[1]["score"], reverse=True)

    # Limit
    results = results[: args.limit]

    if not results:
        if args.json:
            print(json.dumps({"query": args.query, "results": [], "count": 0}))
        else:
            print(f"No results for: {args.query}")
        sys.exit(0)

    # Output
    if args.json:
        out = {
            "query": args.query,
            "count": len(results),
            "results": [
                {
                    "path": str(fp.relative_to(base)),
                    "score": round(r["score"], 4),
                    "keyword_score": round(r["keyword_score"], 4),
                    "temporal_boost": round(r["temporal_boost"], 4),
                    "status": r["status"],
                    "title": r["title"],
                    "match_lines": [{"line": ln, "text": t} for ln, t in r["match_lines"][:5]],
                }
                for fp, r in results
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        header = f"Found {len(results)} result(s) for: {args.query}"
        if use_color:
            print(f"\033[1m{header}\033[0m")
        else:
            print(header)
        print()
        for fp, r in results:
            print(format_result_text(fp, r, base, args.context, use_color))
            print()


if __name__ == "__main__":
    main()
