#!/usr/bin/env bash
# llm_local_tool_test_script.bash — golden file diff test suite for llm_local_tool
# Script Forge Standard #10: Diff-Stable Test Output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPTS_DIR/lib/resolve_base.sh"
BASE="$(resolve_dil_base_or_die "$SCRIPTS_DIR" "${BASE_DIL:-}")"

TOOL_NAME="llm_local_tool"
TEST_SCRIPT_NAME="llm_local_tool_test_script"
GOLDEN_DIR="$SCRIPT_DIR/${TEST_SCRIPT_NAME%_test_script}_test_golden"
LOG_DIR="$BASE/_shared/logs/$TEST_SCRIPT_NAME"
mkdir -p "$LOG_DIR" "$GOLDEN_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${TEST_SCRIPT_NAME}.run.${TIMESTAMP}.log"

REBUILD=false
SINGLE_TEST=""
KEEP_TEMP=false
QUIET=false
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) REBUILD=true; shift ;;
    --test) SINGLE_TEST="$2"; shift 2 ;;
    --keep-temp) KEEP_TEMP=true; shift ;;
    --quiet) QUIET=true; shift ;;
    -h|--help)
      echo "Usage: $TEST_SCRIPT_NAME [--rebuild] [--test N] [--keep-temp] [--quiet]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

TEST_WORKSPACE="$(mktemp -d /tmp/${TOOL_NAME}-test.XXXXXX)"
if ! $KEEP_TEMP; then
  trap 'rm -rf "$TEST_WORKSPACE"' EXIT
fi

normalize() {
  sed \
    -e "s|$TEST_WORKSPACE|<TMP>|g" \
    -e "s|$BASE|<BASE>|g" \
    -e "s|$HOME|<HOME>|g" \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}Z/TIMESTAMP/g' \
    -e 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}/DATE/g' \
    -e 's/[0-9]\{8\}_[0-9]\{6\}/DATETIME/g' \
    -e 's/pid=[0-9]*/pid=<PID>/g'
}

ACTUAL_DIR="$TEST_WORKSPACE/actual"
mkdir -p "$ACTUAL_DIR"

run_test() {
  local test_number="$1"
  local test_label="$2"
  local test_function="$3"
  TOTAL=$((TOTAL + 1))

  if [[ -n "$SINGLE_TEST" && "$SINGLE_TEST" != "$test_number" ]]; then
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  if ! $QUIET; then
    printf "\n[%s] %s\n" "$test_number" "$test_label"
  fi

  local actual_file="$ACTUAL_DIR/test_$(printf '%02d' "$test_number").actual"
  local golden_file="$GOLDEN_DIR/test_$(printf '%02d' "$test_number").golden"

  $test_function 2>&1 | normalize > "$actual_file"

  if $REBUILD; then
    cp "$actual_file" "$golden_file"
    if ! $QUIET; then
      echo "  REBUILT: $golden_file"
    fi
    PASSED=$((PASSED + 1))
    return
  fi

  if [[ ! -f "$golden_file" ]]; then
    echo "  SKIP: no golden file (run with --rebuild)"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  if diff -u "$golden_file" "$actual_file" > /dev/null 2>&1; then
    if ! $QUIET; then
      echo "  PASS"
    fi
    PASSED=$((PASSED + 1))
  else
    echo "  FAIL: output differs from golden baseline"
    diff -u "$golden_file" "$actual_file" || true
    FAILED=$((FAILED + 1))
  fi
}

# --- Test cases ---

test_01_help_output() {
  $TOOL_NAME --help 2>&1 || true
}

test_02_bare_registry_resolution() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

resolved = mod.resolve_model_target(Path("$BASE"), "allenai/olmo-3-32b-think")
print(f"resolved_ref={resolved['resolved_ref']}")
print(f"host={resolved['entry'].get('host') if resolved['entry'] else 'none'}")
print(f"endpoint={resolved['endpoint']}")
PY
}

test_03_auto_load_request() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

calls = []

class DummyResult:
    returncode = 0
    stdout = "loaded\n"
    stderr = ""

def fake_run(cmd, text, capture_output, timeout, check):
    calls.append(cmd)
    return DummyResult()

mod.subprocess.run = fake_run
resolved = {
    "entry": {"loaded": False, "model_id": "allenai/olmo-3-32b-think", "host": "framemoowork"},
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}
mod.ensure_model_loaded(resolved)
print("calls=" + " ".join(calls[0]))
PY
}

test_03b_remote_load_uses_ssh() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

