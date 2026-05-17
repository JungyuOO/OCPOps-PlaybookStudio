# 260516 Official Corpus Chunking Worklog

## 목적

v0.1.4 협의 문서의 방향에 맞춰 official corpus의 청크 텍스트를 다음처럼 분리했다.

- `raw_text`: 원본 보존용. 기존 source `chunks.jsonl`의 `text`를 그대로 남긴다.
- `markdown`: 사람/뷰어 표시용. 코드블록과 표시는 사람이 읽을 수 있는 형태로 둔다.
- `embedding_text`: Qdrant 벡터 임베딩용. 목차, 내부 마커, URL, 깨진 placeholder는 제거하되 명령어, 옵션, YAML/JSON 구조, 리소스명, 에러명은 검색 신호로 보존한다.
- `normalized_text`: BM25/keyword fallback용. 개행, 표 구분자, 표시용 기호를 줄인 flat 텍스트로 둔다.
- 목차와 문서 경로는 본문에 섞지 않고 `book_title`, `chapter`, `section`, `section_path`, `toc_path`, `breadcrumb`, `source_url`, `viewer_path` 같은 컬럼/payload 필드로 보존한다.

이번 작업은 v0.1.4의 전체 schema migration 구현이 아니라, 기존 `document_chunks`/Qdrant 호환 구조 안에서 text layer와 Qdrant projection을 먼저 정리한 작업이다.

## 기준 문서

- `spec/v0.1.4/planner.md`
- `spec/v0.1.4/db-corpus-schema.md`
- `spec/v0.1.4/db-parsing-schema.md`

## 현재 ref

- target branch: `feat/dev-ui`
- target head before worktree changes: `87cec00`
- initial working branch used by mistake: `dev`
- initial dev head: `be15cff`
- 작업 기준: 기존 `document_chunks` 호환 구조 유지
- Qdrant collection: `openshift_docs`

## 변경된 산출물

### 새로 생성한 파일

`corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/text_layers.jsonl`

역할:
- v0.1.4 4계층 계약 검수용 산출물.
- 각 row에서 `raw_text`, `markdown`, `normalized_text`, `embedding_text`를 한 번에 확인한다.
- Qdrant에 raw 원문을 싣지 않더라도, 로컬과 DB에서는 4계층을 추적할 수 있게 한다.
- 대용량 재생성 가능 산출물이므로 Git push 대상에서는 제외한다.

현재 상태:
- input source chunks: `27,907`
- text layer rows: `27,907`
- required layer 누락: `0`
- empty `raw_text`: `0`
- empty `markdown`: `0`

`corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl`

역할:
- Qdrant 적재용 official embedding projection.
- 원본 `chunks.jsonl`을 직접 덮어쓰지 않고, 임베딩/검색용 텍스트만 별도 산출한다.
- 각 row에는 `embedding_text`, `normalized_text`, 목차/경로 메타데이터가 같이 들어간다.
- 대용량 재생성 가능 산출물이므로 Git push 대상에서는 제외한다.

현재 상태:
- input source chunks: `27,907`
- embedding rows: `25,910`
- suppressed rows: `1,997`
  - empty embedding: `89`
  - exact duplicate: `484`
  - contained overlap: `1,424`

### 수정한 코드

- `src/play_book_studio/config/corpus_paths.py`
  - `OFFICIAL_GOLD_EMBEDDING_CHUNKS_PATH` 추가.
  - `OFFICIAL_GOLD_TEXT_LAYERS_PATH` 추가.

- `src/play_book_studio/ingestion/official_gold_import.py`
  - official embedding projection 생성 로직 추가.
  - `embedding_text` 정제 로직 추가.
  - `normalized_text` flat 정규화 로직 추가.
  - 목차/경로 컬럼을 embedding projection row에 포함.
  - 기존 DB import 시 `embedding_text`와 metadata text layer를 분리 저장하도록 보강.

- `src/play_book_studio/ingestion/official_embedding_qdrant.py`
  - embedding projection JSONL을 읽어 Qdrant 후보를 생성.
  - Qdrant upsert, skipped point 삭제, DB sync를 수행.
  - 품질 게이트를 추가.

- `src/play_book_studio/db/qdrant_indexer.py`
  - Qdrant payload에서 `raw_text` 유출 방지.
  - `payload.text`는 표시/답변용 `markdown`으로 유지.
  - `text_fields.embedding_text`를 벡터 입력용 필드로 분리.
  - `text_fields.normalized_text`를 별도 BM25/keyword용 필드로 보존.

