# v0.2.0 DB Migration Plan

## Direction

The project already uses flat sequential SQL migrations under `db/migrations/000*.sql`. v0.2.x must continue that model.

Do not create versioned SQL folders such as `db/migrations/v0.2.0/`. Version ownership belongs in `spec/`, not in the migration runner path.

Official corpus storage schema is not finalized in v0.2.0. Do not create official corpus tables until v0.2.2 finishes corpus audit and enrichment prototype work.

Vector backend schema is also not finalized in v0.2.0. Do not create pgvector tables until Qdrant vs pgvector benchmark evidence exists.

## Current State

Existing migration sequence:

```text
0000_schema_migrations.sql
0001_ingestion_foundation.sql
0002_learning_foundation.sql
0003_terminal_learning_runtime.sql
0004_repository_session_scope.sql
0005_course_runtime_chunks.sql
0006_course_runtime_assets.sql
0007_course_runtime_manifest.sql
0008_chunk_runtime_enrichment.sql
0009_qdrant_payload_contract.sql
```

Next migrations, if approved, should continue from `0010`.

The migration runner confirms this flat model: `src/play_book_studio/db/migrations.py` uses `root.glob("*.sql")`, so nested migration folders are not applied.

## Planned Numbering

Tentative future sequence:

```text
0010_corpus_foundation_tables.sql
0011_enrichment_run_tables.sql
0012_runtime_context_tables.sql
0013_operation_watch_tables.sql
0014_feedback_eval_tables.sql
0015_runtime_operation_indexes.sql
```

These files must not be created until the v0.2.0 ERD is reviewed.

For corpus-related files, an additional gate applies: do not create them until v0.2.2 decides whether to enrich existing `chunks.jsonl`, rebuild from official source documents, split `manual_synthesis`, or partially rebuild selected books.

For vector-related files, an additional gate applies: do not create pgvector migrations until v0.2.4 compares enriched retrieval performance and operational complexity against Qdrant.

## Existing Migration Audit

Before adding `0010`, audit existing migrations against current code.

Initial migration scan:

| Migration | Creates / Alters |
| --- | --- |
| `0000_schema_migrations.sql` | `schema_migrations` |
| `0001_ingestion_foundation.sql` | `tenants`, `workspaces`, `document_sources`, `document_versions`, `parse_jobs`, `parsed_documents`, `document_blocks`, `document_assets`, `document_chunks`, `embedding_jobs`, `qdrant_index_entries`, `question_logs`, `answer_logs` |
| `0002_learning_foundation.sql` | `learning_paths`, `learning_steps`, `learning_step_documents`, `lab_tasks`, `command_checks`, `learner_progress`, `lab_attempts` |
| `0003_terminal_learning_runtime.sql` | `terminal_sessions`, `terminal_events`, `learning_step_attempts`, `command_check_results` |
| `0004_repository_session_scope.sql` | `repositories`, `chat_sessions`, `chat_messages`; alters document tables |
| `0005_course_runtime_chunks.sql` | `course_chunks` |
| `0006_course_runtime_assets.sql` | `course_assets` |
| `0007_course_runtime_manifest.sql` | `course_manifests` |
| `0008_chunk_runtime_enrichment.sql` | alters `document_chunks` |
| `0009_qdrant_payload_contract.sql` | alters `qdrant_index_entries` |

Initial source reference scan shows several created tables with no direct source references: `answer_logs`, `embedding_jobs`, `lab_attempts`, `learner_progress`, `learning_step_documents`, and `question_logs`. Treat these as audit candidates only, not drop targets.

Second-pass reference scan:

Scope:

```text
src/play_book_studio
tests
deploy
apps/web/src
```

The counts below are simple exact-string references, not proof of runtime usage. They are useful for deciding where manual review is needed before any future schema cleanup.

