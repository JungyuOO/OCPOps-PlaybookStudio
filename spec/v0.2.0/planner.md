# v0.2.0 - Project Structure and Database Foundation Planner

## Goal

v0.2.0의 목표는 RAG 데이터 재구축, OCP runtime context, Operation Watcher, feedback/eval loop를 구현하기 전에 프로젝트 구조와 DB 변경 운영 방식을 현업 수준으로 정리하는 것이다.

이번 버전에서는 기능을 크게 추가하지 않는다. 대신 앞으로 추가될 corpus, enrichment, runtime snapshot, operation watcher, notification, feedback 테이블이 뒤엉키지 않도록 ERD 후보, migration/SQL 작성 규칙, 폴더 구조, 도메인 경계를 먼저 정리한다.

Official corpus storage schema is intentionally not finalized in v0.2.0. The final storage/import design for official documentation must be decided after the v0.2.2 corpus audit and LLM enrichment prototype results.

## Why This Comes First

v0.2.x에서 추가될 기능은 모두 데이터 모델 의존도가 높다.

- enriched corpus artifact
- LLM enrichment run/result
- Qdrant/BM25 indexing state
- OCP namespace/resource snapshot
- Event/Log/Alert retention
- Operation Watcher run/target/event/notification
- answer feedback and failure cases
- benchmark/eval history

이 상태에서 바로 기능을 구현하면 ad-hoc table과 migration이 계속 늘어나고, 나중에 `UPDATE`, `UPSERT`, `DROP`, rollback, seed data, retention cleanup이 관리되지 않을 수 있다. 따라서 v0.2.0은 "구현 전 정리 버전"으로 둔다.

## Scope

### Included

1. 프로젝트 폴더 구조 정리 원칙
2. DB migration 디렉터리와 파일 규칙
3. CREATE / UPDATE / UPSERT / DROP / SEED SQL 작성 기준
4. v0.2.x 전체 ERD 도메인 경계
5. table/index/constraint naming convention
6. migration safety checklist
7. 기존 파일 이동/정리 전략
8. official corpus 저장 방식은 v0.2.2 분석 이후 확정한다는 경계 명시
9. Qdrant 유지 vs pgvector 전환 decision frame 작성

### Excluded

- 대규모 기존 파일 이동
- production table 변경
- official corpus 저장 테이블 확정
- `document_sources`, `parsed_documents`, `document_chunks` 대체 결정
- 실제 runtime collector 구현
- full corpus enrichment
- Qdrant collection 교체
- Qdrant 제거 또는 pgvector migration
- Operation Watcher 구현
- UI 변경

## Project Structure Plan

기존 파일을 한 번에 대규모 이동하지 않는다. 새 기능부터 정리된 구조에 추가하고, 기존 파일은 해당 도메인을 수정할 때 점진적으로 이동한다.

권장 구조:

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
    migrations/
```

기존 구조를 바로 깨지 않기 위한 원칙:

- import 경로 대규모 변경은 별도 cleanup 버전에서 처리한다.
- 새 v0.2.x 기능은 가능한 새 domain package에 둔다.
- 기존 API contract가 깨지는 파일 이동은 금지한다.
- 단순 문서/스펙/SQL은 먼저 정리하고, runtime code 이동은 나중에 한다.

## Repository Cleanup Plan

v0.2.0에서는 새 기능 구현 전에 실제로 사용하지 않는 폴더, 파일, 코드, DB migration을 정리할 기준을 만든다. 다만 바로 대규모 삭제하지 않고 먼저 usage audit를 수행한다.

Initial scan summary:

- `git ls-files`: 1,501 tracked files
- largest tracked area: `corpus` with 940 files
- `src`: 305 tracked Python/source files
- `tests`: 95 tracked test files
- `apps/web`: 73 tracked source files, while local `node_modules` and `dist` are ignored
- raw local generated files are much larger because `artifacts/`, reports, frontend dependencies, and generated corpus layers exist outside tracked source

정리 대상 후보:

- 더 이상 import되지 않는 Python module
- 더 이상 호출되지 않는 CLI command
- 오래된 eval/report script
- 중복 corpus artifact
- 사용하지 않는 spec 초안
- docker/deploy에서 참조하지 않는 설정 파일
- DB에 적용되지 않거나 현재 schema와 맞지 않는 migration SQL
- 테이블에는 존재하지만 앱 코드에서 읽거나 쓰지 않는 컬럼
- JSONB payload에 저장하지만 retrieval/answer/UI에서 사용하지 않는 필드

Audit 기준:

- `rg`/import graph로 코드 참조 확인
- CLI/parser 등록 여부 확인
- deploy script/docker compose/OpenShift manifest 참조 확인
- DB repository query에서 테이블/컬럼 사용 여부 확인
- migration 적용 순서와 실제 repository code 기대 schema 비교
- 삭제 전 "remove", "keep", "deprecate", "move later"로 분류

삭제 원칙:

- production path에서 쓰이는지 확실하지 않으면 삭제하지 않는다.
- 삭제 대신 먼저 deprecate note를 남긴다.
- 기존 파일 이동은 import/API contract가 깨지지 않는 범위에서만 한다.
- SQL destructive change는 forward migration에 넣지 않는다.

## Migration Directory Plan

실제 SQL migration은 기존 프로젝트의 flat sequential migration 방식을 유지한다. `db/migrations/v0.2.0/` 같은 버전별 SQL 폴더는 사용하지 않는다.

현재 구조:

```text
db/
  migrations/
    0000_schema_migrations.sql
    0001_ingestion_foundation.sql
    ...
    0009_qdrant_payload_contract.sql
