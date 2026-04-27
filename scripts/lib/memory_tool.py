#!/usr/bin/env python3
"""
memory_tool.py — Create, relocate, and manage DIL memory notes.

Subcommands:
  create      Create a new memory note with schema-compliant frontmatter
  relocate    Move a memory note between scopes (local <-> shared)
  mind_meld   Export a memory to the DIL template repo, generalized and redacted
  promote     Copy any files to the DIL template repo and commit (--redact for LLM pass)

Exit codes: 0=success, 1=general error, 2=validation error
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

try:
    from resolve_base import resolve_dil_base
except ImportError:
    resolve_dil_base = None

try:
    from sf_log import SFLogger
except ImportError:
    SFLogger = None

SCRIPT_NAME = "memory_tool"

VALID_TYPES = {
    "reference", "observation", "decision", "preference",
    "project", "commitment", "lesson", "handoff", "people",
    "system",
}

TYPE_TO_CATEGORY = {
    "decision": "decisions",
    "preference": "preferences",
    "project": "projects",
    "commitment": "commitments",
    "lesson": "lessons",
    "handoff": "handoffs",
    "observation": "observations",
    "people": "people",
    "reference": "reference",
    "system": "system",
}

CATEGORY_NORMALIZE = {
    "preference": "preferences",
    "decision": "decisions",
    "commitment": "commitments",
    "lesson": "lessons",
    "observation": "observations",
    "handoff": "handoffs",
}

REQUIRED_FRONTMATTER_KEYS = [
    "title", "date", "machine", "assistant", "category", "memoryType",
    "priority", "tags", "updated", "source", "domain", "project",
    "status", "owner", "due",
]


def resolve_base(script_dir: str | None = None, explicit: str | None = None) -> str:
    if resolve_dil_base:
        return resolve_dil_base(script_dir, explicit)
    base = os.environ.get("BASE_DIL") or os.environ.get("DIL_BASE") or os.environ.get("CLAWVAULT_BASE")
    if base:
        return str(Path(base).expanduser())
    legacy = Path.home() / "Documents" / "dil_agentic_memory_0001"
    if (legacy / "_shared").is_dir():
        return str(legacy)
    raise RuntimeError("Could not resolve DIL base. Set BASE_DIL.")


def resolve_identity() -> tuple[str, str]:
    machine = os.environ.get("DIL_MACHINE") or subprocess.run(
        ["hostname", "-s"], capture_output=True, text=True, check=True
    ).stdout.strip().lower()

    assistant = (
        os.environ.get("ASSISTANT_ID")
        or os.environ.get("AGENT_NAME")
        or os.environ.get("AGENT_ID")
        or ""
    )
    if not assistant:
        script_dir = Path(__file__).resolve().parent.parent
        identify = script_dir / "identify_agent.sh"
        if identify.is_file():
            try:
                result = subprocess.run(
                    [str(identify)], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip() != "UNRESOLVED":
                    assistant = result.stdout.strip()
            except (subprocess.TimeoutExpired, OSError):
                pass
    if not assistant:
        assistant = "unknown"
    return machine, assistant


def slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9._-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def now_date() -> str:
    return datetime.date.today().isoformat()


def now_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def update_frontmatter_field(path: Path, key: str, new_value: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^({re.escape(key)}:\s*).*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(rf"\g<1>{new_value}", text)
    else:
        text = text.replace("---\n", f"---\n{key}: {new_value}\n", 1)
    path.write_text(text, encoding="utf-8")


def append_to_file(path: Path, line: str) -> None:
    if path.is_file():
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _make_logger(base: str, action: str) -> "SFLogger | None":
    if SFLogger is None:
        return None
    return SFLogger(SCRIPT_NAME, action, base)


def log_operation(base: str, action: str, message: str) -> None:
    log = _make_logger(base, action)
    if log:
        log.info(message)
        log.close()
    else:
        log_dir = Path(base) / "_shared" / "logs" / SCRIPT_NAME
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            hostname = subprocess.run(
                ["hostname", "-s"], capture_output=True, text=True, check=True
            ).stdout.strip().lower()
        except Exception:
            hostname = "unknown"
        log_file = log_dir / f"{hostname}.{SCRIPT_NAME}.{action}.{ts}.log"
        log_file.write_text(message, encoding="utf-8")


# ---------------------------------------------------------------------------
# create subcommand
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> int:
    base = resolve_base(str(Path(__file__).parent), args.base)
    machine, assistant = (args.machine, args.assistant) if args.machine and args.assistant else resolve_identity()
    if args.machine:
        machine = args.machine
    if args.assistant:
        assistant = args.assistant

    if args.scope == "shared":
        scope_dir = Path(base) / "_shared"
        machine = "shared"
        assistant = "shared"
    else:
        scope_dir = Path(base) / machine / assistant
        if not scope_dir.is_dir():
            print(f"Error: scope directory not found: {scope_dir}", file=sys.stderr)
            return 2

    category = args.category or TYPE_TO_CATEGORY.get(args.type, "general")
    target_dir = scope_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)

    title_slug = slugify(args.title)
    filename = f"{title_slug}.md"
    file_path = target_dir / filename
    if file_path.exists():
        filename = f"{title_slug}-{now_date()}.md"
        file_path = target_dir / filename

    body = ""
    if args.content_file:
        body = Path(args.content_file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        body = sys.stdin.read()

    tag_parts = ["clawvault", args.type]
    if args.tags:
        tag_parts.extend(t.strip() for t in args.tags.split(","))
    tag_list = "[" + ", ".join(tag_parts) + "]"

    date_val = now_date()
    note = f"""---