calls = []

class FirstResult:
    returncode = 255
    stdout = ""
    stderr = "ssh: connect to host moosacrem1promax.jay-frog.ts.net port 22: Connection timed out\n"

class SecondResult:
    returncode = 0
    stdout = "loaded remotely\n"
    stderr = ""

def fake_run(cmd, text, capture_output, timeout, check):
    calls.append(cmd)
    if len(calls) == 1:
        return FirstResult()
    return SecondResult()

mod.subprocess.run = fake_run
mod.short_hostname = lambda: "framemoowork"
resolved = {
    "entry": {"loaded": False, "model_id": "allenai/olmo-3-32b-think", "host": "moosacrem1promax"},
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}
mod.ensure_model_loaded(resolved)
print("calls=" + " || ".join(" ".join(call) for call in calls))
PY
}

test_04_timeout_is_passed_through() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

seen = {}

class DummyResponse:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return b'{"choices":[{"message":{"content":"ok","reasoning_content":""}}]}'

def fake_open(request, timeout):
    seen["timeout"] = timeout
    return DummyResponse()

mod.resolve_model_candidates = lambda base, model_ref, preferred_host=None: [{
    "entry": {"loaded": True, "model_id": "allenai/olmo-3-32b-think", "host": "framemoowork"},
    "endpoint": "http://example.invalid/v1/chat/completions",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}]
mod.ensure_model_loaded = lambda resolved, log=None: None
mod.urllib.request.urlopen = fake_open
mod.test_model("allenai/olmo-3-32b-think", "hello", Path("$BASE"), timeout_seconds=77)
print(f"timeout={seen['timeout']}")
PY
}

test_05_guardrails_error_is_classified() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class DummyResult:
    returncode = 1
    stdout = ""
    stderr = "Error: Model loading was stopped due to insufficient system resources."

def fake_run(cmd, text, capture_output, timeout, check):
    return DummyResult()

mod.subprocess.run = fake_run
try:
    mod.ensure_model_loaded({"entry": {"loaded": False, "model_id": "allenai/olmo-3-32b-think"}, "resolved_ref": "lmstudio/allenai/olmo-3-32b-think"})
except Exception as exc:
    print(type(exc).__name__)
    print(str(exc))
PY
}

test_06_tps_prefers_faster_host() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.load_registry = lambda base: [
    {"host": "framemoowork", "server": "lmstudio", "model_id": "allenai/olmo-3-32b-think", "display_name": "a", "tps": 12.5, "status": "active"},
    {"host": "moosacrem1promax", "server": "lmstudio", "model_id": "allenai/olmo-3-32b-think", "display_name": "a", "tps": 33.7, "status": "active"},
]
mod.short_hostname = lambda: "framemoowork"
resolved = mod.resolve_model_candidates(Path("$BASE"), "allenai/olmo-3-32b-think")
print(resolved[0]["entry"]["host"])
print(resolved[0]["entry"]["tps"])
PY
}

test_07_registry_writeback_updates_snapshot() {
  python3 - <<PY
from pathlib import Path
import importlib.util
import json

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "mini-base"
registry_path = base / "_shared" / "_meta"
registry_path.mkdir(parents=True, exist_ok=True)
(registry_path / "model_registry.jsonl").write_text("\n".join([
    json.dumps({"host":"framemoowork","server":"lmstudio","model_id":"ibm/granite-4-h-tiny","display_name":"ibm/granite-4-h-tiny","status":"active","tps":134.418,"total_latency_ms":744,"loaded":False,"route_notes":"Fastest general-purpose local path for quick reasoning and short edits."}),
    json.dumps({"host":"moosacrem1promax","server":"lmstudio","model_id":"allenai/olmo-3-32b-think","display_name":"allenai/olmo-3-32b-think","status":"active","tps":13.722,"total_latency_ms":7288,"loaded":False,"route_notes":"thinking-oriented model; slow but usable"}),
]) + "\n", encoding="utf-8")

updated = mod.update_registry_entry(
    base,
    "framemoowork",
    "lmstudio",
    "ibm/granite-4-h-tiny",
    {
        "loaded": True,
        "last_loaded_at": "2026-04-30T04:08:23Z",
        "total_latency_ms": 321,
        "tps": 999.123,
        "updated": "2026-04-30",
    },
)
summary = mod._format_fastest_test_summary(mod.load_registry(base))
print(updated["loaded"])
print(updated["total_latency_ms"])
print(updated["tps"])
print(summary["model"])
print(summary["host"])
print(summary["tps"])
PY
}

