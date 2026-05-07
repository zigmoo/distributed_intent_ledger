---
title: "llm_tool Contract"
date: 2026-05-01
machine: shared
assistant: shared
category: contract
memoryType: decision
priority: critical
tags: [contract, llm-tool, lmstudio, model-registry, smoke-matrix, context-ratchet, opencode, pi, configure-harness]
updated: 2026-05-07
source: user+claude-code
domain: operations
project: local-llm-infra
status: active
owner: shared
due:
related_task_id: DIL-1512
related_tasks: [DIL-1518, DIL-1519, DIL-1520, DIL-1543, DIL-1556]
---

# llm_tool Contract

## Purpose

`llm_tool` is the LM Studio model lifecycle manager. It probes models, discovers working context lengths via ratcheting, measures TPS, persists all learned attributes to the model registry, and configures agent harnesses (pi, opencode) with registry-derived capabilities.

The model registry (`_shared/_meta/model_registry.jsonl`) is the single source of truth for all model attributes. Every path through llm_tool reads from and writes back to the registry.

## Provenance

- Parent task: DIL-1512 (Integrate LM Studio on moosacrem1promax into agent harnesses)
- Renamed from `llm_matrix_tool` (DIL-1540, 2026-05-04)
- Working name during development: "smoke matrix"
- The context ratchet / retry ratchet strategy is moo's original design, predating the llmfit review. llmfit contributed ideas around fit tiers, scoring weights, and run-mode classification — not the retry/recovery logic.

## Canonical Paths

- Tool drawer: `_shared/scripts/llm_tool/`
- Bash wrapper: `_shared/scripts/llm_tool/llm_tool.bash`
- Python implementation: `_shared/scripts/llm_tool/llm_tool.py`
- Symlink: `_shared/scripts/bin/llm_tool` (extensionless)
- Opencode config: `~/.config/opencode/opencode.json`
- Pi config: `~/.pi/agent/models.json` + `~/.pi/agent/settings.json`
- Model registry: `_shared/_meta/model_registry.jsonl`
- Run ledger: `_shared/logs/llm_tool/llm_tool_runs.jsonl`
- Event CSV: `_shared/logs/llm_tool/llm_tool.events.<YYYYMMDD_HHMMSS>.csv`
- Context cache: `_shared/logs/llm_tool/model_context_cache.jsonl`
- Run logs: `_shared/logs/llm_tool/llm_tool.run.<YYYYMMDD_HHMMSS>.log`

## Registry as Source of Truth (Critical)

The model registry is the canonical store for all model attributes. Every tool path MUST:

1. **Read** from the registry before using defaults
2. **Write** back to the registry after discovering or verifying attributes
3. **Propagate** registry data to client configs (opencode, pi) during configure-harness

### Registry Fields (per model)

| Field | Type | Written by | Read by |
|---|---|---|---|
| `context_window_tokens` | int | ratchet, optimize, manual seed | `resolve_effective_context`, configure-harness, watchdog |
| `min_working_context_length` | int | ratchet | `registry_target_context` |
| `last_verified_context_length` | int | verify | `registry_target_context` |
| `input_modalities` | string[] | manual seed, future: auto-detect | `_pi_model_entry`, `_opencode_model_entry` |
| `reasoning` | bool | manual seed, future: auto-detect | `_pi_model_entry` |
| `tps` | float | optimize, benchmark | display, ranking |
| `images` | bool | manual seed | display |
| `audio` | bool | manual seed | display |
| `context_verification_status` | string | verify, ratchet | watchdog |

### Context Resolution Order

`resolve_effective_context(args, model_id, host)`:

1. CLI `--context` flag (explicit override) — only if user passed it
2. `registry_target_context()` — reads `min_working_context_length`, `last_verified_context_length`, `context_window_tokens` from registry (in that priority)
3. `DEFAULT_CONFIG_CONTEXT` (32768) — last resort fallback

This ensures the registry is always consulted before falling back to defaults.

## Run Modes

| Mode | CLI | Behavior |
|---|---|---|
| **full** | `llm_tool` | Probe every model in opencode config |
| **selected** | `--model <ref>` (repeatable) or `--models-file <path>` | Probe only named models |
| **failures-only** | `--failures-only [--source-log <path>]` | Re-probe models that failed in a prior run log |
| **optimize-only** | `--optimize-only` | Skip first-pass probing; run TPS optimization sweep on selected models |
| **configure** | `--configure-harness {pi,opencode}` | Configure agent harness with registry-derived model route |
| **watchdog** | `--watchdog` | Check loaded models, fix any with insufficient context |

