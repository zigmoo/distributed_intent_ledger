#!/usr/bin/env python3
"""Minimal MCP stdio bridge for selected DIL direct-use tools.

This server intentionally exposes a small allowlist of existing *_tool scripts
and DIL scripts. The direct-use tools remain the source of behavior; this file
only adapts them to MCP for clients such as LM Studio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Literal


SERVER_NAME = "dil-tools"
SERVER_VERSION = "0.1.0"
SCRIPT_NAME = "mcp_dil_tools_server"
SCRIPT_VERSION = "2026-04-14"
SCRIPT_AUTHOR = "codex"
SCRIPT_MODEL = "gpt-5.4"
SCRIPT_OWNER = "moo"
IMPLEMENTATION_TASK_ID = "DIL-1452"
PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_TIMEOUT_SECONDS = 60
SERVER_INSTRUCTIONS = (
    "DIL tools exposes selected local DIL scripts through MCP. "
    "Call tools/list to discover available tools. "
    "The server does not expose resources or prompts."
)

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIL = Path(os.environ.get("BASE_DIL") or SCRIPT_DIR.parents[1]).resolve()
DOMAIN_ROOT = BASE_DIL / "_shared" / "domains" / "personal"
LOG_ROOT = DOMAIN_ROOT / "logs" / SCRIPT_NAME
DATA_ROOT = DOMAIN_ROOT / "data" / SCRIPT_NAME
START_TS = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
RUN_STAMP = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
HOSTNAME_SHORT = os.uname().nodename.split(".", 1)[0].lower() if hasattr(os, "uname") else "unknown"
PID = os.getpid()
SESSION_LOG_FILE = LOG_ROOT / f"{SCRIPT_NAME}.session.{RUN_STAMP}.{PID}.log"

DIL_SEARCH = SCRIPT_DIR / "dil_search.sh"
TASK_TOOL = SCRIPT_DIR / "task_tool.sh"
DIL_TOOL = SCRIPT_DIR / "dil_tool"
BROWSER_CDP_TOOL = SCRIPT_DIR / "browser_cdp_tool"
URL_TOOL = SCRIPT_DIR / "url_tool.sh"
GIT_TOOL = SCRIPT_DIR / "git_tool"
BASH_TOOL = SCRIPT_DIR / "bash_tool"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def safe_name(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() or ch in "._-" else "-" for ch in value)
    safe = safe.strip("-")
    return safe or "run"


def ensure_artifact_dirs() -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)


def append_log(level: str, message: str) -> None:
    ensure_artifact_dirs()
    with SESSION_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] [{SCRIPT_NAME}] [{level}] {message}\n")


def stderr_status(level: str, message: str) -> None:
    """Emit operator-visible status without contaminating MCP stdout."""
    if level != "ERROR" and os.environ.get("MCP_DIL_TOOLS_VERBOSE_STDERR") != "1":
        return
    print(f"[{utc_now()}] [{SCRIPT_NAME}] [{level}] {message}", file=sys.stderr, flush=True)


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    ensure_artifact_dirs()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def init_session_log() -> None:
    append_log("INFO", f"script_name: {SCRIPT_NAME}")
    append_log("INFO", f"script_version: {SCRIPT_VERSION}")
    append_log("INFO", f"script_author: {SCRIPT_AUTHOR}")
    append_log("INFO", f"script_model: {SCRIPT_MODEL}")
    append_log("INFO", f"script_owner: {SCRIPT_OWNER}")
    append_log("INFO", f"implementation_task_id: {IMPLEMENTATION_TASK_ID}")
    append_log("INFO", f"server_name: {SERVER_NAME}")
    append_log("INFO", f"server_version: {SERVER_VERSION}")
    append_log("INFO", f"hostname_short: {HOSTNAME_SHORT}")
    append_log("INFO", f"pid: {PID}")
    append_log("INFO", f"start_ts_utc: {START_TS}")
    append_log("INFO", f"base_dil: {BASE_DIL}")
    append_log("INFO", f"script_path: {Path(__file__).resolve()}")
    append_log("INFO", f"log_file: {SESSION_LOG_FILE}")
    append_log("INFO", f"data_root: {DATA_ROOT}")
    stderr_status("INFO", f"server_ready log_file={SESSION_LOG_FILE}")


def _text_schema(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "dil_search",
        "description": "Search DIL memory, tasks, preferences, and notes using the canonical DIL search script.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _text_schema("Search query."),
                "recall": {"type": "boolean", "description": "Use protocol-aligned recall mode.", "default": False},
                "scope": {
                    "type": "string",
                    "enum": ["all", "memory", "tasks", "preferences", "recall"],
                    "default": "all",
                },
                "domain": {"type": "string", "default": "all"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "context": {"type": "integer", "minimum": 0, "maximum": 10, "default": 1},
                "status": {"type": "string", "default": "active"},
                "json": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "task_search",
        "description": "Search DIL tasks through task_tool.sh search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": _text_schema("Comma-separated status filter, for example todo,in_progress."),
                "project": _text_schema("Exact project slug."),
                "domain": _text_schema("Registered domain name."),
                "latest": {"type": "integer", "minimum": 1, "maximum": 200},
                "count": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "task_review",
        "description": "Show full details for one DIL task through task_tool.sh review.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": _text_schema("Task id such as DIL-1452 or DMDI-12007.")},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dil_status",
        "description": "Run dil_tool status for DIL health and index drift checks.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "browser_cdp_tabs",
        "description": "List current Chromium CDP tabs using the DIL browser_cdp_tool.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "robinhood_portfolio",
        "description": "Read Robinhood holdings through browser_cdp_tool portfolio. This is a read-oriented direct-use DIL tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["shallow", "deep"], "default": "shallow"},
                "max_deep_holdings": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "robinhood_crypto_panel",
        "description": "Read visible Robinhood crypto panel state through browser_cdp_tool crypto-panel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": _text_schema("Crypto symbol, for example BTC."),
                "side": {"type": "string", "enum": ["buy", "sell"], "default": "buy"},
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "url_ticket",
        "description": "Format a remote ticket URL using url_tool.sh ticket for configured ticket-system prefixes.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket_id": _text_schema("Remote ticket id such as DMDI-12007.")},
            "required": ["ticket_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bash_exec",
        "description": (
            "Execute a local bash command through DIL bash_tool with audit logs and JSON artifacts. "
            "Normal mode refuses obvious destructive/system-control patterns. Set dangerous_ok=true only "
            "after explicit user authorization."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": _text_schema("Command string executed by bash -lc."),
                "cwd": _text_schema("Working directory. Defaults to DIL base if omitted."),
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 120},
                "purpose": _text_schema("Human-readable reason for audit logs."),
                "dangerous_ok": {"type": "boolean", "default": False},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_summary",
        "description": "Read a safe Git repository summary through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo": _text_schema("Repository path.")},
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_status",
        "description": "Read safe Git status through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo": _text_schema("Repository path.")},
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_diff",
        "description": "Read safe Git diff information through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "mode": {"type": "string", "enum": ["stat", "name-only", "full"], "default": "stat"},
                "cached": {"type": "boolean", "default": False},
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_log",
        "description": "Read recent Git commits through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "max": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_branch",
        "description": "List Git branch information through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"repo": _text_schema("Repository path.")},
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_add",
        "description": "Stage files through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Repo-relative file paths to stage.",
                },
            },
            "required": ["repo", "files"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_commit",
        "description": "Commit staged changes through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "message": _text_schema("Commit message."),
            },
            "required": ["repo", "message"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_pull",
        "description": "Run guarded git pull through DIL git_tool. Requires explicit yes=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "yes": {"type": "boolean", "default": False},
                "remote": _text_schema("Optional remote name."),
                "branch": _text_schema("Optional branch name."),
            },
            "required": ["repo", "yes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_push",
        "description": "Run guarded git push through DIL git_tool. Requires explicit yes=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "yes": {"type": "boolean", "default": False},
                "remote": _text_schema("Optional remote name."),
                "branch": _text_schema("Optional branch name."),
            },
            "required": ["repo", "yes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_branch_create",
        "description": "Create a local Git branch through DIL git_tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "branch": _text_schema("Branch name to create."),
                "start_point": _text_schema("Optional start point/ref."),
            },
            "required": ["repo", "branch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_branch_switch",
        "description": "Switch to an existing local Git branch through DIL git_tool. Refuses dirty worktrees.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "branch": _text_schema("Branch name to switch to."),
            },
            "required": ["repo", "branch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_branch_delete",
        "description": "Delete a fully merged local Git branch through DIL git_tool. Requires explicit yes=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "branch": _text_schema("Branch name to delete."),
                "yes": {"type": "boolean", "default": False},
            },
            "required": ["repo", "branch", "yes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_merge",
        "description": "Merge a branch through DIL git_tool. Defaults to fast-forward only and requires explicit yes=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _text_schema("Repository path."),
                "branch": _text_schema("Branch/ref to merge."),
                "yes": {"type": "boolean", "default": False},
                "mode": {"type": "string", "enum": ["ff-only", "no-ff"], "default": "ff-only"},
            },
            "required": ["repo", "branch", "yes"],
            "additionalProperties": False,
        },
    },
]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["BASE_DIL"] = str(BASE_DIL)
    return env


def _run(
    args: list[str],
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    tool_name: str = "command",
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    started_at = utc_now()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    artifact_base = DATA_ROOT / f"{SCRIPT_NAME}.{safe_name(tool_name)}.{stamp}.{PID}"
    latest_base = DATA_ROOT / f"{SCRIPT_NAME}.{safe_name(tool_name)}.latest"
    append_log("INFO", f"tool_call_start: {tool_name}")
    append_log("INFO", f"tool_call_command: {json.dumps(args)}")
    try:
        proc = subprocess.run(
            args,
            cwd=str(BASE_DIL),
            env=_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        payload = {
            "command": args,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "started_at": started_at,
            "ended_at": utc_now(),
            "duration_seconds": round(time.monotonic() - started_monotonic, 6),
            "log_file": str(SESSION_LOG_FILE),
            "data_file": str(artifact_base) + ".json",
        }
        write_json_file(Path(payload["data_file"]), payload)
        write_json_file(Path(str(latest_base) + ".json"), payload)
        append_log("INFO", f"tool_call_end: {tool_name} exit_code={proc.returncode}")
        append_log("INFO", f"tool_call_data_file: {payload['data_file']}")
        if proc.stderr:
            append_log("STDERR", proc.stderr.replace("\n", "\\n")[:4000])
        return payload
    except subprocess.TimeoutExpired as exc:
        payload = {
            "command": args,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": f"Command timed out after {timeout}s",
            "started_at": started_at,
            "ended_at": utc_now(),
            "duration_seconds": round(time.monotonic() - started_monotonic, 6),
            "log_file": str(SESSION_LOG_FILE),
            "data_file": str(artifact_base) + ".json",
        }
        write_json_file(Path(payload["data_file"]), payload)
        write_json_file(Path(str(latest_base) + ".json"), payload)
        append_log("ERROR", f"tool_call_timeout: {tool_name} timeout_seconds={timeout}")
        append_log("INFO", f"tool_call_data_file: {payload['data_file']}")
        return payload


def _require_file(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"Required tool not found: {path}")


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    is_error = payload.get("exit_code", 0) != 0
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, indent=2, sort_keys=False),
            }
        ],
        "isError": is_error,
    }


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}

    if name == "dil_search":
        _require_file(DIL_SEARCH)
        cmd = [
            str(DIL_SEARCH),
            str(args["query"]),
            "--scope",
            str(args.get("scope", "all")),
            "--domain",
            str(args.get("domain", "all")),
            "--limit",
            str(args.get("limit", 10)),
            "--context",
            str(args.get("context", 1)),
            "--status",
            str(args.get("status", "active")),
        ]
        if args.get("recall"):
            cmd.append("--recall")
        if args.get("json"):
            cmd.append("--json")
        return _tool_result(_run(cmd, tool_name=name))

    if name == "task_search":
        _require_file(TASK_TOOL)
        cmd = [str(TASK_TOOL), "search", "--json"]
        if args.get("status"):
            cmd += ["--status", str(args["status"])]
        if args.get("project"):
            cmd += ["--project", str(args["project"])]
        if args.get("domain"):
            cmd += ["--domain", str(args["domain"])]
        if args.get("latest"):
            cmd += ["--latest", str(args["latest"])]
        if args.get("count"):
            cmd.append("--count")
        return _tool_result(_run(cmd, tool_name=name))

    if name == "task_review":
        _require_file(TASK_TOOL)
        return _tool_result(_run([str(TASK_TOOL), "review", str(args["task_id"]), "--json"], tool_name=name))

    if name == "dil_status":
        _require_file(DIL_TOOL)
        return _tool_result(_run([str(DIL_TOOL), "status"], tool_name=name))

    if name == "browser_cdp_tabs":
        _require_file(BROWSER_CDP_TOOL)
        return _tool_result(_run([str(BROWSER_CDP_TOOL), "tabs"], tool_name=name))

    if name == "robinhood_portfolio":
        _require_file(BROWSER_CDP_TOOL)
        cmd = [str(BROWSER_CDP_TOOL), "portfolio", "--mode", str(args.get("mode", "shallow"))]
        if args.get("max_deep_holdings"):
            cmd += ["--max-deep-holdings", str(args["max_deep_holdings"])]
        return _tool_result(_run(cmd, timeout=180, tool_name=name))

    if name == "robinhood_crypto_panel":
        _require_file(BROWSER_CDP_TOOL)
        cmd = [
            str(BROWSER_CDP_TOOL),
            "crypto-panel",
            "--symbol",
            str(args["symbol"]).upper(),
            "--side",
            str(args.get("side", "buy")),
        ]
        return _tool_result(_run(cmd, timeout=120, tool_name=name))

    if name == "url_ticket":
        _require_file(URL_TOOL)
        return _tool_result(_run([str(URL_TOOL), "ticket", str(args["ticket_id"])], tool_name=name))

    if name == "bash_exec":
        _require_file(BASH_TOOL)
        cmd = [
            str(BASH_TOOL),
            "--command",
            str(args["command"]),
            "--cwd",
            str(args.get("cwd") or BASE_DIL),
            "--timeout",
            str(args.get("timeout_seconds", 120)),
            "--json",
        ]
        if args.get("purpose"):
            cmd += ["--purpose", str(args["purpose"])]
        if args.get("dangerous_ok"):
            cmd.append("--dangerous-ok")
        return _tool_result(_run(cmd, timeout=int(args.get("timeout_seconds", 120)) + 10, tool_name=name))

    if name == "git_summary":
        _require_file(GIT_TOOL)
        return _tool_result(_run([str(GIT_TOOL), "summary", "--repo", str(args["repo"]), "--json"], tool_name=name))

    if name == "git_status":
        _require_file(GIT_TOOL)
        return _tool_result(_run([str(GIT_TOOL), "status", "--repo", str(args["repo"]), "--json"], tool_name=name))

    if name == "git_diff":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "diff", "--repo", str(args["repo"]), "--json"]
        mode = str(args.get("mode", "stat"))
        if mode == "stat":
            cmd.append("--stat")
        elif mode == "name-only":
            cmd.append("--name-only")
        if args.get("cached"):
            cmd.append("--cached")
        return _tool_result(_run(cmd, tool_name=name))

    if name == "git_log":
        _require_file(GIT_TOOL)
        return _tool_result(
            _run([str(GIT_TOOL), "log", "--repo", str(args["repo"]), "--max", str(args.get("max", 10)), "--json"], tool_name=name)
        )

    if name == "git_branch":
        _require_file(GIT_TOOL)
        return _tool_result(_run([str(GIT_TOOL), "branch", "--repo", str(args["repo"]), "--json"], tool_name=name))

    if name == "git_add":
        _require_file(GIT_TOOL)
        files = args.get("files") or []
        if not isinstance(files, list) or not files:
            raise RuntimeError("git_add requires non-empty files array")
        return _tool_result(
            _run([str(GIT_TOOL), "add", "--repo", str(args["repo"]), "--json", "--", *[str(item) for item in files]], tool_name=name)
        )

    if name == "git_commit":
        _require_file(GIT_TOOL)
        return _tool_result(
            _run([str(GIT_TOOL), "commit", "--repo", str(args["repo"]), "--message", str(args["message"]), "--json"], tool_name=name)
        )

    if name == "git_pull":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "pull", "--repo", str(args["repo"]), "--json"]
        if args.get("yes"):
            cmd.append("--yes")
        if args.get("remote") and args.get("branch"):
            cmd += ["--remote", str(args["remote"]), "--branch", str(args["branch"])]
        return _tool_result(_run(cmd, timeout=180, tool_name=name))

    if name == "git_push":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "push", "--repo", str(args["repo"]), "--json"]
        if args.get("yes"):
            cmd.append("--yes")
        if args.get("remote") and args.get("branch"):
            cmd += ["--remote", str(args["remote"]), "--branch", str(args["branch"])]
        return _tool_result(_run(cmd, timeout=180, tool_name=name))

    if name == "git_branch_create":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "branch-create", "--repo", str(args["repo"]), "--branch", str(args["branch"]), "--json"]
        if args.get("start_point"):
            cmd += ["--start-point", str(args["start_point"])]
        return _tool_result(_run(cmd, tool_name=name))

    if name == "git_branch_switch":
        _require_file(GIT_TOOL)
        return _tool_result(
            _run([str(GIT_TOOL), "branch-switch", "--repo", str(args["repo"]), "--branch", str(args["branch"]), "--json"], tool_name=name)
        )

    if name == "git_branch_delete":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "branch-delete", "--repo", str(args["repo"]), "--branch", str(args["branch"]), "--json"]
        if args.get("yes"):
            cmd.append("--yes")
        return _tool_result(_run(cmd, tool_name=name))

    if name == "git_merge":
        _require_file(GIT_TOOL)
        cmd = [str(GIT_TOOL), "merge", "--repo", str(args["repo"]), "--branch", str(args["branch"]), "--json"]
        if args.get("yes"):
            cmd.append("--yes")
        if str(args.get("mode", "ff-only")) == "no-ff":
            cmd.append("--no-ff")
        else:
            cmd.append("--ff-only")
        return _tool_result(_run(cmd, timeout=180, tool_name=name))

    raise RuntimeError(f"Unknown tool: {name}")


def _response(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    append_log("DEBUG", f"mcp_method: {method} id={msg_id}")

    if method == "initialize":
        append_log("INFO", "mcp_initialize")
        append_log("DEBUG", f"mcp_initialize_params: {json.dumps(params, separators=(',', ':'))[:4000]}")
        stderr_status("INFO", f"mcp_initialize id={msg_id}")
        requested_protocol = str(params.get("protocolVersion", PROTOCOL_VERSION))
        agreed_protocol = (
            requested_protocol
            if requested_protocol in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[-1]
        )
        append_log("INFO", f"mcp_protocol_agreed requested={requested_protocol} agreed={agreed_protocol}")
        return _response(
            msg_id,
            {
                "protocolVersion": agreed_protocol,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return _response(msg_id, {})

    if method == "tools/list":
        append_log("INFO", f"mcp_tools_list count={len(TOOLS)}")
        stderr_status("INFO", f"mcp_tools_list count={len(TOOLS)}")
        return _response(msg_id, {"tools": TOOLS})

    if method == "resources/list":
        append_log("INFO", "mcp_resources_list count=0")
        return _response(msg_id, {"resources": []})

    if method == "resourceTemplates/list":
        append_log("INFO", "mcp_resource_templates_list count=0")
        return _response(msg_id, {"resourceTemplates": []})

    if method == "prompts/list":
        append_log("INFO", "mcp_prompts_list count=0")
        return _response(msg_id, {"prompts": []})

    if method == "tools/call":
        try:
            append_log("INFO", f"mcp_tools_call name={params.get('name')}")
            stderr_status("INFO", f"mcp_tools_call name={params.get('name')}")
            return _response(msg_id, call_tool(str(params.get("name", "")), params.get("arguments") or {}))
        except Exception as exc:  # Keep MCP server alive and return error content.
            append_log("ERROR", f"mcp_tools_call_error name={params.get('name')} error={type(exc).__name__}: {exc}")
            stderr_status("ERROR", f"mcp_tools_call_error name={params.get('name')} error={type(exc).__name__}: {exc}")
            return _response(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                },
            )

    if msg_id is None:
        return None

    return _error(msg_id, -32601, f"Method not found: {method}")


TransportMode = Literal["content-length", "json-line"]


def read_message(stream: BinaryIO) -> tuple[dict[str, Any], TransportMode] | None:
    line = stream.readline()
    if not line:
        return None

    while line in (b"\n", b"\r\n"):
        line = stream.readline()
        if not line:
            return None

    if line.lower().startswith(b"content-length:"):
        length = int(line.decode("ascii").split(":", 1)[1].strip())
        while True:
            header = stream.readline()
            if header in (b"\n", b"\r\n", b""):
                break
        body = stream.read(length)
        return json.loads(body.decode("utf-8")), "content-length"

    return json.loads(line.decode("utf-8")), "json-line"


def write_message(message: dict[str, Any], mode: TransportMode) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if mode == "content-length":
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(body)
    else:
        sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()
    append_log(
        "DEBUG",
        f"mcp_response_sent id={message.get('id')} mode={mode} bytes={len(body)} has_error={'error' in message}",
    )


def main() -> int:
    init_session_log()
    response_mode: TransportMode = "json-line"
    while True:
        try:
            read_result = read_message(sys.stdin.buffer)
        except json.JSONDecodeError as exc:
            append_log("ERROR", f"mcp_parse_error: {exc}")
            stderr_status("ERROR", f"mcp_parse_error: {exc}")
            write_message(_error(None, -32700, f"Parse error: {exc}"), response_mode)
            continue
        except BrokenPipeError as exc:
            append_log("ERROR", f"mcp_read_broken_pipe: {exc}")
            stderr_status("ERROR", f"mcp_read_broken_pipe: {exc}")
            return 1

        if read_result is None:
            append_log("INFO", "stdin_closed; mcp_server_exit")
            stderr_status("INFO", "stdin_closed; mcp_server_exit")
            return 0

        message, response_mode = read_result
        append_log("DEBUG", f"mcp_request_transport mode={response_mode}")
        response = handle(message)
        if response is not None:
            try:
                write_message(response, response_mode)
            except BrokenPipeError as exc:
                append_log("ERROR", f"mcp_write_broken_pipe id={response.get('id')}: {exc}")
                stderr_status("ERROR", f"mcp_write_broken_pipe id={response.get('id')}: {exc}")
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
