# llm_matrix_tool logs

Output directory for llm_matrix_tool run artifacts:

- `llm_matrix_tool_runs.jsonl` — append-only run ledger (one JSON object per run)
- `model_context_cache.jsonl` — learned context sizes per model (persists across runs)
- `llm_matrix_tool.events.<timestamp>.csv` — per-run event CSV (model, status, tokens, tps, elapsed)

These files are created automatically by `llm_matrix_tool` on first run. This directory and its contents are machine-specific operational data, not shared across DIL instances.

Status: pre-alpha.