### JSON Sidecar

`--models-file <path>` accepts a JSON file that can specify:

```json
{
  "models": ["lmstudio/model-a", "lmstudio/model-b"],
  "source_log": "/path/to/prior.log",
  "failures_only": true,
  "optimize": true,
  "optimize_only": false,
  "max_context": 65536,
  "min_context": 8192,
  "limit": 10,
  "probe_timeout": 240
}
```

Sidecar values are defaults — CLI flags take precedence where both are specified.

## Configure Harness

`--configure-harness {pi,opencode}` reads model attributes from the registry and writes them into the target agent's config files.

### Pi Harness (`--configure-harness pi`)

Writes `~/.pi/agent/models.json` and `~/.pi/agent/settings.json`.

Registry fields propagated to pi model entries via `_pi_model_entry()`:

| Registry field | Pi config field | Example |
|---|---|---|
| `display_name` | `name` | `"Qwen 3.6 35B A3B (MoE, Q4_K_M)"` |
| `input_modalities` | `input` | `["text", "image"]` |
| `reasoning` | `reasoning` | `true` |
| `context_window_tokens` | `contextWindow` | `131072` |

Pi requires `"input": ["text", "image"]` (not `"vision": true`) for multimodal support.

### OpenCode Harness (`--configure-harness opencode`)

Writes `~/.config/opencode/opencode.json`.

Registry fields propagated via `_opencode_model_entry()`:

| Registry field | OpenCode config field | Notes |
|---|---|---|
| `display_name` | `name` | Model display name |
| `input_modalities` (if includes "image") | `supports_attachments` | Forward compat — OpenCode doesn't yet support this field (tracked: anomalyco/opencode#20802) |

### Configure Console Output

```
CONFIGURE_START harness=<pi|opencode> target=<host> user=<user> source=<host>
CONFIGURE_SELECT selection=<mode> model_id=<id> model_ref=<provider/id>
CONFIGURE_ENDPOINT base_url=<url>
CONFIGURE_CONTEXT effective=<n> source=<cli|registry|default>
CONFIGURE_LOAD_OK model_id=<id> context=<n>
CONFIGURE_CONTEXT_OK model_id=<id> expected=<n> actual=<n>
CONFIGURE_WRITE_OK config_model=<provider/id>
CONFIGURE_VERIFY_OK harness=<pi|opencode> model_ref=<ref>
```

## Probe Lifecycle (Per Model)

```
1. MODEL_START
2. CONTEXT_PRELOAD (if context cache hit → load model at cached context)
3. First-pass probe via opencode
4. If OK:
   a. Record success to registry
   b. If --optimize: run TPS optimization sweep
   c. Done
5. If FAIL → classify error:
   a. "insufficient system resources" → RESOURCE_RELIEF_TEST
      - Unload all models on remote host
      - Reload target at relief context
      - Re-probe
      - If still fails → RETRY_FAILED, done
      - If recovers → RETRY_OK, optionally optimize
   b. "context length" / "n_keep" → CONTEXT_INCREASE_TEST
      - Run context ratchet (see below)
      - If recovers → optionally optimize
   c. "Invalid model identifier" → reload + re-probe
   d. Other → RETRY_FAILED (not retryable)
```

## Context Ratchet (Original Design)

The context ratchet is the core recovery strategy. When a model fails due to context-length errors, the tool builds a ladder of escalating context sizes and tries each one:

1. Build context ladder from `--min-context` to `--max-context` using 1.5x multiplier steps
2. For each step:
   a. Unload + reload model at candidate context length
   b. Probe
   c. If OK → record minimum working context, stop
   d. If "insufficient system resources" → try resource relief (unload-all + reload)
   e. If resource relief fails → stop (hardware limit reached)
3. If ladder exhausted → record failure

The ladder is geometric (1.5x steps) to cover the range efficiently without testing every possible value. Default range: 8192 to 65536.

### Planned: Registry-Guided Ratchet

Future improvement: the registry should store `recommended_context`, `context_floor`, and `context_ceiling` per model. The ratchet would start at `recommended_context` and ratchet down on failure, instead of climbing blindly from 8K.

## TPS Optimization Sweep

