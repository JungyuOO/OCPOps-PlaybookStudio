# pgvector 수용 기준 점검

## 기준 상태

| 항목 | 값 |
|---|---|
| branch | `dev` |
| base head | `f2fb312` |
| runtime service | `postgres`, `app`, `web` |
| vector backend | `pgvector` |
| Qdrant runtime | 없음 |

## 요구사항 점검

| 요구사항 | 증거 | 판정 |
|---|---|---|
| PostgreSQL에 `chunk_embeddings` 테이블 추가 | `db/migrations/0010_pgvector_chunk_embeddings.sql` | pass |
| `chunk_id`, `model`, `embedding vector(1024)`, hash, timestamp 보유 | `0010_pgvector_chunk_embeddings.sql` column 정의 | pass |
| `chunk_id + model` unique | `PRIMARY KEY (chunk_id, model)` | pass |
| HNSW cosine index 생성 | `idx_chunk_embeddings_embedding_hnsw` 확인 | pass |
| 기존 `document_chunks`는 원문 chunk 테이블로 유지 | migration이 `document_chunks`를 삭제/대체하지 않음 | pass |
| Qdrant 검색 경로 제거 | `src/play_book_studio/retrieval/vector.py` pgvector SQL 검색 | pass |
| 검색 결과는 기존 hit 형식 유지 | `RetrievalHit` 기반 테스트 전체 통과 | pass |
| scope filter를 검색 단계에서 적용 | source scope gate `hit@1=1.0` | pass |
| pending/stale embedding 관리 | `src/play_book_studio/db/embedding_indexer.py` | pass |
| stale embedding 0 | `.kugnus-plan/rag-foundation/05-go-no-go.md` | pass |
| Qdrant service 제거 | `docker-compose.yml`, `deploy/**` active runtime | pass |
| Qdrant seed job 제거 | `deploy/openshift/job-qdrant-seed.yaml` 삭제 | pass |
| legacy readiness 제거 | `/api/health`가 `chunk_embeddings` 기준 | pass |
| Qdrant 없이 health ready | `docker compose ps`, `/api/health` | pass |
| answer citation Viewer 연결 | answer/viewer audit `8 checks pass` | pass |
| RAG foundation 품질 | foundation gate `13/13 pass`, `decision=go` | pass |

## DB 확인

| 확인 | 결과 |
|---|---|
| `chunk_embeddings` table | 있음 |
| `qdrant_index_entries` table | 없음 |
| indexes | `chunk_embeddings_pkey`, `idx_chunk_embeddings_embedding_hnsw`, `idx_chunk_embeddings_model`, `idx_chunk_embeddings_text_hash` |
| indexable chunks | `27184` |
| embedding rows | `27184` |
| missing embeddings | `0` |
| stale embeddings | `0` |
| vector dimension | `1024` |

## 검증 결과

| 검증 | 결과 |
|---|---|
| Python 전체 테스트 | `568 passed, 1 skipped` |
| Web test | `16 passed` |
| Web build | pass |
| Answer / Viewer audit | pass |
| RAG foundation audit | `decision=go` |

## 남은 기록성 참조

| 위치 | 처리 |
|---|---|
| `db/migrations/0001_ingestion_foundation.sql` | 과거 migration 이력으로 유지 |
| `db/migrations/0009_qdrant_payload_contract.sql` | 과거 migration 이력으로 유지 |
| `spec/**` | 과거 작업 기록으로 유지 |
| `tests/test_deploy_seed_commands.py` | Qdrant active runtime 재유입 방지 |
