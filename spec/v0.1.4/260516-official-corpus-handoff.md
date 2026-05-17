# 260516 Official Corpus Handoff

## 작성 목적

본 문서는 v0.1.4 협의 내용을 기준으로 2026-05-16에 진행한 official corpus 청킹/임베딩 작업의 변경 범위와 후속 인계 사항을 정리한다.

작업자는 처음에는 `dev` 브랜치 기준으로 파일을 수정했으나, 최종 인계 대상 브랜치가 `feat/dev-ui`임을 확인한 뒤 변경분을 `feat/dev-ui`로 옮겼다. merge는 수행하지 않았다. 후속 검토자는 `feat/dev-ui`의 변경 파일과 산출물을 확인한 뒤 필요한 범위만 선별하여 반영하면 된다.

## 기준

- target branch: `feat/dev-ui`
- target head before worktree changes: `87cec00`
- initial working branch used by mistake: `dev`
- initial dev head: `be15cff`
- 기준 문서:
  - `spec/v0.1.4/planner.md`
  - `spec/v0.1.4/db-corpus-schema.md`
  - `spec/v0.1.4/db-parsing-schema.md`
- 대상 corpus:
  - `corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`
- Qdrant collection:
  - `openshift_docs`

## 이번 작업의 결론

v0.1.4 계약 중 official corpus의 청킹/임베딩 텍스트 계층 정리는 완료했다.

완료한 범위는 다음과 같다.

- 원본 `chunks.jsonl`은 덮어쓰지 않고 보존.
- 4계층 텍스트를 분리:
  - `raw_text`: 원본 보존.
  - `markdown`: 사람/뷰어 표시용.
  - `normalized_text`: BM25/keyword 검색용.
  - `embedding_text`: Qdrant 벡터 임베딩용.
- 목차와 문서 경로는 본문에 섞지 않고 metadata/payload 필드로 보존.
- Qdrant에는 raw 원문을 싣지 않고 `embedding_text` 기준으로 재적재.
- 공식 문서 Qdrant payload 전체 감사 통과.

이번 작업에 포함하지 않은 범위는 다음과 같다.

- 신규 `corpus_*` SQL 테이블 마이그레이션.
- `corpus_chunk_segments`, `corpus_chunk_commands`, `corpus_chunk_refs` 생성.
- Intent Agent, metadata pre-filter, rank scoring 런타임 적용.
- 챗봇 답변 카드 렌더링/코드블록 표시 로직 변경.
- BM25 loader의 `normalized_text` 전환.

위 항목들은 v0.1.4 문서상 후속 구현 또는 v0.1.5 단계에 해당한다.

## 변경 파일 목록

### 코드 변경

`src/play_book_studio/config/corpus_paths.py`

- official embedding projection 기본 경로 추가.
- official text layers 기본 경로 추가.

`src/play_book_studio/ingestion/official_gold_import.py`

- official source chunk에서 4계층 텍스트를 생성하는 로직 추가.
- `embedding_text` 생성 시 내부 마커, 코드펜스, HTML anchor, viewer path, percent encoded text, 깨진 placeholder를 제거.
- 명령어 검색 신호에 필요한 `$`, `-n`, `--option`, 경로, 리소스명 등은 `embedding_text`에서 보존.
- `normalized_text` 생성 시 BM25/keyword용 flat text로 정규화.
- 목차/section path/source URL/viewer path를 본문이 아니라 metadata 필드로 유지.
- navigation-only, empty embedding, exact duplicate, contained overlap 청크를 억제하는 projection 정책 추가.
- DB import 시 `metadata.text_layers`와 `metadata.normalized_text`를 저장하도록 보강.

`src/play_book_studio/ingestion/official_embedding_qdrant.py`

