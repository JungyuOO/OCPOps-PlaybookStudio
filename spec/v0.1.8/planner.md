# v0.1.8 - Chatbot Latency and Answer Quality Planner

## Goal

서버에 배포된 Playbot 챗봇에서 시작 질문을 하나 클릭했을 때 응답까지 1~2분가량 걸리는 문제를 먼저 계측하고, 실제 병목 지점을 증거 기반으로 좁힌다.

이번 v0.1.8 작업의 목적은 바로 최적화 코드를 넣는 것이 아니라, 운영 서버에서 한 번의 챗봇 요청이 어느 단계에서 오래 걸리는지를 구조화된 로그로 확인할 수 있게 만드는 것이다. 병목이 `embedding`, `Qdrant`, `BM25`, `reranker`, `LLM`, `payload build`, `session persist`, `related links` 중 어디인지 숫자로 확인한 뒤에만 개선 작업을 진행한다.

## Scope Lock

이 브랜치 `feat/v0.1.8/chatbot-latency-quality`의 작업은 이 문서를 기준으로만 진행한다.

### Included

- `/api/chat` 및 `/api/chat/stream` 요청의 서버 측 latency 계측 계획
- 시작 질문 클릭 후 실제 RAG 응답까지 걸리는 단계별 시간 분석
- `retrieval_trace`, `pipeline_trace`, `server_timings_ms`의 운영 로그 노출 계획
- LLM, embedding, Qdrant, reranker, payload serialization 병목 판정 기준
- 계측 결과를 바탕으로 한 개선 후보와 우선순위
- 답변 품질 회귀를 막기 위한 smoke/eval 기준

### Excluded

- starter question 문구 재설계
- RAG retrieval 가중치 추가 수정
- KMSC/official corpus 재시드
- Qdrant 컬렉션 재생성
- LLM 프롬프트 대규모 개편
- 웹 UI redesign
- 성능 원인 확인 전 임의 캐시/skip/bypass 추가

## Current State Analysis

현재 코드에는 기본적인 타이밍 구조가 이미 존재한다.

| 영역 | 현재 구현 | 한계 |
| --- | --- | --- |
| HTTP request timing | `server_chat.py`에서 `answerer_runtime`, `payload_build`, `request_total` 등 측정 | 응답 payload에만 붙고 운영 로그에서 한 턴 단위로 바로 보기 어려움 |
| Answer pipeline timing | `answerer.py`에서 `route_query`, `retrieval_total`, `context_assembly`, `prompt_build`, `llm_generate_total`, `citation_finalize`, `total` 측정 | 로그 한 줄로 요약되지 않고, 일부 하위 단계가 뭉쳐 있음 |
| Retrieval timing | `retriever_pipeline.py`, `retriever_search.py`, `retriever_rerank.py`에 `normalize_query`, `rewrite_query`, `bm25_search`, `vector_search`, `fusion`, `rerank` 존재 | vector 내부의 embedding 호출과 Qdrant 호출 시간이 분리되지 않음 |
| LLM timing | `llm.py`에서 provider round-trip trace를 emit | 첫 토큰 latency, prompt token 크기, provider fallback 여부를 운영 로그에서 쉽게 비교하기 어려움 |
| Payload timing | `server_support.py`에서 citation serialize, related links, related sections, suggested queries 측정 | related link/section 생성이 느릴 경우 request 끝부분 병목으로 보이지만 로그 가시성이 낮음 |
| Stream endpoint | `/api/chat/stream`은 trace event를 내보냄 | 사용자가 보는 첫 응답은 LLM 완료 후 `_stream_answer_delta`가 시작되어 진짜 streaming 효과가 제한적임 |

## Request Path

### Main Chat API Decision

메인 Workspace 챗봇은 질문 종류와 상관없이 `/api/chat/stream` 하나를 사용한다. 시작 질문의 라벨은 UI 분류일 뿐이고, RAG 경로는 `route_kind`로 source scope만 조정한다.

| UI 질문 종류 | API | backend route_kind | retrieval scope |
| --- | --- | --- | --- |
| 자주 묻는 질문 | `/api/chat/stream` | `official` | `official_docs` |
| 단계별 학습 질문 | `/api/chat/stream` | `official` | `official_docs` |
| 실운영 문서 질문 | `/api/chat/stream` | `study_docs` | `study_docs` / KMSC |
| 직접 입력 일반 채팅 | `/api/chat/stream` | empty 또는 현재 context | 전체 또는 context 기반 |

