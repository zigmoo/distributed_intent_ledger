#!/usr/bin/env python3
import argparse
import base64
import csv
import json
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent / "lib"))
from resolve_base import resolve_dil_base
from tool_forge_log import ToolForgeLogger

HOME = Path.home()
DIL_BASE = Path(resolve_dil_base(script_dir=_SCRIPT_DIR))
CONFIG = HOME / ".config" / "opencode" / "opencode.json"
REGISTRY = DIL_BASE / "_shared" / "_meta" / "model_registry.jsonl"
RUN_LEDGER = DIL_BASE / "_shared" / "logs" / "llm_tool" / "llm_tool_runs.jsonl"
CONTEXT_CACHE = DIL_BASE / "_shared" / "logs" / "llm_tool" / "model_context_cache.jsonl"
RUN_STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
EVENTS_CSV = DIL_BASE / "_shared" / "logs" / "llm_tool" / f"llm_tool.events.{RUN_STAMP}.csv"
SSH_TARGETS_BY_HOST = {
    "moosacrem1promax": [
        "moosacrem1promax.jay-frog.ts.net",
        "moosacrem1promax",
        "moosacrem1promax.local",
    ],
    "pi5-16g": [
        "pi5-16g.local",
        "pi5-16g.jay-frog.ts.net",
        "pi5-16g",
    ],
    "pi5-8g": [
        "pi5-8g.local",
        "pi5-8g.jay-frog.ts.net",
        "pi5-8g",
    ],
}

PROVIDER_HOST_MAP = {
    "framemoowork": "framemoowork",
    "moosacrem1promax": "moosacrem1promax",
    "ollama": "moosacrem1promax",
}

PROVIDER_SERVER_MAP = {
    "framemoowork": "lmstudio",
    "moosacrem1promax": "lmstudio",
    "ollama": "ollama",
}

ok = fail = retry_ok = retry_fail = guardrail = bad_id = ctx_err = 0
ratchet_retry_ok = ratchet_retry_fail = 0
optimize_ok = optimize_fail = 0
DEFAULT_MAX_CONTEXT = 65536
DEFAULT_MIN_CONTEXT = 16384
DEFAULT_PROBE_TIMEOUT = 240
DEFAULT_REMOTE_TIMEOUT = 240
DEFAULT_CONFIG_CONTEXT = 32768
OPENCODE_NPM_PACKAGE = "opencode-ai"
OPENCODE_NPM_VERSION = "1.14.33"
LIVE_RENDER_INTERVAL = 10
DUCKDB_SQL = shutil.which("duckdb_sql") or "/org/platform/scripts/bin/duckdb_sql"
ARGS = None
LOG: ToolForgeLogger | None = None
EVENT_FIELDS = [
    "ts",
    "run_stamp",
    "mode",
    "event",
    "model_ref",
    "status",
    "reason",
    "context",
    "tps",
    "elapsed_s",
    "tokens_out",
    "note",
]

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


@dataclass
class ModelRuntimeRecord:
    host: str
    server: str
    provider: str
    registry_key: str
    api_model_id: str
    probe_status: str = "unknown"
    probe_message: str = ""
    context_length: str = "none"

    @property
    def model_ref(self) -> str:
        return f"{self.provider}/{self.registry_key}"


@dataclass
class ProbeResult:
    model_ref: str
    status: str
    reason: str
    output_tokens: int | None
    elapsed_s: float
    returncode: int

    @property
    def message(self) -> str:
        prefix = "OK" if self.status == "ok" else "ERR"
        return f"{prefix}\t{self.reason}"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_elapsed_short(seconds):
    try:
        return f"{float(seconds):.1f}s"
    except Exception:
        return ""


def csv_table_name(csv_path):
    table_name = Path(csv_path).stem
    table_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
    if table_name and table_name[0].isdigit():
        table_name = "_" + table_name
    return table_name


def csv_header_fields(csv_path):
    try:
        with Path(csv_path).open("r", encoding="utf-8") as f:
            first = f.readline().strip()
        if not first:
            return []
        return next(csv.reader([first]))
    except Exception:
        return []


def print_legend():
    print("LEGEND model=full model_ref event=human-readable action status=result state context=ctx length tokens_out=output tokens tps=tok/s elapsed_s=elapsed seconds")
    print("LEGEND labels MODEL_START=testing: <model> CONTEXT_PRELOAD=context preload RESULT=result RETRY_OK=retry ok RETRY_FAILED=retry failed RESOURCE_RELIEF_TEST=resource relief test CONTEXT_INCREASE_TEST=context increase test OPTIMIZE_OK=optimize ok OPTIMIZE_FAILED=optimize failed")


def display_event_label(event, model_ref="", status=""):
    if event == "MODEL_START":
        return f"testing: {model_ref}"
    if event == "CONTEXT_PRELOAD":
        return "context preload"
    if event == "RESOURCE_RELIEF_TEST":
        return "resource relief test"
    if event == "CONTEXT_INCREASE_TEST":
        return "context increase test"
    if event == "OPTIMIZE_CONTEXT":
        return "optimize context"
    if event == "OPTIMIZE_OK":
        return "optimize ok"
    if event == "OPTIMIZE_FAILED":
        return "optimize failed"
    if event == "RETRY_OK":
        return "retry ok"
    if event == "RETRY_FAILED":
        return "retry failed"
    if event == "PRECHECK_OK":
        return "precheck ok"
    if event == "PRECHECK_FAIL":
        return "precheck fail"
    if event == "PRECHECK":
        return "precheck"
    if event == "RESULT":
        return f"result: {status}" if status else "result"
    return event.lower().replace("_", " ")


def append_event_csv(event, model_ref="", status="", reason="", context="", tps="", elapsed_s="", output_tokens="", tokens_out="", note="", mode=""):
    EVENTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not EVENTS_CSV.exists()
    if not tokens_out:
        tokens_out = output_tokens
    row = {
        "ts": now_iso(),
        "run_stamp": RUN_STAMP,
        "mode": mode or (ARGS and ("optimize-only" if ARGS.optimize_only else "failures-only" if ARGS.failures_only else "selected" if ARGS.models or ARGS.models_file else "full")) or "full",
        "event": event,
        "model_ref": model_ref,
        "status": status,
        "reason": reason,
        "context": context,
        "tps": tps,
        "elapsed_s": elapsed_s,
        "tokens_out": tokens_out,
        "note": note,
    }
    with EVENTS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def duckdb_sql_available():
    return DUCKDB_SQL and Path(DUCKDB_SQL).exists()


def run_duckdb_sql(query):
    return subprocess.run([DUCKDB_SQL, "-d", str(EVENTS_CSV), "-s", query, "-g"], text=True, capture_output=True, check=False)


def render_live_tables_once():
    if not EVENTS_CSV.exists():
        return
    try:
        if EVENTS_CSV.stat().st_size <= 0:
            return
    except Exception:
        return
    print(f"LIVE_TABLE_REFRESH csv={EVENTS_CSV}")
    table_name = csv_table_name(EVENTS_CSV)
    fields = set(csv_header_fields(EVENTS_CSV))
    token_field = "tokens_out" if "tokens_out" in fields else "output_tokens" if "output_tokens" in fields else None
    token_select = f"{token_field}" if token_field else "NULL"
    query = (
        "with source as ("
        f"  select ts, model_ref, event, status, context, {token_select} as tokens_out, tps, elapsed_s, note "
        f"  from {table_name}"
        "), summary as ("
        "  select "
        "    'SUMMARY' as model, "
        "    case "
        "      when event='MODEL_START' then 'testing' "
        "      when event='CONTEXT_PRELOAD' then 'context preload' "
        "      when event='RESOURCE_RELIEF_TEST' then 'resource relief test' "
        "      when event='CONTEXT_INCREASE_TEST' then 'context increase test' "
        "      when event='OPTIMIZE_CONTEXT' then 'optimize context' "
        "      when event='OPTIMIZE_OK' then 'optimize ok' "
        "      when event='OPTIMIZE_FAILED' then 'optimize failed' "
        "      when event='RETRY_OK' then 'retry ok' "
        "      when event='RETRY_FAILED' then 'retry failed' "
        "      when event='PRECHECK_OK' then 'precheck ok' "
        "      when event='PRECHECK_FAIL' then 'precheck fail' "
        "      when event='PRECHECK' then 'precheck' "
        "      when event='RESULT' then 'result' "
        "      else lower(event) "
        "    end as event, "
        "    status, "
        "    count(*)::varchar as context, "
        "    null as tokens_out, "
        "    null as tps, "
        "    null as elapsed_s, "
        "    null as note, "
        "    0 as sort_group, "
        "    0 as sort_subgroup "
        "  from source "
        "  group by event, status "
        "), recent as ("
        "  select "
        "    model_ref as model, "
        "    case "
        "      when event='MODEL_START' then 'testing: ' || model_ref "
        "      when event='CONTEXT_PRELOAD' then 'context preload' "
        "      when event='RESOURCE_RELIEF_TEST' then 'resource relief test' "
        "      when event='CONTEXT_INCREASE_TEST' then 'context increase test' "
        "      when event='OPTIMIZE_CONTEXT' then 'optimize context' "
        "      when event='OPTIMIZE_OK' then 'optimize ok' "
        "      when event='OPTIMIZE_FAILED' then 'optimize failed' "
        "      when event='RETRY_OK' then 'retry ok' "
        "      when event='RETRY_FAILED' then 'retry failed' "
        "      when event='PRECHECK_OK' then 'precheck ok' "
        "      when event='PRECHECK_FAIL' then 'precheck fail' "
        "      when event='PRECHECK' then 'precheck' "
        "      when event='RESULT' then 'result: ' || status "
        "      else lower(event) "
        "    end as event, "
        "    status, "
        "    context::varchar as context, "
        "    tokens_out::varchar as tokens_out, "
        "    tps::varchar as tps, "
        "    elapsed_s::varchar as elapsed_s, "
        "    note, "
        "    1 as sort_group, "
        "    row_number() over (order by ts desc) as sort_subgroup "
        "  from source "
        "  order by ts desc limit 12 "
        ") "
        "select model, event, status, context, tokens_out, tps, elapsed_s, note "
        "from ("
        "  select * from summary "
        "  union all "
        "  select * from recent"
        ") "
        "order by sort_group, sort_subgroup, model, event, status;"
    )
    r = run_duckdb_sql(query)
    if r.returncode == 0 and (r.stdout or "").strip():
        print("EVENTS_TABLE_BEGIN")
        print(r.stdout.rstrip())
        print("EVENTS_TABLE_END")
    else:
        err = (r.stderr or r.stdout or "").strip()
        if err:
            print(f"EVENTS_TABLE_ERR {err[:300]}")


