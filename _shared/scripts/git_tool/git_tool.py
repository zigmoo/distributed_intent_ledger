#!/usr/bin/env python3
"""git_tool.py — Python front-end for deterministic, agent-safe git operations."""

from __future__ import annotations

import argparse
import os
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


def _render_template(task_id: str, summary: str, message_ref: str, why: str, evidence: str) -> str:
    template = COMMIT_TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace("{{task_id}}", task_id)
        .replace("{{summary}}", summary)
        .replace("{{message_ref}}", message_ref)
        .replace("{{why}}", why)
        .replace("{{evidence}}", evidence)
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


def _commit(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="git_tool commit", add_help=True)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("-m", "--message", required=True, help="Imperative summary text (without task prefix)")
    parser.add_argument("--message-ref", required=True)
    parser.add_argument("--why", default="n/a")
    parser.add_argument("--evidence", default="n/a")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = _resolve_repo(args.repo)
    _require_staged(repo)

    summary = args.message
    pref = f"{args.task_id}:"
    if summary.startswith(pref):
        summary = summary[len(pref):].lstrip()

    commit_message = _render_template(
        task_id=args.task_id,
        summary=summary,
        message_ref=args.message_ref,
        why=args.why,
        evidence=args.evidence,
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
            "task_id": args.task_id,
            "message_ref": args.message_ref,
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
    parser.add_argument("--task-id", required=True)
    parser.add_argument("-m", "--message", required=True)
    parser.add_argument("--message-ref", required=True)
    parser.add_argument("--why", default="n/a")
    parser.add_argument("--evidence", default="n/a")
    args = parser.parse_args(argv)

    summary = args.message
    pref = f"{args.task_id}:"
    if summary.startswith(pref):
        summary = summary[len(pref):].lstrip()

    print(
        _render_template(
            task_id=args.task_id,
            summary=summary,
            message_ref=args.message_ref,
            why=args.why,
            evidence=args.evidence,
        )
    )
    return 0


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