- `src/play_book_studio/cli.py`
  - `official-gold-import --embedding-chunks-path` 추가.
  - `official-gold-import --text-layers-path` 추가.
  - `official-embedding-qdrant-upsert` 추가.
  - Docker 컨테이너 내부의 `DATABASE_URL=...@postgres:5432/...`를 그대로 사용하도록 DB sync 경로를 정리.

- `tests/test_official_gold_import.py`
  - embedding projection 생성, 목차 컬럼화, placeholder repair, Qdrant 후보 생성 검증 추가.

- `docker-compose.yml`
  - `official-corpus-seed`가 v0.1.4 projection 생성 후 Qdrant/DB upsert를 실행하도록 변경.

- `deploy/docker-compose.prod.yml`
  - production compose seed도 동일한 v0.1.4 official corpus seed 흐름으로 변경.
  - seed profile config 검증을 막던 누락 volume 선언을 보강.

- `deploy/docker-compose.image.yml`
  - image 기반 compose seed도 동일한 v0.1.4 official corpus seed 흐름으로 변경.

- `deploy/openshift/job-official-corpus-seed.yaml`
  - OpenShift official corpus seed Job도 동일한 v0.1.4 official corpus seed 흐름으로 변경.

## Docker Compose Seed 반영

`official-corpus-seed` 실행 시 다음 순서로 동작하게 했다.

1. `official-gold-import`
   - 원본 `chunks.jsonl`을 읽어 DB import를 수행한다.
   - `/app/tmp/official_corpus_v014/embedding_chunks.jsonl`을 생성한다.
   - `/app/tmp/official_corpus_v014/text_layers.jsonl`을 생성한다.
2. `official-embedding-qdrant-upsert`
   - 생성된 `embedding_chunks.jsonl` 기준으로 DB text layer sync를 수행한다.
   - Qdrant `${QDRANT_COLLECTION:-openshift_docs}`에 upsert한다.
   - projection에서 제외된 point를 정리한다.
   - `qdrant_index_entries`를 기록한다.

즉, compose seed를 다시 실행하면 원본 corpus 파일을 덮어쓰지 않고도 v0.1.4 청킹/임베딩 projection이 DB와 Qdrant에 반영된다.

실행 명령:

```powershell
docker compose --profile seed run --rm official-corpus-seed
```

완료 후 기대 상태:

- Qdrant official docs points: `25,910`
- DB official `document_chunks`: `27,907`
- DB `metadata.text_layers` rows: `27,907`
- official `qdrant_index_entries`: `25,910`
- Qdrant payload raw text leak: `0`
- Qdrant `text_fields.embedding_text` mismatch: `0`
- Qdrant `payload.text` empty: `0`

주의:

- generated JSONL은 compose 실행 중 `/app/tmp/official_corpus_v014/`에 생성된다.
- source `chunks.jsonl`은 덮어쓰지 않는다.
- `qdrant-seed`는 course/KMSC 쪽 seed이며 official corpus v0.1.4 반영 경로가 아니다.

## 적용 결과

Qdrant/DB 반영 결과:

- Qdrant upsert: `25,910`
- Qdrant skipped point delete: `1,997`
- DB sync updated: `25,910`
- DB sync suppressed: `1,997`
- Qdrant payload overwrite: `25,910` (`payload_version=1` 반영)
- `qdrant_index_entries` official 기록: `25,910`
- `qdrant_index_entries` skipped 삭제: `1,997`

품질 게이트:

| 항목 | 결과 |
| --- | ---: |
| local `text_layers.jsonl` required layer 누락 | 0 |
| local `embedding_chunks.jsonl` empty text | 0 |
| `[CODE]`, `[/CODE]`, `[TABLE]`, `[/TABLE]`, fenced code marker | 0 |
| HTML anchor / docs URL | 0 |
| percent encoded text | 0 |
| broken dot placeholder (`<. ...>`) | 0 |
| HTML angle entity (`&lt;`, `&gt;`) | 0 |
| tab | 0 |
| Arabic character contamination | 0 |
| quote / backslash contamination | 0 |
| Qdrant payload raw_text key | 0 |
| `text_fields.embedding_text` mismatch | 0 |
| Qdrant `payload.text` empty | 0 |
| non-flat `normalized_text` | 0 |
| Qdrant official points | 25,910 |
| Qdrant `payload_version != 1` | 0 |
| Qdrant vector dim mismatch | 0 |
| Qdrant vector NaN/Inf | 0 |
| DB official rows with 4 text layers | 27,907 |
| DB `markdown == metadata.text_layers.markdown` | 27,907 |
| DB `embedding_text == metadata.text_layers.embedding_text` | 27,907 |
| official `qdrant_index_entries.payload_version=1` | 25,910 |