def start_live_renderer():
    if not duckdb_sql_available():
        print("LIVE_TABLE_DISABLED duckdb_sql not found")
        return None
    stop_event = threading.Event()

    def _loop():
        last_mtime_ns = None
        while not stop_event.is_set():
            try:
                if EVENTS_CSV.exists():
                    mtime_ns = EVENTS_CSV.stat().st_mtime_ns
                    if mtime_ns != last_mtime_ns:
                        last_mtime_ns = mtime_ns
                        render_live_tables_once()
            except Exception as exc:
                print(f"LIVE_TABLE_ERR {exc}")
            stop_event.wait(LIVE_RENDER_INTERVAL)

    thread = threading.Thread(target=_loop, name="duckdb-live-render", daemon=True)
    thread.start()
    return stop_event, thread


def stop_live_renderer(renderer):
    if not renderer:
        return
    stop_event, thread = renderer
    stop_event.set()
    thread.join(timeout=2)


def run(cmd, timeout=None):
    try:
        return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        msg = f"TIMEOUT after {timeout}s: {' '.join(cmd)}"
        if stderr:
            msg += f" | stderr={stderr.strip()[:300]}"
        if stdout:
            msg += f" | stdout={stdout.strip()[:300]}"
        # Return a subprocess-like object with timeout metadata encoded in stderr.
        return subprocess.CompletedProcess(cmd, returncode=124, stdout=stdout, stderr=msg)


def print_summary(total, selected_total, run_mode="full", source_log=None, optimize=False):
    print_legend()
    print(
        f"SUMMARY total={total} selected={selected_total} mode={run_mode} ok={ok} fail={fail} retry_ok={retry_ok} retry_fail={retry_fail} "
        f"ratchet_retry_ok={ratchet_retry_ok} ratchet_retry_fail={ratchet_retry_fail} "
        f"guardrail={guardrail} bad_id={bad_id} ctx_err={ctx_err} optimize_ok={optimize_ok} optimize_fail={optimize_fail}"
    )
    RUN_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": now_iso(),
            "tool": "llm_tool",
            "total": total,
            "selected": selected_total,
            "mode": run_mode,
            "source_log": str(source_log) if source_log else None,
            "optimize": optimize,
            "ok": ok,
            "fail": fail,
            "retry_ok": retry_ok,
            "retry_fail": retry_fail,
            "ratchet_retry_ok": ratchet_retry_ok,
            "ratchet_retry_fail": ratchet_retry_fail,
            "guardrail": guardrail,
            "bad_id": bad_id,
            "ctx_err": ctx_err,
            "optimize_ok": optimize_ok,
            "optimize_fail": optimize_fail,
        }, ensure_ascii=False) + "\n")
    print(f"MATRIX_END {datetime.now().astimezone().isoformat(timespec='seconds')}")


def precheck(cfg):
    print(f"MATRIX_START {datetime.now().astimezone().isoformat(timespec='seconds')}")
    print_legend()
    any_ok = False
    for provider_name, provider in cfg.get("provider", {}).items():
        base_url = provider.get("options", {}).get("baseURL", "")
        if not base_url:
            continue
        models_url = base_url.rstrip("/") + "/models"
        print(f"PRECHECK route={models_url}")
        append_event_csv("PRECHECK", status="start", reason=models_url, note=f"provider={provider_name}")
        r = run(["curl", "-fsS", "--connect-timeout", "3", "--max-time", "5", models_url])
        if r.returncode == 0:
            print(f"PRECHECK_OK route={provider_name}")
            append_event_csv("PRECHECK_OK", status="ok", reason=models_url, note=f"provider={provider_name}")
            any_ok = True
        else:
            print(f"PRECHECK_FAIL route={provider_name} reason=unreachable")
            append_event_csv("PRECHECK_FAIL", status="error", reason=models_url, note=f"provider={provider_name}")
    if not any_ok:
        print("PRECHECK_FAIL: no provider endpoints reachable")
        append_event_csv("PRECHECK_FAIL", status="error", reason="all endpoints unreachable", note="precheck exhausted")
    return any_ok


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the LM Studio model matrix, optimize working models, or configure agent harness model routes."
    )
    parser.add_argument("--model", dest="models", action="append", default=[], help="Model ref to test; repeatable.")
    parser.add_argument("--models-file", help="JSON sidecar describing selected models and run options.")
    parser.add_argument("--failures-only", action="store_true", help="Select only failing models from a prior run log.")
    parser.add_argument("--source-log", help="Prior matrix log to mine for failures.")
    parser.add_argument("--limit", type=int, help="Limit the selected model list to the first N entries.")
    parser.add_argument("--min-context", type=int, default=DEFAULT_MIN_CONTEXT, help="Lowest context to try when ratcheting.")
    parser.add_argument("--max-context", type=int, default=DEFAULT_MAX_CONTEXT, help="Highest context to try when ratcheting or optimizing.")
    parser.add_argument("--probe-timeout", type=int, default=DEFAULT_PROBE_TIMEOUT, help="Timeout seconds for each opencode probe.")
    parser.add_argument("--remote-timeout", type=int, default=DEFAULT_REMOTE_TIMEOUT, help="Timeout seconds for each remote lms command.")
    parser.add_argument("--optimize", action="store_true", help="Run optimize_llm_performance after a model successfully probes.")
    parser.add_argument("--optimize-only", action="store_true", help="Skip first-pass matrix run and run only optimize_llm_performance on the selected models.")
    parser.add_argument("--host", help="Only probe models on this host (e.g., framemoowork, moosacrem1promax).")
    parser.add_argument("--provider", help="Only probe models from this opencode provider name.")
    parser.add_argument("--configure-harness", choices=["opencode", "pi"], help="Configure a target agent harness with a selected model route.")
    parser.add_argument("--target-host", help="Target host to configure. Defaults to local machine.")
    parser.add_argument("--target-user", default="moo", help="Target user account for harness config.")
    parser.add_argument("--source-host", default="moosacrem1promax", help="Model server host, usually an LM Studio host.")
    parser.add_argument("--source-server", default="lmstudio", choices=["lmstudio"], help="Model server type for harness configuration.")
    parser.add_argument("--selection", choices=["powerful", "fastest", "specific"], default="powerful", help="Model selection policy for harness configuration.")
    parser.add_argument("--specific-model", help="Specific backend model id to configure when --selection specific is used.")
    parser.add_argument("--base-url", help="Known OpenAI-compatible base URL. If omitted, discover from the target host.")
    parser.add_argument("--context", type=int, default=DEFAULT_CONFIG_CONTEXT, help="Context length to load on the source model server.")
    parser.add_argument("--skip-load", action="store_true", help="Do not load the selected model on the source server before writing/verifying config.")
    parser.add_argument("--install-harness", action="store_true", help="Install or repair the target harness CLI when supported.")
    parser.add_argument("--configure-dry-run", action="store_true", help="Print planned harness config without writing remote files.")
    return parser.parse_args(argv)


def load_models_sidecar(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"models": data}
    if isinstance(data, dict):
        return data
    raise ValueError(f"Unsupported models sidecar format: {path}")


def latest_log_path():
    logs = sorted(RUN_LEDGER.parent.glob("llm_tool.run.*.log"))
    if not logs:
        return None
    return logs[-1]