- 신규 파일.
- `embedding_chunks.jsonl`을 읽어 Qdrant 후보를 생성.
- 회사 임베더를 사용해 official embedding chunk를 벡터화.
- Qdrant `openshift_docs`에 upsert.
- projection에서 제외된 source chunk point 삭제 옵션 추가.
- DB `document_chunks`의 `markdown`, `embedding_text`, `metadata.text_layers`, `metadata.normalized_text` sync 기능 추가.
- `qdrant_index_entries` 기록 기능 추가.

`src/play_book_studio/db/qdrant_indexer.py`

- Qdrant payload에 `payload_version=1` 추가.
- `payload.text`를 `document_chunks.embedding_text` 기준으로 고정.
- `text_fields.embedding_text`, `text_fields.normalized_text` payload 계약 반영.
- Qdrant payload의 `chunk_metadata`에서 `raw_text`와 `text_layers.raw_text`가 유출되지 않도록 필터링.

`src/play_book_studio/cli.py`

- `official-gold-import`에 다음 옵션 추가:
  - `--embedding-chunks-path`
  - `--text-layers-path`
- 신규 command 추가:
  - `official-embedding-qdrant-upsert`
- 해당 command에서 DB sync, Qdrant upsert, skipped point delete, `qdrant_index_entries` 기록을 수행.
- Docker 컨테이너 내부에서도 `DATABASE_URL=...@postgres:5432/...`를 그대로 사용하도록 DB sync 경로를 정리.

`tests/test_official_gold_import.py`

- embedding projection 생성 검증 추가.
- 4계층 text layer export 검증 추가.
- navigation-only/empty chunk skip 검증 추가.
- placeholder artifact repair 검증 추가.
- Qdrant 후보 payload에서 raw text가 제외되는지 검증 추가.

`docker-compose.yml`

- `official-corpus-seed`를 v0.1.4 projection 생성 후 Qdrant/DB upsert를 수행하는 흐름으로 변경.
- 기존 `official-gold-import --index` 경로가 official Qdrant 적재를 담당하지 않도록 정리.

`deploy/docker-compose.prod.yml`

- production compose seed도 동일한 v0.1.4 official corpus seed 흐름으로 변경.
- `corpus`는 read-only mount이므로 generated JSONL은 `/app/tmp/official_corpus_v014/` 아래에 생성.
- seed profile config 검증을 막던 누락 volume 선언(`app_artifacts`, `app_storage`, `app_reports`)을 보강.

`deploy/docker-compose.image.yml`

- image 기반 seed도 동일한 v0.1.4 official corpus seed 흐름으로 변경.

`deploy/openshift/job-official-corpus-seed.yaml`

- OpenShift official corpus seed Job도 `official-gold-import` 후 `official-embedding-qdrant-upsert`를 실행하도록 변경.

### 새로 생성한 산출물

`corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/text_layers.jsonl`

- 4계층 검수용 JSONL.
- line count: `27,907`
- size: 약 `104.05 MiB`
- 각 row에 `raw_text`, `markdown`, `normalized_text`, `embedding_text` 포함.
- Qdrant에는 싣지 않는 raw 원문을 로컬에서 검수할 수 있게 보존.
- GitHub 일반 파일 크기 제한에 걸릴 수 있으므로 Git push 대상에서는 제외하고, 필요 시 재생성하는 로컬 산출물로 취급한다.

`corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl`

- Qdrant 적재용 official embedding projection JSONL.
- line count: `25,910`
- size: 약 `73.94 MiB`
- `embedding_text`, `normalized_text`, section/toc/source metadata 포함.
- 대용량 재생성 가능 산출물이므로 Git push 대상에서는 제외하고, 필요 시 재생성한다.

`spec/v0.1.4/260516-official-corpus-chunking.md`

- 작업 상세 기록.
- 품질 게이트 결과.
- 기존 파일을 유지한 이유.
- 후속 단계와 책임 구분.
- 재실행 명령과 샘플 조회 명령.

본 handoff 문서:

- `spec/v0.1.4/260516-official-corpus-handoff.md`