`/api/v1/course/chat`과 `/api/v1/course/chat/stream`은 KMSC course viewer/tutor 전용 API로 남긴다. 메인 Workspace starter 또는 일반 챗봇 질문에는 사용하지 않는다. 이 경로는 `course_api.py::_course_chat_payload()`의 course 전용 검색과 answer-line builder를 사용하므로 main RAG latency/quality 측정 대상에서 제외한다.

`/api/chat`은 같은 main RAG의 non-stream JSON adapter로 유지한다. smoke/eval/debug와 외부 단순 API 호출에 필요하지만, 메인 UI 체감 성능 측정은 `/api/chat/stream`을 기준으로 한다.

시작 질문 클릭 시 예상 경로는 다음과 같다.

1. Web에서 starter question 클릭
2. `/api/chat/stream` 요청
3. `server_handler_factory.py` route dispatch
4. `server_chat.py::handle_chat_stream`
5. `ChatAnswerer.answer`
6. `route_non_rag`
7. `ChatRetriever.retrieve`
8. query normalize/rewrite/signal plan
9. BM25 search
10. vector search
11. embedding API call
12. Qdrant search/query
13. private/customer pack vector search 여부 확인
14. fusion
15. reranker model 또는 heuristic rerank
16. context assembly
17. prompt build
18. LLM generation
19. citation finalize / grounding guard
20. payload build
21. related links / related sections / suggested queries
22. session persistence and audit log
23. response return

## Working Hypotheses

아래는 지금 코드와 운영 증상 기준의 가설이다. 실제 수정은 계측 결과를 보고 결정한다.

| 가설 | 설명 | 확인할 로그 |
| --- | --- | --- |
| H1. LLM provider가 가장 느림 | LLM-only 전환 이후 결정형 답변 경로가 사라져 모든 RAG 답변이 provider round-trip을 탄다. | `llm_provider_round_trip`, `llm_generate_total`, model, max_tokens |
| H2. vector search 내부 embedding이 느림 | `vector.py::search_with_trace`에서 `embed_texts([query])`와 Qdrant 호출이 한 덩어리로 보인다. | `embedding_ms`, `qdrant_ms`, embedding endpoint, timeout |
| H3. query signal plan이 embedding query를 여러 개 만든다 | `retriever_search.py`는 각 rewritten query와 각 embedding query마다 vector search를 수행한다. | embedding query count, vector subquery count, duplicate skipped count |
| H4. reranker가 느림 | reranker model이 외부/로컬 모델 호출이면 후보 수에 따라 latency가 커질 수 있다. | `rerank`, candidate_budget, reranked_count, model_applied |
| H5. payload 후처리가 느림 | 관련 문서/섹션 링크 생성이 파일/관계 인덱스를 읽거나 검색하면 LLM 이후에도 오래 걸릴 수 있다. | `payload_related_links`, `payload_related_sections`, `payload_citation_serialize` |
| H6. persistence/audit가 느림 | Postgres/session store 또는 chat audit log write가 느리면 답변 생성 후에도 UI 응답이 늦어진다. | `session_persist_pre_payload`, `session_persist_post_payload`, `answer_log_persist`, audit log timing |
| H7. streaming endpoint가 체감 속도를 줄이지 못함 | 현재 answer delta는 전체 답변 완성 후 전송되므로 LLM 동안 사용자는 기다린다. | first trace time, first answer_delta time, result event time |

## Instrumentation Requirements

### Requirement 1. One-line server latency log

각 챗봇 요청마다 서버 로그에 JSON 한 줄을 남긴다.

필드:

