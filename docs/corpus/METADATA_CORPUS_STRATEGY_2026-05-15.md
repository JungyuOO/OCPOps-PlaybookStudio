# Metadata Corpus Strategy - 2026-05-15

## 1. 오늘의 목표

오늘은 새 PDF를 더 넣거나 품질 수리 기능을 새로 벌리지 않는다.
목표는 S가 담당하는 `데이터 수집 -> 코퍼스 패키지 -> 위키북/Library` 작업과
J가 담당하는 `검색/리랭킹/챗봇/Ops` 작업 사이의 계약을 고정하는 것이다.

### 완료 조건

| 항목 | Pass 기준 | Evidence |
| --- | --- | --- |
| 현재 메타 추출 상태 파악 | 어떤 코드가 어떤 메타를 만들고 어디까지 전달하는지 설명 가능 | `metadata_spine.py`, `document_parsing.py`, `qdrant_indexer.py`, `corpus_handoff.py` |
| 런타임 coverage 실측 | PostgreSQL/Qdrant 기준 현재 coverage 수치 확보 | read-only SQL, Qdrant scroll |
| 코퍼스 전략 고정 | JSON/JSONL, DB, Qdrant, storage의 역할이 분리됨 | 이 문서, `CORPUS_AUDIT.md` |
| J handoff 계약 | J가 챗봇 실패를 어느 쪽 문제로 볼지 분류 가능 | Corpus Handoff Report 계약 |
| 오늘 할 일 분해 | 오늘 끝낼 것과 하지 않을 것이 명확함 | Section 8 |

### 오늘 하지 않을 것

- 새 대량 수집, 공식 문서 전체 재빌드, 대규모 PDF 재처리
- 품질 수리 알고리즘 추가 구현
- 챗봇 reranker/prompt 자체 수정
- `corpus/` 물리 rename/delete 확대
- 특수문자/공백을 일괄 제거하는 파괴적 정규화

---

## 2. 현재 판단

메타데이터 추출은 "안 했다"가 아니다. 이미 deterministic v1이 있다.
하지만 제품 기준으로는 아직 부족하다.

정확한 표현은 다음과 같다.

- DB chunk에는 `metadata_spine_v1`이 100% 붙어 있다.
- Qdrant payload에도 topic, role, command, object, answerable question 등이 전달된다.
- 그런데 coverage가 있다고 해서 품질이 좋다는 뜻은 아니다.
- 현재 자동 생성 질문에는 한국어 조사 오류가 있고, 표/문장 일부가 command로 오탐되는 샘플이 있다.
- 따라서 지금 할 일은 "메타 추출 시작"이 아니라 "answer-ready metadata contract로 고도화"다.

---

## 3. 현재 구현 근거

### 메타 생성 위치

`src/play_book_studio/ingestion/metadata_spine.py`

- `topic`: install, networking, security, storage, monitoring, troubleshooting, ops
- `semantic_role`: concept, procedure, command, config, troubleshooting, reference
- `k8s_objects`: Pod, Deployment, Route, Service, SCC, RBAC 등
- `cli_commands`: oc, kubectl, helm, curl, podman, docker
- `error_strings`: CrashLoopBackOff, ImagePullBackOff, FailedScheduling 등
- `verification_hints`: 확인/검증 문장, `oc get`, `kubectl describe` 계열
- `answerable_questions`: chunk가 답할 수 있는 질문 후보
- `metadata_confidence`: high / medium / low

### 신규 chunk 적용 위치

`src/play_book_studio/ingestion/document_parsing.py`

- chunk 생성 시 `build_chunk_metadata_spine(...)`를 호출한다.
- 결과가 `document_chunks.metadata`에 저장된다.

### 기존 chunk backfill 위치

`src/play_book_studio/db/metadata_spine_backfill.py`

- 기존 `document_chunks`에 spine이 없으면 deterministic rule로 채운다.
- `metadata_spine_source=deterministic_backfill`을 남긴다.

### Qdrant 전달 위치

`src/play_book_studio/db/qdrant_indexer.py`

- Qdrant payload에 `topic`, `semantic_role`, `metadata_confidence`,
  `answerable_questions`, `cli_commands`, `k8s_objects`, `error_strings`,
  `verification_hints`, `chunk_metadata`가 들어간다.

### Retrieval hit 전달 위치

`src/play_book_studio/retrieval/vector.py`

- Qdrant payload의 spine fields를 `RetrievalHit`로 복원한다.

### J handoff report 위치

`src/play_book_studio/db/corpus_handoff.py`

