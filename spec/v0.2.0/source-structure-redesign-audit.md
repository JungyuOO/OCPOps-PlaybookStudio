# v0.2.0 Source Structure Redesign Audit

## Purpose

This document captures the first evidence pass for cleaning and redesigning the active project structure before the Lightspeed-style OpenShift operations assistant work begins.

Historical `spec/` documents are excluded from cleanup. The target is active source structure, stale feature code, generated artifacts, DB schema/code mismatch, and functionality that no longer fits the future RAG/runtime direction.

## Current Source Shape

Tracked source baseline:

| Area | Count / Finding |
| --- | --- |
| Total tracked files | 1,501 |
| `corpus` | 940 tracked files |
| `src` | 305 tracked files |
| `tests` | 95 tracked files |
| `apps/web` | 73 tracked source files |
| `db/migrations` | 10 flat SQL migrations |

Local generated/untracked-heavy areas:

| Area | Finding | Classification |
| --- | --- | --- |
| `artifacts` | 8,174 files, about 2.28 GB | local-generated-cleanup-candidate |
| `reports` | 122 files, about 161 MB | mixed tracked/generated, needs split |
| `apps/web/dist` | 7 files, about 1.42 MB | generated-cleanup-candidate |
| `apps/web/node_modules` | present locally, ignored | dependency cache, do not track |

## Current Python Package Layout

Current package directories under `src/play_book_studio`:

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

Tracked file counts by package:

| Package | Tracked files |
| --- | ---: |
| `answering` | 14 |
| `canonical` | 10 |
| `cluster` | 4 |
| `config` | 7 |
| `course` | 32 |
| `db` | 11 |
| `evals` | 15 |
| `http` | 66 |
| `ingestion` | 50 |
| `intake` | 23 |
| `retrieval` | 65 |

Observed structural issue:

- RAG logic is spread across `answering`, `retrieval`, `ingestion`, `db`, `http`, and `evals`.
- OCP/terminal logic is spread across `cluster`, `http/terminal_*`, `db/terminal_learning_repository.py`, and deploy scripts.
- Course/KMSC logic is isolated under `course`, but it also overlaps with RAG/eval/import paths.
- There is no dedicated `rag`, `ocp`, or `operations` domain package yet.

Second-pass structure finding:

- The largest active packages by tracked file count are `http`, `retrieval`, and `ingestion`.
- This matches the RAG quality problem: retrieval policy, ingestion metadata, answer routing, and API behavior are split across separate packages without a single domain boundary.
- v0.2.0 should not move these modules. The safer path is to define target homes and require new v0.2.x work to use those homes.
- Existing route modules should be treated as delivery adapters, not as the long-term home for operation diagnosis, collector, or watcher logic.

## CLI Entrypoint Findings

Registered CLI commands: 29.

Deploy/compose/OpenShift directly call:

| Command | Deploy refs | README refs | Classification |
| --- | ---: | ---: | --- |
| `db-migrate` | 21 | 0 | keep-production |
| `ui` | 39 | 6 | keep-production |
| `kmsc-course-import` | 6 | 0 | keep-seed |
| `official-gold-import` | 3 | 0 | keep-seed, redesign later |
| `course-chunk-import` | 3 | 0 | keep-seed, review overlap |
| `course-qdrant-upsert` | 3 | 0 | keep-seed, review overlap |
| `learning-seed-import` | 1 | 0 | keep-seed |
| `runtime` | 20 | 1 | keep-production/dev |
| `eval` | 9 | 0 | keep-dev/eval |

Registered commands with no deploy/README refs from the initial scan:

```text
corpus-ingest
corpus-quality-audit
course-ops-anchor-audit
course-ops-guides
course-runtime-status
course-ui-smoke
course-visual-audit
db-corpus-status
db-qdrant-backfill
db-qdrant-index
db-qdrant-refresh-payloads
graph-compact
maintenance-smoke
official-embedding-qdrant-upsert
private-lane-smoke
ragas
retrieval-eval
upload-ingest
```

These are not deletion targets yet. They are audit candidates because they may be local maintenance/eval commands.

## DB Table Usage Findings

Migration runner:

- `src/play_book_studio/db/migrations.py` reads only `db/migrations/*.sql`.
- Nested migration folders are not applied.
- New migration SQL should continue from `0010_*.sql` if approved.

Initial table reference scan found these migration-created tables with zero direct `src/play_book_studio` references:

| Table | Classification |
| --- | --- |
| `answer_logs` | cleanup-candidate, verify audit/logging intent |
| `embedding_jobs` | cleanup-candidate, verify async embedding roadmap |
| `lab_attempts` | cleanup-candidate, verify learning runtime need |
| `learner_progress` | cleanup-candidate, verify learner tracking roadmap |
| `learning_step_documents` | cleanup-candidate, verify doc-to-step linkage |
| `question_logs` | cleanup-candidate, verify answer audit replacement |

No DB object should be dropped in v0.2.0. These need repository query review, production data review, and migration plan before deprecation or removal.

## Python Module Reference Findings

An AST import scan was attempted to find low-reference modules. This scan is useful for narrowing candidates but is not enough for deletion because:

- relative imports need additional resolution,
- CLI commands import modules dynamically inside functions,
- HTTP route factories may reference modules indirectly,
- tests may cover modules without importing the module path directly,
- deploy commands exercise CLI paths not visible as import edges.

Therefore, low import count means "manual review candidate", not "unused".

Initial areas that deserve focused manual review:

- `retrieval/book_adjustment_*`
- `retrieval/scoring_adjustments_*`
- `retrieval/query_terms_*`
- `ingestion/curated_gold*`
- `ingestion/foundry_*`
- `intake/normalization/*`
- older eval/smoke commands not used by deploy

These areas likely contain real behavior and should not be deleted without targeted tests.

## Recommended First Cleanup Actions

Safe first actions:

1. Document generated/local artifact cleanup policy.
2. Keep `spec/` records untouched.
3. Keep `db/migrations/0000` through `0009` untouched.
4. Add cleanup scripts only after confirming ignored paths.
5. Create per-domain audit reports before deleting source files.

Do not yet delete:

- official corpus files
- retrieval/scoring modules
- ingestion official import/rebuild modules
- DB migrations
- tests
- historical specs

## Next Audit Steps

1. Build a proper import graph that resolves relative imports.
2. Map CLI command -> implementation function -> module dependencies.
3. Map HTTP routes -> handler modules.
4. Map deploy jobs -> CLI commands -> DB tables touched.
5. Produce delete/deprecate/move-later candidates with evidence.

Only after those steps should source file deletion begin.