def parse_failure_models_from_log(log_path):
    if not log_path:
        return []
    path = Path(log_path)
    if not path.exists():
        return []
    results = {}
    current = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("MODEL_START "):
            current = line.split(" ", 1)[1].strip()
            results.setdefault(current, "pending")
            continue
        if current is None:
            continue
        if line.startswith("OK    "):
            results[current] = "ok"
        elif line.startswith("RETRY_OK "):
            results[current] = "ok"
        elif line.startswith("ERR   ") or line.startswith("RETRY_FAILED "):
            if results.get(current) != "ok":
                results[current] = "fail"
    return [model for model, status in results.items() if status != "ok"]


def build_selection(cfg, args):
    all_models = model_keys(cfg)
    selected = []
    sidecar = {}
    if args.models_file:
        sidecar = load_models_sidecar(args.models_file)

    if sidecar.get("source_log") and not args.source_log:
        args.source_log = sidecar.get("source_log")
    if sidecar.get("failures_only"):
        args.failures_only = True
    if sidecar.get("optimize"):
        args.optimize = True
    if sidecar.get("optimize_only"):
        args.optimize_only = True
    if sidecar.get("max_context") and args.max_context == DEFAULT_MAX_CONTEXT:
        args.max_context = int(sidecar["max_context"])
    if sidecar.get("min_context") and args.min_context == DEFAULT_MIN_CONTEXT:
        args.min_context = int(sidecar["min_context"])
    if sidecar.get("limit") and args.limit is None:
        args.limit = int(sidecar["limit"])
    if sidecar.get("probe_timeout") and args.probe_timeout == DEFAULT_PROBE_TIMEOUT:
        args.probe_timeout = int(sidecar["probe_timeout"])

    if sidecar.get("models"):
        selected = [m for m in sidecar["models"] if isinstance(m, str) and m.strip()]
    elif args.models:
        selected = [m for m in args.models if m.strip()]
    elif args.failures_only:
        source_log = args.source_log or latest_log_path()
        selected = parse_failure_models_from_log(source_log)
        if source_log:
            print(f"SELECTION failures_only log={source_log} count={len(selected)}")
    else:
        selected = list(all_models)

    if args.limit is not None:
        selected = selected[: max(0, int(args.limit))]

    provider_names = list(cfg.get("provider", {}).keys())

    normalized = []
    seen = set()
    for model_ref in selected:
        if "/" not in model_ref:
            for pname in provider_names:
                if model_ref in cfg["provider"][pname].get("models", {}):
                    model_ref = f"{pname}/{model_ref}"
                    break
            else:
                if provider_names:
                    model_ref = f"{provider_names[0]}/{model_ref}"
        if model_ref not in seen:
            normalized.append(model_ref)
            seen.add(model_ref)

    if not normalized:
        normalized = list(all_models)

    if args.provider:
        normalized = [m for m in normalized if m.startswith(f"{args.provider}/")]
    if args.host:
        normalized = [m for m in normalized if host_for_provider(m.split("/", 1)[0]) == args.host]

    return normalized


def build_context_ladder(min_context, max_context):
    min_context = max(1, int(min_context))
    max_context = max(min_context, int(max_context))
    ladder = []
    current = min_context
    while current < max_context:
        ladder.append(current)
        next_ctx = int(current * 1.5)
        if next_ctx <= current:
            next_ctx = current + 4096
        current = min(next_ctx, max_context)
        if ladder and current == ladder[-1]:
            break
    ladder.append(max_context)
    deduped = []
    for ctx in ladder:
        if not deduped or deduped[-1] != ctx:
            deduped.append(ctx)
    return deduped


def context_cache_get(model_id):
    if not CONTEXT_CACHE.exists():
        return None
    best = None
    for line in CONTEXT_CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("api_model_id") != model_id:
            continue
        if row.get("status") != "ok":
            continue
        try:
            ctx = int(row.get("context_length"))
        except Exception:
            continue
        best = ctx if best is None else min(best, ctx)
    return best


def context_cache_put(model_id, status, ctx, model_ref):
    CONTEXT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": now_iso(),
        "api_model_id": model_id,
        "model_ref": model_ref,
        "status": status,
        "context_length": ctx,
    }
    with CONTEXT_CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def model_keys(cfg):
    keys = []
    for provider_name, provider in cfg.get("provider", {}).items():
        for model_key in provider.get("models", {}).keys():
            keys.append(f"{provider_name}/{model_key}")
    return keys


def model_id_for(cfg, model_ref):
    provider_name, key = model_ref.split("/", 1)
    return cfg["provider"][provider_name]["models"][key]["id"]


def build_record(cfg, model_ref):
    provider_name, key = model_ref.split("/", 1)
    host = host_for_provider(provider_name)
    server = server_for_provider(provider_name)
    return ModelRuntimeRecord(
        host=host,
        server=server,
        provider=provider_name,
        registry_key=key,
        api_model_id=model_id_for(cfg, model_ref),
    )


def probe_model(model, prompt="hello", timeout=DEFAULT_PROBE_TIMEOUT):
    started = perf_counter()
    r = run([
        "opencode", "run", "--pure", "--model", model, "--format", "json", prompt
    ], timeout=timeout)
    elapsed = perf_counter() - started
    text = r.stdout + ("\n" + r.stderr if r.stderr else "")
    last = ""
    output_tokens = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        t = obj.get("type")
        if t == "text":
            last = "OK\t" + str(obj.get("part", {}).get("text", ""))
        elif t == "step_finish":
            tokens = obj.get("part", {}).get("tokens", {}) or {}
            try:
                output_tokens = int(tokens.get("output")) if tokens.get("output") is not None else output_tokens
            except Exception:
                pass
        elif t == "error":
            last = "ERR\t" + str(obj.get("error", {}).get("data", {}).get("message", ""))
    if last:
        status, reason = parse_probe(last)
        return ProbeResult(model_ref=model, status=status, reason=reason, output_tokens=output_tokens, elapsed_s=elapsed, returncode=r.returncode)
    # Some opencode builds occasionally emit plain-text assistant output even with --format json.
    # If the process succeeded and we have plausible assistant text, treat it as a successful probe.
    if r.returncode == 0:
        text_lines = []
        for raw in (r.stdout or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("{") or line.startswith("["):
                continue
            if line.startswith(("Traceback", "ProviderModelNotFoundError", "Error:", "at /", "| ")):
                continue
            text_lines.append(line)
        if text_lines:
            return ProbeResult(model_ref=model, status="ok", reason=text_lines[-1], output_tokens=output_tokens, elapsed_s=elapsed, returncode=r.returncode)
    if r.returncode == 124:
        return ProbeResult(model_ref=model, status="error", reason=(r.stderr or "timeout").strip(), output_tokens=output_tokens, elapsed_s=elapsed, returncode=r.returncode)
    return ProbeResult(model_ref=model, status="error", reason="no structured output", output_tokens=output_tokens, elapsed_s=elapsed, returncode=r.returncode)


def opencode_probe(model, prompt="hello", timeout=DEFAULT_PROBE_TIMEOUT):
    return probe_model(model, prompt=prompt, timeout=timeout).message


def parse_probe(msg):
    if msg.startswith("OK\t"):
        return "ok", msg.split("\t", 1)[1]
    if msg.startswith("ERR\t"):
        return "error", msg.split("\t", 1)[1]
    return "error", msg


def probe_suffix(probe):
    parts = []
    if probe.output_tokens is not None:
        parts.append(f"tokens_out={probe.output_tokens}")
    if probe.elapsed_s is not None:
        parts.append(f"elapsed={format_elapsed_short(probe.elapsed_s)}")
    if probe.output_tokens is not None and probe.elapsed_s and probe.elapsed_s > 0:
        parts.append(f"tps={(probe.output_tokens / probe.elapsed_s):.2f}")
    return " " + " ".join(parts) if parts else ""


def enrich_record_from_live_runtime(record):
    record.context_length = remote_current_context(record.host, record.api_model_id) or "none"
    return record


def short_hostname():
    return socket.gethostname().split(".")[0].lower()


def host_cmd(host, cmd_str, timeout=DEFAULT_REMOTE_TIMEOUT):
    current = short_hostname()
    if host == current:
        return run(["bash", "-c", cmd_str], timeout=timeout)
    targets = SSH_TARGETS_BY_HOST.get(host, [host])
    last = None
    for target in targets:
        for attempt in range(2):
            last = run(
                ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, cmd_str],
                timeout=timeout,
            )
            if last.returncode == 0:
                return last
            err = (last.stderr or last.stdout or "").lower()
            if "could not resolve hostname" not in err and "temporary failure in name resolution" not in err:
                break
            if attempt == 0:
                time.sleep(0.5)
    return last


def host_for_provider(provider_name):
    return PROVIDER_HOST_MAP.get(provider_name, provider_name)


def server_for_provider(provider_name):
    return PROVIDER_SERVER_MAP.get(provider_name, "lmstudio")


def normalize_host(host):
    return (host or short_hostname()).split(".")[0].lower()


def slugify_model_key(model_id):
    key = model_id.split("/")[-1].lower()
    key = re.sub(r"[^a-z0-9._-]+", "-", key)
    key = key.strip("-")
    return key or "model"


def provider_key_for_host(host):
    return normalize_host(host).replace("-", "_").replace(".", "_")