When `--optimize` or `--optimize-only` is specified, the tool sweeps a set of context lengths to find the one that produces the best tokens-per-second:

1. Generate candidate contexts: half current, current, 1.5x, 2x, max
2. For each: reload model, probe, measure TPS
3. Keep the best successful TPS result
4. Persist best context + TPS to registry

## Watchdog

`--watchdog` checks all loaded models on all configured hosts and fixes any with context below the registry target:

1. For each host: query loaded models via HTTP API
2. For each loaded model: look up `registry_target_context()`
3. If loaded context < target: reload at target context
4. Report WATCHDOG_OK or WATCHDOG_FIX_NEEDED

### Reboot Recovery (moosacrem1promax)

A LaunchAgent at `~/Library/LaunchAgents/com.moo.lmstudio-restore.plist` runs on Mac reboot. It waits for LM Studio to come up, then loads the primary model at its registry context length. Script at `~/bin/lmstudio-restore.sh`.

## Event CSV Schema

One CSV file per run. Fields:

| Field | Description |
|---|---|
| `ts` | ISO 8601 UTC timestamp |
| `run_stamp` | Run identifier (YYYYMMDD_HHMMSS) |
| `mode` | Run mode: full, selected, failures-only, optimize-only |
| `event` | Event type (see Event Types below) |
| `model_ref` | Model reference (e.g., `moosacrem1promax/qwen3.6-35b-a3b`) |
| `status` | Result status: start, ok, error |
| `reason` | Human-readable reason or error message |
| `context` | Context length at time of event |
| `tps` | Tokens per second (when measured) |
| `elapsed_s` | Elapsed time for probe |
| `tokens_out` | Output token count |
| `note` | Free-text annotation |

### Event Types

| Event | Meaning |
|---|---|
| `PRECHECK` / `PRECHECK_OK` / `PRECHECK_FAIL` | LM Studio endpoint reachability check |
| `MODEL_START` | Beginning probe cycle for a model |
| `CONTEXT_PRELOAD` | Loading model at previously cached working context |
| `RESULT` | First-pass probe outcome (ok or error) |
| `RESOURCE_RELIEF_TEST` | Attempting unload-all + reload recovery |
| `CONTEXT_INCREASE_TEST` | Beginning context ratchet |
| `RATCHET` | Individual ratchet step at a specific context |
| `RETRY_OK` | Recovery succeeded |
| `RETRY_FAILED` | Recovery exhausted |
| `OPTIMIZE_CONTEXT` | Individual optimization sweep step |
| `OPTIMIZE_OK` | Optimization found best TPS |
| `OPTIMIZE_FAILED` | No successful context in optimization sweep |
| `ERR` | Classified failure (post first-pass) |
| `WATCHDOG_OK` | Loaded model context meets target |
| `WATCHDOG_FIX_NEEDED` | Loaded model context below target |

## Registry Updates

The tool writes back to `_shared/_meta/model_registry.jsonl`. Fields updated:

### After successful probe or ratchet recovery:
- `context_verification_status` → `"ok"`
- `last_context_verified_at` → current timestamp
- `context_verification_host` → host where verified
- `last_verified_context_length` → working context
- `context_window_tokens` → working context
- `min_working_context_length` → min of current and previous

### After optimization:
- `optimization_last_run_at` → current timestamp
- `optimization_best_context_length` → best context
- `optimization_best_tps` → best TPS
- `optimization_history` → last 12 sweep results
- `context_window_tokens` → best context
- `tps` → best TPS
- `success_state` → `"ok"`

### After failure:
- `context_verification_status` → `"guardrail"`, `"invalid_identifier"`, `"too_small"`, or `"error_other"`

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Run completed (individual model failures are recorded, not fatal) |
| `1` | Precheck failed — LM Studio endpoints unreachable |

## Host Routing Contract (Multi-Host)

The tool supports any combination of machine + server + model. Host dispatch is automatic:

- If the target host matches the current machine (`short_hostname()`), commands run locally via `bash -c`
- Otherwise, commands run via SSH with fallback targets from `SSH_TARGETS_BY_HOST`
- Provider-to-host mapping is defined in `PROVIDER_HOST_MAP` and `PROVIDER_SERVER_MAP`

### Supported hosts

