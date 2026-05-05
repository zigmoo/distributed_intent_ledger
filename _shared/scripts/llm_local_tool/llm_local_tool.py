#!/usr/bin/env python3
"""
llm_local_tool.py — Local LLM discovery, testing, and registry management.

Full Script Forge Standards compliance.
Single J2 pipeline → identical console/log output.
Dynamic column widths, active/inactive split, TPS from registry.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import socket
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR / "lib"))

from resolve_base import resolve_dil_base
import script_forge_renderer

try:
    from tool_forge_log import ToolForgeLogger
except ImportError:
    ToolForgeLogger = None

SCRIPT_NAME = "llm_local_tool"

LMSTUDIO_ENDPOINTS_BY_HOST = {
    "framemoowork": "http://10.0.1.130:1234/v1/chat/completions",
    "moosacrem1promax": "http://100.72.152.28:1234/v1/chat/completions",
}

LMSTUDIO_INVENTORY_HOSTS = ("framemoowork", "moosacrem1promax")

SSH_TARGETS_BY_HOST = {
    "moosacrem1promax": [
        "moosacrem1promax.jay-frog.ts.net",
        "moosacrem1promax.local",
    ],
}

DEFAULT_PROVIDER_ENDPOINTS = {
    "lmstudio": "http://127.0.0.1:1234/v1/chat/completions",
    "ollama": "http://framemoowork:11434/v1/chat/completions",
}


class LoadGuardrailsError(RuntimeError):
    """Raised when LM Studio refuses a model load due to local resource guardrails."""


def _ssh_target_for_host(host: str) -> str:
    targets = SSH_TARGETS_BY_HOST.get(host)
    if not targets:
        return host
    if isinstance(targets, str):
        return targets
    return targets[0]

def main() -> int:
    start_time = time.time()

    parser = argparse.ArgumentParser(prog=SCRIPT_NAME, description="Local LLM management tool")
    parser.add_argument("--base", required=True)
    parser.add_argument("--host", help="Prefer this host when resolving a local model (for example framemoowork or moosacrem1promax)")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds for test requests")
    parser.add_argument("subcommand", nargs="?", default="report")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    base = Path(resolve_dil_base(SCRIPT_DIR))
    log = ToolForgeLogger(SCRIPT_NAME, "run", str(base)) if ToolForgeLogger else None

    if log:
        log.section("Processing")

    subcmd = args.subcommand

    if subcmd in ("report", "", None):
        render_report(base, log)
    elif subcmd == "list":
        render_list(base, log)
    elif subcmd == "sync":
        sync_result = sync_inventory(base, log)
        print(
            "✓ SYNC | hosts={hosts} | updated={updated} | added={added} | missing={missing} | errors={errors} | rows={rows}".format(
                hosts=",".join(sorted(set(sync_result["hosts"]))) or "none",
                updated=sync_result["updated"],
                added=sync_result["added"],
                missing=sync_result["missing"],
                errors=len(sync_result.get("errors", [])),
                rows=sync_result["rows"],
            )
        )
    elif subcmd == "opencode":
        if not args.args:
            print("Available opencode actions: add, sync")
        elif args.args[0] == "add":
            opencode_parser = argparse.ArgumentParser(prog=f"{SCRIPT_NAME} opencode add")
            opencode_parser.add_argument("--config-host", required=True, help="Host whose ~/.config/opencode/opencode.json should be updated")
            opencode_parser.add_argument("--model-ref", required=True, help="Registry model reference to add to opencode")
            opencode_parser.add_argument("--source-host", help="Restrict registry resolution to this host")
            opencode_parser.add_argument("--server", help="Restrict registry resolution to this server (for example lmstudio or ollama)")
            opencode_parser.add_argument("--alias", help="Override the opencode model key")
            opencode_parser.add_argument("--set-default", action="store_true", help="Make the added model the default opencode model")
            opencode_parser.add_argument("--force", action="store_true", help="Write the opencode config even if the model preflight fails")
            opencode_parser.add_argument("--probe-prompt", default="ping", help="Prompt used for the preflight model test")
            op_args = opencode_parser.parse_args(args.args[1:])
            result = opencode_add_model(
                base,
                config_host=op_args.config_host,
                model_ref=op_args.model_ref,
                source_host=op_args.source_host,
                server=op_args.server,
                alias=op_args.alias,
                set_default=op_args.set_default,
                force=op_args.force,
                probe_prompt=op_args.probe_prompt,
                log=log,
            )
            if not result.get("ok"):
                preflight = result.get("preflight", {})
                reason = result.get("reason", "preflight_failed")
                error = preflight.get("error") or "model did not respond"
                tps = preflight.get("tps")
                latency = preflight.get("latency_ms")
                probe_bits = []
                if tps is not None:
                    probe_bits.append(f"tps={tps:.1f}")
                if latency is not None:
                    probe_bits.append(f"latency={latency}ms")
                probe_text = " | ".join(probe_bits) if probe_bits else "no response"
                print(
                    "✗ OPENCODE | config_host={config_host} | source_host={source_host} | server={server} | model={model_key} | preflight={preflight} | reason={reason} | error={error}".format(
                        config_host=result["config_host"],
                        source_host=result["source_host"],
                        server=result["server"],
                        model_key=result["model_key"],
                        preflight=probe_text,
                        reason=reason,
                        error=error,
                    )
                )
            else:
                preflight = result.get("preflight", {})
                tps = preflight.get("tps")
                latency = preflight.get("latency_ms")
                print(
                    "✓ OPENCODE | config_host={config_host} | source_host={source_host} | server={server} | model={model_key} | preflight_tps={tps} | preflight_latency={latency}ms | default={default} | changed={changed} | path={path}".format(
                        config_host=result["config_host"],
                        source_host=result["source_host"],
                        server=result["server"],
                        model_key=result["model_key"],
                        tps=f"{tps:.1f}" if tps is not None else "n/a",
                        latency=latency if latency is not None else "n/a",
                        default=str(result["set_default"]).lower(),
                        changed=str(result["changed"]).lower(),
                        path=result["write_result"].get("path", _opencode_config_path()),
                )
            )
        elif args.args[0] == "sync":
            opencode_parser = argparse.ArgumentParser(prog=f"{SCRIPT_NAME} opencode sync")
            opencode_parser.add_argument("--config-host", required=True, help="Host whose ~/.config/opencode/opencode.json should be updated")
            opencode_parser.add_argument("--source-host", default="moosacrem1promax", help="Registry host to sync into opencode (default: moosacrem1promax)")
            opencode_parser.add_argument("--server", default="lmstudio", help="Registry server to sync (default: lmstudio)")
            opencode_parser.add_argument("--alias-prefix", help="Optional alias prefix for generated model keys")
            opencode_parser.add_argument("--set-default", action="store_true", help="Make the fastest synced model the default opencode model")
            op_args = opencode_parser.parse_args(args.args[1:])
            result = opencode_sync_models(
                base,
                config_host=op_args.config_host,
                source_host=op_args.source_host,
                server=op_args.server,
                alias_prefix=op_args.alias_prefix,
                set_default=op_args.set_default,
                log=log,
            )
            print(
                "✓ OPENCODE SYNC | config_host={config_host} | source_host={source_host} | server={server} | models={count} | default={default} | changed={changed} | path={path}".format(
                    config_host=result["config_host"],
                    source_host=result["source_host"],
                    server=result["server"],
                    count=len(result["models"]),
                    default=result.get("default_model") or "n/a",
                    changed=str(result["changed"]).lower(),
                    path=result["write_result"].get("path", _opencode_config_path()),
                )
            )
        else:
            print("Available opencode actions: add, sync")
    elif subcmd == "test" and args.args:
        test_model(
            args.args[0],
            " ".join(args.args[1:]) if len(args.args) > 1 else "hello",
            base,
            log,
            timeout_seconds=args.timeout,
            preferred_host=args.host,
        )
    else:
        print("Available: report, list, sync, opencode add, opencode sync, test <model-or-registry-id> <prompt>")
        print("  Bare registry IDs are resolved via _shared/_meta/model_registry.jsonl.")
        print("  Optional: --host <framemoowork|moosacrem1promax> to prefer a specific LM Studio host.")

    if log:
        duration = time.time() - start_time
        log.info(f"complete | duration={duration:.2f}s")
        log.close()

    return 0

def load_registry(base: Path) -> List[Dict[str, Any]]:
    """Load model registry (JSONL)."""
    path = base / "_shared" / "_meta" / "model_registry.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line.strip()) for line in f if line.strip()]

def short_hostname() -> str:
    return socket.gethostname().split(".")[0]

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _entry_aliases(entry: Dict[str, Any]) -> List[str]:
    aliases = entry.get("aliases") or []
    if isinstance(aliases, str):
        return [aliases]
    return [str(alias) for alias in aliases if alias]

def _entry_candidates(entry: Dict[str, Any]) -> List[str]:
    candidates = [entry.get("model_id"), entry.get("display_name")]
    candidates.extend(_entry_aliases(entry))
    candidates.append(entry.get("backend_model_id"))
    file_path = str(entry.get("file_path") or "")
    if file_path:
        candidates.append(os.path.basename(file_path))
    return [str(candidate) for candidate in candidates if candidate]

def _normalize_model_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "/" in text:
        text = text.split("/", 1)[-1]
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text

def _entry_match_keys(entry: Dict[str, Any]) -> List[str]:
    keys = set()
    for candidate in _entry_candidates(entry):
        normalized = _normalize_model_key(candidate)
        if candidate:
            keys.add(candidate)
        if normalized:
            keys.add(normalized)
            for suffix in ("-gguf", "-mlx-4bit", "-mlx-8bit", "-mlx", "-4bit", "-8bit"):
                if normalized.endswith(suffix):
                    keys.add(normalized[: -len(suffix)])
    return [key for key in keys if key]

def _host_endpoint(host: str, server: str) -> str:
    if server == "lmstudio":
        return LMSTUDIO_ENDPOINTS_BY_HOST.get(host, DEFAULT_PROVIDER_ENDPOINTS["lmstudio"])
    if server == "ollama":
        return DEFAULT_PROVIDER_ENDPOINTS["ollama"]
    raise ValueError(f"Unsupported server: {server}")

def _ssh_targets_for_host(host: str) -> List[str]:
    targets = SSH_TARGETS_BY_HOST.get(host)
    if not targets:
        return [host]
    if isinstance(targets, str):
        return [targets]
    return list(targets)

def _run_host_shell_command(host: str, argv: List[str], log=None, timeout: int = 900, input_text: str | None = None) -> subprocess.CompletedProcess:
    current_host = short_hostname()
    if host == current_host:
        if log:
            log.info(f"command requested locally | host={host} | argv={' '.join(argv)}")
        return subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            input=input_text,
        )

    remote_cmd = " ".join(shlex.quote(part) for part in argv)
    last_result = None
    for ssh_target in _ssh_targets_for_host(host):
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            ssh_target,
            remote_cmd,
        ]
        if log:
            log.info(f"command requested remotely | host={host} | ssh_target={ssh_target} | argv={' '.join(argv)}")
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            input=input_text,
        )
        last_result = result
        if result.returncode == 0:
            return result

        stderr = (result.stderr or result.stdout or "").strip().lower()
        connection_failure = any(
            phrase in stderr
            for phrase in (
                "could not resolve hostname",
                "temporary failure in name resolution",
                "connection timed out",
                "no route to host",
                "connection refused",
            )
        )
        if not connection_failure:
            return result

    return last_result

def _run_inventory_command(host: str, scope: str, log=None) -> subprocess.CompletedProcess:
    argv = ["lms", "ls", "--json"]
    if scope == "llm":
        argv.append("--llm")
    elif scope == "embedding":
        argv.append("--embedding")
    else:
        raise ValueError(f"Unsupported inventory scope: {scope}")
    return _run_host_shell_command(host, argv, log=log, timeout=900)

def _filesystem_inventory_script() -> str:
    return r'''
import json
import os
from datetime import datetime, timezone
from pathlib import Path

def dir_size(path: Path):
    total = 0
    newest = None
    for root, _, files in os.walk(path):
        for name in files:
            full = Path(root) / name
            try:
                st = full.stat()
            except OSError:
                continue
            total += st.st_size
            if newest is None or st.st_mtime > newest:
                newest = st.st_mtime
    return total, newest

root = Path.home() / ".lmstudio" / "models"
rows = []
if root.exists():
    for provider in sorted([p for p in root.iterdir() if p.is_dir()]):
        for model_dir in sorted([p for p in provider.iterdir() if p.is_dir()]):
            size_bytes, latest = dir_size(model_dir)
            rows.append({
                "collection": provider.name,
                "model_dir": model_dir.name,
                "path": str(model_dir),
                "size_bytes": size_bytes,
                "last_modified": datetime.fromtimestamp(latest, timezone.utc).strftime("%Y-%m-%d") if latest else "",
            })
print(json.dumps(rows))
'''

def _run_filesystem_inventory_command(host: str, log=None) -> subprocess.CompletedProcess:
    argv = ["python3", "-c", _filesystem_inventory_script()]
    return _run_host_shell_command(host, argv, log=log, timeout=900)

def _opencode_config_path() -> Path:
    override = os.environ.get("OPENCODE_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "opencode" / "opencode.json"

def _opencode_remote_read_script() -> str:
    return r'''
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("{}")
else:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("{}")
    else:
        print(json.dumps(payload, separators=(",", ":")))
'''

def _opencode_remote_write_script() -> str:
    return r'''
import json
import sys
from datetime import datetime
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(sys.stdin.read() or "{}")
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    backup = path.with_name(f"{path.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(json.dumps({"ok": True, "path": str(path)}))
'''

def _load_opencode_config(host: str, log=None) -> Dict[str, Any]:
    path = _opencode_config_path()
    if host == short_hostname():
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    result = _run_host_shell_command(
        host,
        ["python3", "-c", _opencode_remote_read_script(), str(path)],
        log=log,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"failed to read opencode config on {host}")
    try:
        payload = _decode_json_from_output(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid opencode config JSON on {host}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}

def _write_opencode_config(host: str, config: Dict[str, Any], log=None) -> Dict[str, Any]:
    path = _opencode_config_path()
    payload_text = json.dumps(config, indent=2, sort_keys=False) + "\n"
    backup_text = None
    if host == short_hostname():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup_text = path.read_text(encoding="utf-8")
            backup = path.with_name(f"{path.name}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            backup.write_text(backup_text, encoding="utf-8")
        path.write_text(payload_text, encoding="utf-8")
        return {"ok": True, "path": str(path), "backup_path": str(backup) if backup_text is not None else None}

    result = _run_host_shell_command(
        host,
        ["python3", "-c", _opencode_remote_write_script(), str(path)],
        log=log,
        timeout=120,
        input_text=payload_text,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or f"failed to write opencode config on {host}")
    try:
        payload = _decode_json_from_output(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid opencode write response on {host}: {exc}") from exc
    if not isinstance(payload, dict):
        return {"ok": True, "path": str(path), "backup_path": None}
    payload.setdefault("path", str(path))
    payload.setdefault("backup_path", None)
    return payload

def _sanitize_opencode_key(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text or "model"

def _opencode_base_url_for_entry(entry: Dict[str, Any]) -> str:
    host = str(entry.get("host") or short_hostname())
    server = str(entry.get("server") or "lmstudio")
    endpoint = _host_endpoint(host, server)
    if endpoint.endswith("/chat/completions"):
        return endpoint[: -len("/chat/completions")]
    return endpoint

def _opencode_default_alias(entry: Dict[str, Any], alias: str | None = None) -> str:
    if alias:
        return _sanitize_opencode_key(alias)
    aliases = _entry_aliases(entry)
    if aliases:
        return _sanitize_opencode_key(aliases[0])
    display_name = str(entry.get("display_name") or entry.get("model_id") or "model")
    return _sanitize_opencode_key(display_name.split("/")[-1])

def _opencode_display_name(entry: Dict[str, Any], alias: str | None = None) -> str:
    if alias:
        return alias
    display_name = str(entry.get("display_name") or entry.get("model_id") or "Local Model")
    return display_name

def _apply_opencode_model_mapping(
    config: Dict[str, Any],
    *,
    provider_name: str,
    provider_display_name: str,
    model_key: str,
    model_id: str,
    model_name: str,
    base_url: str,
    set_default: bool,
) -> Dict[str, Any]:
    config = dict(config or {})
    provider_root = config.setdefault("provider", {})
    provider = provider_root.setdefault(provider_name, {})
    provider.setdefault("npm", "@ai-sdk/openai-compatible")
    provider["name"] = provider_display_name
    provider_models = provider.setdefault("models", {})
    provider_options = provider.setdefault("options", {})
    provider_options["baseURL"] = base_url
    provider_options["extraHeaders"] = {"Authorization": "Bearer lm-studio"}
    provider_models[model_key] = {"id": model_id, "name": model_name}
    if set_default:
        config["model"] = f"{provider_name}/{model_key}"
    return config

def _format_opencode_tps_label(name: str, tps: Any) -> str:
    if tps is None:
        return str(name)
    try:
        tps_value = float(tps)
    except (TypeError, ValueError):
        return str(name)
    return f"{name} ({tps_value:.1f} TPS)"

def _lmstudio_api_model_ids(host: str, log=None) -> List[str]:
    """
    Return live LM Studio OpenAI-compatible /v1/models IDs as seen from the target host.
    Falls back to an empty list if the API is unreachable.
    """
    script = r'''
import json
import urllib.request

url = "http://127.0.0.1:1234/v1/models"
try:
    with urllib.request.urlopen(url, timeout=8) as r:
        payload = json.loads(r.read().decode("utf-8"))
except Exception:
    print("[]")
else:
    ids = []
    for item in payload.get("data", []):
        mid = str(item.get("id") or "").strip()
        if mid:
            ids.append(mid)
    print(json.dumps(ids, separators=(",", ":")))
'''
    result = _run_host_shell_command(host, ["python3", "-c", script], log=log, timeout=20)
    if result.returncode != 0:
        return []
    try:
        payload = _decode_json_from_output(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item).strip() for item in payload if str(item).strip()]

def _choose_api_model_id(row: Dict[str, Any], live_api_ids: List[str]) -> str:
    """
    Prefer a live slash-ID from LM Studio /v1/models, matched against registry aliases.
    Fallback to registry backend/model IDs.
    """
    fallback = str(row.get("backend_model_id") or row.get("model_id") or "").strip()
    if not live_api_ids:
        return fallback

    candidate_keys = [key for key in _entry_match_keys(row) if key]
    normalized_candidates = {_normalize_model_key(key) for key in candidate_keys if key}
    normalized_candidates.discard("")

    api_scored: List[tuple[int, str]] = []
    for api_id in live_api_ids:
        norm_api = _normalize_model_key(api_id)
        if not norm_api:
            continue
        if norm_api in normalized_candidates:
            api_scored.append((2, api_id))
            continue
        if any(norm_api.startswith(c) or c.startswith(norm_api) for c in normalized_candidates):
            api_scored.append((1, api_id))

    if api_scored:
        api_scored.sort(key=lambda item: (-item[0], item[1]))
        return api_scored[0][1]
    return fallback

def _registry_rows_for_opencode_sync(base: Path, source_host: str, server: str = "lmstudio") -> List[Dict[str, Any]]:
    registry = load_registry(base)
    rows = [
        row for row in registry
        if str(row.get("host") or "") == source_host
        and str(row.get("server") or "") == server
        and str(row.get("status") or "") != "missing"
    ]
    rows.sort(key=lambda row: (
        -float(row.get("tps")) if row.get("tps") not in (None, "") else 0.0,
        str(row.get("display_name") or row.get("model_id") or ""),
    ))
    return rows

def _opencode_sync_model_map(
    base: Path,
    *,
    source_host: str,
    server: str = "lmstudio",
    log=None,
    alias_prefix: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    models: Dict[str, Dict[str, Any]] = {}
    live_api_ids = _lmstudio_api_model_ids(source_host, log=log) if server == "lmstudio" else []
    for row in _registry_rows_for_opencode_sync(base, source_host, server=server):
        alias = _sanitize_opencode_key(alias_prefix or _opencode_default_alias(row))
        name = _format_opencode_tps_label(_opencode_display_name(row), row.get("tps"))
        api_id = _choose_api_model_id(row, live_api_ids)
        models[alias] = {
            "id": api_id,
            "name": name,
        }
        # Add a second alias based on the API ID to reduce key mismatch errors.
        api_alias = _sanitize_opencode_key(str(api_id).split("/")[-1]) if api_id else alias
        if api_alias and api_alias not in models:
            models[api_alias] = {
                "id": api_id,
                "name": name,
            }
    return models

def opencode_sync_models(
    base: Path,
    *,
    config_host: str,
    source_host: str = "moosacrem1promax",
    server: str = "lmstudio",
    alias_prefix: str | None = None,
    set_default: bool = False,
    log=None,
) -> Dict[str, Any]:
    config = _load_opencode_config(config_host, log=log)
    before = json.dumps(config, sort_keys=True)
    provider_root = config.setdefault("provider", {})
    provider = provider_root.setdefault(server, {})
    provider.setdefault("npm", "@ai-sdk/openai-compatible")
    provider["name"] = f"LM Studio ({source_host}.local)"
    provider_options = provider.setdefault("options", {})
    provider_options["baseURL"] = _opencode_base_url_for_entry({"host": source_host, "server": server})
    provider_options["extraHeaders"] = {"Authorization": "Bearer lm-studio"}
    provider["models"] = _opencode_sync_model_map(base, source_host=source_host, server=server, log=log, alias_prefix=alias_prefix)

    if set_default:
        fastest = next(iter(provider["models"].keys()), None)
        if fastest:
            config["model"] = f"{server}/{fastest}"

    after = json.dumps(config, sort_keys=True)
    write_result = _write_opencode_config(config_host, config, log=log)
    return {
        "ok": True,
        "changed": before != after,
        "config_host": config_host,
        "source_host": source_host,
        "server": server,
        "models": provider["models"],
        "default_model": config.get("model"),
        "write_result": write_result,
    }

def opencode_add_model(
    base: Path,
    *,
    config_host: str,
    model_ref: str,
    source_host: str | None = None,
    server: str | None = None,
    alias: str | None = None,
    set_default: bool = False,
    force: bool = False,
    probe_prompt: str = "ping",
    log=None,
) -> Dict[str, Any]:
    candidates = resolve_model_candidates(base, model_ref, preferred_host=source_host)
    selected = None
    for candidate in candidates:
        entry = candidate.get("entry") or {}
        entry_host = str(entry.get("host") or "")
        entry_server = str(entry.get("server") or "")
        if source_host and entry_host != source_host:
            continue
        if server and entry_server != server:
            continue
        selected = candidate
        break
    if selected is None:
        if source_host or server:
            raise ValueError(f"No matching registry entry found for {model_ref} on host={source_host or '*'} server={server or '*'}")
        selected = candidates[0]

    entry = selected.get("entry") or {}
    provider_name = str(entry.get("server") or server or "lmstudio")
    model_key = _opencode_default_alias(entry, alias)
    model_id = str(entry.get("backend_model_id") or entry.get("model_id") or model_ref)
    model_name = _opencode_display_name(entry, alias)
    source_host_value = str(entry.get("host") or source_host or short_hostname())
    base_url = _opencode_base_url_for_entry({"host": source_host_value, "server": provider_name})
    provider_display_name = f"LM Studio ({source_host_value}.local)" if provider_name == "lmstudio" else f"{provider_name.title()} ({source_host_value})"

    preflight = probe_model(
        model_ref,
        probe_prompt,
        base,
        log=log,
        timeout_seconds=180,
        preferred_host=source_host_value,
    )
    if not preflight.get("ok") and not force:
        return {
            "ok": False,
            "reason": "preflight_failed",
            "preflight": preflight,
            "config_host": config_host,
            "source_host": source_host_value,
            "server": provider_name,
            "model_key": model_key,
            "model_id": model_id,
            "model_name": model_name,
            "base_url": base_url,
            "set_default": set_default,
            "changed": False,
            "write_result": None,
        }

    config = _load_opencode_config(config_host, log=log)
    before = json.dumps(config, sort_keys=True)
    updated = _apply_opencode_model_mapping(
        config,
        provider_name=provider_name,
        provider_display_name=provider_display_name,
        model_key=model_key,
        model_id=model_id,
        model_name=model_name,
        base_url=base_url,
        set_default=set_default,
    )
    after = json.dumps(updated, sort_keys=True)
    changed = before != after
    write_result = _write_opencode_config(config_host, updated, log=log)
    return {
        "ok": True,
        "changed": changed,
        "config_host": config_host,
        "source_host": source_host_value,
        "server": provider_name,
        "model_key": model_key,
        "model_id": model_id,
        "model_name": model_name,
        "base_url": base_url,
        "set_default": set_default,
        "preflight": preflight,
        "write_result": write_result,
    }

def _looks_like_inventory_row(node: Dict[str, Any]) -> bool:
    keys = set(node)
    row_keys = {
        "model_id",
        "modelId",
        "display_name",
        "displayName",
        "backend_model_id",
        "backendModelId",
        "file_path",
        "filePath",
        "path",
        "size_bytes",
        "sizeBytes",
        "size",
        "name",
    }
    return bool(keys & row_keys)

def _extract_inventory_items(payload: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if isinstance(node, dict):
            container_keys = ("models", "items", "data", "variants", "results", "entries")
            found_container = False
            for key in container_keys:
                value = node.get(key)
                if isinstance(value, (list, dict)):
                    found_container = True
                    visit(value)
            if _looks_like_inventory_row(node):
                items.append(node)
            elif not found_container:
                for value in node.values():
                    if isinstance(value, (list, dict)):
                        visit(value)

    visit(payload)
    return items

def _coerce_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return default

def _coerce_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _coalesce_field(item: Dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in item and item.get(name) not in (None, ""):
            return item.get(name)
    return default

def _format_size_human(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.2f} {unit}"
        value /= 1024
    return "unknown"

def _parse_inventory_payload(payload: Any, host: str, scope: str, inventory_ref: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in _extract_inventory_items(payload):
        model_id = str(_coalesce_field(item, "model_id", "modelId", "id", "key", "name", default="")).strip()
        if not model_id:
            continue
        size_bytes = _coerce_int(_coalesce_field(item, "size_bytes", "sizeBytes", "size", default=None))
        loaded = _coerce_bool(_coalesce_field(item, "loaded", "is_loaded", "resident", "running", default=None), default=None)
        downloaded = _coerce_bool(_coalesce_field(item, "downloaded", default=True), default=True)
        row = {
            "host": host,
            "server": "lmstudio",
            "model_id": model_id,
            "display_name": str(_coalesce_field(item, "display_name", "displayName", default=model_id)),
            "backend_model_id": str(_coalesce_field(item, "backend_model_id", "backendModelId", default=model_id)),
            "downloaded": downloaded if downloaded is not None else True,
            "loaded": loaded,
            "api_visible": _coerce_bool(_coalesce_field(item, "api_visible", "apiVisible", default=True), default=True),
            "size_bytes": size_bytes if size_bytes is not None else 0,
            "size_human": str(_coalesce_field(item, "size_human", "sizeHuman", default=_format_size_human(size_bytes))),
            "file_path": str(_coalesce_field(item, "file_path", "filePath", "path", default="")),
            "last_modified": str(_coalesce_field(item, "last_modified", "lastModified", default=utc_today())),
            "context_window_tokens": _coerce_int(_coalesce_field(item, "context_window_tokens", "contextWindowTokens", default=None)),
            "max_output_tokens": _coerce_int(_coalesce_field(item, "max_output_tokens", "maxOutputTokens", default=None)),
            "reasoning": _coerce_bool(_coalesce_field(item, "reasoning", default=None), default=None),
            "images": _coerce_bool(_coalesce_field(item, "images", default=None), default=None),
            "ocr": _coerce_bool(_coalesce_field(item, "ocr", default=None), default=None),
            "public_weights": _coerce_bool(_coalesce_field(item, "public_weights", "publicWeights", default=None), default=None),
            "license_status": str(_coalesce_field(item, "license_status", "licenseStatus", default="unknown")),
            "inventory_ref": inventory_ref,
            "source": f"live {inventory_ref} sync on {host}",
            "updated": utc_today(),
        }
        rows.append(row)
    return rows

def _parse_filesystem_inventory_payload(payload: Any, host: str, inventory_ref: str) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        model_name = str(_coalesce_field(item, "model_dir", "modelDir", "name", default="")).strip()
        if not model_name:
            continue
        size_bytes = _coerce_int(_coalesce_field(item, "size_bytes", "sizeBytes", default=None))
        file_path = str(_coalesce_field(item, "path", "file_path", "filePath", default=""))
        rows.append({
            "host": host,
            "server": "lmstudio",
            "model_id": model_name,
            "display_name": model_name,
            "backend_model_id": model_name,
            "downloaded": True,
            "loaded": None,
            "api_visible": True,
            "size_bytes": size_bytes if size_bytes is not None else 0,
            "size_human": _format_size_human(size_bytes),
            "file_path": file_path,
            "last_modified": str(_coalesce_field(item, "last_modified", "lastModified", default=utc_today())),
            "context_window_tokens": None,
            "max_output_tokens": None,
            "reasoning": None,
            "images": None,
            "ocr": None,
            "public_weights": None,
            "license_status": "unknown",
            "inventory_ref": inventory_ref,
            "source": f"live filesystem inventory on {host}",
            "updated": utc_today(),
        })
    return rows

def _decode_json_from_output(output: str) -> Any:
    text = (output or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        if not line.startswith(("{", "[")):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("Unable to locate JSON payload in command output", text, 0)

def _match_registry_row_for_inventory(registry: List[Dict[str, Any]], host: str, model_name: str, file_path: str | None = None) -> int | None:
    if file_path:
        for idx, row in enumerate(registry):
            if str(row.get("host") or "") == host and str(row.get("server") or "") == "lmstudio" and str(row.get("file_path") or "") == file_path:
                return idx
    model_name_basename = os.path.basename(model_name)
    for idx, row in enumerate(registry):
        if str(row.get("host") or "") != host or str(row.get("server") or "") != "lmstudio":
            continue
        candidates = {
            str(row.get("model_id") or ""),
            str(row.get("display_name") or ""),
            str(row.get("backend_model_id") or ""),
            os.path.basename(str(row.get("file_path") or "")),
        }
        if model_name in candidates or model_name_basename in candidates:
            return idx
    return None

def _merge_inventory_rows(existing_row: Dict[str, Any] | None, inventory_row: Dict[str, Any]) -> Dict[str, Any]:
    if existing_row is None:
        merged = dict(inventory_row)
        merged.setdefault("status", "active")
        merged.setdefault("loaded", False)
        merged.setdefault("downloaded", True)
        merged.setdefault("owner", "shared")
        return merged

    merged = dict(existing_row)
    for key, value in inventory_row.items():
        if key in {"tps", "first_token_ms", "total_latency_ms", "last_loaded_at", "route_role", "route_notes", "route_task_types", "capability_notes", "success_state"}:
            continue
        if value is None:
            continue
        merged[key] = value
    merged.setdefault("status", existing_row.get("status") or "active")
    merged.setdefault("owner", existing_row.get("owner") or "shared")
    return merged

def sync_inventory(base: Path, log=None) -> Dict[str, Any]:
    registry = load_registry(base)
    rows_by_key = {}
    for idx, row in enumerate(registry):
        key = (str(row.get("host") or ""), str(row.get("server") or ""), str(row.get("model_id") or ""))
        rows_by_key[key] = idx

    summary = {
        "hosts": [],
        "scopes": [],
        "updated": 0,
        "added": 0,
        "missing": 0,
        "rows": 0,
        "errors": [],
    }

    for host in LMSTUDIO_INVENTORY_HOSTS:
        summary["hosts"].append(host)
        host_live_keys = set()
        result = _run_filesystem_inventory_command(host, log=log)
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            summary["errors"].append({"host": host, "stage": "filesystem", "error": stderr or "unknown error"})
            if log:
                log.error(f"filesystem inventory sync failed | host={host} | stderr={stderr}")
            continue

        try:
            payload = _decode_json_from_output(result.stdout or "")
        except json.JSONDecodeError as exc:
            summary["errors"].append({"host": host, "stage": "filesystem", "error": str(exc)})
            if log:
                log.error(f"filesystem inventory returned invalid JSON | host={host} | error={exc}")
            continue

        filesystem_rows = _parse_filesystem_inventory_payload(payload, host, "filesystem inventory")
        summary["scopes"].append("filesystem")
        for fs_row in filesystem_rows:
            idx = _match_registry_row_for_inventory(registry, host, fs_row["model_id"], fs_row.get("file_path"))
            key = (host, "lmstudio", fs_row["model_id"])
            host_live_keys.add(key)
            if idx is None:
                registry.append(fs_row)
                rows_by_key[key] = len(registry) - 1
                summary["added"] += 1
            else:
                registry[idx] = _merge_inventory_rows(registry[idx], fs_row)
                summary["updated"] += 1

        for idx, existing in enumerate(list(registry)):
            key = (str(existing.get("host") or ""), str(existing.get("server") or ""), str(existing.get("model_id") or ""))
            if key[0] != host or key[1] != "lmstudio":
                continue
            if key not in host_live_keys and str(existing.get("status") or "") != "missing":
                merged = dict(existing)
                merged["downloaded"] = False
                merged["loaded"] = False
                merged["status"] = "missing"
                merged["inventory_ref"] = "filesystem inventory"
                merged["source"] = f"live filesystem inventory on {host}"
                merged["updated"] = utc_today()
                registry[idx] = merged
                summary["missing"] += 1

    write_registry(base, registry)
    summary["rows"] = len(registry)
    if log:
        log.info(f"sync complete | hosts={','.join(sorted(set(summary['hosts'])))} | updated={summary['updated']} | added={summary['added']} | missing={summary['missing']} | errors={len(summary['errors'])}")
    return summary

def write_registry(base: Path, rows: List[Dict[str, Any]]) -> None:
    path = base / "_shared" / "_meta" / "model_registry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        for row in rows:
            tmp.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)

def update_registry_entry(base: Path, host: str, server: str, model_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    rows = load_registry(base)
    updated_row = None
    for row in rows:
        if str(row.get("host") or "") == host and str(row.get("server") or "") == server and str(row.get("model_id") or "") == model_id:
            row.update(updates)
            updated_row = row
            break
    if updated_row is None:
        raise ValueError(f"Registry row not found for {server}/{model_id} on host={host}")
    write_registry(base, rows)
    return updated_row

def _run_load_command(host: str, model_key: str, log=None) -> subprocess.CompletedProcess:
    current_host = short_hostname()
    if host == current_host:
        cmd = ["lms", "load", model_key, "-y"]
        if log:
            log.info(f"load requested locally | host={host} | model={model_key}")
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )

    remote_cmd = f"lms load {shlex.quote(model_key)} -y"
    ssh_targets = SSH_TARGETS_BY_HOST.get(host) or [host]
    if isinstance(ssh_targets, str):
        ssh_targets = [ssh_targets]

    last_result = None
    for ssh_target in ssh_targets:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            ssh_target,
            remote_cmd,
        ]
        if log:
            log.info(f"load requested remotely | host={host} | ssh_target={ssh_target} | model={model_key}")
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
        last_result = result
        if result.returncode == 0:
            return result

        stderr = (result.stderr or result.stdout or "").strip().lower()
        connection_failure = any(
            phrase in stderr
            for phrase in (
                "could not resolve hostname",
                "temporary failure in name resolution",
                "connection timed out",
                "no route to host",
                "connection refused",
            )
        )
        if not connection_failure:
            return result

    return last_result

def resolve_model_candidates(base: Path, model_ref: str, preferred_host: str | None = None) -> List[Dict[str, Any]]:
    """
    Resolve a model reference to ordered registry candidates and endpoints.

    Accepts bare registry IDs such as `allenai/olmo-3-32b-think` as well as
    provider-prefixed refs like `lmstudio/allenai/olmo-3-32b-think`.
    """
    registry = load_registry(base)
    raw_ref = model_ref.strip()

    provider = None
    candidate_ref = raw_ref
    if raw_ref.startswith("lmstudio/"):
        provider, candidate_ref = "lmstudio", raw_ref[len("lmstudio/"):]
    elif raw_ref.startswith("ollama/"):
        provider, candidate_ref = "ollama", raw_ref[len("ollama/"):]

    normalized_ref = _normalize_model_key(candidate_ref)
    normalized_raw_ref = _normalize_model_key(raw_ref)
    matches = []
    for entry in registry:
        if provider and entry.get("server") != provider:
            continue
        match_keys = _entry_match_keys(entry)
        if (
            candidate_ref in match_keys
            or raw_ref in match_keys
            or normalized_ref in match_keys
            or normalized_raw_ref in match_keys
            or any(normalized_ref and key.startswith(normalized_ref) for key in match_keys)
            or any(normalized_raw_ref and key.startswith(normalized_raw_ref) for key in match_keys)
        ):
            matches.append(entry)

    if matches:
        current_host = short_hostname()
        ordered = []
        for entry in matches:
            host = str(entry.get("host") or current_host)
            tps = entry.get("tps")
            try:
                tps_score = float(tps) if tps is not None else -1.0
            except (TypeError, ValueError):
                tps_score = -1.0
            ordered.append({
                "entry": entry,
                "endpoint": _host_endpoint(host, str(entry.get("server", provider or "lmstudio"))),
                "resolved_ref": f'{entry.get("server")}/{entry.get("model_id")}',
                "_sort_key": (
                    0 if preferred_host and host == preferred_host else 1,
                    -tps_score,
                    0 if host == current_host else 1,
                    host,
                ),
            })

        ordered.sort(key=lambda item: item["_sort_key"])
        for item in ordered:
            item.pop("_sort_key", None)
        return ordered

    if provider in DEFAULT_PROVIDER_ENDPOINTS:
        return [{
            "entry": None,
            "endpoint": DEFAULT_PROVIDER_ENDPOINTS[provider],
            "resolved_ref": raw_ref,
        }]

    raise ValueError(f"Unknown model prefix or unregistered model: {model_ref}")

def resolve_model_target(base: Path, model_ref: str, preferred_host: str | None = None) -> Dict[str, Any]:
    candidates = resolve_model_candidates(base, model_ref, preferred_host=preferred_host)
    if not candidates:
        raise ValueError(f"Unknown model prefix or unregistered model: {model_ref}")
    return candidates[0]

def ensure_model_loaded(resolved: Dict[str, Any], log=None) -> None:
    entry = resolved.get("entry")
    if not entry:
        return

    if entry.get("loaded") is True:
        return

    model_key = str(entry.get("model_id") or resolved.get("resolved_ref") or "").strip()
    if not model_key:
        raise ValueError("Resolved model entry does not include a usable model_id")
    host = str(entry.get("host") or short_hostname())
    result = _run_load_command(host, model_key, log)

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        lowered = stderr.lower()
        if "insufficient system resources" in lowered or "guardrails" in lowered:
            raise LoadGuardrailsError(stderr or f"lms load failed with exit code {result.returncode}")
        raise RuntimeError(stderr or f"lms load failed with exit code {result.returncode}")

    if log:
        stdout = (result.stdout or "").strip()
        if stdout:
            log.info(stdout.splitlines()[-1])

def _format_fastest_test_summary(registry: List[Dict[str, Any]]) -> Dict[str, Any]:
    active = [row for row in registry if row.get("status") == "active"]
    candidates = active or registry
    best = None
    best_tps = -1.0
    for row in candidates:
        try:
            tps = float(row.get("tps")) if row.get("tps") is not None else -1.0
        except (TypeError, ValueError):
            tps = -1.0
        if tps > best_tps:
            best = row
            best_tps = tps
    if not best:
        return {"model": "n/a", "host": "n/a", "output": "No registry rows found.", "latency_ms": "—", "tps": "—"}
    return {
        "model": f"{best.get('server', 'unknown')}/{best.get('model_id', 'unknown')}",
        "host": best.get("host", "unknown"),
        "output": best.get("route_notes") or best.get("capability_notes") or best.get("display_name") or "Registry-backed snapshot",
        "latency_ms": best.get("total_latency_ms") or best.get("first_token_ms") or "—",
        "tps": best.get("tps") or "—",
    }

def render_report(base: Path, log=None):
    """Render full J2 report (console + log identical)."""
    registry = load_registry(base)
    
    # Classify models
    active = [m for m in registry if m.get("status") == "active"]
    inactive = [m for m in registry if m.get("status") != "active"]
    
    # Dynamic column widths
    caps = {"model_id": 12, "display_name": 30, "host": 12, "server": 12, "context_window_tokens": 10, "tps": 8}
    widths = calc_column_widths(active + inactive, caps)
    
    # Render tables
    active_table = render_table(active, widths, "Active Models", log, emit=False)
    inactive_table = render_table(inactive, widths, "Inactive Models", log, emit=False)
    
    # Surface the current fastest registry-backed model snapshot.
    test_result = _format_fastest_test_summary(registry)
    
    # Single J2 render for both outputs
    template_path = SCRIPT_DIR / "j2_templates" / "report.j2"
    report = script_forge_renderer.render_template(str(template_path), {
        "registry_file": "_shared/_meta/model_registry.jsonl",
        "scope": "shared",
        "active_table": active_table,
        "inactive_table": inactive_table,
        "test": test_result,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    print(report)
    if log:
        log._write(report)

def render_list(base: Path, log=None):
    """Full aligned table of all models."""
    registry = load_registry(base)
    caps = {"model_id": 12, "display_name": 30, "host": 12, "server": 12, "context_window_tokens": 10, "tps": 8}
    widths = calc_column_widths(registry, caps)
    render_table(registry, widths, "All Models", log, emit=True)

def render_table(models: List[Dict], widths: Dict[str, int], title: str, log=None, emit: bool = True):
    """Render aligned table with dynamic widths."""
    headers = list(widths.keys())
    # Abbreviate specific headers to fit column widths
    header_labels = []
    for h in headers:
        if h == "context_window_tokens":
            header_labels.append("CxtWndTok")  # Abbreviated to fit 10-char column
        else:
            header_labels.append(h.replace('_', ' ').title())
    header_row = " | ".join(f"{label}".center(widths[h]) for label, h in zip(header_labels, headers))
    separator = "-" * len(header_row)
    lines = [f"\n=== {title} ===", header_row, separator]
    
    for model in models:
        row = " | ".join(str(model.get(h, '—'))[:widths[h]].ljust(widths[h]) for h in headers)
        lines.append(row)
    
    if log:
        log.info(f"Rendered {len(models)} {title.lower()}")
    rendered = "\n".join(lines)
    if emit:
        print(rendered)
    return rendered

def calc_column_widths(models: List[Dict], caps: Dict[str, int]) -> Dict[str, int]:
    """Dynamic column widths from content, capped."""
    widths = {k: len(k) for k in caps}
    for model in models:
        for field in caps:
            content = str(model.get(field, ''))
            widths[field] = min(max(widths[field], len(content)), caps[field])
    return widths

def probe_model(model_id: str, prompt: str, base: Path, log=None, timeout_seconds: int = 60, preferred_host: str | None = None) -> Dict[str, Any]:
    """Run a real HTTP probe and return a structured result."""
    try:
        candidates = resolve_model_candidates(base, model_id, preferred_host=preferred_host)
        last_guardrails = None
        current_host = short_hostname()
        for resolved in candidates:
            try:
                ensure_model_loaded(resolved, log)
                endpoint = resolved["endpoint"]
                resolved_host_value = resolved["entry"].get("host") if resolved["entry"] else None
                resolved_host = str(resolved_host_value) if resolved_host_value else current_host
                request_timeout = timeout_seconds if resolved_host == current_host else max(timeout_seconds, 180)
                payload_model = model_id
                if resolved["entry"] is not None:
                    payload_model = str(resolved["entry"].get("model_id") or model_id)
                elif model_id.startswith(("lmstudio/", "ollama/")):
                    payload_model = model_id.split("/", 1)[1]
                start = time.time()
                payload = json.dumps({
                    "model": payload_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                }).encode("utf-8")
                request = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=request_timeout) as response:
                    body = response.read().decode("utf-8")
                response_data = json.loads(body)
                latency_ms = int((time.time() - start) * 1000)
                tps = 100 / latency_ms * 1000  # rough estimate
                result = response_data["choices"][0]["message"]["content"].strip()
                if not result and response_data["choices"][0]["message"].get("reasoning_content"):
                    result = response_data["choices"][0]["message"]["reasoning_content"].strip()
                resolved_ref = resolved["resolved_ref"]
                entry = resolved["entry"] or {}
                host = entry.get("host") if entry else "unknown"
                server = entry.get("server") if entry else "unknown"
                model_key = str(entry.get("model_id") or model_id)
                print(f"✓ SUCCESS | {model_id} | Host: {host} | Resolved: {resolved_ref} | Latency: {latency_ms}ms | TPS: {tps:.1f} | Response: {result}")
                try:
                    update_registry_entry(
                        base,
                        str(host),
                        str(server),
                        model_key,
                        {
                            "loaded": True,
                            "last_loaded_at": utc_now_iso(),
                            "total_latency_ms": latency_ms,
                            "tps": round(tps, 3),
                            "updated": utc_today(),
                        },
                    )
                    if log:
                        log.info(f"registry updated | host={host} | server={server} | model_id={model_key} | latency={latency_ms}ms | tps={tps:.1f}")
                except Exception as update_exc:
                    if log:
                        log.error(f"registry update failed | {update_exc}")
                if log:
                    log.info(f"test success | host={host} | latency={latency_ms}ms | tps={tps:.1f}")
                return {
                    "ok": True,
                    "model_id": model_id,
                    "prompt": prompt,
                    "host": host,
                    "server": server,
                    "resolved_ref": resolved_ref,
                    "latency_ms": latency_ms,
                    "tps": tps,
                    "response": result,
                    "resolved": resolved,
                }
            except LoadGuardrailsError as e:
                last_guardrails = e
                host = resolved["entry"].get("host") if resolved["entry"] else "unknown"
                if log:
                    log.error(f"guardrails | host={host} | {str(e)}")
                continue
        if last_guardrails:
            raise last_guardrails
        raise RuntimeError("No usable LM Studio host found for this model")
    except Exception as e:
        if isinstance(e, urllib.error.HTTPError):
            message = f"HTTP {e.code}: {e.reason}"
        else:
            message = str(e)
        if log:
            log.error(message)
        return {
            "ok": False,
            "model_id": model_id,
            "prompt": prompt,
            "error": message,
            "exception": e,
        }

def test_model(model_id: str, prompt: str, base: Path, log=None, timeout_seconds: int = 60, preferred_host: str | None = None):
    """Real HTTP test with configurable timeout."""
    result = probe_model(model_id, prompt, base, log=log, timeout_seconds=timeout_seconds, preferred_host=preferred_host)
    if result.get("ok"):
        print(f"✓ SUCCESS | {model_id} | Host: {result['host']} | Resolved: {result['resolved_ref']} | Latency: {result['latency_ms']}ms | TPS: {result['tps']:.1f} | Response: {result['response']}")
        return
    error = result.get("error", "unknown error")
    if isinstance(result.get("exception"), LoadGuardrailsError):
        print(f"✗ FAILED | {model_id} | Guardrails: {error}")
    elif "HTTP " in error:
        print(f"✗ FAILED | {model_id} | {error}")
    else:
        print(f"✗ FAILED | {model_id} | Error: {error}")

if __name__ == "__main__":
    raise SystemExit(main())
