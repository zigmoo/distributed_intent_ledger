# DIL Universal Inbox Ingestion Pipeline — Consolidated Spec

**Status:** Draft
**Primary task:** DIL-1427
**Follow-on tasks:** DIL-1428 (authored-document path), DIL-1429 (failure-state triage workflow)
**Project:** dil-ingestion-pipe
**Date:** 2026-04-03

---

## 1. Purpose

Define a universal DIL-local inbox ingestion specification that accepts any incoming asset type (URL, repo, documents, media, data, code, unknown), preserves original files in raw storage, applies adapter-based extraction when available, records deterministic manifests, enforces sensitivity-aware promotion gates, and emits auditable proof paths.

## 2. Scope

- Build ingestion for `dil-active` first, then generalize to DIL template.
- Support any file dropped into inbox: image, video, presentation, PDF, Word doc, text, data, code, legal/health docs, and unknown formats.

---

## 3. Design Constraints

### 3.0.1 Manifest Format: YAML Frontmatter in `.md`

- Consistent with all other DIL artifacts (tasks, memory notes, indexes).
- First-class Obsidian citizens: wiki-links, backlink discovery, graph view, full-text search.
- Cross-domain connections work via wiki-links, making every manifest a node in the knowledge graph.
- Transition history is logged to separate changelog files (existing DIL pattern), not embedded in YAML arrays.

### 3.0.2 Implementation Language: Vanilla Python (stdlib only) + Bash Wrapper

**Rationale:** The DIL template is designed for third-party users who clone it from GitHub. Zero external dependencies means it works immediately on any machine with Python 3.8+.

**stdlib coverage:**

| Need | Module |
|---|---|
| MIME detection | `mimetypes` + `subprocess.run(['file', '--mime-type', ...])` |
| SHA256 hashing | `hashlib` |
| File size / paths | `os.path`, `pathlib` |
| URL fetch | `urllib.request` |
| URL vs path detection | `urllib.parse` |
| Stdin buffering | `tempfile` |
| JSON I/O | `json` |
| CLI argument parsing | `argparse` |
| Timestamps | `datetime` |

**YAML frontmatter writing:** Thin helper function (~15 lines) for flat/shallow dict serialization. Full `pyyaml` not needed.

**Optional dependencies:** Adapters that need deep extraction (PDF text, docx parsing) may declare requirements, but the core pipeline never requires anything beyond stdlib. Missing tooling triggers `extraction_status: pending_tooling`.

**Why this matters:**
- Zero `pip install` — clone and run.
- Portable: macOS, Linux, WSL, Raspberry Pi, servers.
- No C library dependencies (`libmagic`, etc.).
- Agent-friendly: any coding agent can read, modify, and extend without understanding dependency management.
- Long-term stable: stdlib doesn't break between minor versions.

### 3.0.3 CLI Interface

**Entry point:** `_shared/scripts/ingest_source.sh` (bash wrapper) -> `_shared/scripts/lib/ingest_source.py` (Python core)

**Usage:**

```bash
# File path (auto-detect type)
ingest_source.sh /path/to/document.pdf

# URL (auto-detect, fetch, then detect)
ingest_source.sh https://example.com/paper.html

# Stdin (buffer to temp, detect)
cat something | ingest_source.sh -

# Optional overrides when auto-detection isn't enough
ingest_source.sh --source-type pdf --domain work --sensitivity internal /path/to/file
```

**Auto-detection:** The tool auto-detects source type, MIME, size, and content hash. The user/agent should not need to specify what the input is.

**Defaults:** Domain defaults to `personal` if not specified.

**Output format:** Pipe-delimited, matching `create_task.sh` conventions:
```
OK | ingest_id | domain | status | path
ERR | code | message
```

**Exit codes:** 0=success, 2=input validation, 3=duplicate, 4=missing prereq, 5=post-creation validation failure.

**Bash wrapper responsibilities:** Environment setup (no venv needed), path resolution (`$BASE_DIL`), pipe-delimited output relay, exit code forwarding.

---

## 4. Core Requirements

### 4.1 Raw-First Preservation

- Never mutate or discard source payload.
- Store originals under scoped raw paths first.

### 4.2 Deterministic Manifest Per Item

Each ingested item produces a manifest with these fields:

| Field | Description |
|---|---|
| `ingest_id` | Unique ingestion event ID |
| `source_type` | Adapter type (url, repo, pdf, etc.) |
| `source_uri_or_path` | Original location/path |
| `raw_scope_path` | Where the raw file was stored in DIL |
| `original_source` | Upstream origin when known; else `unknown` |
| `mime_type` | Detected MIME type |
| `extension` | File extension |
| `size_bytes` | Payload size |
| `sha256` | Content hash |
| `ingested_at` | Timestamp |
| `actor` | Agent/user that triggered ingestion |
| `status` | Current pipeline state |
| `extraction_status` | Adapter extraction outcome |
| `sensitivity` | Sensitivity classification |
| `content_tier` | `raw` (unprocessed) / `draft` (extracted) / `curated` (promoted). Distinct from pipeline `status` — prevents tier collapse. |
| `access_policy` | Derived from domain + sensitivity. Controls content access (not metadata — metadata is always globally discoverable). |
| `duplicate_of` | `<canonical_ingest_id>` or empty. Links duplicate submissions to the canonical item for audit. |

### 4.3 Adapter-Based Extraction

Type adapters for:

| Adapter | Covers |
|---|---|
| `url` | Web pages, bookmarks |
| `repo` | Git repositories |
| `pdf` | PDF documents |
| `doc/docx` | Word documents |
| `ppt/pptx` | Presentations |
| `txt/md` | Plain text, Markdown |
| `code` | Source code files |
| `csv/json` | Structured data |
| `image` | Images (PNG, JPG, SVG, etc.) |
| `audio/video` | Media files |
| `unknown` | Fallback for unrecognized types |

- Adapters output normalized extraction notes and dual provenance references (scoped raw path + original source attribute when known).

#### Adapter Contract (Fixed Function Signature)

Every adapter is a Python module in `_shared/scripts/lib/adapters/` with a single `extract()` function:

```python
def extract(raw_path: str, manifest: dict, output_dir: str) -> dict:
    """
    Args:
        raw_path:   absolute path to the raw file (read-only, never modify)
        manifest:   the full frontmatter dict (MIME, hash, domain, sensitivity, etc.)
        output_dir: directory where extraction notes should be written

    Returns:
        {
            "status": "extracted" | "pending_tooling" | "failed",
            "notes": ["path/to/note1.md", "path/to/note2.md"],
            "error": None | "human-readable reason"
        }
    """
```

**Design rationale:**
- `raw_path` — adapter reads from here, never modifies (raw-first preservation).
- `manifest` — gives the adapter everything without re-detecting.
- `output_dir` — pipeline controls path policy, not the adapter.
- Return dict, not exceptions — `pending_tooling` is a valid state, not an error.
- `notes` list — some adapters produce one note (txt/md), some produce many (repo).

#### Adapter Discovery

MIME-to-adapter registry dict in the Python core:

```python
ADAPTERS = {
    "text/plain":       "adapters.txt_md",
    "text/markdown":    "adapters.txt_md",
    "application/pdf":  "adapters.pdf",
    # ...
    "_default":         "adapters.unknown",
}
```

**Adding a new adapter:** Drop a `.py` file in `_shared/scripts/lib/adapters/` with an `extract()` function, add a MIME mapping. No framework, no base class, no registration ceremony.

**The `unknown` adapter:** Writes a pointer note with metadata only — no extraction, returns `status: pending_tooling`.

### 4.4 Fallback Behavior

- If adapter/tooling unavailable, retain source, write pointer/metadata note, set `extraction_status: pending_tooling`.

### 4.5 De-Duplication

- **Pre-ingest de-dupe:** Compute `sha256`; if payload already exists in raw scope, do not copy the file again. However, every submission is recorded as an **ingest event** in the registry with `status: duplicate` and `duplicate_of: <canonical_ingest_id>`. This preserves the audit trail — "who tried to ingest what, when" — even when the content is not new.
- **Post-extraction semantic de-dupe:** Detect near-duplicate notes by normalized title/source/key-claim fingerprint; record as ingest event with `duplicate_of` reference and block duplicate promotion.

### 4.6 Sensitivity Classification

Auto-classified by domain default using `default_sensitivity` field in `domain_registry.json`.

**Levels:**

| Level | Meaning |
|---|---|
| `public` | Safe to share outside DIL |
| `private` | Visible within DIL, not for external sharing |
| `internal` | Domain-restricted; metadata visible in global index, content access gated |
| `restricted` | Sensitive (legal, health, employer-IP); metadata visible, content requires explicit access |

