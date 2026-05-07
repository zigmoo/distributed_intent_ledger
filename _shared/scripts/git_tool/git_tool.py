#!/usr/bin/env python3
"""git_tool.py — Python front-end for deterministic, agent-safe git operations."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base

try:
    from tool_forge_log import ToolForgeLogger
except ImportError:
    ToolForgeLogger = None

SCRIPT_NAME = "git_tool"
BACKEND_BASH = SCRIPTS_DIR / "git_tool_bash" / "git_tool.bash"
COMMIT_TEMPLATE = SCRIPT_DIR / "j2_templates" / "commit_message.txt.j2"


def _parse_message_file(path: Path) -> dict[str, str]:
    """Parse a DIL message .md file: YAML frontmatter + body.

    Returns dict with keys: task_id, summary, why, evidence, body.
    Missing fields return empty string.  No pip dependencies (stdlib only).
    """
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    frontmatter_raw = parts[1]
    body = parts[2].strip()

    fm: dict[str, str] = {}
    for line in frontmatter_raw.splitlines():
        m = re.match(r'^(\w[\w-]*)\s*:\s*"?(.*?)"?\s*$', line)
        if m:
            fm[m.group(1)] = m.group(2)

    result: dict[str, str] = {"body": body}

    title = fm.get("title", "")
    title_match = re.match(r'^([A-Z]+-\d+)\s*:\s*(.+)$', title)
    if title_match:
        result["task_id"] = title_match.group(1)
        result["summary"] = title_match.group(2).strip()
    elif title:
        result["summary"] = title

    for key in ("why", "evidence"):
        if key in fm:
            result[key] = fm[key]

    return result


def _render_template(task_id: str, summary: str, message_ref: str, why: str, evidence: str) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(COMMIT_TEMPLATE.parent)),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template(COMMIT_TEMPLATE.name)
    return tmpl.render(
        task_id=task_id,
        summary=summary,
        message_ref=message_ref,
        why=why,
        evidence=evidence,
    )


def _resolve_repo(repo_value: str | None) -> Path:
    candidate = Path(repo_value or os.getcwd()).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise SystemExit(f"ERROR: Repository path is not a directory: {candidate}")
    proc = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ERROR: Not inside a Git worktree: {candidate}")
    return Path(proc.stdout.strip()).resolve()


def _require_staged(repo: Path) -> None:
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit("ERROR: Refusing empty commit: no staged changes")


def _resolve_commit_fields(args: argparse.Namespace) -> tuple[str, str, str, str, str]:
    """Merge message-file fields with CLI args.  CLI wins when provided."""
    parsed: dict[str, str] = {}
    ref_path = Path(args.message_ref) if args.message_ref else None
    if ref_path and ref_path.exists():
        parsed = _parse_message_file(ref_path)

    task_id = args.task_id or parsed.get("task_id", "")
    if not task_id:
        raise SystemExit("ERROR: --task-id is required (not found in message file either)")

    summary = args.message or parsed.get("summary", "")
    if not summary:
        raise SystemExit("ERROR: -m/--message is required (not found in message file either)")

    pref = f"{task_id}:"
    if summary.startswith(pref):
        summary = summary[len(pref):].lstrip()

    why = args.why if args.why != "n/a" else parsed.get("why", parsed.get("body", "n/a")) or "n/a"
    evidence = args.evidence if args.evidence != "n/a" else parsed.get("evidence", "n/a") or "n/a"
    message_ref = args.message_ref or ""

    return task_id, summary, message_ref, why, evidence


def _commit(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="git_tool commit", add_help=True)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("-m", "--message", default=None, help="Imperative summary text (without task prefix)")
    parser.add_argument("--message-ref", required=True)
    parser.add_argument("--why", default="n/a")
    parser.add_argument("--evidence", default="n/a")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = _resolve_repo(args.repo)
    _require_staged(repo)

    task_id, summary, message_ref, why, evidence = _resolve_commit_fields(args)

    commit_message = _render_template(
        task_id=task_id,
        summary=summary,
        message_ref=message_ref,
        why=why,
        evidence=evidence,
    )

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write(commit_message)
        msg_file = handle.name

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "commit", "-F", msg_file],
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        try:
            os.remove(msg_file)
        except OSError:
            pass

    if args.json:
        import json

        payload = {
            "status": "ok" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "repo": str(repo),
            "task_id": task_id,
            "message_ref": message_ref,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        print(json.dumps(payload, indent=2))
    else:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)

    return proc.returncode


def _commit_template(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="git_tool commit-template", add_help=True)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("-m", "--message", default=None)
    parser.add_argument("--message-ref", required=True)
    parser.add_argument("--why", default="n/a")
    parser.add_argument("--evidence", default="n/a")
    args = parser.parse_args(argv)

    task_id, summary, message_ref, why, evidence = _resolve_commit_fields(args)

    print(
        _render_template(
            task_id=task_id,
            summary=summary,
            message_ref=message_ref,
            why=why,
            evidence=evidence,
        )
    )
    return 0


def _reword(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="git_tool reword", add_help=True)
    parser.add_argument("sha", help="Commit SHA to reword")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("-m", "--message", default=None)
    parser.add_argument("--message-ref", required=True)
    parser.add_argument("--why", default="n/a")
    parser.add_argument("--evidence", default="n/a")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = _resolve_repo(args.repo)

    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True, capture_output=True, check=False,
    )
    if dirty.stdout.strip():
        raise SystemExit("ERROR: Refusing reword with uncommitted changes. Commit or stash first.")

    short = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", args.sha],
        text=True, capture_output=True, check=False,
    )
    if short.returncode != 0:
        raise SystemExit(f"ERROR: Unknown commit: {args.sha}")
    sha_short = short.stdout.strip()

    task_id, summary, message_ref, why, evidence = _resolve_commit_fields(args)
    commit_message = _render_template(
        task_id=task_id, summary=summary,
        message_ref=message_ref, why=why, evidence=evidence,
    )

    msg_file = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt")
    msg_file.write(commit_message)
    msg_file.close()

    try:
        env = os.environ.copy()
        env["GIT_SEQUENCE_EDITOR"] = f"sed -i 's/^pick {sha_short}/reword {sha_short}/'"
        env["GIT_EDITOR"] = f"cp {msg_file.name}"

        proc = subprocess.run(
            ["git", "-C", str(repo), "rebase", "-i", f"{args.sha}^"],
            text=True, capture_output=True, check=False, env=env,
        )
    finally:
        try:
            os.remove(msg_file.name)
        except OSError:
            pass

    if args.json:
        import json
        payload = {
            "status": "ok" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "sha": args.sha,
            "task_id": task_id,
            "message_ref": message_ref,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        print(json.dumps(payload, indent=2))
    else:
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)

    return proc.returncode


def _passthrough(argv: list[str]) -> int:
    if not BACKEND_BASH.exists():
        raise SystemExit(f"ERROR: backend missing: {BACKEND_BASH}")
    proc = subprocess.run([str(BACKEND_BASH), *argv], check=False)
    return proc.returncode


def main() -> int:
    base_parser = argparse.ArgumentParser(add_help=False)
    base_parser.add_argument("--base", default=None)
    known, remaining = base_parser.parse_known_args(sys.argv[1:])

    base = Path(resolve_dil_base(SCRIPT_DIR, known.base or os.environ.get("BASE_DIL"))).resolve()
    if base.name == "scripts" and base.parent.name == "_shared":
        base = (base / ".." / "..").resolve()
    log = ToolForgeLogger(SCRIPT_NAME, "run", str(base)) if ToolForgeLogger else None
    if log:
        log.section("Initialization")
        log.info(f"base: {base}")

    argv = remaining
    action = argv[0] if argv else "help"
    rest = argv[1:] if argv else []

    if action == "commit":
        rc = _commit(rest)
    elif action == "commit-template":
        rc = _commit_template(rest)
    elif action == "reword":
        rc = _reword(rest)
    else:
        rc = _passthrough(argv)

    if log:
        log.section("Result")
        log.info(f"action: {action}")
        log.info(f"exit_code: {rc}")
        log.close()

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