| 필드 | 설명 |
| --- | --- |
| `event` | `chat_latency` |
| `request_id` | 요청 단위 UUID |
| `session_id` | chat session id |
| `route` | `/api/chat` 또는 `/api/chat/stream` |
| `route_kind` | payload의 route_kind, 없으면 빈 문자열 |
| `preferred_source_scope` | context preferred source scope |
| `query_len` | query 길이 |
| `response_kind` | rag, clarification, no_answer 등 |
| `warnings` | answer warnings |
| `total_ms` | 전체 request |
| `answerer_ms` | answerer runtime |
| `retrieval_ms` | retrieval total |
| `bm25_ms` | BM25 |
| `vector_ms` | vector total |
| `embedding_ms` | embedding client 호출 |
| `qdrant_ms` | Qdrant HTTP 호출 |
| `rerank_ms` | reranker |
| `llm_ms` | LLM total |
| `llm_provider_ms` | provider round-trip |
| `prompt_build_ms` | prompt build |
| `context_ms` | context assembly |
| `citation_finalize_ms` | citation finalize |
| `payload_build_ms` | response payload build |
| `related_links_ms` | related links |
| `related_sections_ms` | related sections |
| `suggested_queries_ms` | follow-up suggestions |
| `session_persist_ms` | pre + post session persist |
| `top_book_slugs` | reranked top book slugs |
| `source_scopes` | selected citations source scopes if available |
| `llm_model` | runtime LLM model |
| `reranker_model` | reranker model |

예상 로그 형태:

```json
{"event":"chat_latency","request_id":"...","route":"/api/chat","route_kind":"official","response_kind":"rag","total_ms":74231.5,"retrieval_ms":18320.4,"embedding_ms":8210.1,"qdrant_ms":912.3,"rerank_ms":10244.8,"llm_provider_ms":50112.7,"payload_build_ms":318.2}
```

### Requirement 2. Vector search sub-timing

`vector.py::search_with_trace`는 현재 embedding과 Qdrant를 합친 runtime만 반환한다. 다음 항목을 분리해야 한다.

- `embedding_ms`
- `qdrant_ms`
- `hydrate_ms`
- `endpoint_used`
- `attempted_endpoints`
- `request_timeout_seconds`
- `hit_count`
- `top_score`

### Requirement 3. Query plan fan-out visibility

`retriever_search.py::search_vector_candidates`에서 다음을 trace/runtime에 포함한다.

- rewritten query count
- embedding query count
- deduped embedding query count
- metadata filter applied 여부
- metadata filter fallback 여부
- private vector search status
- official/private hit count

이 값이 없으면 vector latency가 “한 번 느린 것”인지 “여러 번 호출해서 느린 것”인지 판단할 수 없다.

### Requirement 4. Reranker decision visibility

`maybe_rerank_hits`의 trace는 이미 풍부하지만, one-line server log에는 요약이 올라와야 한다.

- `model_applied`
- `decision_reason`
- `candidate_budget`
- `reranked_count`
- `top1_changed`
- `rebalance_reasons`

### Requirement 5. First visible response timing

stream endpoint에서는 사용자가 체감하는 시간을 분리해야 한다.

- `request_received_ms`
- first trace event sent time
- first answer delta sent time
- result event sent time

현재 구조상 `_stream_answer_delta`는 answerer 완료 후 호출된다. 따라서 LLM 응답이 60초면 첫 글자도 60초 뒤에 나온다. 이 구조를 바꿀지는 계측 후 별도 결정한다.

## Measurement Plan

### Server-side commands

배포 후 운영 서버에서 같은 starter question을 3회 이상 클릭하고 app 로그를 확인한다.

```bash
oc logs deployment/app -n pbs-ocpops --tail=300 | grep chat_latency
```

watch가 불안정하면 pod를 지정한다.

```bash
POD=$(oc get pod -n pbs-ocpops -l app.kubernetes.io/name=app -o jsonpath='{.items[0].metadata.name}')
oc logs "$POD" -n pbs-ocpops --tail=300 | grep chat_latency
```

### Test questions

최소 측정 질문은 starter question과 최근 문제 케이스를 포함한다.

| 분류 | 질문 | 기대 |
| --- | --- | --- |
| Official command | 전체 프로젝트 목록은 어떤 명령으로 확인하나요? | official docs, command-bearing chunk |
| Official storage | PVC와 PV 바인딩 상태는 어떤 명령으로 확인하나요? | storage/PVC chunk |
| Official concept | Service와 Route 연결 구조를 먼저 이해하고 싶은데, 어디를 보면 될까요? | networking concept chunk |
| Official install | OCP 설치는 어떤 순서로 시작하면 될까요? | install overview chunk |
| KMSC operations | 운영 문서에서 PVC 리스트와 바인딩 상태는 어떤 명령으로 확인하나요? | study_docs/KMSC scope |
| Follow-up | `oc delete secrets kubeadmin -n kube-system` 실행 전 주의사항은 뭐야? | previous citation context 유지 |

### Data collection table

각 질문별로 아래 표를 채운다.

