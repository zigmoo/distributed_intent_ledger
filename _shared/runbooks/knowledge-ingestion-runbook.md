---
title: "Knowledge Ingestion Runbook"
date: 2026-04-03
machine: shared
assistant: shared
category: runbook
memoryType: reference
priority: high
tags: [runbook, ingestion, knowledge, create-memory, authored-docs, low-inference]
updated: 2026-04-03
source: internal
domain: operations
project: dil-ingestion-pipe
status: active
owner: shared
due:
---

# Knowledge Ingestion Runbook

Use this runbook to decide whether content belongs in the ingestion pipeline or should be written directly as a DIL memory note.

## Decision Rule

1. Use `_shared/scripts/ingest_source.sh` for externally sourced assets.
   - URLs
   - downloaded files
   - copied documents
   - PDFs, images, presentations, code files, data files
   - repos or folders imported from elsewhere
2. Use `_shared/scripts/create_memory.sh` for authored notes created directly inside DIL.
   - preferences
   - lessons
   - observations
   - decisions
   - commitments
3. Use the authored-document path for in-place specs/RFCs/design docs once that path is implemented.

## Why This Split Exists

- `ingest_source.sh` preserves originals, writes manifests, updates the knowledge registry, applies adapters, and records provenance.
- `create_memory.sh` is for native DIL notes where the content itself is the source of truth.
- Do not use `create_memory.sh` as a substitute for importing an external asset.

## Canonical Examples

Use `ingest_source.sh`:
- "Store this article/PDF/image in the knowledge pipeline."
- "Import this URL."
- "Ingest this repo/folder."
- "Put this downloaded file into DIL."

Use `create_memory.sh`:
- "Remember that I like this wallpaper."
- "Store this design principle as a lesson."
- "Make a preference note about favorite desktops."
- "Write down this observation."

Use authored-doc path later:
- "Start a spec."
- "Draft an RFC."
- "Create a white paper."

## Operational Notes

- Global discovery for ingested items comes from `_shared/_meta/knowledge_registry_active.md`.
- Raw ingested assets live under `_shared/domains/{domain}/knowledge/raw/`.
- Draft extraction notes are agent-scoped.
- Curated shared knowledge is promoted later to `_shared/knowledge/compiled/`.

## If User Intent Is Ambiguous

Prefer asking or making the narrowest safe assumption:
- If the user is handing you external material, ingest it.
- If the user is asking you to author a note from scratch, create a memory note.
- If a request sounds like "write this down" rather than "import this asset", `create_memory.sh` is usually correct.