def read_registry_rows():
    if not REGISTRY.exists():
        return []
    rows = []
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def numeric_value(row, key, default=0.0):
    try:
        value = row.get(key)
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def normalize_model_identity(value):
    text = str(value or "").lower()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    for suffix in ("-gguf", "-mlx-4bit", "-mlx-6bit", "-mlx-8bit", "-4bit", "-6bit", "-8bit"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return re.sub(r"[^a-z0-9]+", "", text)


def row_model_identities(row):
    values = {
        row.get("model_id"),
        row.get("backend_model_id"),
        row.get("display_name"),
        row.get("indexedModelIdentifier"),
    }
    values.update(row.get("aliases", []) or [])
    return {str(v) for v in values if v}


def model_identity_matches(row, model_id):
    wanted = str(model_id or "")
    identities = row_model_identities(row)
    if wanted in identities:
        return True
    wanted_norm = normalize_model_identity(wanted)
    return bool(wanted_norm) and wanted_norm in {normalize_model_identity(v) for v in identities}


def registry_candidates(source_host, source_server="lmstudio", min_tps=5.0):
    host = normalize_host(source_host)
    candidates = []
    for row in read_registry_rows():
        if normalize_host(row.get("host")) != host:
            continue
        if str(row.get("server") or "") != source_server:
            continue
        if str(row.get("status") or "active") not in ("active", "missing"):
            continue
        if row.get("downloaded") is False:
            continue
        model_id = row.get("backend_model_id") or row.get("model_id")
        if not model_id:
            continue
        tps = numeric_value(row, "tps", 0.0)
        if tps and tps < min_tps:
            continue
        candidates.append(row)
    return candidates


def choose_registry_model(source_host, source_server, selection, specific_model=None):
    candidates = registry_candidates(source_host, source_server)
    if specific_model:
        for row in candidates:
            if model_identity_matches(row, specific_model):
                return row
        # Specific models can be API-visible even before the registry has a fresh row.
        return {
            "model_id": specific_model,
            "backend_model_id": specific_model,
            "display_name": specific_model,
            "host": normalize_host(source_host),
            "server": source_server,
            "tps": None,
            "size_bytes": 0,
        }
    if not candidates:
        raise RuntimeError(f"No registry candidates for host={source_host} server={source_server}")
    if selection == "fastest":
        return sorted(candidates, key=lambda r: numeric_value(r, "tps", 0.0), reverse=True)[0]
    # "powerful" means largest responsive model first, with registry TPS as the useful-responsiveness gate.
    return sorted(
        candidates,
        key=lambda r: (numeric_value(r, "size_bytes", 0.0), numeric_value(r, "tps", 0.0)),
        reverse=True,
    )[0]


def shell_export_env(env):
    return " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items())


def remote_home_for_user(target_host, target_user):
    if not target_user:
        return str(HOME)
    if target_user == "root":
        return "/root"
    return f"/home/{target_user}"


def run_on_target(target_host, cmd, timeout=DEFAULT_REMOTE_TIMEOUT):
    return host_cmd(target_host or short_hostname(), cmd, timeout=timeout)


def openai_models_url(base_url):
    return base_url.rstrip("/") + "/models"


def source_host_ip_candidates(source_host, timeout=DEFAULT_REMOTE_TIMEOUT):
    cmd = (
        "if command -v ipconfig >/dev/null 2>&1; then "
        "  ipconfig getifaddr en0 2>/dev/null; ipconfig getifaddr en1 2>/dev/null; "
        "fi; "
        "if command -v hostname >/dev/null 2>&1; then hostname -I 2>/dev/null | tr ' ' '\\n'; fi; "
        "if command -v ifconfig >/dev/null 2>&1; then ifconfig | awk '/inet / {print $2}'; fi"
    )
    r = host_cmd(source_host, cmd, timeout=timeout)
    values = []
    for line in (r.stdout or "").splitlines():
        value = line.strip()
        if not value or value.startswith("127."):
            continue
        if re.match(r"^[0-9]+(\.[0-9]+){3}$", value) and value not in values:
            values.append(value)
    return values


def discover_base_url_from_target(target_host, source_host, timeout=DEFAULT_REMOTE_TIMEOUT):
    host = normalize_host(source_host)
    candidates = [
        f"http://{source_host}:1234/v1",
        f"http://{host}.local:1234/v1",
        f"http://{host}:1234/v1",
        f"http://{host}.jay-frog.ts.net:1234/v1",
    ]
    for ip_addr in source_host_ip_candidates(source_host, timeout=timeout):
        candidates.append(f"http://{ip_addr}:1234/v1")

    seen = set()
    for base_url in candidates:
        if base_url in seen:
            continue
        seen.add(base_url)
        url = openai_models_url(base_url)
        r = run_on_target(
            target_host,
            f"curl -fsS --connect-timeout 3 --max-time 5 {shlex.quote(url)} >/dev/null",
            timeout=timeout,
        )
        if r and r.returncode == 0:
            return base_url
    raise RuntimeError(f"No reachable LM Studio endpoint from target={target_host} source={source_host}")


def build_opencode_config(source_host, base_url, selected_row, fallback_rows=None):
    provider = provider_key_for_host(source_host)
    selected_model_id = selected_row.get("backend_model_id") or selected_row.get("model_id")
    selected_key = slugify_model_key(selected_model_id)
    models = {
        selected_key: {
            "id": selected_model_id,
            "name": selected_row.get("display_name") or selected_model_id,
        }
    }
    for row in fallback_rows or []:
        model_id = row.get("backend_model_id") or row.get("model_id")
        if not model_id or model_id == selected_model_id:
            continue
        models.setdefault(slugify_model_key(model_id), {
            "id": model_id,
            "name": row.get("display_name") or model_id,
        })
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider}/{selected_key}",
        "provider": {
            provider: {
                "npm": "@ai-sdk/openai-compatible",
                "name": f"LM Studio ({source_host})",
                "models": models,
                "options": {
                    "baseURL": base_url,
                    "extraHeaders": {
                        "Authorization": "Bearer lm-studio"
                    },
                },
            }
        },
    }


def encode_json_for_remote(data):
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def install_opencode_on_target(target_host, target_user, timeout=DEFAULT_REMOTE_TIMEOUT):
    home = remote_home_for_user(target_host, target_user)
    cmd = (
        f"set -e; cd {shlex.quote(home)}; "
        f"mkdir -p .config/opencode .local/bin; "
        f"cd .config/opencode; "
        f"npm install {OPENCODE_NPM_PACKAGE}@{OPENCODE_NPM_VERSION} >/tmp/llm_tool_opencode_install.log 2>&1; "
        f"ln -sfn {shlex.quote(home + '/.config/opencode/node_modules/.bin/opencode')} "
        f"{shlex.quote(home + '/.local/bin/opencode')}; "
        f"{shlex.quote(home + '/.local/bin/opencode')} --version"
    )
    return run_on_target(target_host, cmd, timeout=timeout)


def write_opencode_config_on_target(target_host, target_user, cfg, dry_run=False, timeout=DEFAULT_REMOTE_TIMEOUT):
    home = remote_home_for_user(target_host, target_user)
    payload = encode_json_for_remote(cfg)
    config_dir = f"{home}/.config/opencode"
    config_path = f"{config_dir}/opencode.json"
    if dry_run:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return subprocess.CompletedProcess([], 0, stdout="dry-run\n", stderr="")
    py = (
        "import base64, pathlib, sys; "
        "path=pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True); "
        "data=base64.b64decode(sys.argv[2]).decode('utf-8'); path.write_text(data + '\\n', encoding='utf-8')"
    )
    cmd = (
        f"set -e; mkdir -p {shlex.quote(config_dir)}; "
        f"if test -f {shlex.quote(config_path)}; then "
        f"  cp {shlex.quote(config_path)} {shlex.quote(config_path)}.bak.$(date +%Y%m%d_%H%M%S); "
        f"fi; "
        f"python3 -c {shlex.quote(py)} {shlex.quote(config_path)} {shlex.quote(payload)}; "
        f"jq -r '.model' {shlex.quote(config_path)}"
    )
    return run_on_target(target_host, cmd, timeout=timeout)


def build_pi_config(source_host, base_url, selected_row, fallback_rows=None):
    """Build a pi models.json config with the selected model and fallbacks."""
    provider = provider_key_for_host(source_host)
    selected_model_id = selected_row.get("backend_model_id") or selected_row.get("model_id")
    models = [{"id": selected_model_id, "name": selected_row.get("display_name") or selected_model_id}]
    for row in fallback_rows or []:
        model_id = row.get("backend_model_id") or row.get("model_id")
        if not model_id or model_id == selected_model_id:
            continue
        models.append({"id": model_id, "name": row.get("display_name") or model_id})
    return {
        "providers": {
            provider: {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": "lm-studio",
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": models,
            }
        },
        "_selectedModel": selected_model_id,
        "_selectedProvider": provider,
    }


