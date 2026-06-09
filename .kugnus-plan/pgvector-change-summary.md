# pgvector 전환 변경 요약

## 목적

PBS RAG 저장소를 PostgreSQL 중심으로 정리한다.

문서 원문, 검색 scope, embedding 상태, citation, Viewer 연결을 같은 DB 기준으로 확인할 수 있게 한다.

## 변경 전후

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 원문 chunk | PostgreSQL `document_chunks` | 유지 |
| vector 저장 | Qdrant | PostgreSQL `chunk_embeddings` |
| vector 검색 | Qdrant HTTP 검색 | PostgreSQL pgvector SQL 검색 |
| stale 확인 | 별도 index 상태와 payload 비교 | DB hash 기준 확인 |
| readiness | Qdrant index entry 기준 포함 | `chunk_embeddings` 기준 |
| runtime service | postgres, qdrant, app, web | postgres, app, web |

## Migration 10/11

| migration | 역할 | 이유 |
|---|---|---|
| `0010_pgvector_chunk_embeddings.sql` | `chunk_embeddings` 테이블과 pgvector HNSW index 생성 | 문서 chunk의 embedding을 PostgreSQL 안에서 관리 |
| `0011_drop_legacy_qdrant_index_entries.sql` | 기존 `qdrant_index_entries` 테이블 제거 | Qdrant 기준 readiness와 stale 판단 제거 |

`document_chunks`는 원문 chunk 테이블로 유지한다. `chunk_embeddings`는 검색용 embedding, model, hash, timestamp를 별도로 관리한다. 이 구조에서는 원문 chunk와 검색 색인이 같은 DB 안에 있으므로 citation, Viewer, stale embedding 판단을 같은 기준으로 확인할 수 있다.

기존 `0001`, `0009` migration에 Qdrant 관련 이력이 남아 있는 것은 과거 DB 변경 기록이다. 최종 스키마는 `0011` 적용 후 `qdrant_index_entries` 없이 `chunk_embeddings`를 사용한다.

## 주요 변경 파일

| 영역 | 파일 |
|---|---|
| DB migration | `db/migrations/0010_pgvector_chunk_embeddings.sql`, `db/migrations/0011_drop_legacy_qdrant_index_entries.sql` |
| embedding 색인 | `src/play_book_studio/db/embedding_indexer.py` |
| 검색 | `src/play_book_studio/retrieval/vector.py`, `src/play_book_studio/retrieval/payload.py` |
| 상태 확인 | `src/play_book_studio/db/corpus_status.py`, `src/play_book_studio/http/runtime_report.py` |
| 배포 | `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `deploy/openshift/core.yaml` |
| 검증 | `tests/test_embedding_indexer.py`, `tests/test_vector_retriever.py`, `tests/test_corpus_status.py`, `tests/test_deploy_seed_commands.py` |

## 현재 확인값

| 항목 | 값 |
|---|---|
| 실행 서비스 | `app`, `postgres`, `web` |
| indexable chunk | `27184` |
| embedding rows | `27184` |
| missing embedding | `0` |
| stale embedding | `0` |
| vector dimension | `1024` |
| RAG gate | `13/13 pass` |
| source scope gate | `hit@1=1.0` |
| answer/viewer audit | `8 checks pass` |

## 검증 결과

| 검증 | 결과 |
|---|---|
| Python 전체 테스트 | `568 passed, 1 skipped` |
| Web test | `16 passed` |
| Web build | pass |
| `git diff --check` | pass |

## 남은 주의사항

| 항목 | 내용 |
|---|---|
| 과거 migration | `0001`, `0009`에는 기존 Qdrant table 이력이 남아 있음 |
| 과거 spec | `spec/**`에는 이전 구조 설명이 남아 있음 |
| fresh smoke volume | `ocpops_pgvector_fresh_smoke_storage`는 삭제하지 않고 남겨둠 |
| audit output | dev compose에서 `.kugnus-plan`을 `/app/.kugnus-plan`로 mount |