### Push 대상에서 제외한 로컬 산출물

다음 경로는 `.gitignore`에 추가했다.

- `corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/`
- `corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/`

이유:

- 두 파일은 source `chunks.jsonl`과 코드로 재생성 가능한 generated artifact다.
- `text_layers.jsonl`은 약 104MiB로 GitHub 일반 push 제한에 걸릴 수 있다.
- 리뷰/인계에는 JSONL 전체보다 본 handoff 문서와 재실행 명령이 더 적합하다.
- 실제 Qdrant/DB 반영은 로컬에서 이미 수행됐고, 후속 작업자는 필요한 경우 재생성 명령으로 동일 산출물을 만들 수 있다.

### 파일로 남지 않는 로컬 반영 상태

다음 항목은 git diff에는 나타나지 않지만 로컬 DB/Qdrant에 반영된 상태다.

- DB `document_chunks`
  - official rows: `27,907`
  - `embedding_text` 반영 rows: `25,910`
  - suppressed rows: `1,997`
  - `metadata.text_layers` 반영 rows: `27,907`
- Qdrant `openshift_docs`
  - official docs points: `25,910`
  - `payload_version=1`
  - `payload.text == text_fields.embedding_text`
  - `raw_text` payload 미포함
- DB `qdrant_index_entries`
  - official index entries: `25,910`
  - `payload_version=1`

## Docker Compose 반영 상태

이제 `official-corpus-seed`를 실행하면 v0.1.4 작업이 한 번에 반영되도록 연결했다.

실행 흐름:

1. `official-gold-import`
   - 원본 `chunks.jsonl`을 읽는다.
   - DB `document_chunks`를 갱신한다.
   - `/app/tmp/official_corpus_v014/embedding_chunks.jsonl`을 생성한다.
   - `/app/tmp/official_corpus_v014/text_layers.jsonl`을 생성한다.
2. `official-embedding-qdrant-upsert`
   - 위에서 만든 `embedding_chunks.jsonl`을 읽는다.
   - DB `document_chunks.markdown`, `document_chunks.embedding_text`, `metadata.text_layers`, `metadata.normalized_text`를 sync한다.
   - Qdrant `${QDRANT_COLLECTION:-openshift_docs}`에 v0.1.4 embedding payload를 upsert한다.
   - projection에서 제외된 official point는 `--delete-skipped`로 정리한다.
   - `qdrant_index_entries`를 기록한다.

반영된 파일:

- `docker-compose.yml`
- `deploy/docker-compose.prod.yml`
- `deploy/docker-compose.image.yml`
- `deploy/openshift/job-official-corpus-seed.yaml`

따라서 compose seed 기준으로는 더 이상 예전 `official-gold-import --index` 경로가 official Qdrant 적재를 담당하지 않는다.

### 다음 작업자용 실행 요약

로컬 compose 기준 실행:

```powershell
docker compose --profile seed run --rm official-corpus-seed
```

production compose 파일 기준 실행:

```powershell
docker compose -f deploy/docker-compose.prod.yml --profile seed run --rm official-corpus-seed
```

image compose 파일 기준 실행:

```powershell
$env:APP_ENV_FILE='../.env'
docker compose -f deploy/docker-compose.image.yml --profile seed run --rm official-corpus-seed
```

참고:

- `deploy/docker-compose.prod.yml`은 기본적으로 repo root의 `.env.production`을 기대한다.
- `deploy/docker-compose.image.yml`은 compose 파일 위치 기준 env file을 읽으므로, repo root `.env`를 쓰려면 위처럼 `APP_ENV_FILE='../.env'`를 지정한다.
- 운영에서 shadow collection을 쓰려면 실행 전에 `QDRANT_COLLECTION`을 원하는 collection 이름으로 지정한다.
- generated JSONL은 컨테이너 내부 `/app/tmp/official_corpus_v014/`에 생성된다. 원본 `corpus/.../chunks.jsonl`은 덮어쓰지 않는다.