**Domain defaults** (added to `domain_registry.json`):

```json
{
    "personal": { "default_sensitivity": "private" },
    "work":     { "default_sensitivity": "internal" },
    "triv":     { "default_sensitivity": "private" }
}
```

**CLI override:** `--sensitivity <level>` when domain default isn't appropriate.

Sensitivity is recorded in the manifest and the global registry index at intake.

### 4.7 Validation and Promotion Gates

- Validate path existence, hash/provenance consistency, schema compliance, and citation linkage.
- Enforce dual provenance fields on derived notes: `raw_scope_path` and `original_source` (if known; else explicit `unknown` marker).
- Apply sensitivity policy (especially legal/health) before promotion to `_shared`.

### 4.8 Cross-Domain Knowledge Visibility Model

The DIL's core principle is shared knowledge across all agents and machines. The ingestion pipeline must not create private knowledge silos. At the same time, certain domains (e.g., work) have legitimate isolation needs — portability, IP boundaries, compliance.

The governing model is: **global metadata index, domain-scoped storage, policy-driven access, reference-based connections across boundaries.**

The architecture rests on three distinct tiers that must never be collapsed:

1. **Globally discoverable metadata** — the registry record. Answers "an item exists" with ID, type, domain, sensitivity, content_tier, and location. For discovery and routing only. Discoverable by all agents, subject to registry visibility policy.
2. **Domain-gated raw content** — the actual imported asset or extraction in domain scope. May be private, regulated, or unreviewed. Discovery is global; access is domain-restricted.
3. **Curated shared knowledge** — reviewed/promoted output in `_shared/knowledge/*`. The reusable, cross-domain layer for broader consumption. `content_tier: curated`.

`content_tier` and `status` are orthogonal axes and must remain separate:
- `content_tier` = what the item is: `raw` | `draft` | `curated`
- `status` = where it is in the pipeline: `received` | `dedup_checked` | `ingested_raw` | `extracted` | `validated` | `promoted_shared` | `archived`
- An item can be `content_tier: draft` with `status: failed_validation`. Both fields are updated independently.

#### 4.8.1 Global Discovery Index

- Every ingestion event writes a row to `_shared/_meta/knowledge_registry_active.md` **immediately upon intake** — not deferred until promotion.
- Registry column schema:

| Column | Source | Purpose |
|---|---|---|
| `ingest_id` | allocated at intake | primary key |
| `domain` | CLI or auto | discovery scoping |
| `source_type` | auto-detected | adapter routing |
| `title` | filename or extracted | human discovery |
| `raw_scope_path` | pipeline | locating the artifact |
| `sensitivity` | domain default or CLI | access decisions |
| `visibility` | derived from sensitivity | quick filter |
| `status` | state machine | pipeline position |
| `sha256` | computed | dedup, integrity |
| `mime_type` | auto-detected | adapter selection, filtering |
| `size_bytes` | computed | capacity planning, filtering |
| `ingested_at` | timestamp | chronology |
| `original_source` | intake | provenance — where the item came from (may be truncated for display) |
| `access_policy` | derived | who can access the content behind this row |
| `content_tier` | state machine | `raw` / `draft` / `curated` — orthogonal to status |
| `duplicate_of` | dedup gate | `<canonical_ingest_id>` or empty — audit trail for duplicates |
| `actor` | env detection | attribution |

- `content_tier`: orthogonal to `status`. Tier = what the item is; status = where it is in the pipeline. This separation prevents the registry from being misread as a content catalog.
- `duplicate_of`: ensures duplicate submissions are visible as auditable events, not silently dropped.
- `original_source`: included in the registry because agents need provenance for discovery without opening every manifest. May be truncated for display in wide tables.
- The registry is a **metadata-only** discovery index. It answers: "an item exists, here is its ID, type, domain, sensitivity, tier, provenance, and where it lives." Content access is enforced by domain policy, not by registry membership.
- Agents can discover what exists across domains by reading this index, subject to registry visibility policy. Rows with `visibility: restricted` may limit metadata exposure to authorized agents/domains.
- Raw files remain in domain-scoped storage; the index provides awareness, not content duplication.

#### 4.8.2 Domain-Gated Access

- The index entry includes `domain` and `visibility` fields.
- Agents respect domain access policy: they can see existence and metadata of items in any domain, but raw content stays in the domain's scoped paths.
- Sensitivity classifications (legal, health, employer-IP) further restrict access within domains.