| Provider | Host | Server | Endpoint source |
|---|---|---|---|
| `framemoowork` | `framemoowork` | `lmstudio` | `baseURL` from opencode.json |
| `moosacrem1promax` | `moosacrem1promax` | `lmstudio` | `baseURL` from opencode.json |
| `ollama` | `moosacrem1promax` | `ollama` | `baseURL` from opencode.json |

### SSH targets (remote hosts)

- `moosacrem1promax`: tries `moosacrem1promax.jay-frog.ts.net`, then `moosacrem1promax.local`

### CLI filtering

- `--host framemoowork` — only probe models whose provider maps to framemoowork
- `--provider moosacrem1promax` — only probe models from that opencode provider
- Both can be combined

### Precheck

Precheck reads `baseURL` from each provider in opencode.json and curls `{baseURL}/models`. At least one provider must respond for the run to proceed.

- LM Studio CLI: `lms load`, `lms unload`, `lms ps` (run on target host)
- Probe tool: `opencode run --pure --model <ref> --format json "hello"`

## Live Rendering

When `duckdb_sql` is available, the tool runs a background thread that periodically (every 10 seconds) queries the event CSV via DuckDB and renders a summary + recent-events table to stdout. This provides real-time visibility during long matrix runs.

## Console Output Contract

Key structured lines emitted to stdout (consumed by the bash wrapper's `tee` into the run log):

```
MATRIX_START <iso-timestamp>
PRECHECK route=<url>
PRECHECK_OK route=<label>
MODELS total=<n> selected=<n>
MODEL_START <model_ref>
CONTEXT_PRELOAD <model_ref> :: context=<n> (from cache)
OK    <model_ref> tokens_out=<n> elapsed=<s> tps=<n>
ERR   <model_ref> :: <reason>
RETRY_OK <model_ref> :: <description>
RETRY_FAILED <model_ref> :: <description>
RATCHET  <model_ref> context=<n>
OPTIMIZE_CONTEXT <model_ref> context=<n>
OPTIMIZE_OK <model_ref> :: best_context=<n> best_tps=<n>
SUMMARY total=<n> selected=<n> mode=<mode> ok=<n> fail=<n> ...
MATRIX_END <iso-timestamp>
```

## Dependencies

| Dependency | Purpose | Notes |
|---|---|---|
| `opencode` | Model probing | Must be in PATH |
| `curl` | Precheck endpoint reachability | System package |
| `ssh` | Remote LM Studio CLI commands | Uses `-F /dev/null` to bypass config issues |
| `lms` | LM Studio CLI (on remote host) | load, unload, ps |
| `duckdb_sql` | Live table rendering (optional) | Falls back gracefully if absent |
| Python stdlib | All Python logic | No pip dependencies (Tool Forge Standard #2) |

## Bugs Fixed (2026-05-07)

1. **`--ttl -1` silently failed** — LM Studio rejects `-1` as TTL, causing every ratchet reload to silently fail. Removed from all `lms load` calls.
2. **Load path ignored registry** — `configure-harness` used `args.context` (default 32768) without consulting `registry_target_context()`. Fixed with `resolve_effective_context()`.
3. **Configure-harness didn't propagate capabilities** — `build_pi_config` and `build_opencode_config` only wrote `id` and `name`. Now writes `input`, `reasoning`, `contextWindow` from registry via `_pi_model_entry()` / `_opencode_model_entry()`.
4. **`resolve_base` matched nested `_shared/_meta/`** — the walker found `_shared/scripts/_shared/_meta/` before the real `_shared/_meta/`. Fixed to require `model_registry.jsonl` or `READ_THIS_DIL_FIRST.md` as specific markers.

## Known Limitations

1. Sequential model processing — no parallelism within a run.
2. `host_cmd` interpolates model IDs into shell strings — shell injection risk if model IDs ever contain metacharacters (tracked in DIL-1520).
3. Registry updates filter on `server == "lmstudio"` — ollama models won't get registry writes until ollama rows are added to the registry.
4. TPS measurement via opencode probe includes massive overhead (process startup, thinking tokens) — does not reflect true inference speed. Direct HTTP probe would be more accurate.
5. Model identity matching between opencode config refs, LM Studio API IDs, and registry `model_id`/`backend_model_id` is fragile — identifiers must match exactly or the registry lookup fails silently.
6. `input_modalities` and `reasoning` flags are currently seeded manually — future: auto-detect from LM Studio's model metadata (`vision`, `trainedForToolUse`) during probe.