- scope별 문서 수, chunk 수, metadata coverage, topology state,
  golden question 후보, known blocker를 만든다.

---

## 4. 런타임 실측 결과

측정 시각: 2026-05-15, local Docker runtime

### PostgreSQL chunk coverage

| scope | documents | chunks | spine | topic | role | commands | objects | errors | verify | answerable | low_conf |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| official_docs | 29 | 27,907 | 27,907 | 27,907 | 27,907 | 15,096 | 12,586 | 1,344 | 12,697 | 27,907 | 0 |
| study_docs | 9 | 523 | 523 | 523 | 523 | 54 | 200 | 37 | 51 | 523 | 0 |
| user_upload | 10 | 108 | 108 | 108 | 108 | 44 | 80 | 0 | 45 | 108 | 0 |

### Confidence 분포

| scope | high | medium | low |
| --- | ---: | ---: | ---: |
| official_docs | 13,733 | 14,174 | 0 |
| study_docs | 53 | 470 | 0 |
| user_upload | 50 | 58 | 0 |

### Qdrant 상태

| 항목 | 값 |
| --- | ---: |
| collection | `openshift_docs` |
| status | green |
| points_count | 28,538 |
| indexed_vectors_count | 27,232 |
| vector_size | 1024 |

### 확인된 품질 gap

Qdrant sample과 handoff report에서 다음 문제가 확인됐다.

- `중요한 특성는 무엇을 확인해야 하나요?`처럼 자동 질문의 한국어 조사가 어색하다.
- 표 행이 `kubectl 및 oc 자동화된 명령줄 | 포함됨...` 형태로 command 오탐될 수 있다.
- 일부 generated question은 section title만 반복해서 실제 사용 질문처럼 보이지 않는다.
- handoff endpoint는 owner 없이 호출하면 private `user_upload`를 제외한다. J 공유용 report에는 admin/owner scope 정책이 필요하다.
- coverage는 높지만 "정답 chunk가 검색 상위에 올라오는지"는 아직 별도 golden question 평가로 증명해야 한다.

---

## 5. 데이터 계층 계약

한 문서가 제품에 들어오면 계층을 분리해서 본다.

| 계층 | 역할 | 저장 위치 | 원칙 |
| --- | --- | --- | --- |
| Raw source | 원본 보존 | storage / source package | 절대 파괴하지 않음 |
| Parsed markdown | Reader와 chunk 원천 | PostgreSQL `parsed_documents` | 사람이 읽을 수 있어야 함 |
| Chunk | 검색/답변 최소 단위 | PostgreSQL `document_chunks` | section, page, asset evidence 필요 |
| Metadata spine | 검색/리랭킹/평가 feature | `document_chunks.metadata`, Qdrant payload | deterministic 우선, evidence 필수 |
| Vector index | semantic retrieval | Qdrant | PostgreSQL chunk에서 재생성 가능해야 함 |
| Topology | 지식망 탐색/확장 | topology snapshot | node/edge는 chunk/asset evidence 필요 |
| Handoff report | J와 공유하는 계약 | API/report | corpus health와 known blocker 공개 |

중요한 원칙:

- `corpus/**/*.json` 또는 `jsonl`은 seed/import/evidence다.
- 제품 runtime truth는 PostgreSQL, Qdrant, storage다.
- JSON/JSONL이 있다고 제품 데이터가 건강한 것은 아니다.
- DB/Qdrant에 들어간 payload가 J가 쓰는 실제 계약이다.

---

## 6. 정규화 정책

J 의견처럼 "특수문자와 공백을 전부 제거"하면 안 된다.
OCP 문서에서는 특수문자와 공백이 의미 그 자체인 경우가 많다.

### 제거/수리 대상

- NUL byte, zero-width char, 깨진 제어문자
- PDF 추출 중 생긴 과도한 빈 줄
- 반복 page header/footer
- 줄바꿈 때문에 깨진 단어: `비활 성화`, `my-proje ct`
- code fence 없이 평문에 섞인 YAML/command
- OCR/파서가 만든 명백한 중복 문장

### 보존 대상

- YAML indentation
- CLI flag: `--namespace`, `-o yaml`
- Kubernetes object path: `authentication.config/cluster`
- URL, file path, image reference
- label/annotation key: `openshift.io/scc`
- error string 대소문자
- backtick/code fence
- 표의 column 구분

### 산출물별 text view