def write_pi_config_on_target(target_host, target_user, cfg, dry_run=False, timeout=DEFAULT_REMOTE_TIMEOUT):
    """Write pi models.json and settings.json on the target host."""
    home = remote_home_for_user(target_host, target_user)
    models_path = f"{home}/.pi/agent/models.json"
    settings_path = f"{home}/.pi/agent/settings.json"
    provider = cfg.get("_selectedProvider", "")
    model_id = cfg.get("_selectedModel", "")
    if dry_run:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return subprocess.CompletedProcess([], 0, stdout="dry-run\n", stderr="")
    models_payload = encode_json_for_remote(cfg)
    models_py = (
        "import base64, json, pathlib, sys; "
        "path=pathlib.Path(sys.argv[1]); "
        "new=json.loads(base64.b64decode(sys.argv[2]).decode('utf-8')); "
        "existing=json.loads(path.read_text()) if path.exists() else {'providers':{}}; "
        "existing['providers'].update(new['providers']); "
        "path.write_text(json.dumps(existing, indent=4) + '\\n'); "
        "print(new.get('_selectedProvider','') + '/' + new.get('_selectedModel',''))"
    )
    settings_py = (
        "import json, pathlib, sys; "
        "path=pathlib.Path(sys.argv[1]); "
        "s=json.loads(path.read_text()) if path.exists() else {}; "
        "s['defaultProvider']=sys.argv[2]; s['defaultModel']=sys.argv[3]; "
        "path.write_text(json.dumps(s, indent=2) + '\\n')"
    )
    cmd = (
        f"set -e; "
        f"for f in {shlex.quote(models_path)} {shlex.quote(settings_path)}; do "
        f"  test -f \"$f\" && cp \"$f\" \"$f.bak.$(date +%Y%m%d_%H%M%S)\"; "
        f"done; "
        f"python3 -c {shlex.quote(models_py)} {shlex.quote(models_path)} {shlex.quote(models_payload)}; "
        f"python3 -c {shlex.quote(settings_py)} {shlex.quote(settings_path)} {shlex.quote(provider)} {shlex.quote(model_id)}"
    )
    return run_on_target(target_host, cmd, timeout=timeout)


def verify_pi_on_target(target_host, target_user, provider, model_id, timeout=DEFAULT_PROBE_TIMEOUT):
    """Probe pi on the target host with a simple prompt."""
    cmd = f"pi --provider {shlex.quote(provider)} --model {shlex.quote(model_id)} -p 'Answer with exactly OK' 2>&1 | head -5"
    return run_on_target(target_host, cmd, timeout=timeout)


def load_source_model(source_host, model_id, context_len, timeout=DEFAULT_REMOTE_TIMEOUT):
    safe_id = shlex.quote(model_id)
    cmd = f"lms unload -a >/dev/null 2>&1 || true; lms load {safe_id} --context-length {int(context_len)} --ttl 3600 -y"
    return host_cmd(source_host, cmd, timeout=timeout)


def verify_source_context(source_host, model_id, expected_context, fail_below=True):
    actual = remote_current_context(source_host, model_id)
    try:
        actual_int = int(str(actual))
    except Exception:
        actual_int = None
    expected_int = int(expected_context)
    if actual_int is None:
        record_registry_context(model_id, "context_unknown", "none", host=source_host)
        print(f"CONFIGURE_CONTEXT_UNKNOWN model_id={model_id} expected={expected_int} actual={actual or 'none'}")
        return not fail_below
    if actual_int < expected_int:
        record_registry_context(model_id, "too_small", actual_int, host=source_host)
        print(f"CONFIGURE_CONTEXT_TOO_SMALL model_id={model_id} expected={expected_int} actual={actual_int}")
        return not fail_below
    record_registry_context(model_id, "ok", actual_int, host=source_host)
    print(f"CONFIGURE_CONTEXT_OK model_id={model_id} expected={expected_int} actual={actual_int}")
    return True


def verify_opencode_on_target(target_host, target_user, model_ref, timeout=DEFAULT_PROBE_TIMEOUT):
    home = remote_home_for_user(target_host, target_user)
    opencode = f"{home}/.local/bin/opencode"
    prompt = "Answer with exactly OK"
    cmd = f"{shlex.quote(opencode)} run --pure --model {shlex.quote(model_ref)} --format json {shlex.quote(prompt)}"
    return run_on_target(target_host, cmd, timeout=timeout)


def configure_harness_pi(args):
    """Configure pi agent harness with a selected model route."""
    target_host = args.target_host or short_hostname()
    source_host = args.source_host
    specific = args.specific_model if args.selection == "specific" else None
    selected = choose_registry_model(source_host, args.source_server, args.selection, specific_model=specific)
    if specific:
        selected = dict(selected)
        selected["backend_model_id"] = specific
        selected["model_id"] = specific
        selected.setdefault("display_name", specific)
    fallback_rows = sorted(
        registry_candidates(source_host, args.source_server),
        key=lambda r: numeric_value(r, "tps", 0.0),
        reverse=True,
    )[:3]
    model_id = selected.get("backend_model_id") or selected.get("model_id")
    if not model_id:
        raise RuntimeError("Selected model has no backend model id")
    base_url = args.base_url or discover_base_url_from_target(target_host, source_host, timeout=args.remote_timeout)
    cfg = build_pi_config(source_host, base_url, selected, fallback_rows=fallback_rows)
    provider = cfg["_selectedProvider"]
    model_ref = f"{provider}/{model_id}"

    print(f"CONFIGURE_START harness=pi target={target_host} user={args.target_user} source={source_host}")
    print(f"CONFIGURE_SELECT selection={args.selection} model_id={model_id} model_ref={model_ref}")
    print(f"CONFIGURE_ENDPOINT base_url={base_url}")

    if args.configure_dry_run:
        write_pi_config_on_target(target_host, args.target_user, cfg, dry_run=True, timeout=args.remote_timeout)
        print("CONFIGURE_LOAD_SKIPPED dry_run=true")
        print("CONFIGURE_WRITE_SKIPPED dry_run=true")
        print("CONFIGURE_VERIFY_SKIPPED dry_run=true")
        return 0

    if args.skip_load:
        print("CONFIGURE_LOAD_SKIPPED skip_load=true")
        if not verify_source_context(source_host, model_id, args.context, fail_below=True):
            print(f"CONFIGURE_AUTO_LOAD model_id={model_id} context={int(args.context)}")
            load = load_source_model(source_host, model_id, args.context, timeout=args.remote_timeout)
            if load.returncode != 0:
                print(f"CONFIGURE_LOAD_FAIL model_id={model_id}")
                print((load.stderr or load.stdout or "").strip())
                return 1
            print(f"CONFIGURE_LOAD_OK model_id={model_id} context={int(args.context)}")
            if not verify_source_context(source_host, model_id, args.context, fail_below=True):
                return 1
    else:
        load = load_source_model(source_host, model_id, args.context, timeout=args.remote_timeout)
        if load.returncode != 0:
            print(f"CONFIGURE_LOAD_FAIL model_id={model_id}")
            print((load.stderr or load.stdout or "").strip())
            return 1
        print(f"CONFIGURE_LOAD_OK model_id={model_id} context={int(args.context)}")
        if not verify_source_context(source_host, model_id, args.context, fail_below=True):
            return 1

    written = write_pi_config_on_target(
        target_host, args.target_user, cfg, dry_run=False, timeout=args.remote_timeout,
    )
    if written.returncode != 0:
        print("CONFIGURE_WRITE_FAIL harness=pi")
        print((written.stderr or written.stdout or "").strip())
        return 1
    print(f"CONFIGURE_WRITE_OK config_model={(written.stdout or '').strip()}")

    verified = verify_pi_on_target(target_host, args.target_user, provider, model_id, timeout=args.probe_timeout)
    if verified.returncode != 0:
        print("CONFIGURE_VERIFY_FAIL harness=pi")
        print((verified.stderr or verified.stdout or "").strip()[:1000])
        return 1
    stdout = (verified.stdout or "").strip()
    if "ok" in stdout.lower() or len(stdout) > 0:
        print(f"CONFIGURE_VERIFY_OK harness=pi model_ref={model_ref}")
    else:
        print(f"CONFIGURE_VERIFY_FAIL harness=pi reason=empty_response")
        return 1
    return 0