| query | total_ms | retrieval_ms | vector_ms | embedding_ms | qdrant_ms | rerank_ms | llm_ms | payload_ms | bottleneck | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 전체 프로젝트 목록... |  |  |  |  |  |  |  |  |  |  |
| PVC와 PV 바인딩... |  |  |  |  |  |  |  |  |  |  |
| Service와 Route... |  |  |  |  |  |  |  |  |  |  |
| OCP 설치... |  |  |  |  |  |  |  |  |  |  |
| 운영 문서 PVC... |  |  |  |  |  |  |  |  |  |  |

## Bottleneck Decision Rules

| 조건 | 판단 | 우선 조치 |
| --- | --- | --- |
| `llm_provider_ms > 30000` and 전체의 60% 이상 | LLM 병목 | prompt/context 축소, max_tokens 조정, streaming 재구조 검토 |
| `embedding_ms > 5000` 단일 호출 | embedding endpoint 병목 | timeout/endpoint 상태 확인, query fan-out 축소, cache 검토 |
| `vector_ms > 10000` and embedding query count > 2 | vector fan-out 병목 | embedding query 개수 제한, 중복 제거 강화 |
| `qdrant_ms > 3000` | Qdrant 병목 | collection/index 상태, payload filter, Qdrant resource 확인 |
| `rerank_ms > 8000` | reranker 병목 | candidate_budget 축소, intent별 rerank skip, reranker timeout 검토 |
| `payload_build_ms > 3000` | payload 후처리 병목 | related links/sections lazy load 또는 cap 적용 |
| `session_persist_ms > 1000` | persistence 병목 | session store write 횟수 축소, audit log async 검토 |
| stream first delta가 `llm_ms` 이후에만 발생 | 체감 latency 구조 문제 | true token streaming 또는 early progress event 강화 |

## Improvement Candidates

개선은 로그로 병목이 확인된 뒤 적용한다.

### Candidate A. LLM latency reduction

- context chunk 수와 prompt size를 로그에 포함한다.
- starter question처럼 단순 command lookup이면 max token을 더 낮춘다.
- answer shape는 유지하되 장황한 system/user prompt 반복을 줄인다.
- provider round-trip이 큰 경우 model/endpoint 성능을 별도 점검한다.

적용 조건:

- `llm_provider_ms`가 반복적으로 30초 이상
- retrieval은 10초 미만인데 전체가 1분 이상

### Candidate B. Vector fan-out cap

- query signal plan이 만든 embedding query가 너무 많으면 top N만 사용한다.
- metadata filter fallback이 있는 경우 official search를 중복 수행하므로 fallback 조건을 좁힌다.
- 같은 normalized query는 현재 dedupe하지만, 의미상 중복 확장도 줄인다.

적용 조건:

- `embedding_query_count >= 3`
- `vector_ms`가 전체의 30% 이상

### Candidate C. Reranker budget control

- starter question과 command lookup은 reranker candidate budget을 낮춘다.
- concept query만 model rerank를 넓게 쓰고, command query는 heuristic 중심으로 둔다.
- reranker timeout을 명시하고 fallback trace를 남긴다.

적용 조건:

- `rerank_ms > 8000`
- `top1_changed=false`가 반복되는데 reranker 시간이 큼

### Candidate D. Payload lazy work

- related links/sections는 첫 답변 payload에서 최소 개수만 만들고 상세는 별도 endpoint로 lazy load한다.
- citation serialize에 필요한 presentation context를 캐시한다.
- follow-up suggestion은 citation 기반 3개만 빠르게 만들고 retrieval-backed suggestion은 no-answer/clarification에만 제한한다.

적용 조건:

- `payload_related_links_ms` 또는 `payload_related_sections_ms`가 1초 이상 반복

### Candidate E. True streaming or early visible answer

- 현재 stream은 trace event만 먼저 가고 answer delta는 answerer 완료 후 나간다.
- LLM provider가 streaming을 지원하면 token streaming으로 바꾸거나, 최소한 retrieval 완료 후 “근거 찾음/답변 생성 중” 상태를 UI가 표시하도록 한다.

적용 조건:

- LLM이 병목이지만 정확도 때문에 LLM 호출 자체를 줄이기 어려움
- 사용자가 “멈춘 것처럼 보임”을 체감

## Implementation Plan

### Phase 1. Logging foundation