테스트:

- 현재 환경에는 `pytest`가 설치되어 있지 않아 pytest runner는 실행 불가.
- 대신 `tests/test_official_gold_import.py`, `tests/test_qdrant_indexer.py`의 `test_*` 함수를 직접 호출해 `23 passed`.
- `python -m compileall` 통과.
- `git diff --check` 통과.
- 퇴근 전 `retrieval_smoke_queries.jsonl` 5건 실행:
  - report: `reports/official_corpus_v014_260516_preleave_retrieval_smoke.json`
  - `hit@1=0.8`, `hit@3=1.0`, `hit@5=1.0`, `warning_free_rate=1.0`
  - top-1 miss 1건은 `operators`가 top-3에 포함되어 후속 rank/rerank 조정 대상으로 기록.

샘플 확인:

- `payload.text`: 표시/답변용 markdown
- `text_fields.embedding_text`: 벡터 입력용 flat text
- `normalized_text == embedding_text`: false
- `section_path`: 있음
- `toc_path`: 있음
- `raw_text`: Qdrant payload에 없음

검색 smoke:

| 질문 | 관찰 |
| --- | --- |
| `PVC Pending 상태 확인 명령어` | storage/PVC 상태 확인 청크가 top-1 |
| `MachineConfigPool degraded 확인 방법` | `machineconfigpools` 상태 확인 청크가 상위권 |
| `이미지 레지스트리 ReadWriteMany 스토리지` | registry storage 청크가 top-3 |
| `etcd 백업 어느 노드에서 실행` | vector-only 검색에서는 etcd 리더/복제 설명이 먼저 올라올 수 있음. `cluster-backup.sh` 확장 질의에서는 backup command 청크가 top-1. 이는 v0.1.4 문서의 Intent Agent/metadata rank가 아직 런타임에 붙지 않은 잔여 gap으로 본다. |

## 기존 파일을 지우지 않은 이유

| 파일/폴더 | 현재 역할 | 지우지 않은 이유 |
| --- | --- | --- |
| `gold_corpus_ko/chunks.jsonl` | official corpus의 원본 청크 소스. `embedding_chunks.jsonl`을 재생성하는 기준 입력. | 원본 truth이므로 삭제/덮어쓰기 금지. 문제가 생기면 여기서 다시 projection을 만들 수 있어야 한다. |
| `gold_corpus_ko/text-layers/text_layers.jsonl` | v0.1.4 4계층 검수용 산출물. | Qdrant에는 raw 원문을 싣지 않기 때문에, 로컬에서 `raw_text/markdown/normalized_text/embedding_text`를 함께 확인하는 계약 증거가 필요하다. |
| `gold_corpus_ko/embeddings/embedding_chunks.jsonl` | 이번에 만든 Qdrant 적재용 projection. `embedding_text`와 `normalized_text`가 분리되어 있다. | 새 runtime/Qdrant 적재 기준 파일이다. 삭제 대상이 아니라 이번 작업의 핵심 산출물이다. |
| `gold_corpus_ko/bm25_corpus.jsonl` | 기존 BM25 파일형 인덱스/캐시. 현재 설정의 `retrieval_bm25_corpus_path`가 이 파일을 읽을 수 있다. | `normalized_text`가 생겼다고 즉시 대체되지 않는다. BM25 loader를 DB 또는 `embedding_chunks.jsonl.normalized_text` 기준으로 바꾸기 전까지 삭제하면 fallback 검색이 깨질 수 있다. |
| `gold_manualbook_ko/playbook_documents.jsonl` | manual book/document catalog 계열 산출물. 문서 뷰어와 manual book 쪽에서 참조될 수 있다. | Qdrant 임베딩 projection 입력은 아니지만 문서 표시/탐색 계층의 산출물이라 이번 청킹 작업 범위에서 삭제하지 않는다. |
| `gold_manualbook_ko/playbooks/` | manual book playbook JSON 산출물 폴더. | RAG 임베딩용 청크와 목적이 다르다. 뷰어/매뉴얼북 재료일 수 있어 삭제하지 않는다. |
| `silver_ko/` | gold 이전 단계의 중간/원천 계열 자료. | gold corpus를 재검증하거나 재생성할 때 추적 가능한 upstream/intermediate 역할을 한다. 이번 작업은 official gold projection 정리라 삭제하지 않는다. |

## v0.1.4 기준 진행 상태

