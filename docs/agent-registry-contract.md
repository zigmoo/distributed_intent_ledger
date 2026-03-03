# Agent Registry Contract (v1)

## Purpose

Define a canonical agent registry so DIL can reliably coordinate:
- agent identity across machines and runtimes
- model/provider routing (including local model inventories such as Ollama)
- capability and format support for the real file/media types users handle
- operational constraints (for example, agents that do not support fallback LLMs)

## Canonical Location

- Suggested path in a DIL vault: `_shared/_meta/agent_registry.json`
- Schema: `schema/agent_registry.schema.json`

## Required Bootstrap Behavior

1. Resolve runtime identity:
   - `machine = hostname -s | tr '[:upper:]' '[:lower:]'`
   - `assistant` from env/process-derived slug
2. Load machine + agent registries.
3. If current agent is missing:
   - create an agent record with discoverable attributes
   - attach machine binding and runtime host information
   - set `status=active` unless explicitly known otherwise
4. If current agent exists:
   - refresh discoverable runtime fields (non-destructive)
   - do not clobber curated governance fields without explicit authorization
5. Persist and return proof:
   - updated path
   - updated agent excerpt
   - timestamp

## Core Requirements

- Every agent record MUST include:
  - identity (`agent_id`, `display_name`)
  - ownership/accountability (`owner`, `maintainers`)
  - machine/runtime binding (`machine`, `runtime_host`)
  - model configuration (`primary_model`, provider/runtime metadata)
  - runtime profiles (`runtime_profiles`) for local/cloud runtimes and inventories
  - fallback capability (`supports_fallback_llms`)
  - format/capability declarations (`supported_formats`, `capabilities`)

- Agents that do not support fallback LLMs MUST explicitly declare:
  - `supports_fallback_llms: false`
  - `fallback_models: []`

- Local model inventories SHOULD be captured when discoverable:
  - e.g., Ollama model list + key metadata (name, size, quantization, context)
  - inventories SHOULD be attached to the runtime profile that discovered them

## Supported Format Categories (minimum)

- `text/plain`
- `text/markdown`
- `application/json`
- `application/yaml`
- `text/csv`
- `application/pdf`
- `image/*`
- `audio/*`
- `video/*`

## Runtime Profile Guidance

Each `runtime_profile` SHOULD represent one runtime endpoint and include:
- runtime identity (`runtime_id`, `runtime_type`)
- connection mode (`local`, `remote`, `hybrid`)
- endpoint hints (`endpoint`, `agent_runtime_host_ref`)
- model inventory (`model_inventory`)

Example runtime types:
- `ollama`
- `openai-compatible`
- `anthropic`
- `custom-gateway`

## Fallback LLM Semantics

- `supports_fallback_llms=true`: agent may route to backup models when policy allows.
- `supports_fallback_llms=false`: fallback is prohibited for that agent/runtime.
- For agents like `zeroclaw` (current behavior), set:
  - `supports_fallback_llms: false`
  - `model_config.supports_fallback_llms: false`
  - `model_config.fallback_models: []`
  - `model_config.fallback_strategy: "none"`

## Notes

- Registry is contract-first and append/update auditable.
- Inventory fields are intentionally extensible to support mixed environments (cloud APIs, local runtimes, hybrid deployments).