title: "{args.title}"
date: {date_val}
machine: {machine}
assistant: {assistant}
category: {category}
memoryType: {args.type}
priority: normal
tags: {tag_list}
updated: {date_val}
source: internal
domain: operations
project: clawvault
status: active
owner: {assistant}
due:
---

# {args.title}

{body}
"""

    if args.dry_run:
        print("--- DRY RUN ---")
        print(f"Target: {file_path}")
        print(note[:500])
        return 0

    file_path.write_text(note, encoding="utf-8")

    if args.scope == "shared":
        rel_path = f"_shared/{category}/{filename}"
        index_file = Path(base) / "_shared" / "_meta" / "vault_index.md"
    else:
        rel_path = f"{machine}/{assistant}/{category}/{filename}"
        index_file = scope_dir / "_meta" / "vault_index.md"

    append_to_file(index_file, f"| {rel_path} | {args.title} |")

    changelog = scope_dir / "handoffs" / "change_log.md"
    append_to_file(
        changelog,
        f"| {now_timestamp()} | {assistant} | {SCRIPT_NAME} | {rel_path} | create | create memory via {SCRIPT_NAME} |",
    )

    log = _make_logger(base, "create")
    if log:
        log.section("Memory Created")
        log.info(f"file: {file_path}")
        log.info(f"title: {args.title}")
        log.info(f"type: {args.type}")
        log.info(f"category: {category}")
        log.info(f"scope: {args.scope}")
        log.info(f"machine: {machine}")
        log.info(f"assistant: {assistant}")
        log.info(f"index updated: {index_file}")
        log.info(f"changelog updated: {changelog}")
        log.info(f"body source: {'--content-file' if args.content_file else 'stdin' if body else 'empty'}")
        log.info(f"body length: {len(body)} chars")
        log.close()

    print(f"Memory created: {file_path}")
    return 0


# ---------------------------------------------------------------------------
# relocate subcommand
# ---------------------------------------------------------------------------

def cmd_relocate(args: argparse.Namespace) -> int:
    base = resolve_base(str(Path(__file__).parent), args.base)
    base_path = Path(base)

    source = Path(args.source).resolve()
    if not source.is_file():
        print(f"Error: source file not found: {source}", file=sys.stderr)
        return 2

    if not str(source).startswith(str(base_path)):
        print(f"Error: source is not inside the DIL tree: {source}", file=sys.stderr)
        return 2

    fm = parse_frontmatter(source)
    if not fm:
        print(f"Error: could not parse frontmatter from {source}", file=sys.stderr)
        return 2

    category = fm.get("category", "general")
    category = CATEGORY_NORMALIZE.get(category, category)
    filename = source.name

    if args.target_scope == "shared":
        target_dir = base_path / "_shared" / category
        new_machine = "shared"
        new_assistant = "shared"
        new_owner = "shared"
    else:
        parts = args.target_scope.split("/", 1)
        if len(parts) != 2:
            print(
                f"Error: target scope must be 'shared' or 'machine/assistant', got: {args.target_scope}",
                file=sys.stderr,
            )
            return 2
        new_machine, new_assistant = parts
        target_dir = base_path / new_machine / new_assistant / category
        new_owner = new_assistant

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename

    if target.exists() and not args.force:
        print(f"Error: target already exists: {target}  (use --force to overwrite)", file=sys.stderr)
        return 2

    rel_source = source.relative_to(base_path)

    if args.dry_run:
        print("--- DRY RUN ---")
        print(f"Move: {source} -> {target}")
        print(f"Patch frontmatter: machine={new_machine}, assistant={new_assistant}, owner={new_owner}")
        return 0

    # Move file
    source.rename(target)

    # Patch frontmatter
    update_frontmatter_field(target, "machine", new_machine)
    update_frontmatter_field(target, "assistant", new_assistant)
    update_frontmatter_field(target, "owner", new_owner)
    update_frontmatter_field(target, "updated", now_date())

    rel_target = target.relative_to(base_path)

    # Update source index (remove old entry)
    old_scope_dir = (source.parent.parent if category else source.parent)
    # Walk up to find the scope root (where _meta/ lives)
    for candidate in [source.parent.parent, source.parent.parent.parent, source.parent]:
        idx = candidate / "_meta" / "vault_index.md"
        if idx.is_file():
            lines = idx.read_text(encoding="utf-8").splitlines()
            lines = [l for l in lines if str(rel_source) not in l and filename not in l]
            idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
            break

    # Update target index (add new entry)
    if args.target_scope == "shared":
        target_index = base_path / "_shared" / "_meta" / "vault_index.md"
    else:
        target_index = base_path / new_machine / new_assistant / "_meta" / "vault_index.md"

    title = fm.get("title", "").strip('"').strip("'")
    append_to_file(target_index, f"| {rel_target} | {title} |")

    # Changelog
    if args.target_scope == "shared":
        changelog = base_path / "_shared" / "handoffs" / "change_log.md"
    else:
        changelog = base_path / new_machine / new_assistant / "handoffs" / "change_log.md"

    _, assistant = resolve_identity()
    append_to_file(
        changelog,
        f"| {now_timestamp()} | {assistant} | {SCRIPT_NAME} | {rel_target} | relocate | relocated from {rel_source} |",
    )

    log = _make_logger(base, "relocate")
    if log:
        log.section("Source")
        log.info(f"file: {source}")
        log.info(f"relative: {rel_source}")
        log.info(f"category: {category}")

        log.section("Target")
        log.info(f"scope: {args.target_scope}")
        log.info(f"file: {target}")
        log.info(f"relative: {rel_target}")
        log.info(f"machine: {new_machine}")
        log.info(f"assistant: {new_assistant}")

        log.section("Result")
        log.info(f"Moved {rel_source} -> {rel_target}")
        log.info(f"Frontmatter patched: machine={new_machine}, assistant={new_assistant}, owner={new_owner}")
        log.info(f"Source index cleaned")
        log.info(f"Target index updated: {target_index}")
        log.info(f"Changelog updated")
        log.close()

    print(f"Relocated: {rel_source} -> {rel_target}")
    return 0


# ---------------------------------------------------------------------------
# mind_meld subcommand
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE_REPO = str(Path.home() / "projects" / "ai_projects" / "distributed_intent_ledger")
DEFAULT_OLLAMA_MODEL = "gemma4:latest"

MIND_MELD_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a technical editor preparing a memory note for publication in an
    open-source template repository. Your job is to generalize the content
    so it teaches the underlying principle without exposing private details.

    Rules:
    1. PRESERVE the core principle, lesson, policy, or guideline completely.
    2. REMOVE all PII: real names, email addresses, usernames, employee IDs.
    3. REMOVE all business-identifiable information: company names, product
       names, internal project names/IDs, Jira ticket IDs, internal URLs,
       internal hostnames, IP addresses, team names, org-specific jargon.
    4. REPLACE removed specifics with generic equivalents that illustrate
       the same point (e.g., "ACME Corp" -> "the organization",
       "PROJ-1234" -> "the tracking ticket", "pr-etl-server-01" ->
       "the production ETL server").
    5. Keep the same Markdown structure (headings, lists, blockquotes).
    6. Keep the same tone and voice.
    7. Do NOT add new content or opinions. Only generalize what exists.
    8. If the content contains NO PII or business-identifiable info,
       return it unchanged and note that no redaction was needed.

    Return ONLY the generalized Markdown body (no frontmatter, no wrapping).
""")


