# llm_matrix_tool

Purpose: run an LM Studio model matrix from framemoowork against the Mac LM Studio host, with:
- early route precheck
- per-model pass/fail visibility
- context ratchet retry up to the configured ceiling
- failure-only reruns from a prior log
- subset selection via CLI args or JSON sidecar
- optional `optimize_llm_performance()` pass after a model first runs
- summary counters
- context discovery persistence into `_shared/_meta/model_registry.jsonl`
- harness configuration for verified model routes, starting with OpenCode

## Entry points
- Bash wrapper: `llm_matrix_tool.bash`
- Python implementation: `llm_matrix_tool.py`
- Extensionless bin command: `llm_matrix_tool`

## Usage
```bash
llm_matrix_tool;
```

### Common modes

- Rerun only failures from a previous log:
```bash
llm_matrix_tool --failures-only --source-log /path/to/old.log;
```
- Rerun a selected subset:
```bash
llm_matrix_tool --model lmstudio/lfm2-5-1-2b --model lmstudio/qwen3.6-35b-a3b;
```
- Use a JSON sidecar:
```bash
llm_matrix_tool --models-file /path/to/selection.json;
```

### Configure OpenCode on a target machine

Configure a target user's OpenCode harness from an LM Studio source host. The tool can select the most powerful responsive model from the registry, the fastest responsive model, or a specific model.

```bash
llm_matrix_tool \
  --configure-harness opencode \
  --target-host pi5-16g.local \
  --target-user moo \
  --source-host moosacrem1promax \
  --selection powerful \
  --install-harness;
```

Use a specific model and a known endpoint when DNS discovery is flaky:

```bash
llm_matrix_tool \
  --configure-harness opencode \
  --target-host pi5-16g.local \
  --target-user moo \
  --source-host moosacrem1promax \
  --selection specific \
  --specific-model qwen/qwen3.6-35b-a3b \
  --base-url http://10.0.1.142:1234/v1;
```

If the source LM Studio model is already loaded and reachable, skip source-host SSH control and only write/verify the target harness:

```bash
llm_matrix_tool \
  --configure-harness opencode \
  --target-host pi5-16g.local \
  --target-user moo \
  --source-host moosacrem1promax \
  --selection specific \
  --specific-model qwen/qwen3.6-35b-a3b \
  --base-url http://10.0.1.142:1234/v1 \
  --skip-load;
```