test_08_sync_inventory_updates_registry() {
  python3 - <<PY
from pathlib import Path
import importlib.util
import json

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "sync-base"
registry_path = base / "_shared" / "_meta"
registry_path.mkdir(parents=True, exist_ok=True)
(registry_path / "model_registry.jsonl").write_text("\n".join([
    json.dumps({"host":"framemoowork","server":"lmstudio","model_id":"ibm/granite-4-h-tiny","display_name":"ibm/granite-4-h-tiny","status":"active","downloaded":False,"loaded":False,"size_bytes":1,"size_human":"1 B","file_path":"","last_modified":"2026-04-20","tps":134.418,"route_notes":"Fastest general-purpose local path for quick reasoning and short edits."}),
    json.dumps({"host":"framemoowork","server":"lmstudio","model_id":"old/stale-model","display_name":"old/stale-model","status":"active","downloaded":True,"loaded":False,"size_bytes":2,"size_human":"2 B","file_path":"","last_modified":"2026-04-20"}),
    json.dumps({"host":"moosacrem1promax","server":"lmstudio","model_id":"liquid/lfm2.5-1.2b","display_name":"liquid/lfm2.5-1.2b","status":"active","downloaded":False,"loaded":False,"size_bytes":3,"size_human":"3 B","file_path":"","last_modified":"2026-04-20","tps":141.042,"route_notes":"Very fast small-model backup for simpler work."}),
    json.dumps({"host":"moosacrem1promax","server":"lmstudio","model_id":"text-embedding-nomic-embed-text-v1.5","display_name":"text-embedding-nomic-embed-text-v1.5","status":"active","downloaded":False,"loaded":False,"size_bytes":4,"size_human":"4 B","file_path":"","last_modified":"2026-04-20"}),
]) + "\n", encoding="utf-8")

commands = []

def fake_filesystem(host, log=None):
    commands.append(host)
    payloads = {
        "framemoowork": [
            {"collection": "lmstudio", "model_dir": "ibm/granite-4-h-tiny", "path": "/lmstudio/granite", "size_bytes": 4541927916, "last_modified": "2026-04-30"},
            {"collection": "lmstudio", "model_dir": "text-embedding-nomic-embed-text-v1.5", "path": "/lmstudio/embed", "size_bytes": 88195727, "last_modified": "2026-04-30"},
        ],
        "moosacrem1promax": [
            {"collection": "lmstudio", "model_dir": "liquid/lfm2.5-1.2b", "path": "/lmstudio/lfm2.5", "size_bytes": 1245540516, "last_modified": "2026-04-30"},
            {"collection": "lmstudio", "model_dir": "text-embedding-nomic-embed-text-v1.5", "path": "/lmstudio/embed-remote", "size_bytes": 88195727, "last_modified": "2026-04-30"},
        ],
    }
    return type("R", (), {"returncode": 0, "stdout": json.dumps(payloads[host]), "stderr": ""})()

mod._run_filesystem_inventory_command = fake_filesystem
mod.LMSTUDIO_INVENTORY_HOSTS = ("framemoowork", "moosacrem1promax")
summary = mod.sync_inventory(base)
registry = mod.load_registry(base)

def find(host, model_id):
    for row in registry:
        if row.get("host") == host and row.get("server") == "lmstudio" and row.get("model_id") == model_id:
            return row
    raise AssertionError(f"missing row: {host} {model_id}")

granite = find("framemoowork", "ibm/granite-4-h-tiny")
stale = find("framemoowork", "old/stale-model")
small = find("moosacrem1promax", "liquid/lfm2.5-1.2b")

print(summary["added"])
print(summary["missing"])
print(granite["size_bytes"])
print(granite["file_path"])
print(granite["inventory_ref"])
print(stale["status"])
print(stale["downloaded"])
print(small["size_bytes"])
print(small["file_path"])
PY
}