def extract_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n.*?\n---\n(.*)$", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def llm_generalize(body: str, model: str) -> str:
    prompt = f"Here is the memory note body to generalize:\n\n{body}"
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=f"{MIND_MELD_SYSTEM_PROMPT}\n\n{prompt}",
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"Error: ollama returned {result.returncode}: {result.stderr}", file=sys.stderr)
            return ""
        output = result.stdout.strip()
        output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
        output = re.sub(r"^Thinking.*?\.\.\.done thinking\.\n?", "", output, flags=re.DOTALL)
        return output.strip()
    except FileNotFoundError:
        print("Error: ollama not found. Install ollama or use --skip-llm.", file=sys.stderr)
        return ""
    except subprocess.TimeoutExpired:
        print("Error: ollama timed out after 120s.", file=sys.stderr)
        return ""


def templatize_frontmatter(fm: dict[str, str]) -> str:
    category = fm.get("category", "general")
    category = CATEGORY_NORMALIZE.get(category, category)
    mem_type = fm.get("memoryType", "reference")
    title = fm.get("title", "").strip('"').strip("'")

    tags_raw = fm.get("tags", "[]")
    skip_tags = {"clawvault", "dil-active"}
    if tags_raw.startswith("["):
        tags = [t.strip() for t in tags_raw.strip("[]").split(",") if t.strip() not in skip_tags]
    else:
        tags = [t.strip() for t in tags_raw.split(",") if t.strip() not in skip_tags]
    tag_list = "[" + ", ".join(tags) + "]"

    return f"""---
title: "{title}"
date: YYYY-MM-DD
machine: <machine>
assistant: <assistant>
category: {category}
memoryType: {mem_type}
priority: normal
tags: {tag_list}
updated: YYYY-MM-DD
source: internal
domain: operations
project: dil
status: active
owner: <assistant>
due:
---"""