def configure_harness(args):
    if args.configure_harness == "pi":
        return configure_harness_pi(args)
    if args.configure_harness != "opencode":
        raise RuntimeError(f"Unsupported harness: {args.configure_harness}")
    target_host = args.target_host or short_hostname()
    source_host = args.source_host
    specific = args.specific_model if args.selection == "specific" else None
    selected = choose_registry_model(source_host, args.source_server, args.selection, specific_model=specific)
    if specific:
        selected = dict(selected)
        selected["backend_model_id"] = specific
        selected["model_id"] = specific
        selected.setdefault("display_name", specific)
    fallback_rows = sorted(
        registry_candidates(source_host, args.source_server),
        key=lambda r: numeric_value(r, "tps", 0.0),
        reverse=True,
    )[:3]
    model_id = selected.get("backend_model_id") or selected.get("model_id")
    if not model_id:
        raise RuntimeError("Selected model has no backend model id")
    base_url = args.base_url or discover_base_url_from_target(target_host, source_host, timeout=args.remote_timeout)
    cfg = build_opencode_config(source_host, base_url, selected, fallback_rows=fallback_rows)
    model_ref = cfg["model"]

    print(f"CONFIGURE_START harness=opencode target={target_host} user={args.target_user} source={source_host}")
    print(f"CONFIGURE_SELECT selection={args.selection} model_id={model_id} model_ref={model_ref}")
    print(f"CONFIGURE_ENDPOINT base_url={base_url}")

    if args.configure_dry_run:
        write_opencode_config_on_target(
            target_host,
            args.target_user,
            cfg,
            dry_run=True,
            timeout=args.remote_timeout,
        )
        print("CONFIGURE_LOAD_SKIPPED dry_run=true")
        print("CONFIGURE_WRITE_SKIPPED dry_run=true")
        print("CONFIGURE_VERIFY_SKIPPED dry_run=true")
        return 0

    if args.skip_load:
        print("CONFIGURE_LOAD_SKIPPED skip_load=true")
        if not verify_source_context(source_host, model_id, args.context, fail_below=True):
            print(f"CONFIGURE_AUTO_LOAD model_id={model_id} context={int(args.context)}")
            load = load_source_model(source_host, model_id, args.context, timeout=args.remote_timeout)
            if load.returncode != 0:
                print(f"CONFIGURE_LOAD_FAIL model_id={model_id}")
                print((load.stderr or load.stdout or "").strip())
                return 1
            print(f"CONFIGURE_LOAD_OK model_id={model_id} context={int(args.context)}")
            if not verify_source_context(source_host, model_id, args.context, fail_below=True):
                return 1
    else:
        load = load_source_model(source_host, model_id, args.context, timeout=args.remote_timeout)
        if load.returncode != 0:
            print(f"CONFIGURE_LOAD_FAIL model_id={model_id}")
            print((load.stderr or load.stdout or "").strip())
            return 1
        print(f"CONFIGURE_LOAD_OK model_id={model_id} context={int(args.context)}")
        if not verify_source_context(source_host, model_id, args.context, fail_below=True):
            return 1

    if args.install_harness:
        installed = install_opencode_on_target(target_host, args.target_user, timeout=args.remote_timeout)
        if installed.returncode != 0:
            print("CONFIGURE_INSTALL_FAIL harness=opencode")
            print((installed.stderr or installed.stdout or "").strip())
            return 1
        print(f"CONFIGURE_INSTALL_OK harness=opencode version={(installed.stdout or '').strip()}")

    written = write_opencode_config_on_target(
        target_host,
        args.target_user,
        cfg,
        dry_run=False,
        timeout=args.remote_timeout,
    )
    if written.returncode != 0:
        print("CONFIGURE_WRITE_FAIL harness=opencode")
        print((written.stderr or written.stdout or "").strip())
        return 1
    print(f"CONFIGURE_WRITE_OK config_model={(written.stdout or '').strip()}")

    verified = verify_opencode_on_target(target_host, args.target_user, model_ref, timeout=args.probe_timeout)
    if verified.returncode != 0:
        print("CONFIGURE_VERIFY_FAIL harness=opencode")
        print((verified.stderr or verified.stdout or "").strip()[:1000])
        record_opencode_context_failure(model_id, verified.stdout, verified.stderr, source_host)
        return 1
    probe = parse_opencode_json_probe(verified.stdout)
    if probe.status != "ok":
        print(f"CONFIGURE_VERIFY_FAIL harness=opencode reason={probe.reason}")
        record_opencode_context_failure(model_id, verified.stdout, verified.stderr, source_host)
        return 1
    print(f"CONFIGURE_VERIFY_OK harness=opencode model_ref={model_ref}{probe_suffix(probe)}")
    return 0


def parse_opencode_json_probe(stdout):
    last = ""
    output_tokens = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "text":
            text = str(obj.get("part", {}).get("text", ""))
            if text.strip():
                last = text.strip()
        elif obj.get("type") == "step_finish":
            tokens = obj.get("part", {}).get("tokens", {}) or {}
            try:
                output_tokens = int(tokens.get("output")) if tokens.get("output") is not None else output_tokens
            except Exception:
                pass
    if last:
        return ProbeResult(model_ref="", status="ok", reason=last, output_tokens=output_tokens, elapsed_s=0.0, returncode=0)
    return ProbeResult(model_ref="", status="error", reason="no text output", output_tokens=output_tokens, elapsed_s=0.0, returncode=0)


def extract_context_error(text):
    if not text:
        return None
    patterns = [
        r"n_keep:\s*(\d+)\s*>=\s*n_ctx:\s*(\d+)",
        r"context length\s*\([^)]*n_ctx:\s*(\d+)[^)]*\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            nums = [int(x) for x in match.groups() if x is not None]
            if len(nums) >= 2:
                return {"n_keep": nums[0], "n_ctx": nums[1]}
            if len(nums) == 1:
                return {"n_keep": None, "n_ctx": nums[0]}
    if "context length" in text.lower() or "n_ctx" in text.lower():
        return {"n_keep": None, "n_ctx": None}
    return None


def record_opencode_context_failure(model_id, stdout="", stderr="", source_host=""):
    text = "\n".join(part for part in [stdout or "", stderr or ""] if part)
    ctx = extract_context_error(text)
    if not ctx:
        return False
    n_ctx = ctx.get("n_ctx")
    record_registry_context(model_id, "too_small", n_ctx if n_ctx is not None else "none", host=source_host)
    detail = f"n_ctx={n_ctx}" if n_ctx is not None else "n_ctx=unknown"
    if ctx.get("n_keep") is not None:
        detail = f"n_keep={ctx['n_keep']} {detail}"
    print(f"CONFIGURE_CONTEXT_ERROR_RECORDED model_id={model_id} {detail}")
    return True


def remote_current_context(host, model_id):
    safe_id = shlex.quote(model_id)
    py = (
        "import json,sys; d=json.load(sys.stdin); mid=sys.argv[1];"
        " m=[x for x in d if x.get('identifier')==mid];"
        " print(m[0].get('contextLength') if m else '')"
    )
    r = host_cmd(host, f"lms ps --json | python3 -c {shlex.quote(py)} {safe_id}")
    return (r.stdout or "").strip()


def retry_with_unload_all(record, context_len, probe_timeout=DEFAULT_PROBE_TIMEOUT):
    host = record.host
    timeout = ARGS.remote_timeout if ARGS else DEFAULT_REMOTE_TIMEOUT
    host_cmd(host, "lms unload -a || true", timeout=timeout)
    safe_id = shlex.quote(record.api_model_id)
    host_cmd(host, f"lms load {safe_id} --context-length {int(context_len)} --ttl 3600 -y", timeout=timeout)
    return probe_model(record.model_ref, timeout=probe_timeout)


def record_registry_context(model_id, status, ctx, host="moosacrem1promax"):
    if not REGISTRY.exists():
        return
    ctx_val = None
    if ctx not in (None, "", "none", "null"):
        try:
            ctx_val = int(str(ctx))
        except Exception:
            ctx_val = None
    rows = []
    updated = 0
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("server") or "") != "lmstudio":
            rows.append(row)
            continue
        row_host = row.get("host")
        if host and row_host and normalize_host(row_host) != normalize_host(host):
            rows.append(row)
            continue
        if model_identity_matches(row, model_id):
            row["context_verification_status"] = status
            row["last_context_verified_at"] = now_iso()
            row["context_verification_host"] = host
            aliases = row.get("aliases") or []
            if model_id not in aliases and model_id not in {row.get("model_id"), row.get("backend_model_id")}:
                row["aliases"] = aliases + [model_id]
            if ctx_val is not None:
                row["last_verified_context_length"] = ctx_val
                row["context_window_tokens"] = ctx_val
                if status == "ok":
                    prev = row.get("min_working_context_length")
                    if prev is None:
                        row["min_working_context_length"] = ctx_val
                    else:
                        try:
                            row["min_working_context_length"] = min(int(prev), ctx_val)
                        except Exception:
                            row["min_working_context_length"] = ctx_val
            updated += 1
        rows.append(row)
    if not updated:
        row = {
            "host": host,
            "server": "lmstudio",
            "model_id": model_id,
            "backend_model_id": model_id,
            "display_name": model_id,
            "status": "active",
            "owner": "shared",
            "source": "llm_tool context verification",
            "updated": now_iso(),
            "context_verification_status": status,
            "last_context_verified_at": now_iso(),
            "context_verification_host": host,
        }
        if ctx_val is not None:
            row["last_verified_context_length"] = ctx_val
            row["context_window_tokens"] = ctx_val
            if status == "ok":
                row["min_working_context_length"] = ctx_val
        rows.append(row)
        updated = 1
    if updated:
        REGISTRY.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"REGISTRY_UPDATE model_id={model_id} status={status} ctx={ctx} rows={updated}")
    # Durable per-tool cache used for next-run preloading even when registry IDs do not match API ids.
    context_cache_put(model_id, status, ctx, model_id)