test_09_sync_inventory_skips_unreachable_hosts() {
  python3 - <<PY
from pathlib import Path
import importlib.util
import json

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "best-effort-base"
registry_path = base / "_shared" / "_meta"
registry_path.mkdir(parents=True, exist_ok=True)
(registry_path / "model_registry.jsonl").write_text("\n".join([
    json.dumps({"host":"framemoowork","server":"lmstudio","model_id":"ibm/granite-4-h-tiny","display_name":"ibm/granite-4-h-tiny","status":"active","downloaded":False,"loaded":False,"size_bytes":1,"size_human":"3 B","file_path":"","last_modified":"2026-04-20","tps":134.418}),
    json.dumps({"host":"moosacrem1promax","server":"lmstudio","model_id":"liquid/lfm2.5-1.2b","display_name":"liquid/lfm2.5-1.2b","status":"active","downloaded":False,"loaded":False,"size_bytes":3,"size_human":"3 B","file_path":"","last_modified":"2026-04-20","tps":141.042}),
]) + "\n", encoding="utf-8")

def fake_filesystem_inventory(host, log=None):
    if host == "framemoowork":
        return type("R", (), {"returncode": 0, "stdout": json.dumps([
            {"collection": "lmstudio", "model_dir": "ibm/granite-4-h-tiny", "path": "/lmstudio/granite", "size_bytes": 4541927916, "last_modified": "2026-04-30"},
        ]), "stderr": ""})()
    return type("R", (), {"returncode": 255, "stdout": "", "stderr": "ssh: connect to host timed out"})()

mod._run_filesystem_inventory_command = fake_filesystem_inventory
summary = mod.sync_inventory(base)
registry = mod.load_registry(base)

def find(host, model_id):
    for row in registry:
        if row.get("host") == host and row.get("server") == "lmstudio" and row.get("model_id") == model_id:
            return row
    raise AssertionError(f"missing row: {host} {model_id}")

granite = find("framemoowork", "ibm/granite-4-h-tiny")
remote = find("moosacrem1promax", "liquid/lfm2.5-1.2b")

print(summary["added"])
print(summary["missing"])
print(len(summary["errors"]))
print(granite["size_bytes"])
print(granite["file_path"])
print(remote["status"])
print(remote["tps"])
PY
}

test_10_opencode_add_writes_model_mapping() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-base"
base.mkdir(parents=True, exist_ok=True)

entry = {
    "host": "framemoowork",
    "server": "lmstudio",
    "model_id": "allenai/olmo-3-32b-think",
    "backend_model_id": "allenai/olmo-3-32b-think",
    "display_name": "OLMo 3 32B Think",
    "tps": 13.5,
}
mod.resolve_model_candidates = lambda base, model_ref, preferred_host=None: [{
    "entry": entry,
    "endpoint": "http://10.0.1.130:1234/v1/chat/completions",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}]
mod.probe_model = lambda *a, **k: {
    "ok": True,
    "model_id": "allenai/olmo-3-32b-think",
    "prompt": "ping",
    "host": "framemoowork",
    "server": "lmstudio",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
    "latency_ms": 321,
    "tps": 9.9,
    "response": "pong",
}
mod._load_opencode_config = lambda host, log=None: {
    "model": "opencode/kimi-k2.6",
    "provider": {
        "ollama": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Ollama (moosacrem1promax)",
            "models": {"gemma4": {"id": "gemma4:latest", "name": "Gemma 4 (Ollama)"}},
            "options": {"baseURL": "http://moosacrem1promax.jay-frog.ts.net:11434/v1"},
        }
    },
}
written = {}
def fake_write(host, config, log=None):
    written["host"] = host
    written["config"] = config
    return {"ok": True, "path": "/fake/opencode.json"}
mod._write_opencode_config = fake_write
result = mod.opencode_add_model(
    base,
    config_host="framemoowork",
    model_ref="allenai/olmo-3-32b-think",
    source_host="framemoowork",
    alias="olmo-think",
    set_default=True,
)
print(result["ok"])
print(result["config_host"])
print(result["preflight"]["tps"])
print(written["host"])
print(written["config"]["provider"]["lmstudio"]["models"]["olmo-think"]["id"])
print(written["config"]["model"])
PY
}

test_11_opencode_preflight_blocks_write_without_force() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-fail-base"
base.mkdir(parents=True, exist_ok=True)

entry = {
    "host": "framemoowork",
    "server": "lmstudio",
    "model_id": "allenai/olmo-3-32b-think",
    "backend_model_id": "allenai/olmo-3-32b-think",
    "display_name": "OLMo 3 32B Think",
}
mod.resolve_model_candidates = lambda base, model_ref, preferred_host=None: [{
    "entry": entry,
    "endpoint": "http://10.0.1.130:1234/v1/chat/completions",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}]