def cmd_mind_meld(args: argparse.Namespace) -> int:
    base = resolve_base(str(Path(__file__).parent), args.base)
    log = _make_logger(base, "mind_meld")

    source = Path(args.source).resolve()
    if not source.is_file():
        if log:
            log.error(f"Source file not found: {source}")
            log.close()
        print(f"Error: source file not found: {source}", file=sys.stderr)
        return 2

    fm = parse_frontmatter(source)
    if not fm:
        if log:
            log.error(f"Could not parse frontmatter from {source}")
            log.close()
        print(f"Error: could not parse frontmatter from {source}", file=sys.stderr)
        return 2

    template_repo = Path(args.template_repo).resolve()
    if not (template_repo / "_shared").is_dir():
        if log:
            log.error(f"Template repo not found or missing _shared/: {template_repo}")
            log.close()
        print(f"Error: template repo not found or missing _shared/: {template_repo}", file=sys.stderr)
        return 2

    title = fm.get("title", "").strip('"').strip("'")
    category = fm.get("category", "general")
    category = CATEGORY_NORMALIZE.get(category, category)
    filename = source.name
    target_dir = template_repo / "_shared" / category
    target = target_dir / filename

    if log:
        log.section("Source")
        log.info(f"file: {source}")
        log.info(f"title: {title}")
        log.info(f"category: {category}")
        log.info(f"original frontmatter keys: {', '.join(sorted(fm.keys()))}")
        log.info(f"body length: {len(extract_body(source))} chars")

        log.section("Target")
        log.info(f"template_repo: {template_repo}")
        log.info(f"target_dir: {target_dir}")
        log.info(f"target_file: {target}")
        log.info(f"target_exists: {target.exists()}")

    # Step 1: Templatize frontmatter
    new_frontmatter = templatize_frontmatter(fm)
    if log:
        log.section("Frontmatter Templatization")
        log.info("Replaced machine, assistant, dates with placeholders")
        log.info("Stripped PII-bearing tags (clawvault, dil-active)")
        log.info(f"Category normalized: {fm.get('category', '?')} -> {category}")

    # Step 2: Generalize body via LLM (or skip)
    body = extract_body(source)
    if args.skip_llm:
        generalized_body = body
        if log:
            log.section("LLM Redaction")
            log.info("SKIPPED — --skip-llm flag set, using original body unchanged")
        print("(Skipping LLM redaction pass — using original body)")
    else:
        model = args.model or DEFAULT_OLLAMA_MODEL
        if log:
            log.section("LLM Redaction")
            log.info(f"model: {model}")
            log.info(f"input body length: {len(body)} chars")
            log.info("Sending body to ollama for PII/business-info generalization...")
        print(f"Running LLM generalization pass ({model})...")
        generalized_body = llm_generalize(body, model)
        if not generalized_body:
            if log:
                log.error("LLM generalization returned empty — ollama may have failed or timed out")
                log.close()
            print("LLM pass failed. Use --skip-llm to bypass.", file=sys.stderr)
            return 1
        if log:
            log.info(f"output body length: {len(generalized_body)} chars")
            log.info(f"body changed: {body != generalized_body}")

    # Step 3: Assemble the output
    output = f"{new_frontmatter}\n\n{generalized_body}\n"

    # Step 4: Show for approval
    print("\n" + "=" * 60)
    print("MIND MELD — Proposed template note")
    print("=" * 60)
    print(output)
    print("=" * 60)
    print(f"\nTarget: {target}")

    if args.dry_run:
        if log:
            log.section("Result")
            log.info("DRY RUN — no files written")
            log.close()
        print("(dry run — not writing)")
        return 0

    # Step 5: Ask for approval
    approved = False
    if sys.stdin.isatty():
        response = input("\nWrite this file? [y/N] ").strip().lower()
        if response not in ("y", "yes"):
            if log:
                log.section("Result")
                log.info("User declined — aborted, no files written")
                log.close()
            print("Aborted.")
            return 0
        approved = True
    else:
        print("(non-interactive — writing automatically)")
        approved = True

    # Step 6: Write
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() and not args.force:
        if log:
            log.error(f"Target already exists and --force not set: {target}")
            log.close()
        print(f"Error: target already exists: {target}  (use --force to overwrite)", file=sys.stderr)
        return 2

    target.write_text(output, encoding="utf-8")

    # Update template repo index if it exists
    template_index = template_repo / "_shared" / "_meta" / "vault_index.md"
    rel_target = f"_shared/{category}/{filename}"
    append_to_file(template_index, f"| {rel_target} | {title} |")

    if log:
        log.section("Result")
        log.info(f"Written: {target}")
        log.info(f"Output size: {len(output)} chars")
        log.info(f"Vault index updated: {template_index}")
        log.info(f"Approval: {'interactive' if sys.stdin.isatty() else 'automatic'}")
        log.info(f"Force overwrite: {args.force}")
        log.info(f"LLM redacted: {not args.skip_llm}")
        if not args.skip_llm:
            log.info(f"LLM model: {args.model or DEFAULT_OLLAMA_MODEL}")
        log.close()

    print(f"Mind meld complete: {target}")
    return 0


