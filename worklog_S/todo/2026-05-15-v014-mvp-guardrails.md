# v0.1.4 MVP Guardrails

Date: 2026-05-15

Purpose: J의 v0.1.4 설계를 기준으로 하되, 전체 schema를 한 번에 구현하지 않고 metadata strategy 중심 MVP로 제한한다.

## Fixed Rules

1. J의 v0.1.4 설계를 기준으로 삼는다.
2. 전체 테이블을 한 번에 구현하지 않는다.
3. 먼저 metadata strategy가 반영되는 최소 경로를 구현한다.
4. 기존 `document_chunks` / retrieval / answering 코드를 깨지 않는다.
5. Qdrant는 truth가 아니라 corpus projection으로 취급한다.
6. 모든 변경은 dry-run 가능한 샘플 데이터와 검증 쿼리를 포함한다.
7. 운영문서용 facet 확장 가능성을 열어둔다.

## MVP Scope

우선 구현/설계 대상으로 보는 최소 경로:

- `document_sources`
- `parsed_documents`
- `document_blocks`
- `corpus_documents`
- `corpus_chunks`
- `corpus_chunk_segments`
- `qdrant_index_entries`

## Not Full Implementation Yet

아직 full 구현하지 않는다:

- `corpus_chunk_refs`
- `corpus_question_candidates`
- `document_assets` 고도화
- command 자동 추출 고도화
- full answer card renderer

이 항목들은 v0.1.4 설계에는 포함되지만 MVP에서는 dry-run/gap 기록까지만 둔다.

## Metadata Strategy Rules

- 검색/필터/권한/인용에 쓰이는 값은 컬럼으로 둔다.
- 특정 도메인에서만 쓰이는 값은 `facets` JSONB로 둔다.
- import/debug/generation 정보는 `metadata` JSONB로 둔다.
- `metadata` JSONB에 검색 필터 값을 숨기지 않는다.

## Required Search Metadata

`corpus_documents` / `corpus_chunks`에는 최소한 다음 검색 메타데이터를 반영한다:

- `corpus_scope`
- `visibility`
- `document_slug`
- `book_slug`
- `title`
- `locale`
- `ocp_version`
- `domain`
- `platform`
- `provider`
- `doc_type`
- `audience_level`
- `chunk_type`
- `task_intent`
- `lifecycle_phase`
- `privilege_scope`
- `navigation_only`
- `facets`
- `metadata`

## Operations Facets Extension

KMSC/KOMSCO 운영문서/PPT를 고려해 `facets.operations` 확장 가능성을 열어둔다.

Candidate keys:

- `design_id`
- `test_case_id`
- `project_name`
- `module_name`
- `network_zone`
- `node_role`
- `environment`

## Qdrant Projection Rule

Qdrant payload는 `corpus_chunks` 기준 deterministic projection으로 만든다.

- 본문 segment 전체를 payload에 넣지 않는다.
- `payload_hash`와 `payload_version`으로 재색인 여부를 판단한다.
- Qdrant는 truth가 아니다. PostgreSQL corpus에서 재생성 가능해야 한다.

## Compatibility Rule

기존 코드가 `document_chunks`를 보고 있다면 바로 삭제하지 않는다.

Required approach:

- compatibility view 또는 adapter 제공
- retrieval / answering interface 유지
- v0.1.4 corpus table hydration은 점진 전환

## Required Work Output

작업 결과에는 반드시 포함한다:

- 생성/수정한 파일 목록
- DB migration 초안
- 샘플 insert 또는 fixture
- 검증 SQL
- 기존 기능 호환성 체크 목록
- 아직 구현하지 않은 TODO 목록

## Important Interpretation

이 guardrail은 현재 순서와 충돌하지 않는다.

현재 순서:

1. inventory baseline
2. corpus folder contract
3. term bridge
4. actual data dry-run mapping
5. gap audit
6. MVP implementation draft

즉, 이 문서는 4~6단계를 더 정확히 제한한다.

단, `DB migration 초안`은 실제 적용 migration이 아니라 dry-run/gap audit 이후의 draft로 본다. J의 v0.1.4 원칙상 합의 전 실제 SQL 적용은 하지 않는다.

## Working Sequence

J 설계와 GPT guardrail을 합친 실제 작업 순서는 아래로 고정한다.

1. `docs/metadata-strategy.md` 작성
   - 컬럼 vs `facets` vs `metadata` 기준
   - parsing metadata와 corpus metadata 차이
   - Qdrant payload projection 기준
   - `facets.operations` 확장안
   - `navigation_only`, command/env scope 처리 기준
2. 실제 데이터 3종 sample mapping 작성
   - official doc 1개
   - KMSC/PPT 운영문서 1개
   - PVC 또는 command-heavy chunk 1개
3. `db/migrations/0009_corpus_layer.sql` 초안 작성
   - 바로 적용하지 않는다.
   - 2단계 sample mapping으로 검증된 필드만 MVP에 넣는다.
4. Qdrant payload projection 함수 초안 작성
   - 전체 임베딩 재생성은 하지 않는다.
   - `build_qdrant_payload(corpus_chunk)` 형태로 deterministic payload만 검증한다.
5. Compatibility path 작성
   - 현재 `document_chunks`는 이미 실제 테이블이므로 무턱대고 `CREATE VIEW document_chunks AS ...`로 대체하지 않는다.
   - MVP에서는 adapter 또는 별도 compatibility view 이름을 우선 검토한다.
6. Smoke test 작성
   - "OCP가 뭐야?"
   - "PV는 어디서 확인해?"
   - "MachineConfigPool degraded면 어디부터 봐?"

주의: 2단계 sample mapping 없이 3단계 migration 초안을 먼저 확정하지 않는다. 이 순서는 fantasy schema를 막기 위한 안전장치다.