```

v0.2.x에서 새 migration이 필요하면 이어서 추가한다.

```text
db/
  migrations/
    0010_corpus_foundation_tables.sql
    0011_enrichment_run_tables.sql
    0012_runtime_context_tables.sql
    0013_operation_watch_tables.sql
    0014_feedback_eval_tables.sql
    0015_runtime_operation_indexes.sql
  seeds/
    0010_default_retention_policies.sql
    0011_default_feedback_reason_tags.sql
  rollback/
    0014_drop_feedback_eval_tables.sql
    0013_drop_operation_watch_tables.sql
```

버전과 migration의 매핑은 SQL 폴더가 아니라 `spec/v0.2.0/db-migration-plan.md`에서 관리한다.

파일명 규칙:

```text
NNNN_action_domain_subject.sql
```

예:

```text
0010_create_corpus_artifacts.sql
0011_create_enrichment_runs.sql
0012_alter_document_chunks_add_search_signals.sql
0013_create_operation_watch_tables.sql
0014_insert_default_operation_notification_types.sql
```

## Vector Backend Decision

현재 프로젝트는 PostgreSQL을 system of record로 쓰고 Qdrant를 vector backend로 사용한다. v0.2.x에서 runtime context, operation watcher, feedback/eval까지 PostgreSQL 중심으로 확장할 예정이므로, Qdrant hard dependency를 계속 유지할지 pgvector로 단순화할지 검토한다.

v0.2.0에서는 결정하지 않는다. `spec/v0.2.0/vector-backend-decision.md`에 decision frame만 남기고, 실제 결정은 v0.2.4 enriched retrieval benchmark에서 Qdrant와 pgvector를 비교한 뒤 내린다.

검토 방향:

```text
Qdrant hard dependency
  -> vector backend abstraction
  -> pgvector default candidate
  -> Qdrant optional backend
```

## SQL Operation Rules

### CREATE

CREATE migration은 가능한 한 독립적이고 idempotent하게 작성한다.

Rules:

- `CREATE TABLE IF NOT EXISTS` 사용
- primary key 명시
- foreign key 이름 명시
- `created_at`, `updated_at` 기본 포함
- tenant/workspace/user boundary가 필요한 테이블은 처음부터 포함
- JSONB는 schema-less dumping 용도가 아니라 확장 필드로만 사용

### UPDATE / ALTER

ALTER는 작은 단위로 나눈다.

Rules:

- nullable column 추가 후 backfill, 그 다음 not null 적용
- large table rewrite가 필요한 변경은 별도 migration으로 분리
- 기존 데이터 backfill query 포함
- reversible한지 rollback 메모 작성

### UPSERT

sync/run/state 계열 테이블은 upsert 기준을 명확히 한다.

Rules:

- conflict key를 명시한다.
- `updated_at = now()`를 포함한다.
- immutable source fields는 update하지 않는다.
- mutable state fields만 update한다.

Example pattern:

```sql
INSERT INTO operation_watch_targets (...)
VALUES (...)
ON CONFLICT (operation_run_id, resource_kind, namespace, resource_name)
DO UPDATE SET
  last_seen_at = EXCLUDED.last_seen_at,
  status = EXCLUDED.status,
  updated_at = now();