# ---------------------------------------------------------------------------
# promote subcommand
# ---------------------------------------------------------------------------

def resolve_target_path(source: Path, base_path: Path, template_repo: Path) -> Path:
    """Map a source file to its target location in the template repo.

    Uses the template repo's actual directory structure as the authority.
    Matches source path segments to find the best landing spot.
    """
    # If inside the DIL _shared tree, compute relative path from _shared/
    try:
        shared_dir = base_path / "_shared"
        rel = source.relative_to(shared_dir)
        # Prefer top-level match over _shared/ to avoid duplication
        candidate_top = template_repo / rel
        candidate_shared = template_repo / "_shared" / rel
        first_segment = rel.parts[0] if rel.parts else None
        if first_segment and (template_repo / first_segment).is_dir():
            return candidate_top
        if candidate_shared.parent.is_dir():
            return candidate_shared
        return candidate_top
    except ValueError:
        pass

    # If inside /az/talend/scripts/, map to scripts/
    try:
        scripts_root = Path("/az/talend/scripts")
        rel = source.relative_to(scripts_root)
        return template_repo / "scripts" / rel
    except ValueError:
        pass

    # If inside a known scripts/lib pattern anywhere
    parts = source.parts
    for i, p in enumerate(parts):
        if p == "scripts":
            rel = Path(*parts[i:])
            return template_repo / rel

    # Fallback: just put it in the root
    return template_repo / source.name