| v0.1.4 항목 | 현재 상태 |
| --- | --- |
| 4계층 텍스트 분리 | 로컬 `text_layers.jsonl` + DB `metadata.text_layers` 기준 반영 완료 |
| 목차/경로 컬럼화 | 완료 |
| Qdrant payload text contract | 완료 |
| Qdrant 재임베딩/재적재 | 완료 |
| `bm25_corpus.jsonl` 대체 | 미완료. BM25 loader 전환 전까지 유지 |
| `corpus_documents`, `corpus_chunks` 등 새 테이블 | 후속 단계. v0.1.5 SQL migration 영역 |
| `corpus_chunk_segments` | 후속 단계 |
| `corpus_chunk_commands` / `env_scope` | 후속 단계 |
| `corpus_chunk_refs` | 후속 단계 |
| Intent Agent / metadata rank scoring | 후속 단계 |

## 남은 단계와 책임 구분

v0.1.4 계약 문서 기준으로 보면, 오늘 작업은 청킹/임베딩/Qdrant projection을 기존 `document_chunks` 호환 구조 위에서 선반영한 것이다. v0.1.4 문서 자체의 원래 범위는 SQL 마이그레이션과 런타임 전환이 아니라 계약 정의와 dry-run 검증이며, 실제 신규 테이블 구현은 문서상 v0.1.5 작업이다.

| 계약 항목 | 오늘 처리 상태 | 다음 행동 | 책임 |
| --- | --- | --- | --- |
| `raw_text` / `markdown` / `normalized_text` / `embedding_text` 4계층 | 완료. 로컬 `text_layers.jsonl`, DB `metadata.text_layers`, Qdrant `text_fields`로 확인 가능. | 정식 `corpus_chunks` 테이블이 생기면 컬럼으로 승격. | 다음 DB migration 작업자 |
| 임베딩용 청크 projection | 완료. `embedding_chunks.jsonl` 25,910건 생성. | 품질 정책이 바뀌면 이 파일을 재생성. | corpus/ingestion 작업자 |
| Qdrant payload에서 raw 원문 제외 | 완료. `raw_text` 유출 0건. | 신규 projection에서도 같은 rule 유지. | retrieval/indexing 작업자 |
| Qdrant 재임베딩/재적재 | 완료. `openshift_docs` official docs 25,910건 재적재. | 운영/공유 환경 적용 전 snapshot/drop 정책 확인. | backend/retrieval 작업자 |
| `bm25_corpus.jsonl` 대체 | 미완료. `normalized_text`는 만들었지만 BM25 loader는 아직 주로 `row.text`를 tokenize한다. | BM25 loader가 `text_fields.normalized_text` 또는 DB `metadata.normalized_text`를 읽도록 변경 후 기존 파일 제거 여부 결정. | retrieval 작업자 |
| 새 corpus 테이블 6개 | 후속 단계. 현재 DB에는 `qdrant_index_entries`만 있고 `corpus_documents`, `corpus_chunks`, `corpus_chunk_segments`, `corpus_chunk_commands`, `corpus_chunk_refs`, `corpus_question_candidates`는 아직 생성하지 않았다. | v0.1.5 SQL migration 작성. | DB/backend 작업자 |
| `corpus_chunk_segments` | 후속 단계. 이번 작업은 텍스트 정제와 projection을 다루며, 카드 렌더용 typed segment row 생성은 포함하지 않았다. | prose/command/output/table segment 생성기 구현. | parsing/corpus 작업자 |
| `corpus_chunk_commands` / `env_scope` | 후속 단계. 명령어 문자열은 보존했지만 command template, placeholders, env_scope 구조화는 아직 포함하지 않았다. | 명령어 추출기와 환경 후속질문 trigger 구현. | retrieval/agent 작업자 |
| `corpus_chunk_refs` | 후속 단계. next/prerequisite/related graph는 아직 테이블화하지 않았다. | structural next + heuristic refs 생성. | corpus/learning 작업자 |
| Intent Agent / metadata pre-filter / rank scoring | 후속 단계. Qdrant payload 기본 구조는 준비했으나 질문 신호 추출과 scoring 정책은 런타임에 연결하지 않았다. | 후속 메타데이터 기반 query signal, rank scoring, hard filter 금지 규칙 구현. | retrieval 담당자 |
| 챗봇 답변 카드 / 코드블록 표시 | 이번 작업 범위에는 포함하지 않았다. 청크 텍스트와 별개로 answer renderer/hydration 영역에서 다룰 항목이다. | segments 기반 카드 렌더링과 prompt 직렬화 구현. | chatbot/UI/backend 작업자 |

회의 시 확인하면 좋은 사항은 다음과 같다.

