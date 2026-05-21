# v0.2.0 Repository Cleanup Audit Plan

## Goal

Reduce project clutter before v0.2.x adds new RAG, runtime, watcher, and feedback systems.

This is an audit-first cleanup plan. Do not delete files just because they look old. Classify usage first, then remove in small commits.

`spec/` version documents are project history and should be preserved by default. Cleanup focuses on active source code, generated artifacts, stale runtime outputs, unused functional modules, obsolete scripts, and database schema/code that no longer fits the redesigned product direction.

## Cleanup Targets

Potential cleanup areas:

- unused Python modules
- unused CLI commands
- old eval scripts
- stale reports and generated artifacts
- obsolete corpus intermediates
- unused deploy scripts
- dead frontend components
- unused DB tables/columns
- stale SQL migrations or schema assumptions
- duplicated spec documents

Out of scope by default:

- historical `spec/v*` planner documents
- version decision records
- migration history already applied in production
- tests for still-supported behavior

## Initial Repository Findings

Initial v0.2.0 scan results:

| Area | Finding | Action |
| --- | --- | --- |
| Tracked files | `git ls-files` reports 1,501 tracked files | Use this as the cleanup baseline |
| Largest tracked area | `corpus` has 940 tracked files, mostly curated assets and JSON/JSONL | Do not delete until corpus strategy is decided in v0.2.2 |
| Source code | `src` has 305 tracked files | Audit by domain before moving |
| Tests | `tests` has 95 tracked files | Keep unless target code is removed |
| Frontend source | `apps/web` has 73 tracked files | Actual local folder is larger because of ignored `node_modules` and `dist` |
| Reports | `reports` has tracked report files and many ignored local reports | Separate tracked historical reports from ignored generated reports |
| Artifacts | `artifacts/runtime` has thousands of ignored local generated JSON files | Local cleanup candidate, not source cleanup |
| DB migrations | `db/migrations` has flat `0000` through `0009` SQL files | Keep flat migration model |

Raw filesystem scan also found large ignored/generated areas:

- `artifacts/`: about 8,174 local files, mostly ignored runtime JSON artifacts
- `apps/web/node_modules` and `apps/web/dist`: present locally but ignored
- `reports/`: many generated JSON/Markdown reports are ignored by `.gitignore`
- official `embedding_chunks.jsonl` and `text-layers` are ignored generated corpus artifacts

Second-pass cleanup findings:

| Area | Verification | Classification | Action |
| --- | --- | --- | --- |
| `apps/web/dist` | ignored by `.gitignore` and `.dockerignore`; not present in `git ls-files apps/web/dist` | ignored local build output | Do not track; clean locally only when needed |
| top-level `reports/*.json`, `reports/*.md` | 18 tracked files; multiple historical `spec/v*` docs cite them as baseline evidence | mixed generated/history artifacts | Split unreferenced generated files from archived evidence |
| `corpus/data/wiki_assets` and KMSC parsed preview assets | hundreds of tracked image assets | corpus strategy dependency | Do not delete in v0.2.0; revisit during v0.2.2/v0.2.3 corpus rebuild |
| `storage/.gitignore` | only tracked file under `storage` | runtime storage placeholder | Keep |

Initial delete-now report candidates:

| Path | Verification | Classification | Action |
| --- | --- | --- | --- |
| `reports/official_corpus_v014_260516_preleave_retrieval_smoke.json` | no refs from `src`, `tests`, `deploy`, `apps`, `README.md`, `pyproject.toml`, or `spec` | unreferenced generated report | delete-now |
| `reports/v007_command_lookup_live_smoke.json` | no refs from `src`, `tests`, `deploy`, `apps`, `README.md`, `pyproject.toml`, or `spec` | unreferenced generated report | delete-now |
| `reports/v012_studio_live_smoke_beginner_after.json` | no refs from `src`, `tests`, `deploy`, `apps`, `README.md`, `pyproject.toml`, or `spec` | unreferenced generated report | delete-now |
| `reports/v012_studio_live_smoke_beginner_dragonkue.json` | no refs from `src`, `tests`, `deploy`, `apps`, `README.md`, `pyproject.toml`, or `spec` | unreferenced generated report | delete-now |

Historical report evidence moved out of `reports/`:

| Source | Destination | Reason |
| --- | --- | --- |
| `reports/ocp_command_learning_v006_live_smoke.json` | `spec/v0.0.6/evidence/ocp_command_learning_v006_live_smoke.json` | cited by v0.0.6 planner |
| `reports/v007_official_chunk_quality_baseline.*` | `spec/v0.0.7/evidence/` | cited by v0.0.7 and v0.1.2 specs |
| `reports/v007_user_study_chunk_quality_baseline.*` | `spec/v0.0.7/evidence/` | cited by v0.0.7 and v0.1.2 specs |
| `reports/studio_live_smoke_report.json` | `spec/v0.1.2/evidence/studio_live_smoke_report.json` | v0.1.2 baseline evidence; runtime can regenerate `reports/studio_live_smoke_report.json` |
| `reports/v012_*.json` baseline/eval reports | `spec/v0.1.2/evidence/` | cited by v0.1.2 planner |

After this split, `reports/` should contain runtime-generated local output only. New report files should remain ignored unless a future planner explicitly promotes them into a versioned `spec/<version>/evidence/` folder.

Cleanup must therefore distinguish:

```text
tracked source cleanup
ignored local generated artifact cleanup
DB schema cleanup
corpus strategy cleanup
```

## Classification

Every candidate should be classified as one of:

```text
keep
move-later
deprecate
delete-now
needs-owner-decision
do-not-touch
```

## Audit Methods

Use multiple checks before deleting:

- `rg` references
- Python import references
- CLI parser registration
- test references
- Docker/Compose/OpenShift manifest references
- API route references
- DB repository query references
- frontend import references
- docs/spec references

## Initial Entrypoint Findings

CLI parser currently registers 29 commands:

```text
ask
corpus-ingest
corpus-quality-audit
course-chunk-import
course-ops-anchor-audit
course-ops-guides
course-qa
course-qdrant-upsert
course-runtime-status
course-ui-smoke
course-visual-audit
db-corpus-status
db-migrate
db-qdrant-backfill
db-qdrant-index
db-qdrant-refresh-payloads
eval
graph-compact
kmsc-course-import
learning-seed-import
maintenance-smoke
official-embedding-qdrant-upsert
official-gold-import
private-lane-smoke
ragas
retrieval-eval
runtime
ui
upload-ingest
```

Deploy/compose/OpenShift manifests directly call a smaller subset:

| Command | Seen in deploy path | Notes |
| --- | --- | --- |
| `db-migrate` | yes | compose and OpenShift job |
| `course-chunk-import` | yes | compose seed path |
| `official-gold-import` | yes | compose/OpenShift official seed |
| `kmsc-course-import` | yes | compose/OpenShift KMSC seed |
| `course-qdrant-upsert` | yes | compose qdrant seed |
| `learning-seed-import` | yes | OpenShift learning seed |
| `ui` | yes | Dockerfile CMD |
| `course-qa` | README/dev command | not production deploy |

Commands not seen in deploy are not automatically unused. They may be eval/dev/maintenance commands. Classify them separately before removal.

Second-pass CLI classification:

| Command | Evidence found | v0.2.0 classification | Action |
| --- | --- | --- | --- |
| `ui` | `deploy/Dockerfile` CMD | keep-production | Do not rename or move in v0.2.0 |
| `db-migrate` | compose/OpenShift migration jobs, parser tests | keep-production | Keep |
| `official-gold-import` | compose/OpenShift official seed jobs, tests | keep-seed | Keep; redesign after corpus audit |
| `kmsc-course-import` | compose/OpenShift KMSC seed jobs, parser tests | keep-seed | Keep |
| `course-chunk-import` | compose/OpenShift course runtime seed jobs, parser tests | keep-seed | Keep |
| `course-qdrant-upsert` | compose/OpenShift qdrant seed jobs | keep-seed | Keep until vector backend decision |
| `learning-seed-import` | OpenShift learning seed job, tests | keep-seed | Keep |
| `official-embedding-qdrant-upsert` | parser/tests; qdrant payload/index path | keep-dev-maintenance | Keep until v0.2.4 backend decision |
| `db-qdrant-index` | tests and qdrant indexer path | keep-dev-maintenance | Keep until v0.2.4 backend decision |
| `db-qdrant-backfill` | tests and qdrant indexer path | keep-dev-maintenance | Keep until v0.2.4 backend decision |
| `db-qdrant-refresh-payloads` | tests and qdrant indexer path | keep-dev-maintenance | Keep until v0.2.4 backend decision |
| `db-corpus-status` | tests | keep-dev-maintenance | Keep; useful for corpus readiness checks |
| `course-runtime-status` | tests | keep-dev-maintenance | Keep while course runtime remains supported |
| `upload-ingest` | tests | keep-dev-maintenance | Keep; supports upload pipeline debugging |
| `course-qa` | README/dev command | keep-dev-eval | Keep |
| `ask` | CLI parser/dispatch only in scan | audit-candidate | Manual review before removal |
| `eval` | CLI parser/dispatch only in scan | keep-dev-eval | Keep unless replaced by v0.2.x eval harness |
| `retrieval-eval` | CLI parser/dispatch only in scan | keep-dev-eval | Keep until v0.2.4 benchmark harness replaces it |
| `ragas` | CLI parser/dispatch only in scan | audit-candidate | Manual review; may be superseded by v0.2.8 eval loop |
| `runtime` | CLI parser/dispatch only in scan | keep-dev-maintenance | Keep; runtime readiness report |
| `maintenance-smoke` | CLI parser/dispatch only in scan | keep-dev-smoke | Keep until smoke suite is consolidated |
| `private-lane-smoke` | CLI parser/dispatch only in scan | keep-dev-smoke | Keep until smoke suite is consolidated |
| `graph-compact` | CLI parser/dispatch only in scan | audit-candidate | Manual review before removal |
| `corpus-ingest` | CLI parser/dispatch only in scan | audit-candidate | Revisit in v0.2.2 corpus audit |
| `corpus-quality-audit` | CLI parser/dispatch only in scan | keep-dev-eval | Keep; directly relevant to v0.2.2 corpus quality work |
| `course-visual-audit` | CLI parser/dispatch only in scan | keep-dev-eval | Keep while course UI assets remain supported |
| `course-ui-smoke` | CLI parser/dispatch only in scan | keep-dev-smoke | Keep until smoke suite is consolidated |
| `course-ops-anchor-audit` | CLI parser/dispatch only in scan | audit-candidate | Manual review with course/KMSC scope |
| `course-ops-guides` | CLI parser/dispatch only in scan | audit-candidate | Manual review with course/KMSC scope |

No CLI command should be removed in v0.2.0. The output of this pass is a follow-up queue, not a deletion list.

## File Cleanup Rules

- Do not move large groups of files in the same commit as behavior changes.
- Prefer deleting generated reports/artifacts over source code.
- If a file is referenced only by old specs, do not delete it solely for that reason; specs are records.
- If a report file is tracked and cited by an older `spec/v*` planner as evidence, keep it until that evidence is migrated into a durable spec appendix.
- If a module is imported dynamically, manual review is required.
- If unsure, keep and document.

## DB Cleanup Rules

- Do not drop tables/columns in v0.2.0.
- First document unused table/column candidates.
- Confirm repository code does not read/write them.
- Confirm deploy/migration scripts do not assume them.
- Plan deprecation and eventual drop in later migration.

Initial table reference scan found these migration-created tables with zero direct `src/play_book_studio` references:

| Table | Initial src refs | Initial classification |
| --- | ---: | --- |
| `answer_logs` | 0 | cleanup-candidate, verify audit/logging path |
| `embedding_jobs` | 0 | cleanup-candidate, verify planned async embedding path |
| `lab_attempts` | 0 | cleanup-candidate, verify learning runtime history needs |
| `learner_progress` | 0 | cleanup-candidate, verify UI/API roadmap |
| `learning_step_documents` | 0 | cleanup-candidate, verify learning doc linkage |
| `question_logs` | 0 | cleanup-candidate, verify answer audit replacement |

Important: zero direct reference is not enough to drop a table. These must be checked against migrations, tests, possible raw SQL strings, planned features, and production data before any destructive change.

## Expected Report Shape

```markdown
| Path/Object | Type | Current references | Classification | Action | Notes |
| --- | --- | --- | --- | --- | --- |
```

## Acceptance Criteria

- Cleanup candidates are listed before deletion.
- DB cleanup candidates are separated from code cleanup.
- No production path is removed without reference evidence.
- Follow-up cleanup work can be split into small commits.
