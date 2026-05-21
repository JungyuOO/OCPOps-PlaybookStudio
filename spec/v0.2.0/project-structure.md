# v0.2.0 Project Structure Plan

## Direction

Do not reorganize the whole repository at once. v0.2.x should introduce new features into clearer domain boundaries, then move old code gradually when touched.

Historical `spec/` documents remain as records. The structural redesign targets runtime source, active feature modules, database access layers, generated artifacts, and feature folders that no longer match the new OpenShift operations assistant direction.

## Target Domain Layout

Potential future Python package layout:

```text
src/play_book_studio/
  rag/
    corpus/
    enrichment/
    retrieval/
    evaluation/
  ocp/
    runtime/
    collector/
    watcher/
  operations/
    diagnosis/
    notifications/
  db/
    repositories/
```

## Current Structure Snapshot

Current top-level package directories under `src/play_book_studio`:

```text
answering
canonical
cluster
config
course
db
evals
http
ingestion
intake
retrieval
```

Current observations:

- RAG behavior is split across `answering`, `retrieval`, `ingestion`, `db`, `http`, and `evals`.
- OCP/terminal behavior is split across `cluster`, `http/terminal_*`, `db/terminal_learning_repository.py`, and deploy scripts.
- Course/KMSC runtime has its own `course` and `course/pipeline` area.
- There is no dedicated `rag`, `ocp`, or `operations` package yet.

This means v0.2.x should avoid mass-moving existing code. New code can introduce clearer domain homes while old paths remain stable.

Tracked source counts by current package:

| Package | Tracked files | v0.2.x direction |
| --- | ---: | --- |
| `retrieval` | 65 | Keep stable; new enriched retrieval abstractions should be introduced behind a backend-neutral boundary before moving old modules. |
| `http` | 66 | Keep routes stable; add new route handlers only when the domain API contract is clear. |
| `ingestion` | 50 | Keep existing import/rebuild paths; new corpus audit/enrichment code should move toward `rag/corpus` and `rag/enrichment`. |
| `course` | 32 | Keep KMSC/course runtime isolated; do not mix new official corpus rebuild work into course modules. |
| `intake` | 23 | Keep upload normalization separate from official corpus rebuild. |
| `evals` | 15 | Keep current eval entrypoints; new v0.2.x benchmark artifacts should be versioned under `spec/<version>/evidence` when promoted. |
| `answering` | 14 | Keep answer generation stable; operation diagnosis should use a new domain boundary before changing answer routing. |
| `db` | 11 | Keep repositories stable; new DB code should be grouped by domain repository. |
| `canonical` | 10 | Keep canonical parsers/utilities shared. |
| `config` | 7 | Keep configuration central; avoid feature-specific env sprawl. |
| `cluster` | 4 | Candidate source for future `ocp/runtime` or `ocp/collector`, but do not move in v0.2.0. |

## Target Placement Matrix

| Future work | Target package | Existing code to reference, not move in v0.2.0 |
| --- | --- | --- |
| Official corpus audit | `rag/corpus` | `ingestion/official_*`, `ingestion/corpus_*`, `config/corpus_*` |
| LLM enrichment prototype | `rag/enrichment` | `ingestion/official_gold_enrichment.py`, `retrieval/query_signal_pipeline.py` |
| Backend-neutral retrieval | `rag/retrieval` | `retrieval/*`, `db/qdrant_indexer.py`, `ingestion/qdrant_store.py` |
| RAG evaluation harness | `rag/evaluation` | `evals/*`, `corpus/manifests/eval/*` |
| OCP namespace/resource snapshots | `ocp/runtime` or `ocp/collector` | `cluster/*`, `http/ops_console_api.py` |
| Terminal/event transcript capture | `ocp/runtime` | `http/terminal_session.py`, `http/terminal_ws.py`, `db/terminal_learning_repository.py` |
| Operation watcher | `ocp/watcher` and `operations/diagnosis` | terminal runtime and future runtime context tables |
| Notifications | `operations/notifications` | none yet; design starts in v0.2.9 |

## Move Rules

- Do not move an existing module only to match the target layout.
- Move a module only when the target version changes behavior in that domain and has focused tests.
- New packages may be introduced with new code, but compatibility imports should be kept until all callers are migrated.
- `http` route files should call domain services; they should not become the permanent home for RAG, OCP collector, or watcher logic.
- `db` should expose repositories by domain rather than one-off SQL in feature routes.

## Rules

- New corpus audit/enrichment code should live under `rag/`.
- OCP state collection code should live under `ocp/`.
- Operation watcher and notifications should live under `ocp/watcher/` or `operations/notifications/`.
- Existing imports should not be mass-renamed in v0.2.0.
- Moving existing code requires tests or smoke validation.

## Non-goals

- No large source tree migration in v0.2.0.
- No API route rename.
- No frontend route rename.
- No migration runner rewrite.

## Acceptance Criteria

- New v0.2.x code has a clear target home.
- Old code remains stable until a focused cleanup version.
- Refactor risk is separated from RAG/data model work.