compose seed 완료 판단 기준:

| 확인 항목 | 기대값 |
| --- | --- |
| seed 명령 | `official-gold-import` 후 `official-embedding-qdrant-upsert` 실행 |
| Qdrant official points | `25,910` |
| DB official `document_chunks` | `27,907` |
| DB `metadata.text_layers` rows | `27,907` |
| DB `qdrant_index_entries` official rows | `25,910` |
| Qdrant `payload.text == text_fields.embedding_text` mismatch | `0` |
| Qdrant `raw_text` payload 유출 | `0` |

주의:

- `qdrant-seed`는 KMSC/course 계열 upsert용이며, 이번 official corpus v0.1.4 반영 경로가 아니다.
- `bm25_corpus.jsonl`은 아직 삭제하지 않는다. BM25 loader가 `normalized_text`를 읽도록 전환된 뒤 제거 여부를 결정한다.
- compose config 검증은 다음 명령으로 확인했다.

```powershell
docker compose --profile seed config
$env:APP_ENV_FILE='../.env'
docker compose -f deploy/docker-compose.prod.yml --profile seed config
docker compose -f deploy/docker-compose.image.yml --profile seed config
```

## 유지한 기존 파일과 이유

`corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`

- official corpus의 원본 source chunk.
- projection을 다시 만들 때 필요한 기준 입력이므로 삭제하거나 덮어쓰지 않았다.

`corpus/sources/official/imported-gold/gold_corpus_ko/bm25_corpus.jsonl`

- 기존 BM25 fallback 파일.
- 이번 작업으로 `normalized_text`는 준비됐지만 BM25 loader 전환은 아직 하지 않았다.
- loader 전환 전 삭제하면 fallback 검색 경로가 깨질 수 있어 유지했다.

`corpus/sources/official/imported-gold/gold_manualbook_ko/*`

- manual book/viewer 계열 산출물로 추정된다.
- Qdrant embedding projection 입력은 아니지만 표시/탐색 계층에서 참조될 수 있어 삭제하지 않았다.

`corpus/sources/official/imported-gold/silver_ko/*`

- gold 이전 단계의 중간 또는 upstream 자료.
- 재생성/검증 경로 추적에 필요할 수 있어 삭제하지 않았다.

## 검증 결과

Qdrant official docs 전체 감사:

| 항목 | 결과 |
| --- | ---: |
| official docs points | 25,910 |
| `payload_version != 1` | 0 |
| `text_fields` 누락 | 0 |
| `payload.text != text_fields.embedding_text` | 0 |
| `raw_text` payload 유출 | 0 |
| empty text | 0 |
| newline/tab | 0 |
| `[CODE]`, `[/CODE]`, `[TABLE]`, `[/TABLE]` | 0 |
| fenced code marker | 0 |
| `<a href` anchor | 0 |
| viewer path in text | 0 |
| percent encoded text | 0 |
| Arabic character contamination | 0 |
| quote/backslash contamination | 0 |
| vector dim mismatch | 0 |
| vector NaN/Inf | 0 |

DB 검증:

| 항목 | 결과 |
| --- | ---: |
| official `document_chunks` rows | 27,907 |
| embedding rows | 25,910 |
| suppressed rows | 1,997 |
| `metadata.text_layers` rows | 27,907 |
| official `qdrant_index_entries` | 25,910 |
| official `qdrant_index_entries.payload_version=1` | 25,910 |

코드 검증:

- `compileall`: 통과.
- `git diff --check`: 통과.
- 현재 환경에 `pytest`가 설치되어 있지 않아 pytest runner는 실행하지 못했다.
- 대신 `tests/test_official_gold_import.py`, `tests/test_qdrant_indexer.py`의 `test_*` 함수를 직접 호출해 `23 passed`.

퇴근 전 retrieval smoke:

- 실행 파일: `corpus/manifests/eval/retrieval_smoke_queries.jsonl`
- 결과 파일: `reports/official_corpus_v014_260516_preleave_retrieval_smoke.json`
- case count: `5`
- `hit@1`: `0.8`
- `hit@3`: `1.0`
- `hit@5`: `1.0`
- `warning_free_rate`: `1.0`
- 관찰: `머신 설정은 어떤 Operator가 관리해?` 케이스는 top-1이 `disconnected_environments`, top-3에 `operators`가 들어왔다. 이는 청크 payload 오염보다는 후속 rank/rerank 조정 포인트로 본다.

## 확인된 이슈와 해석

초기 Qdrant scroll 조회에서 `text_fields=null` 또는 서로 다른 청크가 섞인 것처럼 보인 사례가 있었다.

확인 결과:

- `text_fields=null`은 official docs만 조회하지 않고 전체 collection을 조회하면서 `study_docs`, `uploads`, `applied_playbook` point가 함께 나온 영향이다.
- 이후 `source.corpus_scope=official_docs` 필터를 걸고 재조회했을 때 official payload는 정상으로 확인됐다.
- Python `json.dumps`가 출력한 dict에서는 동일 객체 안에 같은 key가 두 번 보존될 수 없으므로, `embedding_text`가 중복 key처럼 보인 사례는 긴 터미널 출력 복사/스크롤 과정에서 서로 다른 출력 일부가 붙은 artifact로 판단한다.
- 전체 official docs 25,910건 감사에서 payload contamination은 재현되지 않았다.

## BM25 관련 판단

BM25는 토큰 매칭 기반 검색이므로, 표시용 `markdown`이나 벡터용 `embedding_text`보다 검색 전용 `normalized_text`를 보는 것이 더 자연스럽다.

다만 품질 개선 포인트는 `bm25_corpus.jsonl` 삭제가 아니라 BM25 loader의 입력 소스를 `normalized_text`로 전환하는 것이다.

권장 순서:

1. BM25 loader가 DB 또는 `embedding_chunks.jsonl`의 `normalized_text`를 tokenize하도록 수정.
2. BM25 smoke query로 기존 결과와 비교.
3. 런타임에서 `bm25_corpus.jsonl` 의존이 사라졌는지 확인.
4. 이후 `bm25_corpus.jsonl` 삭제 또는 deprecated 처리 결정.

## 후속 작업 제안

다음 작업은 이번 branch에서 반드시 이어서 해야 하는 작업이 아니라, 후속 담당자가 범위를 정해 진행하면 되는 항목이다.

1. BM25 loader를 `normalized_text` 기준으로 전환.
2. v0.1.5 SQL migration에서 `corpus_documents`, `corpus_chunks`, `corpus_chunk_segments`, `corpus_chunk_commands`, `corpus_chunk_refs`, `corpus_question_candidates` 생성.
3. `corpus_chunk_segments` 기반 답변 카드 렌더링 구현.
4. `corpus_chunk_commands` 기반 command template, placeholder, env_scope 구조화.
5. Intent Agent와 metadata 기반 pre-filter/rank scoring 연결.
6. 챗봇 smoke/evaluation set으로 retrieval + answer 품질 회귀 검증.

## 검토자가 확인하면 좋은 사항

- `embedding_chunks.jsonl`의 정제 수준이 검색 품질 관점에서 적절한지.
- `normalized_text`에서 기호를 제거하는 정책이 BM25 요구와 맞는지.
- Qdrant payload의 `source`, `classification`, `chunk`, `search_signals`, `text_fields` shape이 후속 metadata/rank 작업과 충돌하지 않는지.
- BM25 loader 전환을 이번 변경에 포함할지, 별도 retrieval 변경으로 분리할지.
- `openshift_docs`를 직접 갱신한 현재 방식과 shadow collection 검증 방식 중 어떤 운영 절차를 표준으로 둘지.