#### 4.8.3 Clippable Domain Boundaries

- Domain directory structure is self-contained: raw files, manifests, and domain-local indexes are co-located.
- `cp -r _shared/domains/{domain}/knowledge/` produces a portable, self-contained bundle.
- This supports handoff, backup, and compliance workflows without cross-domain file entanglement.

#### 4.8.4 Cross-Domain Connections

- The `_shared/knowledge/connections/` layer supports reference-based links between items in different domains.
- Connections link by ID/reference, not by embedding content across domain boundaries.
- Example: a personal spec can reference a work ticket by ID without work content leaking into the personal domain's file tree.

#### 4.8.5 Reframed Promotion (Tier Transition)

- Promotion to `_shared/knowledge/compiled/` is a **tier transition**: `content_tier` moves from `draft` to `curated`. It is about curation (validated, extracted, ready for downstream use), not about access.
- The raw item was always discoverable via the global metadata index from the moment of intake.
- On promotion, the registry row is updated with two independent field changes:
  - `content_tier`: `draft` -> `curated` (tier transition)
  - `status`: `validated` -> `promoted_shared` (lifecycle transition)
  - These are orthogonal — tier describes what the item is, status describes where it is in the pipeline.

### 4.9 Promotion Behavior

- Promote only cleaned/validated artifacts.
- Keep source linkage to raw scope for auditability.

### 4.10 Archive Lifecycle and Query Behavior

- Maintain active and archived registries:
  - `_shared/_meta/knowledge_registry_active.md`
  - `_shared/_meta/knowledge_registry_archived/{year}.md`
- Archive fields on archived entries:
  - `lifecycle_state`, `archived_at`, `archive_reason`, `archive_registry_path`
- Archive trigger step:
  - Periodic archive job evaluates age/size/policy thresholds and moves index rows from active registry to yearly archived registry (without breaking source/provenance links).
- Archive query step:
  - Default queries/search run against active registry only.
  - Optional `--include-archived` expands results across archived registries.

---

## 5. Pipeline Triggers and States

### 5.1 Trigger Model

| Trigger | Fires When |
|---|---|
| Intake | Manual `ingest_source` command or drop-folder watcher |
| Extraction | Processor picks manifests with `status=ingested_raw` |
| Validation | Validator runs on `status=extracted` |
| Promotion | Promoter runs on `status=validated` with sensitivity pass |
| Archive | Archiver runs on promoted/registered entries by retention thresholds |
| Retry | Explicit reprocess of `pending_tooling`, `failed_validation`, or `failed` |

### 5.2 State Machine

```text
received -> dedup_checked -> ingested_raw -> extracted -> validated -> promoted_shared -> archived

Failure/holding states:
  duplicate
  pending_tooling
  failed_validation
  failed
```

Every transition writes to two locations:

- **Per-item:** Append to `## State History` section in the item's manifest `.md` — portable, travels with the item if domain is clipped.
- **Unified:** Append row to `_shared/knowledge/_meta/change_log.md` — global timeline view across all items, matches existing DIL task changelog pattern.
- **Fields per entry:** timestamp, actor, command, previous state, new state, manifest path.
- Per-item log is source of truth for that item; unified log is the operational view.

### 5.3 Failure-State Workflow (DIL-1429 — To Be Defined)

The following areas need formal workflow definitions:

- **Review ownership** — who reviews failures (agent-driven, human-triaged, or both)?
- **Retry initiation** — automatic on schedule, manual command, or tooling-availability detection?
- **Retry limits** — max retries before escalation to a terminal state.
- **Triage/resolution actions** — edit manifest and re-submit, delete, force-promote with override flag?
- **Notification** — how failures are surfaced to the user.
- **`pending_tooling` resolution** — detecting when required tooling becomes available and auto-kicking extraction.

---

## 6. Target Paths (DIL Active)

Path tiers mirror content tiers:

### 6.1 Domain-Scoped Raw Intake (content_tier: raw)

```
_shared/domains/{domain}/knowledge/raw/
  urls/
  repos/
  files/
```

Raw files are stored by domain, not by machine/assistant, because the domain is the access and portability boundary. Clipping works at domain level: `cp -r _shared/domains/{domain}/knowledge/` produces a portable bundle.

### 6.2 Agent-Scoped Working Artifacts (content_tier: draft)