| Table | Reference count | v0.2.0 classification | Notes |
| --- | ---: | --- | --- |
| `tenants` | 13 | keep-but-document | Tenant/workspace boundary exists but needs alignment with future OCP user workspace model. |
| `workspaces` | 108 | keep | Current workspace/session surface depends on it. |
| `document_sources` | 31 | keep | Core upload/official/study corpus table. |
| `document_versions` | 7 | keep-but-document | Version table exists; verify whether upload ingestion still creates meaningful versions. |
| `parse_jobs` | 12 | keep-but-document | Parse status/history table; verify status transitions during upload ingestion. |
| `parsed_documents` | 43 | keep | Core parsed artifact table. |
| `document_blocks` | 6 | keep-but-document | Low reference count; verify viewer/parser dependency before redesign. |
| `document_assets` | 6 | keep-but-document | Low reference count; likely needed for uploaded/KMSC assets. |
| `document_chunks` | 78 | keep | Core retrieval and viewer table. |
| `embedding_jobs` | 0 | cleanup-candidate | No direct refs; possible abandoned async embedding design. Do not drop until production data and future async pipeline are checked. |
| `qdrant_index_entries` | 47 | keep | Current Qdrant parity/index bookkeeping depends on it. Revisit after v0.2.4 vector backend decision. |
| `question_logs` | 0 | cleanup-candidate | No direct refs; superseded or never wired answer audit candidate. |
| `answer_logs` | 0 | cleanup-candidate | No direct refs; superseded or never wired answer audit candidate. |
| `learning_paths` | 25 | keep | Learning route seed/API still references it. |
| `learning_steps` | 9 | keep | Learning flow dependency. |
| `learning_step_documents` | 0 | cleanup-candidate | No direct refs; may be intended doc-to-step join but not currently used. |
| `lab_tasks` | 34 | keep | Terminal learning checks depend on it. |
| `command_checks` | 40 | keep | Terminal learning validation depends on it. |
| `learner_progress` | 0 | cleanup-candidate | No direct refs; legacy progress model candidate. |
| `lab_attempts` | 0 | cleanup-candidate | No direct refs; legacy attempt model candidate. |
| `terminal_sessions` | 5 | keep-but-document | Terminal runtime exists; future Operation Watcher may replace/extend it. |
| `terminal_events` | 2 | keep-but-document | Low reference count but needed for terminal transcript/event trail if enabled. |
| `learning_step_attempts` | 1 | keep-but-document | Runtime learning attempt table; low refs require manual flow review. |
| `command_check_results` | 14 | keep | Terminal command validation results. |
| `repositories` | 131 | keep | Repository/session/source scoping depends on it. |
| `chat_sessions` | 25 | keep | Chat history API depends on it. |
| `chat_messages` | 21 | keep | Chat history API depends on it. |
| `course_chunks` | 61 | keep | Course runtime UI/API depends on it. |
| `course_assets` | 23 | keep | Course asset resolution depends on it. |
| `course_manifests` | 8 | keep | Course runtime manifest dependency. |

No table should be dropped in v0.2.0. The six zero-reference tables should move into a later deprecation review only after:

- production row counts are inspected,
- current UI/API flows are checked for implicit assumptions,
- future v0.2.x ERD has a replacement path,
- backup/export notes are written,
- a non-destructive migration first marks the table as deprecated in documentation.

Questions:

- Is each table still read or written by repository code?
- Are all columns still populated?
- Are JSONB fields carrying data that is never consumed?
- Are migration names still accurate?
- Is any table now only historical/deprecated?
- Are indexes aligned with actual query patterns?
- Are there nullable columns that should stay nullable because old data exists?
- Are there destructive cleanup candidates that need deprecation first?

Output should classify each item:

```text
keep
keep-but-document
deprecate
cleanup-candidate
needs-backfill
needs-index
do-not-touch
```

## SQL Rules

### CREATE

- Use explicit primary keys.
- Use explicit foreign key names.
- Include `created_at` and `updated_at`.
- Include tenant/workspace/user boundary where required.
- Avoid JSONB dumping when a typed column is clearly needed.

### ALTER / UPDATE

- Add nullable column first.
- Backfill separately.
- Enforce `NOT NULL` only after verification.
- Avoid large table rewrites in mixed-purpose migrations.

### UPSERT

- Use explicit conflict targets.
- Update only mutable fields.
- Always update `updated_at`.
- Do not overwrite immutable source/provenance columns.

### DROP

- Do not include destructive `DROP` in forward migrations.
- Deprecate first.
- Verify no code path reads/writes the object.
- Prepare backup/export notes before destructive cleanup.

### SEED

- Keep seed files flat and numbered if added.
- Use idempotent `INSERT ... ON CONFLICT`.
- Do not insert environment-specific values.
- Do not insert user data.

## Acceptance Criteria

- Existing migrations are audited before new SQL is added.
- New SQL uses flat sequential numbering.
- UPDATE/UPSERT/DROP rules are documented before implementation.
- Cleanup candidates are classified before removal.
