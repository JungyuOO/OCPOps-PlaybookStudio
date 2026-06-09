# PostgreSQL pgvector 전환 기록

## 현재 상태

| 항목 | 상태 |
|---|---|
| Runtime vector backend | `pgvector` |
| 실행 서비스 | `postgres`, `app`, `web` |
| Qdrant runtime service | 없음 |
| Qdrant 환경변수 | 활성 설정에서 없음 |
| Qdrant 소스/테스트 파일 | 제거 |
| fresh DB migration | 통과 |
| RAG gate | `13/13 pass` |
| Python test suite | `568 passed, 1 skipped` |
| Web test suite | `16 passed` |
| Web production build | 통과 |

## 변경 범위

| 영역 | 변경 |
|---|---|
| DB | `chunk_embeddings` 추가, 기존 chunk 원문은 `document_chunks` 유지 |
| Migration | `0010_pgvector_chunk_embeddings`, `0011_drop_legacy_qdrant_index_entries` 추가 |
| 색인 | pending/stale chunk를 PostgreSQL `chunk_embeddings`에 upsert |
| 검색 | Qdrant HTTP 검색을 PostgreSQL vector similarity search로 교체 |
| 필터 | owner, repository, active document, source scope를 SQL 조건으로 적용 |
| 상태 확인 | Qdrant point 수 대신 `chunk_embeddings` row, stale, model, dimension 확인 |
| 배포 | compose/OpenShift에서 Qdrant service, seed job, env 제거 |
| 화면 | 업로드/라이브러리 문구를 벡터 인덱싱/pgvector 기준으로 변경 |

## 현재 검증값

| 항목 | 값 |
|---|---|
| `indexable_chunks` | `27184` |
| `chunk_embeddings` | `27184` |
| missing embedding | `0` |
| stale embedding | `0` |
| vector dimension | `1024` |
| HNSW index | 있음 |
| legacy Qdrant table | 없음 |
| source count | official `29`, study `9`, upload `33` |
| chunk count | official `27907`, study `523`, upload `780` |

## 검증 명령

```powershell
docker compose ps
curl.exe -s http://127.0.0.1:8765/api/health
npm --prefix apps/web run build
npm --prefix apps/web test
npm --prefix apps/web exec vitest run src/routing/handoff.test.ts
$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m pytest tests/test_db_migrations.py tests/test_corpus_status.py tests/test_vector_retriever.py tests/test_retrieval_access_scope.py tests/test_chat_latency_logging.py tests/test_runtime_seed_inputs.py tests/test_official_gold_import.py tests/test_embedding_indexer.py tests/test_course_search_payload.py tests/test_kmsc_beginner_narrative.py tests/test_upload_ingest_cli.py tests/test_upload_api.py tests/test_uploaded_viewer_source_meta.py tests/test_chunk_quality_audit.py tests/test_chunk_runtime_enrichment.py tests/test_chunk_hydration.py tests/test_retrieval_plan_expansion.py tests/test_retriever_plan.py tests/test_deploy_seed_commands.py -q
$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m pytest -q
docker compose exec -T app python -m play_book_studio.evals.answer_viewer_audit --base-url http://127.0.0.1:8765 --output-dir /app/.kugnus-plan/rag-foundation
docker compose exec -T app python -m play_book_studio.evals.rag_foundation_audit --root-dir /app --output-dir /app/.kugnus-plan/rag-foundation --answer-viewer-check-path /app/.kugnus-plan/rag-foundation/answer_viewer_check.json
```

`rag_foundation_audit`는 compose 내부 DB hostname을 사용하므로 app 컨테이너 안에서 실행한다.
Dev compose는 `.kugnus-plan`을 `/app/.kugnus-plan`에 mount하므로 audit 결과가 host 작업 폴더에 바로 남는다.

## Fresh DB 확인

| 항목 | 값 |
|---|---|
| project | `pbs-pgvector-fresh-smoke` |
| volume | `ocpops_pgvector_fresh_smoke_storage` |
| port | `127.0.0.1:55432` |
| migration result | `12 applied` |
| final schema | `chunk_embeddings` 있음, `qdrant_index_entries` 없음 |

Fresh smoke 컨테이너와 네트워크는 내렸고, 전용 볼륨은 남겨두었다.

## 남아 있는 이력

| 위치 | 이유 |
|---|---|
| `db/migrations/0001_ingestion_foundation.sql` | 과거 migration 이력 |
| `db/migrations/0009_qdrant_payload_contract.sql` | 과거 migration 이력 |
| `db/migrations/0011_drop_legacy_qdrant_index_entries.sql` | legacy table 제거 migration |
| `spec/**` | 과거 작업 기록 |
| `tests/test_deploy_seed_commands.py` | Qdrant 재유입 방지 검사 |

## 완료 기준

| 기준 | 판정 |
|---|---|
| Qdrant 없이 PBS 실행 | pass |
| Qdrant 없이 health ready | pass |
| indexable chunk 수와 embedding row 수 일치 | pass |
| stale embedding 0 | pass |
| RAG foundation `hit@5 1.0` | pass |
| source scope `hit@1 1.0` | pass |
| answer citation Viewer 연결 | pass |
| fresh DB migration 최종 상태 | pass |