mod.probe_model = lambda *a, **k: {"ok": False, "error": "timed out", "exception": RuntimeError("timed out")}
mod._load_opencode_config = lambda host, log=None: {}
writes = []
mod._write_opencode_config = lambda host, config, log=None: writes.append((host, config)) or {"ok": True, "path": "/fake/opencode.json"}
result = mod.opencode_add_model(
    base,
    config_host="framemoowork",
    model_ref="allenai/olmo-3-32b-think",
    source_host="framemoowork",
    alias="olmo-think",
    set_default=False,
)
print(result["ok"])
print(result["reason"])
print(len(writes))
PY
}

test_12_opencode_preflight_force_allows_write() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-force-base"
base.mkdir(parents=True, exist_ok=True)

entry = {
    "host": "framemoowork",
    "server": "lmstudio",
    "model_id": "allenai/olmo-3-32b-think",
    "backend_model_id": "allenai/olmo-3-32b-think",
    "display_name": "OLMo 3 32B Think",
}
mod.resolve_model_candidates = lambda base, model_ref, preferred_host=None: [{
    "entry": entry,
    "endpoint": "http://10.0.1.130:1234/v1/chat/completions",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}]
mod.probe_model = lambda *a, **k: {"ok": False, "error": "timed out", "exception": RuntimeError("timed out")}
mod._load_opencode_config = lambda host, log=None: {}
writes = []
mod._write_opencode_config = lambda host, config, log=None: writes.append((host, config)) or {"ok": True, "path": "/fake/opencode.json"}
result = mod.opencode_add_model(
    base,
    config_host="framemoowork",
    model_ref="allenai/olmo-3-32b-think",
    source_host="framemoowork",
    alias="olmo-think",
    force=True,
    set_default=True,
)
print(result["ok"])
print(result["preflight"]["error"])
print(len(writes))
print(writes[0][1]["model"])
PY
}

test_13_opencode_writebacks_include_backup_metadata() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-backup-base"
base.mkdir(parents=True, exist_ok=True)
mod.resolve_model_candidates = lambda base, model_ref, preferred_host=None: [{
    "entry": {
        "host": "framemoowork",
        "server": "lmstudio",
        "model_id": "allenai/olmo-3-32b-think",
        "backend_model_id": "allenai/olmo-3-32b-think",
        "display_name": "OLMo 3 32B Think",
        "tps": 13.5,
    },
    "endpoint": "http://10.0.1.130:1234/v1/chat/completions",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
}]
mod.probe_model = lambda *a, **k: {
    "ok": True,
    "model_id": "allenai/olmo-3-32b-think",
    "prompt": "ping",
    "host": "framemoowork",
    "server": "lmstudio",
    "resolved_ref": "lmstudio/allenai/olmo-3-32b-think",
    "latency_ms": 321,
    "tps": 9.9,
    "response": "pong",
}
mod._load_opencode_config = lambda host, log=None: {"model": "opencode/kimi-k2.6", "provider": {}}
mod._write_opencode_config = lambda host, config, log=None: {"ok": True, "path": "/fake/opencode.json", "backup_path": "/fake/opencode.json.bak.20260430_000000"}
result = mod.opencode_add_model(
    base,
    config_host="framemoowork",
    model_ref="allenai/olmo-3-32b-think",
    source_host="framemoowork",
    alias="olmo-think",
    set_default=True,
)
print(result["write_result"]["backup_path"])
PY
}

test_14_opencode_sync_labels_moosacrem1promax_models() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-sync-base"
registry_path = base / "_shared" / "_meta"
registry_path.mkdir(parents=True, exist_ok=True)
(registry_path / "model_registry.jsonl").write_text("\n".join([
    '{"host":"framemoowork","server":"lmstudio","model_id":"a","backend_model_id":"a","display_name":"A","status":"active","tps":1.1}',
    '{"host":"moosacrem1promax","server":"lmstudio","model_id":"beta-model","backend_model_id":"beta-backend","display_name":"Beta Model","status":"active","tps":12.34}',
    '{"host":"moosacrem1promax","server":"lmstudio","model_id":"gamma-model","backend_model_id":"gamma-backend","display_name":"Gamma Model","status":"active","tps":9.0}',
]) + "\n", encoding="utf-8")

loaded = {}
written = {}
mod._load_opencode_config = lambda host, log=None: loaded.setdefault(host, {
    "model": "opencode/kimi-k2.6",
    "provider": {
        "lmstudio": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LM Studio (moosacrem1promax.local)",
            "models": {
                "legacy": {"id": "legacy-id", "name": "Legacy"},
            },
            "options": {"baseURL": "http://100.72.152.28:1234/v1", "extraHeaders": {"Authorization": "Bearer lm-studio"}},
        }
        }
    })