1. 요청 시작 시 `request_id` 생성
2. `/api/chat`, `/api/chat/stream` 양쪽에서 동일 schema의 `chat_latency` 로그 출력
3. `pipeline_trace.timings_ms`와 `server_timings_ms`를 flatten
4. LLM runtime meta, reranker trace, vector runtime 요약을 로그에 포함
5. 민감정보 방지: query 원문은 기본 로그에 넣지 않고 `query_len`, `query_hash`, `route_kind`만 기록

### Phase 2. Sub-step instrumentation

1. `vector.py::search_with_trace`에서 embedding/Qdrant/hydration 시간 분리
2. `retriever_search.py`에서 query fan-out count 기록
3. `pipeline_trace`에 vector subquery 요약을 보존
4. stream endpoint에서 first trace/result/answer delta timing 기록

### Phase 3. Baseline measurement

1. app 최신 이미지 배포
2. starter question 5개와 follow-up 1개를 각각 3회 실행
3. `chat_latency` 로그 수집
4. p50/p95가 아니라 먼저 raw row 기준으로 병목 단계 확인
5. 같은 질문에서 변동이 큰 경우 외부 endpoint 상태 확인

### Phase 4. Targeted optimization

계측 결과 기준으로 하나만 선택해 수정한다.

- LLM 병목이면 prompt/context/max_tokens/streaming
- embedding/vector 병목이면 query fan-out/caching/filter fallback
- reranker 병목이면 budget/skip policy
- payload 병목이면 lazy load/cache
- persistence 병목이면 write 횟수/비동기화

### Phase 5. Quality regression gate

성능 개선 후에도 다음 품질 조건은 유지한다.

- citation 없는 답변 금지
- no-answer guard 유지
- KMSC route_kind는 `study_docs` scope 유지
- official starter는 official docs를 우선 검색
- follow-up은 이전 citation context를 유지하되 문서에 없는 실패 진단을 만들지 않음

## Test Plan

### Unit tests

- latency log flatten helper가 nested timings를 안정적으로 flatten하는지 검증
- query 원문이 log payload에 직접 포함되지 않는지 검증
- vector runtime에 `embedding_ms`, `qdrant_ms`, `hydrate_ms`가 포함되는지 검증
- fan-out count가 중복 query 제거 후 값으로 기록되는지 검증

### Integration tests

- fake answerer 또는 fake LLM으로 `/api/chat` 응답에 `server_timings_ms`와 `pipeline_trace.timings_ms`가 유지되는지 검증
- `/api/chat/stream`에서 trace event와 result event가 정상 순서로 나오는지 검증
- KMSC route_kind 요청이 `preferred_source_scope=study_docs`로 기록되는지 검증

### Manual server validation

운영 서버에서 다음 명령으로 로그가 나오는지 확인한다.

```bash
oc logs deployment/app -n pbs-ocpops --tail=300 | grep chat_latency
```

필수 확인:

- 한 질문당 `chat_latency` 로그 1줄
- `total_ms`가 실제 UI 체감 시간과 크게 어긋나지 않음
- 가장 큰 단계가 눈으로 바로 보임
- query 원문이 로그에 노출되지 않음

## Risk and Decision Log

| 항목 | 리스크 | 결정 |
| --- | --- | --- |
| 로그 민감정보 | 사용자 질문에 고객 정보가 들어갈 수 있음 | 기본 로그에는 원문 query를 넣지 않고 hash/length만 기록 |
| 과도한 로그 | 모든 요청에 상세 로그를 남기면 노이즈 증가 | `event=chat_latency` 한 줄 요약 중심, 상세 trace는 payload/debug 유지 |
| 성능 계측 오버헤드 | 계측 자체가 지연을 만들 수 있음 | `perf_counter` 기반 숫자 계산만 사용하고 외부 호출 금지 |
| 섣부른 최적화 | 품질 회귀 가능 | 병목 확인 전 retrieval/LLM/seed 로직 수정 금지 |
| stream 구조 변경 | 프로토콜/UI 영향 큼 | v0.1.8에서는 먼저 측정, true streaming은 별도 decision으로 분리 |

## Open Questions

