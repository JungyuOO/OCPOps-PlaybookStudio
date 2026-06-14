# 변경 파일 묶음

## 기준

| 항목 | 값 |
|---|---|
| branch | `dev` |
| base head | `7dde93d` |
| 목적 | OpenShift Lightspeed 호출 연동, PBS RAG 근거 결합, Viewer 표시, smoke 검증 |
| 실행 서비스 | `postgres`, `app`, `web` |
| 제외 서비스 | Qdrant |

전체 파일 목록은 `git diff --name-status`와 `git ls-files --others --exclude-standard`로 확인한다.
이 문서는 변경 목적을 설명하기 위한 영역별 묶음이다.

## 변경 묶음

| 영역 | 대표 파일 |
|---|---|
| 환경/설정 | `.env.production.example`, `src/play_book_studio/config/settings.py`, `docker-compose.yml` |
| OpenShift Lightspeed client | `src/play_book_studio/integrations/lightspeed.py`, `src/play_book_studio/integrations/__init__.py` |
| OpenShift Lightspeed answer path | `src/play_book_studio/answering/answerer.py`, `src/play_book_studio/answering/prompt.py`, `src/play_book_studio/answering/pipeline_helpers.py` |
| OpenShift Lightspeed Viewer | `src/play_book_studio/http/server_routes_viewer.py`, `src/play_book_studio/http/server_support.py`, `src/play_book_studio/http/presenters_runtime.py` |
| OpenShift Lightspeed CLI smoke | `src/play_book_studio/cli.py`, `scripts/mock_lightspeed_server.py` |
| DB migration | `db/migrations/0010_pgvector_chunk_embeddings.sql`, `db/migrations/0011_drop_legacy_qdrant_index_entries.sql` |
| DB 상태 확인 | `src/play_book_studio/db/corpus_status.py`, `src/play_book_studio/db/document_repository.py`, `src/play_book_studio/db/embedding_indexer.py` |
| 검색 | `src/play_book_studio/retrieval/vector.py`, `src/play_book_studio/retrieval/payload.py`, `src/play_book_studio/retrieval/retriever_search.py`, `src/play_book_studio/retrieval/retriever_pipeline.py` |
| 검색 신호 | `src/play_book_studio/retrieval/query_signal_pipeline.py`, `src/play_book_studio/retrieval/query_understanding.py`, `src/play_book_studio/retrieval/intent_profile.py` |
| course 검색 | `src/play_book_studio/course/chunk_loader.py`, `src/play_book_studio/course/search_payload.py`, `src/play_book_studio/course/build_index.py` |
| ingestion | `src/play_book_studio/ingestion/corpus_import.py`, `src/play_book_studio/ingestion/kmsc_course_import.py`, `src/play_book_studio/ingestion/pipeline.py`, `src/play_book_studio/ingestion/runtime_catalog_library.py` |
| HTTP/API | `src/play_book_studio/http/server_routes_viewer.py`, `src/play_book_studio/http/server_support.py`, `src/play_book_studio/http/source_books_viewer_resolver.py` |
| answer | `src/play_book_studio/answering/answerer.py`, `src/play_book_studio/answering/prompt.py`, `src/play_book_studio/answering/pipeline_helpers.py` |
| evaluation | `src/play_book_studio/evals/answer_viewer_audit.py`, `src/play_book_studio/evals/rag_foundation_audit.py`, `src/play_book_studio/evals/chunk_quality_audit.py` |
| deploy/runtime | `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `deploy/docker-compose.image.yml`, `deploy/openshift/core.yaml`, `deploy/openshift/app.yaml`, `deploy/openshift/apply-playbookstudio.sh`, `deploy/openshift/README.md` |
| web | `apps/web/src/lib/runtimeApi.ts`, `apps/web/src/pages/WorkspacePage.tsx`, `apps/web/src/pages/workspace/WorkspaceAnswer.tsx`, `apps/web/src/pages/workspaceTypes.ts` |
| CLI | `src/play_book_studio/cli.py` |
| docs | `.kugnus-plan/lightspeed-call-proof-report.md`, `.kugnus-plan/lightspeed-pbs-chat-integration.md`, `.kugnus-plan/company-openshift-lightspeed-next.md`, `.kugnus-plan/macbook-crc-lightspeed-runbook.md`, `deploy/openshift/README.md` |
| tests | `tests/test_lightspeed_client.py`, `tests/test_lightspeed_viewer.py`, `tests/test_answerer_llm_final.py`, `tests/test_app_server.py`, `tests/test_runtime_seed_inputs.py`, `apps/web/src/pages/workspace/WorkspaceAnswer.test.tsx` |

## OpenShift Lightspeed 연동

| 항목 | 처리 |
|---|---|
| 호출 방향 | PBS Backend에서 OpenShift 운영 질문을 감지하면 OpenShift Lightspeed `POST /v1/query` 호출 |
| 공식 답변 처리 | OpenShift Lightspeed 답변을 공식 기준 답변으로 prompt에 포함 |
| PBS 근거 처리 | 최종 citation은 PBS RAG 검색 결과만 사용 |
| Viewer 처리 | OpenShift Lightspeed 응답은 `/external/lightspeed/{artifact_id}` artifact로 저장하고 PBS Viewer에서 표시 |
| 배지 | 답변 헤더와 related link에 `Lightspeed` 표시 |
| 미설정 상태 | endpoint가 없으면 PBS 내부 근거 답변으로 계속 동작하고 미연결 상태 문구 표시 |
| 권한 확인 | `lightspeed-auth-smoke`로 `/authorized` 결과와 token 권한 확인 |
| 통합 확인 | `lightspeed-integration-smoke`로 auth, query, chat, source-meta, Viewer API 확인 |
| mock 확인 | `scripts/mock_lightspeed_server.py`로 회사 endpoint 없이 app container 경로 검증 |

## 업로드 예외 처리

| 항목 | 처리 |
|---|---|
| 실패 기록 | `uploads/exceptions/<failure_id>/failure-report.json` 생성 |
| 원본 파일 | 저장된 원본이 있으면 예외 폴더로 이동 |
| 민감정보 | report에 원본 본문이나 base64 payload를 넣지 않음 |
| API 응답 | 실패 단계와 failure report 경로 반환 |
| 검증 | `tests/test_upload_api.py`, `tests/test_upload_ingest_cli.py` 통과 |

## 제거된 파일

| 파일 | 이유 |
|---|---|
| `src/play_book_studio/db/qdrant_indexer.py` | PostgreSQL `chunk_embeddings` 색인으로 대체 |
| `src/play_book_studio/ingestion/qdrant_store.py` | Qdrant runtime 제거 |
| `src/play_book_studio/ingestion/official_embedding_qdrant.py` | pgvector 색인 흐름으로 대체 |
| `src/play_book_studio/course/qdrant_course.py` | course 검색 payload 분리 |
| `deploy/openshift/job-qdrant-seed.yaml` | Qdrant seed job 제거 |
| `tests/test_qdrant_indexer.py` | `tests/test_embedding_indexer.py`로 대체 |
| `tests/test_course_qdrant_payload.py` | `tests/test_course_search_payload.py`로 대체 |

## 새 파일

| 파일 | 용도 |
|---|---|
| `.kugnus-plan/lightspeed-call-proof-report.md` | OpenShift Lightspeed API 호출 증명, 코드 위치, 질문 처리 흐름 보고 |
| `.kugnus-plan/lightspeed-pbs-chat-integration.md` | OpenShift Lightspeed PBS Chat 연동 범위와 검증 순서 |
| `src/play_book_studio/integrations/lightspeed.py` | OpenShift Lightspeed API client, auth check, 응답 정규화 |
| `scripts/mock_lightspeed_server.py` | 로컬 통합 smoke용 mock endpoint |
| `tests/test_lightspeed_client.py` | client, auth smoke, integration smoke 검증 |
| `tests/test_lightspeed_viewer.py` | 외부 답변 related link와 Viewer/source-meta 검증 |
| `apps/web/src/pages/workspace/WorkspaceAnswer.test.tsx` | Lightspeed 배지/카드 표시 검증 |
| `db/migrations/0010_pgvector_chunk_embeddings.sql` | `chunk_embeddings`와 pgvector index 생성 |
| `db/migrations/0011_drop_legacy_qdrant_index_entries.sql` | legacy Qdrant index table 제거 |
| `src/play_book_studio/db/embedding_indexer.py` | pending/stale embedding upsert |
| `src/play_book_studio/retrieval/payload.py` | 검색 결과 payload 공통 변환 |
| `src/play_book_studio/evals/answer_viewer_audit.py` | 답변 citation과 Viewer 연결 감사 |
| `src/play_book_studio/evals/rag_foundation_audit.py` | RAG 기초 gate 판정 |
| `corpus/manifests/eval/retrieval_foundation_p0_cases.jsonl` | foundation 평가 케이스 |
| `data/wiki_runtime_books/full_rebuild/monitoring.md` | Viewer fallback 테스트 fixture |

## 포함 대상

| 대상 | 이유 |
|---|---|
| source 변경 | pgvector 전환 런타임 구현 |
| migration | fresh DB와 기존 DB 전환에 필요 |
| deploy 변경 | Qdrant 없는 runtime 보장 |
| tests | 재유입 방지와 수용 기준 검증 |
| `.kugnus-plan/*.md` | 판단 근거와 다음 작업 경계 |

## 제외 대상

| 대상 | 이유 |
|---|---|
| `.kugnus-plan/rag-foundation/*.json` | 상세 chunk preview 포함 가능 |
| Docker volume | 로컬 실행 상태 |
| build output | 재생성 가능 |
| local endpoint 값 | 환경 의존 정보 |
| local secret/token | 민감정보 |

## 검증 기준

| 검증 | 현재 결과 |
|---|---|
| Lightspeed 핵심 Python 테스트 | `37 passed` |
| WorkspaceAnswer Web test | `2 passed` |
| Web build | pass |
| `git diff --check` | pass |
| local runtime | `app`, `postgres`, `web` healthy |
| Lightspeed runtime | 실제 endpoint 설정 상태, `configured=true` |
| Lightspeed chat smoke | `answer_source=lightspeed_with_pbs_rag`, `external_answer_status=used`, Viewer path 생성 |
| Lightspeed Viewer API | `200`, code block 렌더링, raw bold marker 없음 |