def fake_write(host, config, log=None):
    written["host"] = host
    written["config"] = config
    return {"ok": True, "path": "/fake/opencode.json", "backup_path": "/fake/opencode.json.bak.20260430_000000"}
mod._write_opencode_config = fake_write
result = mod.opencode_sync_models(base, config_host="framemoowork", source_host="moosacrem1promax", set_default=False)
models = result["models"]
print(result["ok"])
print(result["source_host"])
print(models["beta-model"]["name"])
print(models["gamma-model"]["name"])
print(written["config"]["provider"]["lmstudio"]["models"]["beta-model"]["id"])
print(written["config"]["provider"]["lmstudio"]["models"]["gamma-model"]["name"])
print(written["config"]["provider"]["lmstudio"]["models"].get("legacy", {}).get("id"))
PY
}

test_15_opencode_sync_sets_default_to_fastest_moosacrem1promax_model() {
  python3 - <<PY
from pathlib import Path
import importlib.util

module_path = Path("$SCRIPT_DIR") / "llm_local_tool.py"
spec = importlib.util.spec_from_file_location("llm_local_tool", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

base = Path("$TEST_WORKSPACE") / "opencode-sync-default-base"
registry_path = base / "_shared" / "_meta"
registry_path.mkdir(parents=True, exist_ok=True)
(registry_path / "model_registry.jsonl").write_text("\n".join([
    '{"host":"moosacrem1promax","server":"lmstudio","model_id":"fast-model","backend_model_id":"fast-backend","display_name":"Fast Model","status":"active","tps":42.5}',
    '{"host":"moosacrem1promax","server":"lmstudio","model_id":"slow-model","backend_model_id":"slow-backend","display_name":"Slow Model","status":"active","tps":3.5}',
]) + "\n", encoding="utf-8")

written = {}
mod._load_opencode_config = lambda host, log=None: {"model": "opencode/kimi-k2.6", "provider": {}}
def fake_write(host, config, log=None):
    written["host"] = host
    written["config"] = config
    return {"ok": True, "path": "/fake/opencode.json", "backup_path": "/fake/opencode.json.bak.20260430_000000"}
mod._write_opencode_config = fake_write
result = mod.opencode_sync_models(base, config_host="framemoowork", source_host="moosacrem1promax", set_default=True)
print(result["ok"])
print(result["default_model"])
print(written["config"]["model"])
print(written["config"]["provider"]["lmstudio"]["models"]["fast-model"]["name"])
PY
}

# Add more test functions here:
# test_02_basic_operation() { ... }
# test_03_error_handling() { ... }

# --- Run tests ---

run_test 1 "help output" test_01_help_output
run_test 2 "bare registry resolution" test_02_bare_registry_resolution
run_test 3 "auto load request" test_03_auto_load_request
run_test 4 "remote load uses ssh" test_03b_remote_load_uses_ssh
run_test 5 "timeout passthrough" test_04_timeout_is_passed_through
run_test 6 "guardrails classification" test_05_guardrails_error_is_classified
run_test 7 "tps preference" test_06_tps_prefers_faster_host
run_test 8 "registry writeback updates snapshot" test_07_registry_writeback_updates_snapshot
run_test 9 "sync inventory updates registry" test_08_sync_inventory_updates_registry
run_test 10 "sync inventory skips unreachable hosts" test_09_sync_inventory_skips_unreachable_hosts
run_test 11 "opencode add writes model mapping" test_10_opencode_add_writes_model_mapping
run_test 12 "opencode add blocks without force" test_11_opencode_preflight_blocks_write_without_force
run_test 13 "opencode force allows write" test_12_opencode_preflight_force_allows_write
run_test 14 "opencode writebacks include backup metadata" test_13_opencode_writebacks_include_backup_metadata
run_test 15 "opencode sync labels moosacrem1promax models" test_14_opencode_sync_labels_moosacrem1promax_models
run_test 16 "opencode sync sets default to fastest moosacrem1promax model" test_15_opencode_sync_sets_default_to_fastest_moosacrem1promax_model

# --- Summary ---

echo ""
if $REBUILD; then
  echo "=== REBUILT: $PASSED golden baselines regenerated ==="
elif [[ $FAILED -eq 0 ]]; then
  echo "=== ALL PASSED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
else
  echo "=== FAILED: $PASSED passed, $FAILED failed, $SKIPPED skipped ($TOTAL total) ==="
fi
echo "Log: $LOG_FILE"

[[ $FAILED -eq 0 ]]