def cmd_promote(args: argparse.Namespace) -> int:
    base = resolve_base(str(Path(__file__).parent), args.base)
    base_path = Path(base)

    template_repo = Path(args.template_repo).resolve()
    if not template_repo.is_dir():
        print(f"Error: template repo not found: {template_repo}", file=sys.stderr)
        return 2

    sources = [Path(s).resolve() for s in args.sources]
    for s in sources:
        if not s.exists():
            print(f"Error: source not found: {s}", file=sys.stderr)
            return 2

    # Build the file map: source -> target
    file_map: list[tuple[Path, Path]] = []
    for source in sources:
        if source.is_file():
            target = resolve_target_path(source, base_path, template_repo)
            file_map.append((source, target))
        elif source.is_dir():
            for f in sorted(source.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    target = resolve_target_path(f, base_path, template_repo)
                    file_map.append((f, target))

    if not file_map:
        print("No files to promote.", file=sys.stderr)
        return 2

    # Show plan
    print(f"Promote {len(file_map)} file(s) to {template_repo.name}:\n")
    for src, tgt in file_map:
        rel_tgt = tgt.relative_to(template_repo)
        marker = "[redact] " if args.redact and src.suffix == ".md" else ""
        print(f"  {marker}{src.name} -> {rel_tgt}")

    if args.dry_run:
        print("\n(dry run — not writing)")
        return 0

    # Confirm
    if sys.stdin.isatty() and not args.yes:
        response = input(f"\nProceed? [y/N] ").strip().lower()
        if response not in ("y", "yes"):
            print("Aborted.")
            return 0

    # Copy files
    copied = []
    for src, tgt in file_map:
        tgt.parent.mkdir(parents=True, exist_ok=True)

        if args.redact and src.suffix == ".md":
            fm = parse_frontmatter(src)
            if fm:
                new_fm = templatize_frontmatter(fm)
                body = extract_body(src)
                model = args.model or DEFAULT_OLLAMA_MODEL
                print(f"  Redacting {src.name} via {model}...")
                generalized = llm_generalize(body, model)
                if not generalized:
                    print(f"  Warning: LLM redaction failed for {src.name}, using original body")
                    generalized = body
                tgt.write_text(f"{new_fm}\n\n{generalized}\n", encoding="utf-8")
            else:
                shutil.copy2(src, tgt)
        else:
            shutil.copy2(src, tgt)

        # Preserve executable bit
        if os.access(src, os.X_OK):
            tgt.chmod(tgt.stat().st_mode | 0o111)

        rel_tgt = tgt.relative_to(template_repo)
        copied.append(str(rel_tgt))
        print(f"  Copied: {rel_tgt}")

    # Git commit if requested
    if args.commit:
        git_dir = str(template_repo)
        try:
            subprocess.run(["git", "-C", git_dir, "add"] + copied, check=True, capture_output=True)

            msg = args.message or f"Promote {len(copied)} file(s) from active DIL"
            subprocess.run(
                ["git", "-C", git_dir, "commit", "-m", msg],
                check=True, capture_output=True,
            )
            print(f"\nCommitted: {msg}")

            if args.push:
                result = subprocess.run(
                    ["git", "-C", git_dir, "push"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    print("Pushed to remote.")
                else:
                    print(f"Push failed: {result.stderr.strip()}", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Git error: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)

    log = _make_logger(base, "promote")
    if log:
        log.section("Promote Summary")
        log.info(f"template_repo: {template_repo}")
        log.info(f"files promoted: {len(copied)}")
        log.info(f"redact mode: {args.redact}")
        if args.redact:
            log.info(f"llm model: {args.model or DEFAULT_OLLAMA_MODEL}")
        for rel in copied:
            log.info(f"  -> {rel}")
        if args.commit:
            log.info(f"git commit: {args.message or f'Promote {len(copied)} file(s) from active DIL'}")
            log.info(f"git push: {args.push}")
        else:
            log.info("git commit: skipped (--commit not set)")
        log.close()

    print(f"\nPromote complete: {len(copied)} file(s)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory_tool",
        description="Create and manage DIL memory notes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- create --
    p_create = sub.add_parser("create", help="Create a new memory note")
    p_create.add_argument("--type", required=True, help=f"Memory type: {', '.join(sorted(VALID_TYPES))}")
    p_create.add_argument("--title", required=True, help="Title of the note")
    p_create.add_argument("--category", default="", help="Category folder (default: auto from type)")
    p_create.add_argument("--tags", default="", help="Comma-separated tags")
    p_create.add_argument("--machine", default="", help="Machine scope (default: from hostname)")
    p_create.add_argument("--assistant", default="", help="Assistant scope (default: from env/process)")
    p_create.add_argument("--scope", default="local", choices=["local", "shared"], help="Write to local scope or _shared")
    p_create.add_argument("--content-file", default="", help="File containing note body (else stdin)")
    p_create.add_argument("--base", default="", help="Base vault path override")
    p_create.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    # -- relocate --
    p_reloc = sub.add_parser("relocate", help="Move a memory note between scopes")
    p_reloc.add_argument("source", help="Path to the source memory file")
    p_reloc.add_argument("--target-scope", required=True, help="Target scope: 'shared' or 'machine/assistant'")
    p_reloc.add_argument("--force", action="store_true", help="Overwrite if target exists")
    p_reloc.add_argument("--base", default="", help="Base vault path override")
    p_reloc.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    # -- mind_meld --
    p_meld = sub.add_parser("mind_meld", help="Export a memory to the DIL template repo, generalized and redacted")
    p_meld.add_argument("source", help="Path to the source memory file")
    p_meld.add_argument("--template-repo", default=DEFAULT_TEMPLATE_REPO, help=f"Path to DIL template repo (default: {DEFAULT_TEMPLATE_REPO})")
    p_meld.add_argument("--model", default="", help=f"Ollama model for generalization (default: {DEFAULT_OLLAMA_MODEL})")
    p_meld.add_argument("--skip-llm", action="store_true", help="Skip LLM redaction, use body as-is")
    p_meld.add_argument("--force", action="store_true", help="Overwrite if target exists")
    p_meld.add_argument("--base", default="", help="Base vault path override")
    p_meld.add_argument("--dry-run", action="store_true", help="Show proposed output without writing")

    # -- promote --
    p_promote = sub.add_parser("promote", help="Copy files to the DIL template repo and optionally commit/push")
    p_promote.add_argument("sources", nargs="+", help="Files or directories to promote")
    p_promote.add_argument("--template-repo", default=DEFAULT_TEMPLATE_REPO, help=f"Path to DIL template repo (default: {DEFAULT_TEMPLATE_REPO})")
    p_promote.add_argument("--redact", action="store_true", help="Run LLM redaction on .md files (mind_meld behavior)")
    p_promote.add_argument("--model", default="", help=f"Ollama model for redaction (default: {DEFAULT_OLLAMA_MODEL})")
    p_promote.add_argument("--commit", action="store_true", help="Git commit after copying")
    p_promote.add_argument("--push", action="store_true", help="Git push after commit (implies --commit)")
    p_promote.add_argument("--message", "-m", default="", help="Commit message (auto-generated if omitted)")
    p_promote.add_argument("--force", action="store_true", help="Overwrite existing files")
    p_promote.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p_promote.add_argument("--base", default="", help="Base vault path override")
    p_promote.add_argument("--dry-run", action="store_true", help="Show plan without executing")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "create":
        return cmd_create(args)
    elif args.command == "relocate":
        return cmd_relocate(args)
    elif args.command == "mind_meld":
        return cmd_mind_meld(args)
    elif args.command == "promote":
        if args.push:
            args.commit = True
        return cmd_promote(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
