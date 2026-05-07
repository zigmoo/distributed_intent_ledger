# llm_tool

LM Studio model lifecycle manager. Probes models, discovers context lengths via ratcheting, measures TPS, persists attributes to the model registry, and configures agent harnesses (pi, opencode) with registry-derived capabilities.

The model registry (`_shared/_meta/model_registry.jsonl`) is the single source of truth.

## Entry points
- Bash wrapper: `llm_tool.bash`
- Python implementation: `llm_tool.py`
- Extensionless bin command: `llm_tool`

## Usage

### Full matrix run
```bash
llm_tool
```

### Probe specific models
```bash
llm_tool --model moosacrem1promax/nemotron-3-nano-omni
llm_tool --model moosacrem1promax/qwen3.6-35b-a3b --optimize
```

### Rerun failures from a prior log
```bash
llm_tool --failures-only --source-log /path/to/old.log
```

### JSON sidecar
```bash
llm_tool --models-file /path/to/selection.json
```

### Configure pi harness

```bash
llm_tool \
  --configure-harness pi \
  --source-host moosacrem1promax \
  --selection specific \
  --specific-model "qwen/qwen3.6-35b-a3b" \
  --target-host framemoowork \
  --skip-load
```

This reads `input_modalities`, `reasoning`, and `context_window_tokens` from the registry and writes them into `~/.pi/agent/models.json` as `input`, `reasoning`, and `contextWindow`.

### Configure opencode harness

```bash
llm_tool \
  --configure-harness opencode \
  --source-host moosacrem1promax \
  --selection powerful \
  --target-host framemoowork
```

### Watchdog (check and fix loaded model context)

```bash
llm_tool --watchdog
llm_tool --watchdog --watchdog-dry-run
llm_tool --watchdog-status
```

## Model Registry Examples

Each line in `_shared/_meta/model_registry.jsonl` is a JSON object. Key fields for two representative models:

### Qwen 3.6 35B A3B (MoE, text + vision)

```json
{
  "model_id": "qwen/qwen3.6-35b-a3b",
  "backend_model_id": "qwen/qwen3.6-35b-a3b",
  "display_name": "Qwen 3.6 35B A3B (MoE, Q4_K_M)",
  "host": "your-own-free-range-lm-studio-server.local",
  "server": "lmstudio",
  "status": "active",
  "downloaded": true,
  "size_human": "20.55 GB",
  "quantization": "Q4_K_M",
  "context_window_tokens": 131072,
  "min_working_context_length": 131072,
  "last_verified_context_length": 131072,
  "context_verification_status": "ok",
  "input_modalities": ["text", "image"],
  "reasoning": true,
  "images": true,
  "tps": 45.0,
  "best_fit_task_types": ["code_generation_fast", "reasoning", "chat", "tool_heavy_agent_loop"]
}
```

### Nemotron-3-Nano-Omni 30B A3B (MoE, text + vision + audio)

```json
{
  "model_id": "nvidia/nemotron-3-nano-omni",
  "backend_model_id": "nemotron-3-nano-omni",
  "display_name": "Nemotron-3-Nano-Omni 30B A3B Reasoning (MoE, Q4_K_M)",
  "host": "your-own-free-range-lm-studio-server.local",
  "server": "lmstudio",
  "status": "active",
  "downloaded": true,
  "size_human": "24.31 GB",
  "quantization": "Q4_K_M",
  "context_window_tokens": 131072,
  "min_working_context_length": 16384,
  "last_verified_context_length": 131072,
  "context_verification_status": "ok",
  "input_modalities": ["text", "image", "audio"],
  "reasoning": true,
  "images": true,
  "audio": true,
  "tps": 45.0,
  "best_fit_task_types": ["reasoning", "code_generation_fast", "multimodal", "vision_or_ocr_extraction"]
}
```

### How configure-harness uses these

When `llm_tool --configure-harness pi --specific-model "qwen/qwen3.6-35b-a3b"` runs, it reads the registry row above and writes to `~/.pi/agent/models.json`:

```json
{
  "id": "qwen/qwen3.6-35b-a3b",
  "name": "Qwen 3.6 35B A3B (MoE, Q4_K_M)",
  "input": ["text", "image"],
  "reasoning": true,
  "contextWindow": 131072
}
```

Pi then knows this model supports images and sends multimodal requests with base64 image content parts.

## Full contract

See `CONTRACT.md` in this drawer for the complete specification.