- 현재 운영 web은 `/api/chat`과 `/api/chat/stream` 중 어느 endpoint를 starter click에 사용하고 있는가?
- LLM endpoint의 평균/최대 응답 시간은 app 외부에서 직접 측정했을 때도 긴가?
- embedding endpoint가 질문당 몇 번 호출되는가?
- reranker는 현재 모든 RAG 질문에 model rerank를 적용하는가, 아니면 일부만 적용하는가?
- KMSC/study_docs 질문에서 official docs와 동일한 rerank budget을 쓰는 것이 맞는가?
- payload related links/sections는 첫 화면에 반드시 동기 생성해야 하는가?

## Implementation Notes

### 2026-05-18

- Main Workspace chat API 구조를 `/api/chat/stream` 중심으로 정리했다.
  - FAQ starter: `route_kind=official`, `preferred_source_scope=official_docs`
  - learning starter: `route_kind=official`, `preferred_source_scope=official_docs`
  - operations starter: `route_kind=study_docs`, `preferred_source_scope=study_docs`
  - 직접 입력 일반 채팅: route scope 없음
- Main Workspace에서 course 전용 `sendCourseChatStream` 분기, `forceCourseMode`, course artifact 렌더링을 제거했다.
- `/api/v1/course/chat*`는 course viewer/tutor 전용 API로 남기고, main Workspace starter/RAG 경로에서는 사용하지 않게 했다.
- `chat_latency` one-line JSON 로그 생성을 추가했다.
  - 로그는 query 원문을 포함하지 않고 `query_len`만 기록한다.
  - `answerer_ms`, `retrieval_ms`, `bm25_ms`, `vector_ms`, `embedding_ms`, `qdrant_ms`, `rerank_ms`, `llm_provider_ms`, `payload_build_ms`, `session_persist_ms`를 flatten한다.
- `VectorRetriever.search_with_trace()`에 `embedding_ms`, `qdrant_ms`, `hydrate_ms`, `request_timeout_seconds`를 추가했다.
- `retriever_search.py`의 vector runtime aggregate가 subquery별 timing을 합산해 top-level vector runtime에 보존하도록 했다.
- 검색 query 문자열에 route/starter 메타를 직접 붙이던 `_answer_query_from_payload()`를 제거했다.
  - `official seeded question`, `단계별 학습 순서`, `KMSC 실운영 문서 ... source_scope:study_docs` 같은 메타 문구가 embedding/BM25 query로 흘러가지 않게 했다.
  - starter/source scope 정보는 `SessionContext.preferred_source_scope`와 open entities 쪽에서만 유지한다.
- 단순 Node 상태/명령 질문이 NotReady troubleshooting subquery 6개로 확장되지 않도록 `NODE_NOTREADY_RE`를 장애 신호 중심으로 좁혔다.
- 검증:
  - `npm run build` in `apps/web`
  - `uv run python -m pytest tests/test_retrieval_decompose.py tests/test_vector_retriever.py tests/test_chat_latency_logging.py tests/test_study_docs_rag_scope.py tests/test_starter_questions.py tests/test_chat_grounding_quality.py tests/test_query_signal_pipeline.py -q`

### 2026-05-18 Retrieval Expansion Update

- Retrieval fan-out now comes from `query_signal_pipeline.build_query_signal_plan()` at the plan layer.
- The legacy deterministic `decompose_retrieval_queries()` hot path was removed so simple command/status questions do not expand into broad troubleshooting searches.
- Vector search no longer expands each retrieval query a second time. It receives the plan-level `retrieval_queries`, metadata filter, and correction notes directly.
- The per-request trace step is now `query_expansion` and reports `retrieval_queries` rather than internal subquery decomposition.
- Regression gate:
  - `uv run python -m pytest tests/test_retrieval_plan_expansion.py tests/test_vector_retriever.py tests/test_chat_latency_logging.py tests/test_study_docs_rag_scope.py tests/test_starter_questions.py tests/test_chat_grounding_quality.py tests/test_query_signal_pipeline.py -q`

## Done When

- `spec/v0.1.8/planner.md`가 v0.1.8 작업 범위의 기준 문서가 된다.
- 챗봇 요청마다 운영 서버 로그에서 `chat_latency` 한 줄을 확인할 수 있다.
- 1~2분 지연이 LLM, embedding, Qdrant, reranker, payload, persistence 중 어디인지 숫자로 설명할 수 있다.
- 병목별 개선 후보가 계측 수치와 연결되어 있다.
- 성능 개선 전후에 같은 starter question 세트로 비교할 수 있다.
- 품질 회귀 방지 조건이 문서에 명확하다.