```

### DROP / Rollback

DROP은 production에서 가장 위험하므로 별도 rollback 폴더에 둔다.

Rules:

- forward migration에 `DROP TABLE` 금지
- destructive change는 rollback script와 data export plan 필요
- column drop은 deprecate -> backfill verification -> drop 순서
- rollback script는 dependency 역순으로 작성

### SEED / INSERT

기본 정책/태그/타입은 seed로 분리한다.

Seed candidates:

- retention policy
- feedback reason tags
- operation notification types
- eval case categories
- source scope definitions

Rules:

- seed는 idempotent upsert로 작성
- user data seed 금지
- environment-specific value 금지

## ERD Domains

v0.2.x에서 다룰 DB 도메인은 다음과 같이 나눈다. 아래 목록은 후보이며 approved migration list가 아니다. 특히 Corpus/RAG 테이블은 v0.2.2 공식문서 데이터 분석 결과에 따라 유지, 확장, 분리, 대체 여부가 바뀔 수 있다.

### Corpus / RAG

Candidate tables:

- `corpus_sources`
- `corpus_artifacts`
- `corpus_chunks`
- `corpus_text_layers`
- `enrichment_runs`
- `enrichment_run_items`
- `retrieval_indexes`
- `qdrant_sync_runs`

Decision gate:

- Do not finalize these tables in v0.2.0.
- Audit existing `document_sources`, `parsed_documents`, `document_chunks`, and Qdrant sync tables first.
- Decide final storage/import shape after v0.2.2 corpus analysis.

### Runtime Context

Candidate tables:

- `ocp_clusters`
- `ocp_user_workspaces`
- `ocp_namespace_bindings`
- `ocp_resource_snapshots`
- `ocp_pod_snapshots`
- `ocp_events`
- `ocp_log_segments`
- `ocp_alerts`
- `ocp_metric_summaries`
- `ocp_context_packs`

### Operation Watcher / Notifications

Candidate tables:

- `operation_runs`
- `operation_steps`
- `operation_watch_targets`
- `operation_events`
- `operation_notifications`
- `operation_diagnoses`

### Feedback / Eval

Candidate tables:

- `answer_feedback`
- `retrieval_failure_cases`
- `benchmark_candidates`
- `eval_runs`
- `eval_run_items`

## Table Design Principles

공통 컬럼:

```text
id
tenant_id
workspace_id
owner_user_id
created_at
updated_at
deleted_at
metadata
```

runtime/OCP 관련 테이블 추가 컬럼:

```text
cluster_id
namespace
resource_kind
resource_name
resource_uid
collected_at
expires_at
stale_at
redaction_status
```

run/status 관련 테이블 추가 컬럼:

```text
status
started_at
completed_at
failed_at
error_code
error_message
attempt_count
```

## Naming Conventions

Indexes:

```text
idx_<table>_<columns>
```

Unique constraints:

```text
uq_<table>_<columns>
```

Foreign keys:

```text
fk_<table>_<referenced_table>
```

Check constraints:

```text
ck_<table>_<condition>
```

## Migration Safety Checklist

모든 DB migration은 다음 항목을 확인한다.

- migration 순서가 명확한가
- rollback 또는 forward-fix 전략이 있는가
- production data에 destructive impact가 없는가
- existing table lock 시간이 길지 않은가
- index 생성이 필요한가
- unique constraint가 기존 데이터와 충돌하지 않는가
- nullable/backfill/not-null 순서를 지켰는가
- tenant/workspace/user isolation이 반영됐는가
- retention/delete 정책이 있는가
- 민감정보 redaction 전략이 있는가

## Deliverables

v0.2.0에서 작성할 문서/구조:

- `spec/v0.2.0/planner.md`
- `spec/v0.2.0/project-structure.md`
- `spec/v0.2.0/db-migration-plan.md`
- `spec/v0.2.0/source-structure-redesign-audit.md`
- `spec/v0.2.0/vector-backend-decision.md`
- `spec/v0.2.0/erd/table-index.md`
- `spec/v0.2.0/erd/corpus-erd.md`
- `spec/v0.2.0/erd/runtime-context-erd.md`
- `spec/v0.2.0/erd/operation-watch-erd.md`
- `spec/v0.2.0/erd/feedback-eval-erd.md`
- `spec/v0.2.0/repository-cleanup-audit.md`

실제 CREATE/ALTER SQL은 ERD 확정 후 기존 flat migration 순서에 이어서 추가한다. v0.2.0에서는 파일명/순서/rollback/seed 규칙과 기존 SQL audit 기준만 확정한다.

## Follow-up Version References

- [v0.2.1 RAG Data Foundation Planning](../v0.2.1/planner.md)
- [v0.2.2 Corpus Audit and LLM Enrichment Prototype](../v0.2.2/planner.md)
- [v0.2.3 Official Corpus Rebuild and Full Enrichment](../v0.2.3/planner.md)
- [v0.2.4 Enriched Retrieval Pipeline Replacement](../v0.2.4/planner.md)
- [v0.2.5 Runtime Context ERD and Storage](../v0.2.5/planner.md)
- [v0.2.6 OCP Runtime Context Collector](../v0.2.6/planner.md)
- [v0.2.7 Operations Assistant Answer Flow](../v0.2.7/planner.md)
- [v0.2.8 Feedback Loop and Continuous Evaluation](../v0.2.8/planner.md)
- [v0.2.9 Operation Watcher and Notifications](../v0.2.9/planner.md)

## Acceptance Criteria

- v0.2.0은 프로젝트 구조와 DB foundation 정리만 다룬다.
- flat migration numbering, naming, rollback, seed 규칙이 명확하다.
- CREATE/UPDATE/UPSERT/DROP 기준이 문서화되어 있다.
- 기존 SQL/폴더/파일/코드를 정리하기 위한 usage audit 기준이 있다.
- v0.2.x 전체 ERD 도메인 경계가 나뉘어 있다.
- official corpus storage schema가 v0.2.0에서 확정되지 않는다는 경계가 명확하다.
- 기존 파일 대규모 이동 없이 새 기능 추가 위치가 정리되어 있다.
- v0.2.1 이후 RAG/corpus 작업이 이 구조 위에서 진행될 수 있다.

## Non-goals

- 실제 production DB 변경
- 대규모 파일 이동
- corpus rebuild
- enrichment 실행
- collector 구현
- watcher 구현
- notification UI 구현

## Completion Check

v0.2.0이 끝나면 팀이 새 기능을 추가하기 전에 어디에 파일을 둘지, DB 변경을 어떤 순서와 형식으로 만들지, UPDATE/UPSERT/DROP을 어떻게 안전하게 다룰지 합의된 상태여야 한다.

## Completion Result

Status: complete

v0.2.0은 실제 production 동작을 바꾸지 않고 프로젝트 구조와 DB foundation 정리를 완료했다.

Acceptance result:

| Criterion | Result | Evidence |
| --- | --- | --- |
| 프로젝트 구조와 DB foundation 정리만 다룸 | pass | 코드 기능 변경, production DB 변경, corpus rebuild 없음 |
| flat migration numbering/naming/rollback/seed 규칙 명확화 | pass | `db-migration-plan.md` |
| CREATE/UPDATE/UPSERT/DROP 기준 문서화 | pass | `planner.md`, `db-migration-plan.md` |
| 기존 SQL/폴더/파일/코드 usage audit 기준 존재 | pass | `repository-cleanup-audit.md`, `source-structure-redesign-audit.md` |
| v0.2.x 전체 ERD 도메인 경계 분리 | pass | `erd/table-index.md`, domain ERD docs |
| official corpus storage schema를 v0.2.0에서 확정하지 않는 경계 명확화 | pass | `db-migration-plan.md`, v0.2.1/v0.2.2 handoff |
| 기존 파일 대규모 이동 없이 새 기능 추가 위치 정리 | pass | `project-structure.md` |
| v0.2.1 이후 RAG/corpus 작업이 이 구조 위에서 진행 가능 | pass | `project-structure.md`, `vector-backend-decision.md`, v0.2.1 planner |

Completed cleanup/audit work:

- Unreferenced generated reports were removed from tracked source.
- Historical report evidence was moved from `reports/` into versioned `spec/<version>/evidence/` folders.
- Existing DB migration tables were classified by current reference evidence.
- CLI commands were classified by production/deploy/dev/eval/audit usage.
- New v0.2.x package placement rules were documented without mass-moving existing runtime code.
- Qdrant vs pgvector decision was framed without creating pgvector migrations or removing Qdrant.

Carry-forward:

- v0.2.1 starts RAG data foundation planning, not more general repository cleanup.
- v0.2.2 performs corpus audit and LLM enrichment prototype work.
- Any future source deletion, DB deprecation, Qdrant removal, or pgvector migration must happen in a later version with focused evidence and tests.
