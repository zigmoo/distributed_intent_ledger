#!/usr/bin/env python3
"""research_tool.py — shared DIL research artifact manager.

Creates and manages research artifacts in:
  _shared/research/benchmarking/
  _shared/research/execution-notes/
  _shared/research/conclusions/
  _shared/research/ideas/
  _shared/research/comparisons/
  _shared/research/prompts/
  _shared/research/errata/

Goals:
- bash-wrapper-first usage
- task-linked, timestamped filenames
- automatic index updates
- configurable artifact type map
- minimal inference for agents and humans
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from resolve_base import resolve_dil_base
except Exception:  # pragma: no cover
    resolve_dil_base = None

DEFAULT_ARTIFACT_TYPES = {
    "benchmarking": {
        "dir": "benchmarking",
        "category": "benchmarking",
        "memoryType": "observation",
        "kind": "benchmark",
        "default_status": "active",
    },
    "execution-notes": {
        "dir": "execution-notes",
        "category": "execution-notes",
        "memoryType": "observation",
        "kind": "execution",
        "default_status": "active",
    },
    "conclusions": {
        "dir": "conclusions",
        "category": "conclusions",
        "memoryType": "decision",
        "kind": "conclusion",
        "default_status": "final",
    },
    "ideas": {
        "dir": "ideas",
        "category": "ideas",
        "memoryType": "observation",
        "kind": "idea",
        "default_status": "draft",
    },
    "comparisons": {
        "dir": "comparisons",
        "category": "comparisons",
        "memoryType": "observation",
        "kind": "comparison",
        "default_status": "active",
    },
    "prompts": {
        "dir": "prompts",
        "category": "prompts",
        "memoryType": "reference",
        "kind": "prompt",
        "default_status": "active",
    },
    "errata": {
        "dir": "errata",
        "category": "errata",
        "memoryType": "decision",
        "kind": "correction",
        "default_status": "final",
    },
}

DEFAULT_ARTIFACT_ALIASES = {
    "benchmark": "benchmarking",
    "bench": "benchmarking",
    "execution": "execution-notes",
    "exec": "execution-notes",
    "notes": "execution-notes",
    "conclusion": "conclusions",
    "conclude": "conclusions",
    "idea": "ideas",
    "comparison": "comparisons",
    "compare": "comparisons",
    "prompt": "prompts",
    "correction": "errata",
    "corrections": "errata",
    "erratum": "errata",
}

VALID_STATUSES = {"active", "draft", "final"}


def load_artifact_registry() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    types = {name: spec.copy() for name, spec in DEFAULT_ARTIFACT_TYPES.items()}
    aliases = dict(DEFAULT_ARTIFACT_ALIASES)

    def merge_payload(payload: dict[str, Any]) -> None:
        type_payload = payload.get("types", payload)
        alias_payload = payload.get("aliases", {})
        if not isinstance(type_payload, dict):
            fail(2, "Artifact type registry payload must be a JSON object")
        if not isinstance(alias_payload, dict):
            fail(2, "Artifact alias registry payload must be a JSON object")
        for name, spec in type_payload.items():
            if not isinstance(spec, dict):
                fail(2, f"Invalid artifact spec for {name}")
            merged = types.get(name, {}).copy()
            merged.update(spec)
            required = ["dir", "category", "memoryType", "kind"]
            missing = [field for field in required if not merged.get(field)]
            if missing:
                fail(2, f"Artifact spec for {name} missing fields: {', '.join(missing)}")
            merged.setdefault("default_status", "active")
            types[name] = merged
        for alias, target in alias_payload.items():
            aliases[str(alias)] = str(target)

    raw_json = os.environ.get("RESEARCH_TOOL_ARTIFACT_TYPES_JSON", "").strip()
    raw_file = os.environ.get("RESEARCH_TOOL_ARTIFACT_TYPES_FILE", "").strip()
    if raw_json:
        try:
            merge_payload(json.loads(raw_json))
        except json.JSONDecodeError as exc:
            fail(2, f"Invalid RESEARCH_TOOL_ARTIFACT_TYPES_JSON: {exc}")
    if raw_file:
        payload_path = Path(raw_file).expanduser()
        if not payload_path.exists():
            fail(2, f"Artifact registry file not found: {payload_path}")
        try:
            merge_payload(json.loads(payload_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            fail(2, f"Invalid artifact registry file {payload_path}: {exc}")

    return types, aliases




def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def fail(code: int, msg: str) -> None:
    eprint(f"ERR | {code} | {msg}")
    raise SystemExit(code)


ARTIFACT_TYPES, VALID_ARTIFACT_ALIASES = load_artifact_registry()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def timestamp_for_filename(ts: dt.datetime | None = None) -> str:
    ts = ts or now_utc()
    return ts.strftime("%Y-%m-%dT%H%M%SZ")


def today() -> str:
    return now_utc().strftime("%Y-%m-%d")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def yaml_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "":
        return ""
    if re.search(r'[\s:\[\]{}#,&*?!|>"\'`%@$\n]', s):
        return json.dumps(s)
    return s


def yaml_list(values: list[str]) -> str:
    return "[" + ", ".join(yaml_scalar(v) for v in values) + "]"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    fm: dict[str, str] = {}
    for line in parts[0].splitlines()[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"')
    return fm, parts[1]


def resolve_base(script_dir: Path, explicit: str | None) -> Path:
    if resolve_dil_base is not None:
        return Path(resolve_dil_base(script_dir=script_dir, explicit=explicit or None)).resolve()
    env = explicit or os.environ.get("BASE_DIL") or os.environ.get("DIL_BASE") or os.environ.get("CLAWVAULT_BASE")
    if env:
        return Path(env).expanduser().resolve()
    legacy = Path.home() / "Documents" / "dil_agentic_memory_0001"
    if (legacy / "_shared").is_dir():
        return legacy.resolve()
    fail(4, "Could not resolve DIL base. Set BASE_DIL to your vault path.")


def resolve_assistant() -> str:
    for env_var in ("ACTOR", "ASSISTANT_ID", "AGENT_NAME", "AGENT_ID"):
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return "shared"


def normalize_artifact_type(value: str) -> str:
    v = value.strip().lower()
    v = VALID_ARTIFACT_ALIASES.get(v, v)
    if v not in ARTIFACT_TYPES:
        fail(2, f"Invalid artifact type: {value}")
    return v


def research_root(base: Path) -> Path:
    return base / "_shared" / "research"


def research_meta_index(base: Path) -> Path:
    return research_root(base) / "_meta" / "index.md"


def vault_index_path(base: Path) -> Path:
    return base / "_shared" / "_meta" / "vault_index.md"


def ensure_research_tree(base: Path) -> None:
    for spec in ARTIFACT_TYPES.values():
        (research_root(base) / spec["dir"]).mkdir(parents=True, exist_ok=True)
    (research_root(base) / "_meta").mkdir(parents=True, exist_ok=True)
    if not research_meta_index(base).exists():
        write_text(
            research_meta_index(base),
            "---\n"
            "title: \"Shared Research Index\"\n"
            f"date: {today()}\n"
            "machine: shared\n"
            "assistant: shared\n"
            "category: system\n"
            "memoryType: index\n"
            "priority: high\n"
            "tags: [research, index, shared]\n"
            f"updated: {today()}\n"
            "source: internal\n"
            "domain: operations\n"
            "project: dil-active\n"
            "status: active\n"
            "owner: shared\n"
            "due:\n"
            "---\n\n"
            "# Shared Research Index\n\n"
            "| Timestamp | Task | Type | Title | Path |\n"
            "|---|---|---|---|---|\n"
        )


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "artifact"


def artifact_filename(task_id: str, artifact_type: str, title: str, timestamp: str) -> str:
    info = ARTIFACT_TYPES[artifact_type]
    kind = info["kind"]
    title_slug = slugify(title)[:48]
    return f"{task_id}-{kind}-{timestamp}-{title_slug}.md"


def artifact_path(base: Path, artifact_type: str, filename: str) -> Path:
    return research_root(base) / ARTIFACT_TYPES[artifact_type]["dir"] / filename


def default_body(task_id: str, artifact_type: str, title: str, related: list[str] | None = None) -> str:
    related = related or []
    lines = [
        f"# {task_id} {ARTIFACT_TYPES[artifact_type]['kind'].title()}: {title}",
        "",
        f"Related task: `{task_id}`",
        "",
    ]
    if related:
        lines.extend(["## Related artifacts", *[f"- {item}" for item in related], ""])
    return "\n".join(lines)


def build_frontmatter(
    *,
    title: str,
    task_id: str,
    artifact_type: str,
    timestamp: str,
    related: list[str],
    project: str,
    owner: str,
    status: str,
    source: str,
    body_kind: str,
    tags: list[str],
) -> str:
    info = ARTIFACT_TYPES[artifact_type]
    fields = [
        ("title", title),
        ("date", today()),
        ("machine", "shared"),
        ("assistant", "shared"),
        ("category", info["category"]),
        ("memoryType", info["memoryType"]),
        ("priority", "high"),
        ("tags", yaml_list(tags)),
        ("updated", today()),
        ("source", source),
        ("domain", "operations"),
        ("project", project),
        ("status", status),
        ("owner", owner),
        ("due", ""),
        ("task_id", task_id),
        ("artifact_type", artifact_type),
        ("timestamp_utc", timestamp),
    ]
    if related:
        fields.append(("related_artifacts", yaml_list(related)))
    lines = ["---"]
    for key, value in fields:
        lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def append_research_index(base: Path, *, timestamp: str, task_id: str, artifact_type: str, title: str, path: Path) -> None:
    idx = research_meta_index(base)
    rel = path.relative_to(base)
    line = f"| {timestamp} | {task_id} | {artifact_type} | {title} | {rel} |\n"
    text = idx.read_text(encoding="utf-8")
    if line in text:
        return
    with idx.open("a", encoding="utf-8") as f:
        f.write(line)


def append_vault_index(base: Path, *, title: str, path: Path) -> None:
    idx = vault_index_path(base)
    if not idx.exists():
        return
    rel = path.relative_to(base)
    line = f"| {rel} | {title} | shared |\n"
    text = idx.read_text(encoding="utf-8")
    if line in text:
        return
    with idx.open("a", encoding="utf-8") as f:
        f.write(line)


def build_artifact_text(
    *,
    frontmatter: str,
    body: str,
    task_id: str,
    artifact_type: str,
    title: str,
) -> str:
    heading = f"# {task_id} {ARTIFACT_TYPES[artifact_type]['kind'].title()}: {title}"
    body = body.strip() or default_body(task_id, artifact_type, title)
    if not body.lstrip().startswith("#"):
        body = heading + "\n\n" + body
    return frontmatter + body.rstrip() + "\n"


def read_body(content_file: str | None) -> str:
    if content_file:
        p = Path(content_file)
        if not p.exists():
            fail(2, f"Content file not found: {p}")
        return p.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def resolve_project(task_id: str, explicit: str | None) -> str:
    return explicit or "dil-active"


def create_artifact(args: argparse.Namespace, artifact_type: str | None = None) -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(script_dir, args.base)
    ensure_research_tree(base)

    artifact_type = normalize_artifact_type(artifact_type or args.type)
    task_id = args.task_id.strip()
    if not re.fullmatch(r"DIL-\d+", task_id):
        fail(2, f"Invalid task id: {task_id}")

    title = args.title.strip()
    if not title:
        fail(2, "Title is required")

    timestamp = args.timestamp or timestamp_for_filename()
    related = [item.strip() for item in (args.related or []) if item.strip()]
    project = resolve_project(task_id, args.project)
    owner = args.owner or "shared"
    status = args.status or ARTIFACT_TYPES[artifact_type].get("default_status", "active")
    if status not in VALID_STATUSES:
        fail(2, f"Invalid status: {status}")

    body = read_body(args.content_file)
    if not body.strip() and not args.allow_empty:
        body = default_body(task_id, artifact_type, title, related)

    filename = artifact_filename(task_id, artifact_type, title, timestamp)
    path = artifact_path(base, artifact_type, filename)
    if path.exists() and not args.force:
        fail(3, f"Artifact already exists: {path}")

    tags = ["dil", task_id.lower(), artifact_type, "research"]
    if args.tags:
        tags.extend([t.strip() for t in args.tags.split(",") if t.strip()])

    frontmatter = build_frontmatter(
        title=title,
        task_id=task_id,
        artifact_type=artifact_type,
        timestamp=timestamp,
        related=related,
        project=project,
        owner=owner,
        status=status,
        source=args.source or "internal",
        body_kind=artifact_type,
        tags=tags,
    )

    artifact_text = build_artifact_text(
        frontmatter=frontmatter,
        body=body,
        task_id=task_id,
        artifact_type=artifact_type,
        title=title,
    )

    if args.dry_run:
        print(f"DRY_RUN | {task_id} | {artifact_type} | {path}")
        print(artifact_text[:1200])
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(artifact_text, encoding="utf-8")

    if args.append_to_index or True:
        append_research_index(base, timestamp=timestamp, task_id=task_id, artifact_type=artifact_type, title=title, path=path)
        append_vault_index(base, title=title, path=path)

    print(f"OK | {task_id} | {artifact_type} | {path}")
    return 0


def validate_artifact(args: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(script_dir, args.base)
    p = Path(args.artifact)
    if not p.is_absolute():
        p = base / p
    if not p.exists():
        fail(4, f"Artifact not found: {p}")
    fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
    required = ["title", "date", "machine", "assistant", "category", "memoryType", "updated", "project", "status", "owner", "task_id", "artifact_type"]
    missing = [k for k in required if not fm.get(k)]
    if missing:
        fail(5, f"Missing required keys: {', '.join(missing)}")
    if fm.get("task_id") and fm["task_id"] not in p.name:
        fail(5, f"Filename does not contain task id: {fm['task_id']}")
    print(f"OK | validate | {p}")
    return 0


def link_artifact(args: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    base = resolve_base(script_dir, args.base)
    artifact = Path(args.artifact)
    if not artifact.is_absolute():
        artifact = base / artifact
    if not artifact.exists():
        fail(4, f"Artifact not found: {artifact}")
    related = [x.strip() for x in (args.related or []) if x.strip()]
    fm, body = parse_frontmatter(artifact.read_text(encoding="utf-8"))
    existing = fm.get("related_artifacts", "")
    existing_items = []
    if existing.startswith("[") and existing.endswith("]"):
        existing_items = [x.strip().strip('"') for x in existing[1:-1].split(",") if x.strip()]
    merged = []
    for item in existing_items + related:
        if item and item not in merged:
            merged.append(item)
    fm["related_artifacts"] = yaml_list(merged)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    text = "\n".join(lines) + body.lstrip()
    artifact.write_text(text, encoding="utf-8")
    print(f"OK | link | {artifact}")
    return 0


def locate_python(args: argparse.Namespace) -> int:
    script = Path(__file__).resolve().parent / "findLatestPy.sh"
    proc = subprocess.run([str(script), *([] if not args.mode else [f"--{args.mode}"])], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    print(proc.stdout.strip())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage DIL research artifacts")
    parser.add_argument("--base", default=None, help="DIL base path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--task-id", required=True)
        p.add_argument("--title", required=True)
        p.add_argument("--content-file", default=None)
        p.add_argument("--timestamp", default=None)
        p.add_argument("--related", action="append", default=[])
        p.add_argument("--append-to-index", action="store_true")
        p.add_argument("--project", default="dil-active")
        p.add_argument("--owner", default="shared")
        p.add_argument("--status", default=None)
        p.add_argument("--source", default="internal")
        p.add_argument("--tags", default=None)
        p.add_argument("--force", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--allow-empty", action="store_true")

    p = sub.add_parser("create", help="Create a research artifact")
    add_common(p)
    p.add_argument("--type", required=True, choices=sorted(set(ARTIFACT_TYPES) | set(VALID_ARTIFACT_ALIASES)))

    for artifact_name, spec in sorted(ARTIFACT_TYPES.items()):
        p = sub.add_parser(artifact_name, help=f"Create a {spec['kind']} artifact")
        add_common(p)
        p.set_defaults(_fixed_type=artifact_name)

    for name, fixed_type in (("benchmark", "benchmarking"), ("execution", "execution-notes"), ("conclude", "conclusions"), ("idea", "ideas")):
        p = sub.add_parser(name, help=f"Create a {fixed_type} artifact")
        add_common(p)
        p.set_defaults(_fixed_type=fixed_type)

    p = sub.add_parser("validate", help="Validate a research artifact")
    p.add_argument("--artifact", required=True)

    p = sub.add_parser("link", help="Add related artifacts to an existing artifact")
    p.add_argument("--artifact", required=True)
    p.add_argument("--related", action="append", default=[])

    p = sub.add_parser("locate-python", help="Print the newest available Python binary path")
    p.add_argument("--mode", choices=["list", "json", "debug"], default=None)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "create":
        return create_artifact(args)
    if args.cmd in ARTIFACT_TYPES:
        return create_artifact(args, artifact_type=args.cmd)
    if hasattr(args, "_fixed_type"):
        return create_artifact(args, artifact_type=args._fixed_type)
    if args.cmd == "validate":
        return validate_artifact(args)
    if args.cmd == "link":
        return link_artifact(args)
    if args.cmd == "locate-python":
        return locate_python(args)
    fail(2, f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