- 오늘 선반영한 `openshift_docs` 재적재 결과를 v0.1.4 호환 구현으로 인정할지.
- BM25 loader 전환을 이번 브랜치에서 이어서 할지, 다음 retrieval 작업으로 넘길지.
- 신규 `corpus_*` SQL migration을 v0.1.5 시작 작업으로 둘지.
- 후속 메타데이터 기반 rank 작업과 이 corpus projection 사이의 payload 필드 계약을 그대로 사용할지.

### BM25 normalized_text 전환 판단

BM25는 벡터 검색이 아니라 토큰 매칭 기반 검색이므로, 표시용 `markdown`이나 벡터용 `embedding_text`보다 검색 전용 `normalized_text`를 보는 것이 시스템적으로 더 자연스럽다. 이번 작업으로 `normalized_text`는 로컬 `embedding_chunks.jsonl`, 로컬 `text_layers.jsonl`, DB `metadata.normalized_text`, Qdrant `text_fields.normalized_text`에 준비됐다.

다만 품질 개선 포인트는 `bm25_corpus.jsonl` 파일 삭제가 아니라 **BM25 loader의 입력 소스를 `normalized_text`로 전환하는 것**이다. 파일을 먼저 삭제하면 fallback 검색 경로가 깨질 수 있다.

권장 순서:

1. BM25 loader가 DB 또는 `embedding_chunks.jsonl`의 `normalized_text`를 tokenize하도록 수정한다.
2. BM25 검색 smoke query로 기존 결과와 비교한다.
3. 런타임에서 `bm25_corpus.jsonl` 의존이 사라진 것을 확인한다.
4. 그 뒤 `bm25_corpus.jsonl` 삭제 또는 deprecated 처리를 결정한다.

따라서 이번 청킹/임베딩/Qdrant projection 범위는 완료됐고, BM25 loader 전환은 검색 런타임까지 함께 정리하려는 경우 이어서 진행할 후속 검토 항목이다.

## 후속 작업 참고 사항

1. `bm25_corpus.jsonl`을 바로 삭제하지 말고, 먼저 BM25 로더가 `normalized_text`를 읽도록 바꿔야 한다.
2. 챗봇 답변 카드 품질은 이번 Qdrant projection만으로 완전히 해결되지 않는다. v0.1.4 문서의 `corpus_chunk_segments`와 `corpus_chunk_commands`가 구현되어야 코드/프로즈/출력 예시 카드가 안정적으로 분리된다.
3. retrieval 품질은 청크 텍스트 정제만으로 끝나지 않는다. 후속 메타데이터 적용, rank scoring, Intent Agent 계층이 붙어야 `PVC Pending` 같은 질문에서 top-k 안정성이 올라간다.
4. Qdrant dump는 PowerShell `Invoke-RestMethod` 대신 Python 또는 raw byte 방식으로 확인해야 한다. PowerShell 디코딩 문제로 한국어가 깨져 보일 수 있다.
5. `official-embedding-qdrant-upsert --sync-db`는 DB sync, Qdrant upsert, `qdrant_index_entries` 기록까지 함께 수행한다. 직접 payload overwrite만 수행한 경우에도 index entry parity를 별도 확인해야 한다.

## 재실행 명령

embedding projection 재생성:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m play_book_studio.cli official-gold-import --dry-run --embedding-chunks-path corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl --text-layers-path corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/text_layers.jsonl
```

Qdrant/DB 반영:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m play_book_studio.cli official-embedding-qdrant-upsert --collection openshift_docs --delete-skipped --sync-db
```

샘플 조회:

```powershell
@'
import json, urllib.request
point_id='9e5fac0d-2410-52b2-b795-3a0dfc8e1e9b'
url=f'http://127.0.0.1:6335/collections/openshift_docs/points/{point_id}'
payload=json.loads(urllib.request.urlopen(url, timeout=10).read().decode('utf-8'))['result']['payload']
print(json.dumps({
  'chunk_id': payload.get('chunk_id'),
  'display_text_has_newline': '\n' in (payload.get('text') or ''),
  'payload_embedding_matches_field': payload.get('text_fields',{}).get('embedding_text') is not None,
  'normalized_equals_embedding': payload.get('text_fields',{}).get('normalized_text') == payload.get('text_fields',{}).get('embedding_text'),
  'display_text': payload.get('text'),
  'normalized_text': payload.get('text_fields',{}).get('normalized_text'),
  'embedding_text': payload.get('text_fields',{}).get('embedding_text'),
  'section_path': payload.get('section_path'),
  'toc_path': payload.get('toc_path'),
}, ensure_ascii=False, indent=2))
'@ | python -
```
