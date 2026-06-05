# 변경 파일 묶음

## 기준

| 항목 | 값 |
|---|---|
| branch | `dev` |
| base head | `f2fb312` |
| 목적 | PostgreSQL pgvector 전환, RAG 기초 안정화, 업로드 실패 기록 정리 |
| 실행 서비스 | `postgres`, `app`, `web` |
| 제외 서비스 | Qdrant |

전체 파일 목록은 `git diff --name-status`와 `git ls-files --others --exclude-standard`로 확인한다.
이 문서는 변경 목적을 설명하기 위한 영역별 묶음이다.

## 변경 묶음

| 영역 | 대표 파일 |
|---|---|
| 환경/설정 | `.env.production.example`, `.gitignore`, `src/play_book_studio/config/settings.py`, `src/play_book_studio/config/validation.py` |
| DB migration | `db/migrations/0010_pgvector_chunk_embeddings.sql`, `db/migrations/0011_drop_legacy_qdrant_index_entries.sql` |
| DB 상태 확인 | `src/play_book_studio/db/corpus_status.py`, `src/play_book_studio/db/document_repository.py`, `src/play_book_studio/db/embedding_indexer.py` |
| 검색 | `src/play_book_studio/retrieval/vector.py`, `src/play_book_studio/retrieval/payload.py`, `src/play_book_studio/retrieval/retriever_search.py`, `src/play_book_studio/retrieval/retriever_pipeline.py` |
| 검색 신호 | `src/play_book_studio/retrieval/query_signal_pipeline.py`, `src/play_book_studio/retrieval/query_understanding.py`, `src/play_book_studio/retrieval/intent_profile.py` |
| course 검색 | `src/play_book_studio/course/chunk_loader.py`, `src/play_book_studio/course/search_payload.py`, `src/play_book_studio/course/build_index.py` |
| ingestion | `src/play_book_studio/ingestion/corpus_import.py`, `src/play_book_studio/ingestion/kmsc_course_import.py`, `src/play_book_studio/ingestion/pipeline.py`, `src/play_book_studio/ingestion/runtime_catalog_library.py` |
| HTTP/API | `src/play_book_studio/http/course_api.py`, `src/play_book_studio/http/runtime_report.py`, `src/play_book_studio/http/server_routes_viewer.py`, `src/play_book_studio/http/upload_api.py` |
| answer | `src/play_book_studio/answering/context.py` |
| evaluation | `src/play_book_studio/evals/answer_viewer_audit.py`, `src/play_book_studio/evals/rag_foundation_audit.py`, `src/play_book_studio/evals/chunk_quality_audit.py` |
| deploy/runtime | `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `deploy/docker-compose.image.yml`, `deploy/openshift/core.yaml`, `deploy/openshift/kustomization.yaml` |
| web | `apps/web/src/lib/runtimeApi.ts`, `apps/web/src/pages/PlaybookLibraryPage.tsx` |
| CLI | `src/play_book_studio/cli.py` |
| docs | `README.md`, `corpus/README.md`, `deploy/DEPLOY.md`, `deploy/openshift/README.md`, `.kugnus-plan/*.md`, `.kugnus-plan/rag-foundation/*.md` |
| tests | `tests/test_embedding_indexer.py`, `tests/test_course_search_payload.py`, `tests/test_vector_retriever.py`, `tests/test_corpus_status.py`, `tests/test_deploy_seed_commands.py` |

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
| Python 전체 테스트 | `568 passed`, `1 skipped` |
| Web test | `16 passed` |
| Web build | pass |
| RAG foundation | `13/13 pass`, `decision=go` |
| answer / Viewer audit | `8/8 pass` |
| host route | API/Web 접근 OK |
