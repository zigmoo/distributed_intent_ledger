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