```
<machine>/<assistant>/knowledge/drafts/
<machine>/<assistant>/knowledge/notes/
```

Extraction workspace is machine/assistant-scoped to prevent collision between agents.

### 6.3 Curated Shared Knowledge (content_tier: curated)

```
_shared/knowledge/compiled/
_shared/knowledge/sources/
_shared/knowledge/connections/
```

### 6.4 Global Metadata Index

```
_shared/_meta/knowledge_registry_active.md
_shared/_meta/knowledge_registry_archived/{year}.md
```

### 6.5 Unified Changelog

```
_shared/knowledge/_meta/change_log.md
```

---

## 7. Authored-Document Path (DIL-1428 — To Be Defined)

The ingestion pipeline handles externally-sourced assets. Documents *authored in-place* (specs, white papers, RFCs, design docs) have a different lifecycle:

### 7.1 Authoring Path

- Documents born inside the system under `<machine>/<assistant>/knowledge/drafts/`.
- Promoted to `_shared/knowledge/compiled/` when finalized.

### 7.2 Document Type Taxonomy

Distinguish authored docs from ingested assets:

| Type | Description |
|---|---|
| `spec` | Technical specification |
| `white-paper` | Position/research paper |
| `rfc` | Request for comments / proposal |
| `design-doc` | Architecture/design document |
| `policy` | Operational policy statement |

### 7.3 Versioning Semantics

- Revision chain tracking for documents that evolve (not point-in-time snapshots).
- Status lifecycle: `draft` -> `review` -> `final` -> `superseded`.

### 7.4 Authored-Document Adapter

- Pass-through adapter: skips extraction, goes straight to validation/promotion.
- Integrates with DIL-1427's adapter matrix.
- Manifest extension: `document_type` field.

### 7.5 Promotion Gate

- Reuses DIL-1427's validation gate with authored-doc-specific checks (required sections, status field for draft/review/final).

---

## 8. ASCII Information Flow

