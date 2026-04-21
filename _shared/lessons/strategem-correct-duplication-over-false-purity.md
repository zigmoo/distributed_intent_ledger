---
title: "Strategem: correct duplication over false purity"
date: YYYY-MM-DD
machine: <machine>
assistant: <assistant>
category: lessons
memoryType: reference
priority: normal
tags: [reference, strategy, normalization, knowledge-ingestion, information-architecture]
updated: YYYY-MM-DD
source: internal
domain: operations
project: dil
status: active
owner: <assistant>
due:
---

# Strategem: correct duplication over false purity

# Strategem

- Proper information design is not about eliminating duplication entirely.
- The goal is the correct amount of duplication, with clear authority boundaries.
- Intentional duplication can preserve provenance, auditability, portability, queryability, and policy enforcement.
- This mirrors the reporting/database principle that good normalization serves usability rather than ideological deduplication.

# Example

- Raw artifact plus metadata registry is healthy duplication when the registry is the discovery layer and the raw artifact remains the content source of truth.
- Per-item history plus unified changelog is healthy duplication when one is item-local truth and the other is an operational timeline.
- Curated shared knowledge may duplicate distilled insights from domain-gated raw content when the curated layer is explicitly a promoted derivative, not a hidden second source of truth.

# Phrase

> Correct duplication beats false purity.