def record_registry_performance(model_id, best_context, best_tps, history, host="moosacrem1promax"):
    if not REGISTRY.exists():
        return
    rows = []
    updated = 0
    for line in REGISTRY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("server") or "") != "lmstudio":
            rows.append(row)
            continue
        keys = {str(row.get("model_id") or ""), str(row.get("backend_model_id") or "")}
        if model_id in keys:
            row["optimization_last_run_at"] = now_iso()
            row["optimization_best_context_length"] = best_context
            row["optimization_best_tps"] = best_tps
            row["optimization_history"] = history[-12:]
            row["context_window_tokens"] = best_context
            row["tps"] = best_tps
            row["success_state"] = "ok"
            row["context_verification_status"] = "ok"
            row["last_context_verified_at"] = now_iso()
            row["context_verification_host"] = host
            updated += 1
        rows.append(row)
    if updated:
        REGISTRY.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"REGISTRY_OPTIMIZE model_id={model_id} best_ctx={best_context} best_tps={best_tps} rows={updated}")


def ratchet_context_retry(record, min_context=DEFAULT_MIN_CONTEXT, max_context=DEFAULT_MAX_CONTEXT, probe_timeout=DEFAULT_PROBE_TIMEOUT):
    global ratchet_retry_ok, ratchet_retry_fail
    contexts = build_context_ladder(min_context, max_context)
    for c in contexts:
        print(f"RATCHET  {record.model_ref} context={c}")
        append_event_csv("RATCHET", model_ref=record.model_ref, context=c, note="context load candidate")
        load_remote_model(record, c)
        probe = probe_model(record.model_ref, timeout=probe_timeout)
        if probe.status == "ok":
            ratchet_retry_ok += 1
            record_registry_context(record.api_model_id, "ok", c, host=record.host)
            suffix = probe_suffix(probe)
            print(f"RETRY_OK {record.model_ref} :: context raised to {c}{suffix}")
            append_event_csv(
                "RETRY_OK",
                model_ref=record.model_ref,
                status="ok",
                context=c,
                reason=probe.reason,
                tps=f"{(probe.output_tokens / probe.elapsed_s):.2f}" if probe.output_tokens and probe.elapsed_s else "",
                elapsed_s=format_elapsed_short(probe.elapsed_s),
                output_tokens=probe.output_tokens or "",
                note="context ratchet",
            )
            return True
        msg = probe.message
        if "insufficient system resources" in msg:
            ratchet_retry_fail += 1
            record_registry_context(record.api_model_id, "guardrail", c, host=record.host)
            print(f"RESOURCE_RELIEF_TEST {record.model_ref} :: unload-all then retry context {c}")
            append_event_csv("RESOURCE_RELIEF_TEST", model_ref=record.model_ref, status="error", context=c, reason=msg, note="guardrail")
            probe2 = retry_with_unload_all(record, c, probe_timeout=probe_timeout)
            if probe2.status == "ok":
                ratchet_retry_ok += 1
                record_registry_context(record.api_model_id, "ok", c, host=record.host)
                suffix = probe_suffix(probe2)
                print(f"RETRY_OK {record.model_ref} :: unload-all + context {c} recovered{suffix}")
                append_event_csv(
                    "RETRY_OK",
                    model_ref=record.model_ref,
                    status="ok",
                    context=c,
                    reason=probe2.reason,
                    tps=f"{(probe2.output_tokens / probe2.elapsed_s):.2f}" if probe2.output_tokens and probe2.elapsed_s else "",
                    elapsed_s=format_elapsed_short(probe2.elapsed_s),
                    output_tokens=probe2.output_tokens or "",
                    note="resource relief",
                )
                return True
            reason2 = probe2.reason
            print(f"RETRY_FAILED {record.model_ref} :: guardrail persisted after unload-all ({reason2})")
            append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", context=c, reason=reason2, note="guardrail persisted")
            return False
    ratchet_retry_fail += 1
    record_registry_context(record.api_model_id, "too_small_or_other", "none", host=record.host)
    print(f"RETRY_FAILED {record.model_ref} :: context ratchet exhausted (max tried {max_context})")
    append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", reason=f"context ratchet exhausted max={max_context}", note="context sweep exhausted")
    return False


def load_remote_model(record, context_len):
    safe_id = shlex.quote(record.api_model_id)
    timeout = ARGS.remote_timeout if ARGS else DEFAULT_REMOTE_TIMEOUT
    host_cmd(record.host, f"lms unload {safe_id} || true; lms load {safe_id} --context-length {int(context_len)} --ttl 3600 -y", timeout=timeout)