| view | 목적 | 처리 |
| --- | --- | --- |
| `source_text` | 원문 보존/감사 | 최소 정리만 |
| `reader_markdown` | 사람이 읽는 문서 | 문단/표/코드블록 복구 |
| `embedding_text` | vector 검색 | noise 축소, 의미 보존 |
| `metadata_text` | rule/LLM metadata 추출 | code/section/evidence 신호 강화 |
| `display_title` | UI 카드 | 줄바꿈/긴 파일명만 안전 처리 |

---

## 7. Metadata Spine 고도화 전략

### v1 현재 상태

v1은 deterministic rule 기반이다.

장점:

- 빠르고 재현 가능하다.
- Qwen/외부 endpoint가 죽어도 동작한다.
- DB와 Qdrant에 이미 전체 반영되어 있다.

한계:

- topic이 너무 넓다. `security`와 `networking` 정도로만 잡히면 J가 정교하게 쓰기 어렵다.
- 한국어 질문 생성 품질이 낮다.
- command 추출이 표/문장과 code block을 충분히 구분하지 못한다.
- image/diagram evidence와 아직 강하게 묶이지 않는다.
- version/product/environment metadata가 부족하다.

### v2 목표

v2는 "검색 가능한 메타"가 아니라 "답변 가능한 메타"여야 한다.

필수 추가 필드:

| field | 목적 |
| --- | --- |
| `product` / `version` | OCP 4.20 등 버전 불일치 방지 |
| `source_kind` | official / customer / upload / generated 구분 |
| `operation_stage` | install / configure / verify / troubleshoot / repair |
| `task_intent` | 사용자가 하려는 일: 권한 부여, 라우트 확인, 장애 분석 등 |
| `prerequisites` | 답변 전에 필요한 조건 |
| `expected_output` | 명령 실행 후 봐야 할 결과 |
| `risk_level` | 위험 명령/권한 상승 여부 |
| `asset_evidence_ids` | 이미지/표/다이어그램 근거 |
| `topology_node_ids` | 지식망 node 연결 |
| `quality_blockers` | 답변에 쓰면 안 되는 이유 |
| `golden_question_ids` | 평가 질문과 연결 |

### Qwen 사용 원칙

Qwen은 자동 Gold 승격자가 아니다.

- deterministic rule이 먼저 추출한다.
- Qwen은 low-confidence chunk에 대해 보강 초안을 만든다.
- Qwen 결과는 `evidence`, `confidence`, `reason`을 남긴다.
- 사람이 승인하거나 rule로 검증된 것만 Gold/handoff에 반영한다.

---

## 8. J와의 작업 분리 계약

### S 쪽 책임

- 원천 데이터 패키지 정리
- PDF/AsciiDoc/official/customer/upload parsing
- reader markdown 품질
- chunk/evidence/topology/metadata spine
- corpus handoff report
- golden question expected chunk 지정

### J 쪽 책임

- query rewrite
- BM25/vector/reranker/fusion
- selected chunk selection
- answer generation
- citation formatting
- Ops live context와 chatbot integration

### 공동 책임

- metadata matching
- retrieval failure classification
- golden question pass/fail
- citation precision

### 실패 분류

| 실패 상황 | 책임 분류 | 예시 |
| --- | --- | --- |
| 정답 chunk가 corpus에 없음 | corpus_gap | 문서 자체가 누락됨 |
| 정답 chunk는 있는데 메타/토픽이 틀림 | metadata_gap | SCC 문서가 networking으로만 잡힘 |
| 정답 chunk는 있는데 검색 상위에 없음 | retrieval_gap | BM25/vector/reranker 문제 |
| 정답 chunk가 선택됐는데 답변이 틀림 | answer_gap | prompt/LLM 생성 문제 |
| citation이 엉뚱함 | citation_gap | selection 또는 citation mapping 문제 |
| 버전/환경이 맞지 않음 | context_gap | OCP 4.20 질문에 다른 버전 근거 사용 |

### J에게 넘길 Handoff Report 필드

- `corpus_version`
- scope별 document/chunk/gold/topology count
- metadata coverage
- golden questions
- expected chunk ids
- known blockers
- private/user upload 포함 여부와 owner scope

J가 챗봇 응답마다 남겨야 할 trace:

- `query`
- `rewritten_query`
- `selected_chunk_ids`
- `reranker_result`
- `citations`
- `response_kind`
- `pipeline_trace`

---

## 9. 오늘 할 일 우선순위

### P0. Corpus folder IA를 먼저 고정

작업:

- `corpus/README.md`에서 `sources / manifests / data`의 역할을 한눈에 보이게 한다.
- KMSC `course_pbs`를 현재 clean reference package로 명시한다.
- official `imported-gold`는 제품 Gold가 아니라 legacy seed/evidence라고 명시한다.

완료 기준:

- 처음 보는 사람이 `corpus/`에 들어와도 어디가 reference package이고 어디가 legacy인지 구분한다.

### P0. 전략 문서 고정

작업:

- 이 문서를 팀 공유 기준으로 사용한다.
- `CORPUS_AUDIT.md`와 연결해 `corpus/`가 seed/import/evidence 영역임을 명확히 한다.

완료 기준:

- S/J가 "무엇이 코퍼스이고 무엇이 runtime truth인지" 같은 말로 설명할 수 있다.

### P0. 현재 coverage report를 저장 가능한 형태로 뽑기

작업:

- PostgreSQL coverage SQL을 스크립트/문서화한다.
- `/api/corpus/handoff-report`가 user_upload를 owner/admin 기준으로 어떻게 노출할지 결정한다.

완료 기준:

- J에게 "현재 corpus 상태"를 숫자로 넘길 수 있다.

### P0. Cleaning/normalization 계약 잠금

작업:

- "특수문자/공백 전체 제거 금지"를 계약으로 고정한다.
- source_text, reader_markdown, embedding_text, metadata_text를 분리한다.

완료 기준:

- 데이터 정리 작업자가 원문을 망가뜨리지 않고 검색용 텍스트를 개선할 수 있다.

### P0. Golden question seed 20개 설계

작업:

- official/customer/upload에서 최소 20개 질문을 뽑는다.
- 각 질문에 expected document, expected chunk id, required metadata를 붙인다.

완료 기준:

- J의 검색/리랭커 결과와 우리가 기대한 chunk를 비교할 수 있다.

### P1. Metadata v2 설계 상세화

작업:

- v2 필드 중 오늘 필요한 최소 필드를 고른다.
- 기존 v1과 backward compatible하게 확장한다.

완료 기준:

- 구현 전 schema drift 없이 v2 migration/backfill 계획을 세울 수 있다.

### P1. Handoff endpoint 보강 계획

작업:

- user_upload/private 데이터가 J report에 빠지는 문제를 owner/admin scope로 정리한다.
- 민감정보가 새지 않게 scope별 공개 정책을 적는다.

완료 기준:

- "내 업로드 문서는 왜 report에 안 보이냐"를 정책/권한 문제로 설명 가능하다.

---

## 10. 오늘 산출물

필수:

1. `docs/corpus/METADATA_CORPUS_STRATEGY_2026-05-15.md`
2. DB/Qdrant coverage 수치
3. J 공유용 1페이지 요약
4. Golden question seed 초안

선택:

1. coverage SQL을 CLI 명령으로 고정
2. `/api/corpus/handoff-report` owner/admin scope 개선 계획
3. metadata v2 schema draft

---

## 11. Acceptance Criteria

| Criteria | Status |
| --- | --- |
| 메타 추출이 어디서 일어나는지 설명 가능 | PASS |
| 현재 coverage 수치 확보 | PASS |
| coverage와 품질의 차이를 명시 | PASS |
| 특수문자/공백 일괄 제거 금지 명시 | PASS |
| J/S 책임 경계 명시 | PASS |
| 오늘 하지 않을 작업 명시 | PASS |
| golden question 실제 20개 확정 | TODO |
| handoff report owner/admin scope 확정 | TODO |
| metadata v2 schema 구현 | NOT TODAY |

---

## 12. 바로 공유할 요약

현재 코퍼스 메타 추출은 이미 v1이 있고 DB/Qdrant까지 전달된다.
하지만 챗봇 품질을 보장하기에는 아직 "coverage만 높은 상태"다.
오늘은 데이터를 더 쌓지 않고, S가 만드는 answer-ready corpus와 J가 쓰는 retrieval/chat trace 사이의 계약을 고정한다.

핵심 합의:

- S는 원천, parsing, chunk, metadata, topology, handoff, expected chunk를 책임진다.
- J는 query, retrieval, reranker, answer, citation trace를 책임진다.
- 실패는 `corpus_gap`, `metadata_gap`, `retrieval_gap`, `answer_gap`, `citation_gap`, `context_gap`으로 분류한다.
- 특수문자/공백은 전부 제거하지 않는다. OCP 문서에서는 YAML, CLI, URL, label, annotation, error string이 데이터의 핵심이다.
- JSON/JSONL은 seed/import/evidence이고, 제품 truth는 PostgreSQL/Qdrant/storage다.