```text
+---------------------------------------------+
| Input Sources                               |
| URLs | local repos | docs | media | code    |
| data files | legal/health docs | unknown    |
+--------------------+------------------------+
                     |
                     v
+---------------------------------------------+
| Ingestion Entry (dil-active)                |
| ingest_source.*                             |
| - capture source                            |
| - detect MIME/size/hash                     |
| - create manifest w/ dual provenance:       |
|   raw_scope_path + original_source          |
| - assign content_tier: raw                  |
+--------------------+------------------------+
                     |
                     +-------------------------------------------+
                     |                                           |
                     v                                           v
+---------------------------------------------+   +------------------------------------------+
| Pre-Ingest De-Dupe Gate                     |   | GLOBAL METADATA INDEX WRITE (immediate)  |
| - hash de-dupe (pre-ingest)                 |   | -> knowledge_registry_active.md          |
| - if duplicate: record ingest event with    |   | metadata only — discoverable subject to  |
|   duplicate_of: <canonical_ingest_id>       |   | registry visibility policy               |
+-----------+----------------------+----------+   | content_tier: raw                        |
            |                      |              +------------------------------------------+
            | duplicate            | unique
            v                      v
+-------------------------------+ +----------------------------------------+
| duplicate ingest event        | | TIER 2: DOMAIN-GATED RAW CONTENT      |
| recorded in registry          | | _shared/domains/{domain}/knowledge/raw/|
| duplicate_of: <canonical_id>  | | urls/ repos/ files/                    |
| (audit trail preserved)       | | (immutable-first)                      |
+-------------------------------+ | content_tier: raw                      |
                                  +------------+---------------------------+
                                               |
                                               v
+---------------------------------------------+
| Adapter Router                              |
| url | repo | pdf | docx | pptx | txt | code|
| csv/json | image | audio/video | unknown    |
| authored (pass-through)                     |
+--------------------+------------------------+
                     |
                     v
+---------------------------------------------+
| Extraction Output (agent-scoped)            |
| <machine>/<assistant>/knowledge/drafts/     |
| - summaries/excerpts/concepts               |
| - path + hash + dual provenance refs        |
| content_tier: draft                         |
+--------------------+------------------------+
                     |
                     v
+---------------------------------------------+
| Post-Extraction Semantic De-Dupe Gate       |
| - normalized title/source/claim fingerprint |
| - duplicate marker: duplicate_of            |
+-----------+----------------------+----------+
            |                      |
            | duplicate            | unique
            v                      v
+-------------------------------+ +-------------------------+
| duplicate ingest event        | | Validation Gate         |
| recorded in registry          | | schema/path/hash/cite   |
| duplicate_of: <canonical_id>  | | provenance/sensitivity  |
| (audit trail preserved)       | | domain access policy    |
+-------------------------------+ +-----------+-------------+
                                              |
                                 +------------+------------+
                                 |                         |
                                 | FAIL/PENDING            | PASS
                                 v                         v
                +-------------------------+   +----------------------------------+
                | Failure States          |   | TIER 3: CURATED SHARED KNOWLEDGE |
                | pending_tooling         |   | PROMOTION (tier transition)      |
                | failed_validation       |   | -> _shared/knowledge/compiled/   |
                | failed                  |   | content_tier updated: curated    |
                +------------+------------+   | status updated: promoted_shared  |
                             |                | (tier and status are independent)|
                             |                +------------+---------------------+
                             |                             |
                             |                             v
                             |                +--------------------------+
                             |                | Cross-Domain Connections |
                             |                | _shared/knowledge/       |
                             |                |   connections/           |
                             |                | - reference-based links  |
                             |                | - links by ID, not by    |
                             |                |   embedding content      |
                             |                | - spans domain boundaries|
                             |                +------------+-------------+
                             |                             |
                             v                             v
                +--------------------------+  +--------------------------+
                | Failure Triage Workflow   |  | periodic archive job     |
                | - review ownership       |  | + archived query support |
                | - retry mechanics        |  +------------+-------------+
                | - retry limits/escalate  |               |
                | - notification           |               +-----> knowledge_registry_archived/{year}.md
                | - tooling detection      |               |
                +-----------+--------------+               +-----> knowledge_registry_active.md (updated)
                            |
                            | retry
                            +-----------> (re-enter at appropriate pipeline stage)

THREE-TIER ARCHITECTURE (tier and lifecycle/status are independent axes):

  content_tier:  raw          |  draft         |  curated
  status:        received ... ingested_raw ... extracted ... validated ... promoted_shared ... archived

+-----------------------------------------------------------------------+
| TIER 1: GLOBAL METADATA INDEX                                         |
| knowledge_registry_active.md                                          |
| - Written at intake, discoverable subject to visibility policy        |
| - METADATA ONLY — discovery and routing, not content access           |
| - Columns: id, domain, type, title, path, original_source,           |
|   sensitivity, visibility, access_policy, status, content_tier,       |
|   duplicate_of, sha256, mime_type, size_bytes, ingested_at, actor     |
+-----------------------------------------------------------------------+
          |                        |                        |
          v                        v                        v
+-----------------------------+ +-----------------------------+ +-----------------------------+
| TIER 2: DOMAIN-GATED       | | TIER 2: DOMAIN-GATED       | | TIER 2: DOMAIN-GATED       |
| RAW CONTENT                 | | RAW CONTENT                 | | RAW CONTENT                 |
| _shared/domains/personal/   | | _shared/domains/work/       | | _shared/domains/triv/       |
|   knowledge/raw/            | |   knowledge/raw/            | |   knowledge/raw/            |
| default_sensitivity: private| | default_sensitivity:internal| | default_sensitivity: private|
+-----------------------------+ +-----------------------------+ +-----------------------------+
  Clippable: cp -r _shared/domains/{domain}/knowledge/ -> portable bundle
                              |
                              | promotion (validation + sensitivity gate)
                              | content_tier: draft -> curated
                              | status: validated -> promoted_shared
                              v
+-----------------------------------------------------------------------+
| TIER 3: CURATED SHARED KNOWLEDGE                                      |
| _shared/knowledge/compiled/    (validated, cross-domain reusable)     |
| _shared/knowledge/sources/     (source references)                    |
| _shared/knowledge/connections/ (cross-domain relational links)        |
| content_tier: curated                                                 |
+-----------------------------------------------------------------------+

(*) original_source may be literal `unknown` when not available.
```

---

## 9. Related Tasks

| Task | Title | Status |
|---|---|---|
| DIL-1427 | Define universal inbox ingestion spec with adapter matrix and sensitivity gates | in_progress |
| DIL-1428 | Define authored-document path: in-place drafting, versioning, and promotion for specs and white papers | todo |
| DIL-1429 | Define failure-state triage and retry workflow for ingestion pipeline | todo |
