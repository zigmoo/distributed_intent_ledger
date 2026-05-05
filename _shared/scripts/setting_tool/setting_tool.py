#!/usr/bin/env python3
"""setting_tool.py — Read and update DIL global settings with defaults."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base

try:
    from tool_forge_log import ToolForgeLogger
except ImportError:
    ToolForgeLogger = None

SCRIPT_NAME = "setting_tool"
DEFAULT_SETTINGS_FILE = "_shared/_meta/agent_runtime_policy.json"
DEFAULTS: dict[str, Any] = {
    "scriptForgeQcDashboardBuildRetentionCount": 30,
    "scriptForgeQcDataRetentionWindowDays": 180,
    "scriptForgeQcDataRetentionMaxTestExecutions": 500,
}


def fail(code: int, message: str) -> None:
    print(f"ERR | {code} | {message}", file=sys.stderr)
    raise SystemExit(code)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def settings_path(base: Path, override: str | None) -> Path:
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else base / path
    return base / DEFAULT_SETTINGS_FILE


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(2, f"Invalid JSON in settings registry {path}: {exc}")
    if not isinstance(payload, dict):
        fail(2, f"Settings registry must contain a JSON object: {path}")
    return payload


def write_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def parse_value(raw: str, value_type: str) -> Any:
    if value_type == "json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            fail(2, f"Invalid JSON value: {exc}")
    if value_type == "str":
        return raw
    if value_type == "int":
        try:
            return int(raw)
        except ValueError:
            fail(2, f"Invalid integer value: {raw}")
    if value_type == "float":
        try:
            return float(raw)
        except ValueError:
            fail(2, f"Invalid float value: {raw}")
    if value_type == "decimal":
        try:
            Decimal(raw)
        except InvalidOperation:
            fail(2, f"Invalid decimal value: {raw}")
        return raw
    if value_type == "bool":
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        fail(2, f"Invalid boolean value: {raw}")
    if value_type == "date":
        try:
            dt.date.fromisoformat(raw)
        except ValueError:
            fail(2, f"Invalid date value, expected YYYY-MM-DD: {raw}")
        return raw
    if value_type == "timestamp":
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            dt.datetime.fromisoformat(normalized)
        except ValueError:
            fail(2, f"Invalid timestamp value, expected ISO-8601: {raw}")
        return raw
    if value_type == "sequence":
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = [item.strip() for item in raw.split(",") if item.strip()]
        if not isinstance(value, list):
            fail(2, "Sequence value must be a JSON array or comma-separated list")
        return value
    if value_type == "path":
        value = os.path.expandvars(os.path.expanduser(raw.strip()))
        if not value:
            fail(2, "Path value must not be empty")
        if "\x00" in value:
            fail(2, "Path value must not contain NUL bytes")
        return value
    if value_type == "url":
        value = raw.strip()
        if not value or any(ch.isspace() for ch in value):
            fail(2, "URL value must not be empty or contain whitespace")
        parsed = urlparse(value)
        if not parsed.scheme:
            fail(2, f"URL value must include a scheme: {raw}")
        if parsed.scheme in {"http", "https"} and not parsed.netloc:
            fail(2, f"HTTP(S) URL value must include a host: {raw}")
        return value
    fail(2, f"Unsupported value type: {value_type}")


def effective_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULTS)
    merged.update(settings)
    return merged


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def command_get(args: argparse.Namespace, path: Path) -> int:
    settings = load_settings(path)
    if args.key in settings:
        value = settings[args.key]
        source = "registry"
    elif args.key in DEFAULTS:
        value = DEFAULTS[args.key]
        source = "default"
    else:
        fail(3, f"setting not found: {args.key}")

    payload = {"ok": True, "key": args.key, "value": value, "source": source, "path": str(path)}
    if args.json:
        emit_json(payload)
    else:
        print(f"{args.key}={json.dumps(value)} | source={source} | path={path}")
    return 0


def command_set(args: argparse.Namespace, path: Path) -> int:
    settings = load_settings(path)
    value = parse_value(args.value, args.type)
    old_value = settings.get(args.key)
    existed = args.key in settings
    settings[args.key] = value
    settings["updatedAt"] = now_utc()
    settings.setdefault("source", "setting_tool")

    if not args.dry_run:
        write_settings(path, settings)

    payload = {
        "ok": True,
        "dry_run": args.dry_run,
        "action": "update" if existed else "add",
        "key": args.key,
        "old_value": old_value,
        "value": value,
        "path": str(path),
    }
    if args.json:
        emit_json(payload)
    else:
        marker = "DRY RUN" if args.dry_run else "OK"
        print(f"{marker} | {payload['action']} | {args.key}={json.dumps(value)} | path={path}")
    return 0


def command_list(args: argparse.Namespace, path: Path) -> int:
    settings = load_settings(path)
    effective = effective_settings(settings) if args.include_defaults else settings
    if args.json:
        rows = []
        for key, value in effective.items():
            source = "registry" if key in settings else "default"
            rows.append({"key": key, "value": value, "source": source})
        emit_json({"ok": True, "path": str(path), "settings": rows})
    else:
        for key in sorted(effective):
            source = "registry" if key in settings else "default"
            print(f"{key}={json.dumps(effective[key])} | source={source}")
    return 0


def command_defaults(args: argparse.Namespace) -> int:
    if args.json:
        emit_json({"ok": True, "defaults": DEFAULTS})
    else:
        for key in sorted(DEFAULTS):
            print(f"{key}={json.dumps(DEFAULTS[key])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="setting_tool",
        description="Read and update DIL global settings with defaults",
    )
    parser.add_argument("--base", required=True, help="DIL base path")
    parser.add_argument("--settings-file", help=f"settings registry path (default: {DEFAULT_SETTINGS_FILE})")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--dry-run", action="store_true", help="preview without side effects")
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_parser = subparsers.add_parser("get", help="read one setting, falling back to defaults")
    get_parser.add_argument("key")

    set_parser = subparsers.add_parser("set", help="add or update one setting")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument(
        "--type",
        choices=[
            "json",
            "str",
            "int",
            "float",
            "decimal",
            "bool",
            "date",
            "timestamp",
            "sequence",
            "path",
            "url",
        ],
        default="json",
        help="value parser (default: json)",
    )

    list_parser = subparsers.add_parser("list", help="list settings")
    list_parser.add_argument(
        "--include-defaults",
        action="store_true",
        help="include defaulted values that are not present in the registry",
    )

    subparsers.add_parser("defaults", help="list built-in defaults")

    arguments = parser.parse_args()

    base = Path(arguments.base).expanduser().resolve()
    path = settings_path(base, arguments.settings_file)

    log = ToolForgeLogger(SCRIPT_NAME, arguments.command, str(base)) if ToolForgeLogger else None

    if log:
        log.section("Initialization")
        log.info(f"base: {base}")
        log.info(f"settings_file: {path}")
        log.info(f"command: {arguments.command}")
        log.info(f"dry_run: {arguments.dry_run}")

    if log:
        log.section("Processing")

    if arguments.command == "get":
        result = command_get(arguments, path)
    elif arguments.command == "set":
        result = command_set(arguments, path)
    elif arguments.command == "list":
        result = command_list(arguments, path)
    elif arguments.command == "defaults":
        result = command_defaults(arguments)
    else:
        fail(2, f"unsupported command: {arguments.command}")

    if log:
        log.section("Result")
        log.info("done")
        log.close()

    return result


if __name__ == "__main__":
    raise SystemExit(main())