def optimize_llm_performance(record, current_context, max_context, probe_timeout=DEFAULT_PROBE_TIMEOUT):
    """
    Sweep a bounded set of context lengths and keep the best successful TPS result.
    This is a practical optimization pass over the adjustable LM Studio context parameter.
    """
    global optimize_ok, optimize_fail
    current_context = int(current_context) if current_context not in (None, "", "none") else None
    max_context = max(int(max_context), DEFAULT_MIN_CONTEXT)

    candidates = []
    if current_context:
        candidates.extend([
            max(DEFAULT_MIN_CONTEXT, current_context // 2),
            current_context,
            min(max_context, int(current_context * 1.5)),
            min(max_context, int(current_context * 2)),
            max_context,
        ])
    else:
        candidates.extend(build_context_ladder(DEFAULT_MIN_CONTEXT, max_context))

    # Deduplicate while preserving order.
    seen = set()
    ordered = []
    for ctx in candidates:
        ctx = int(ctx)
        if ctx < DEFAULT_MIN_CONTEXT or ctx > max_context or ctx in seen:
            continue
        ordered.append(ctx)
        seen.add(ctx)

    if not ordered:
        ordered = [max_context]

    history = []
    best = None
    for ctx in ordered:
        print(f"OPTIMIZE_CONTEXT {record.model_ref} context={ctx}")
        append_event_csv("OPTIMIZE_CONTEXT", model_ref=record.model_ref, context=ctx, note="tps sweep")
        load_remote_model(record, ctx)
        probe = probe_model(record.model_ref, timeout=probe_timeout)
        if probe.status != "ok":
            history.append({
                "context": ctx,
                "status": probe.status,
                "reason": probe.reason,
                "elapsed_s": round(probe.elapsed_s, 3),
            })
            continue

        tps = None
        if probe.output_tokens and probe.elapsed_s > 0:
            tps = round(probe.output_tokens / probe.elapsed_s, 3)
        history.append({
            "context": ctx,
            "status": "ok",
            "reason": probe.reason,
            "elapsed_s": round(probe.elapsed_s, 3),
            "output_tokens": probe.output_tokens,
            "tps": tps,
        })
        if best is None:
            best = history[-1]
        else:
            best_tps = best.get("tps") if best else None
            candidate_tps = tps
            if candidate_tps is not None and (best_tps is None or candidate_tps > best_tps):
                best = history[-1]

    if best is None:
        optimize_fail += 1
        print(f"OPTIMIZE_FAILED {record.model_ref} :: no successful context among {ordered}")
        append_event_csv("OPTIMIZE_FAILED", model_ref=record.model_ref, status="error", reason="no successful context", note="tps sweep failed")
        return None

    optimize_ok += 1
    best_context = best["context"]
    best_tps = best.get("tps")
    record_registry_performance(record.api_model_id, best_context, best_tps, history, host=record.host)
    print(f"OPTIMIZE_OK {record.model_ref} :: best_context={best_context} best_tps={best_tps}")
    append_event_csv("OPTIMIZE_OK", model_ref=record.model_ref, status="ok", context=best_context, tps=best_tps or "", note="tps sweep best")
    return best


def run_selected_models(cfg, models, args):
    global ok, fail, retry_ok, retry_fail, guardrail, bad_id, ctx_err
    for m in models:
        record = build_record(cfg, m)
        print(f"TESTING: {record.model_ref}")
        append_event_csv("MODEL_START", model_ref=record.model_ref, status="start", context=record.context_length, note="probe")
        cached_ctx = context_cache_get(record.api_model_id)
        if cached_ctx:
            print(f"CONTEXT_PRELOAD {record.model_ref} :: context={cached_ctx} (from cache)")
            append_event_csv("CONTEXT_PRELOAD", model_ref=record.model_ref, status="ok", context=cached_ctx, note="from cache")
            load_remote_model(record, cached_ctx)

        probe = probe_model(record.model_ref, timeout=args.probe_timeout)
        record.probe_status = probe.status
        record.probe_message = probe.reason

        if probe.status == "ok":
            ok += 1
            enrich_record_from_live_runtime(record)
            record_registry_context(record.api_model_id, "ok", record.context_length, host=record.host)
            suffix = probe_suffix(probe)
            print(f"OK    {record.model_ref}{suffix}")
            append_event_csv(
                "RESULT",
                model_ref=record.model_ref,
                status="ok",
                context=record.context_length,
                reason=probe.reason,
                tps=f"{(probe.output_tokens / probe.elapsed_s):.2f}" if probe.output_tokens and probe.elapsed_s else "",
                elapsed_s=format_elapsed_short(probe.elapsed_s),
                output_tokens=probe.output_tokens or "",
                note="first-pass success",
            )
            if args.optimize:
                optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
            continue

        fail += 1
        reason = record.probe_message
        msg = probe.message
        append_event_csv(
            "RESULT",
            model_ref=record.model_ref,
            status="error",
            context=record.context_length,
            reason=reason,
            elapsed_s=format_elapsed_short(probe.elapsed_s),
            output_tokens=probe.output_tokens or "",
            note="first-pass failure",
        )
        if "Model is unloaded" in msg or "is unloaded" in reason:
            load_ctx = context_cache_get(record.api_model_id) or DEFAULT_MIN_CONTEXT
            print(f"MODEL_LOAD {record.model_ref} :: unload-all then loading at context={load_ctx}")
            append_event_csv("MODEL_LOAD", model_ref=record.model_ref, status="start", context=load_ctx, reason="model unloaded", note="auto-load")
            host_cmd(record.host, "lms unload -a || true", timeout=ARGS.remote_timeout if ARGS else DEFAULT_REMOTE_TIMEOUT)
            load_remote_model(record, load_ctx)
            probe_reload = probe_model(record.model_ref, timeout=args.probe_timeout)
            if probe_reload.status == "ok":
                retry_ok += 1
                enrich_record_from_live_runtime(record)
                record_registry_context(record.api_model_id, "ok", record.context_length, host=record.host)
                suffix = probe_suffix(probe_reload)
                print(f"RETRY_OK {record.model_ref} :: loaded and probed successfully{suffix}")
                append_event_csv(
                    "RETRY_OK", model_ref=record.model_ref, status="ok", context=load_ctx,
                    reason=probe_reload.reason,
                    tps=f"{(probe_reload.output_tokens / probe_reload.elapsed_s):.2f}" if probe_reload.output_tokens and probe_reload.elapsed_s else "",
                    elapsed_s=format_elapsed_short(probe_reload.elapsed_s),
                    output_tokens=probe_reload.output_tokens or "", note="auto-load",
                )
                if args.optimize:
                    optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
                continue
            reload_reason = probe_reload.reason
            if "context length" in reload_reason or "n_keep" in reload_reason:
                print(f"CONTEXT_INCREASE_TEST {record.model_ref} :: auto-load needs ratchet")
                append_event_csv("CONTEXT_INCREASE_TEST", model_ref=record.model_ref, status="start", context=load_ctx, reason=reload_reason, note="post-load ratchet")
                if ratchet_context_retry(record, min_context=args.min_context, max_context=args.max_context, probe_timeout=args.probe_timeout):
                    if args.optimize:
                        optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
                continue
            retry_fail += 1
            print(f"RETRY_FAILED {record.model_ref} :: loaded but probe failed ({reload_reason})")
            append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", context=load_ctx, reason=reload_reason, note="auto-load failed")
            continue
        if "insufficient system resources" in msg:
            guardrail += 1
            record_registry_context(record.api_model_id, "guardrail", "none", host=record.host)
            print(f"RESOURCE_RELIEF_TEST {record.model_ref} :: unload-all then retry context {args.max_context if args.max_context < 16384 else 16384}")
            append_event_csv("RESOURCE_RELIEF_TEST", model_ref=record.model_ref, status="error", reason=reason, context=args.max_context, note="guardrail")
            relief_ctx = min(args.max_context, max(DEFAULT_MIN_CONTEXT, 16384))
            probe_relief = retry_with_unload_all(record, relief_ctx, probe_timeout=args.probe_timeout)
            if probe_relief.status == "ok":
                retry_ok += 1
                enrich_record_from_live_runtime(record)
                record_registry_context(record.api_model_id, "ok", record.context_length, host=record.host)
                suffix = probe_suffix(probe_relief)
                print(f"RETRY_OK {record.model_ref} :: unload-all + context {relief_ctx} recovered{suffix}")
                append_event_csv(
                    "RETRY_OK",
                    model_ref=record.model_ref,
                    status="ok",
                    context=relief_ctx,
                    reason=probe_relief.reason,
                    tps=f"{(probe_relief.output_tokens / probe_relief.elapsed_s):.2f}" if probe_relief.output_tokens and probe_relief.elapsed_s else "",
                    elapsed_s=format_elapsed_short(probe_relief.elapsed_s),
                    output_tokens=probe_relief.output_tokens or "",
                    note="resource relief",
                )
                if args.optimize:
                    optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
                continue
            retry_fail += 1
            reason_relief = probe_relief.reason
            print(f"RETRY_FAILED {record.model_ref} :: unload-all did not recover ({reason_relief})")
            append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", context=relief_ctx, reason=reason_relief, note="resource relief")
            continue
        elif "Invalid model identifier" in msg:
            bad_id += 1
            record_registry_context(record.api_model_id, "invalid_identifier", "none", host=record.host)
        elif "context length" in msg or "n_keep" in msg:
            ctx_err += 1
            record_registry_context(record.api_model_id, "too_small", "none", host=record.host)
        else:
            record_registry_context(record.api_model_id, "error_other", "none", host=record.host)

        print(f"ERR   {record.model_ref} :: {reason}")
        append_event_csv("ERR", model_ref=record.model_ref, status="error", context=record.context_length, reason=reason, note="classified failure")

        if "context length" in msg or "n_keep" in msg:
            print(f"CONTEXT_INCREASE_TEST {record.model_ref} :: start")
            append_event_csv("CONTEXT_INCREASE_TEST", model_ref=record.model_ref, status="start", context=record.context_length, reason=reason, note="ratchet")
            if ratchet_context_retry(record, min_context=args.min_context, max_context=args.max_context, probe_timeout=args.probe_timeout):
                if args.optimize:
                    optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
            continue
        if "Invalid model identifier" in msg:
            print(f"CONTEXT_INCREASE_TEST {record.model_ref} :: start (identifier remap + reload)")
            append_event_csv("CONTEXT_INCREASE_TEST", model_ref=record.model_ref, status="start", context=record.context_length, reason=reason, note="identifier remap")
            load_remote_model(record, min(args.max_context, 16384))
            msg2 = opencode_probe(record.model_ref, timeout=args.probe_timeout)
            if msg2.startswith("OK"):
                retry_ok += 1
                enrich_record_from_live_runtime(record)
                record_registry_context(record.api_model_id, "ok", record.context_length, host=record.host)
                print(f"RETRY_OK {record.model_ref} :: reload applied and probe succeeded")
                append_event_csv("RETRY_OK", model_ref=record.model_ref, status="ok", context=record.context_length, reason=reason, note="identifier remap")
                if args.optimize:
                    optimize_llm_performance(record, record.context_length, args.max_context, probe_timeout=args.probe_timeout)
            else:
                retry_fail += 1
                reason2 = msg2.split("\t", 1)[1] if "\t" in msg2 else msg2
                print(f"RETRY_FAILED {record.model_ref} :: reload did not recover ({reason2})")
                append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", context=record.context_length, reason=reason2, note="identifier remap")
            continue
        print(f"RETRY_FAILED {record.model_ref} :: not retryable (non-context/non-identifier error)")
        append_event_csv("RETRY_FAILED", model_ref=record.model_ref, status="error", context=record.context_length, reason=reason, note="not retryable")


def main(argv=None):
    global ARGS, LOG, ok, fail, retry_ok, retry_fail, guardrail, bad_id, ctx_err
    global optimize_ok, optimize_fail
    ARGS = parse_args(argv)
    LOG = ToolForgeLogger("llm_tool", "run", str(DIL_BASE))
    if ARGS.configure_harness:
        try:
            return configure_harness(ARGS)
        finally:
            LOG.close()
    run_mode = "optimize-only" if ARGS.optimize_only else "failures-only" if ARGS.failures_only else "selected" if ARGS.models or ARGS.models_file else "full"
    source_log = ARGS.source_log or (load_models_sidecar(ARGS.models_file).get("source_log") if ARGS.models_file else None)
    LOG.info(f"mode={run_mode} base={DIL_BASE} source_log={source_log}")
    total = 0
    selected_total = 0
    renderer = start_live_renderer()
    rc = 0

    try:
        cfg = load_config()
        if not precheck(cfg):
            LOG.error("precheck failed — no provider endpoints reachable")
            rc = 1
            return rc
        LOG.info("precheck passed")
        models = build_selection(cfg, ARGS)
        total = len(model_keys(cfg))
        selected_total = len(models)
        LOG.info(f"models total={total} selected={selected_total}")
        print(f"MODELS total={total} selected={selected_total}")

        if ARGS.optimize_only:
            for m in models:
                record = build_record(cfg, m)
                cached_ctx = context_cache_get(record.api_model_id)
                start_ctx = cached_ctx or ARGS.min_context
                print(f"MODEL_START {record.model_ref}")
                append_event_csv("MODEL_START", model_ref=record.model_ref, status="start", context=start_ctx, note="optimize-only")
                optimize_llm_performance(record, start_ctx, ARGS.max_context, probe_timeout=ARGS.probe_timeout)
        else:
            run_selected_models(cfg, models, ARGS)
    finally:
        stop_live_renderer(renderer)
        print_summary(total, selected_total, run_mode=run_mode, source_log=source_log, optimize=ARGS.optimize or ARGS.optimize_only)
        LOG.info(f"finished rc={rc} ok={ok} fail={fail} retry_ok={retry_ok} retry_fail={retry_fail}")
        LOG.close()

    return rc


if __name__ == "__main__":
    sys.exit(main())
