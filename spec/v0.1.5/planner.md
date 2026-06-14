# v0.1.5 RAG Query Signal Pipeline

## 한 줄 요약

v0.1.4에서 만든 metadata/search signal 계약을 실제 RAG pipeline 안으로 녹인다. 별도 "Intent Agent" 서비스를 만들지 않고, 사용자 질문이 들어오면 한 번의 query understanding 단계에서 **신호 추출, 질문 정규화, embedding 검색 문장 2~3개 확장, metadata filter plan, reranker candidate plan**을 함께 만든 뒤 retrieval 품질을 검증한다.

## 배경

v0.1.4는 Qdrant payload와 검색 신호의 구조를 잡았다.

- `source`, `classification`, `chunk`, `search_signals`, `text_fields` nested payload 계약
- `payload_version` 추가
- deterministic `understand_query_signals()` baseline
- Qdrant metadata filter 전달 경로
- remote BGE reranker 기반 최종 ordering

다만 아직 남은 것은 "이 신호를 운영 질문에서 충분히 잘 뽑고, 실제 retrieval 품질이 좋아지는지 검증하는 것"이다.

추가로 요구사항이 바뀌었다. 기존 표현처럼 별도 Intent Agent를 앞단에 두는 방식이 아니라, **RAG pipeline 내부의 Query Understanding 단계**로 구현한다. 즉 사용자는 일반 chat 질문을 보내고, backend RAG pipeline이 내부적으로 한 번에 다음을 처리해야 한다.

1. 사용자 질문 기반 신호 추출
2. 질문 정규화
3. 오타/표기 흔들림 보정
4. embedding 검색용 문장 2~3개 확장
5. metadata filter 후보 생성
6. reranker에 넘길 10개 후보 chunk 구성

## v0.1.4에서 아직 완료되지 않은 사항

1. **실제 34건 corpus 기준 검증**
   - PBS Library 운영 위키/공식문서 34건 전체 본문 기준으로 metadata/search signal 품질을 확인해야 한다.
   - 제목만 보고 분류하지 않는다.

2. **Qdrant 재색인 검증**
   - 새 nested payload가 실제 Qdrant에 들어가는지 확인한다.
   - `payload_version=1` payload와 기존 flat compatibility field가 같이 존재해야 한다.
   - filter-first retrieval이 fallback 없이 동작하는지 확인한다.

3. **신호 추출 품질 검증**
   - PVC Pending, etcd backup, UPI vs Agent install, ImagePullBackOff 같은 질문에서 `domain`, `objects`, `error_states`, `intent_labels`, `answer_shapes`, `execution_target`를 잘 뽑는지 검증한다.

4. **remote reranker 튜닝**
   - v0.1.5에서는 object/error/command family/answer shape/book 후보 boost를 후속 scoring에 쓰지 않는다.
   - fusion 결과 10개 후보를 remote BGE reranker에 넘기고, reranker가 최종 top-5를 고른다.

5. **운영 smoke/eval**
   - unit test는 통과했지만 live OCP/RAG smoke는 아직 별도 검증이 필요하다.
   - citation 품질과 fallback 발생 여부를 함께 확인한다.

## v0.1.5 원칙

1. **별도 Intent Agent를 만들지 않는다.**
   - 이름은 내부적으로 `QuerySignalPipeline` 또는 `QueryUnderstandingPipeline`로 둔다.
   - LLM Agent를 별도 runtime/service로 분리하지 않는다.
   - v0.1.5의 기본 경로는 RAG pipeline 내부의 LLM one-shot signal extraction이다.
   - deterministic/rule-based pipeline은 LLM 장애, timeout, invalid JSON, local test 환경을 위한 fallback이다.

2. **One-shot으로 처리한다.**
   - 신호 추출, 정규화, 오타 보정, query expansion을 여러 단계 LLM 호출로 쪼개지 않는다.
   - 한 번의 LLM 호출 결과가 retrieval plan 전체를 제공해야 한다.
   - LLM은 답변을 생성하지 않고 retrieval-only JSON만 반환한다.

3. **LLM이 hard filter를 직접 확정하지 않는다.**
   - 질문 이해 단계는 신호와 confidence를 만든다.
   - hard metadata filter는 코드가 policy로 만든다.
   - `book_slug`, `objects`, `commands`, `error_states`, `intent_labels`, `answer_shapes`는 hard filter가 아니라 reranker candidate signal이다.
   - LLM output은 allowlist/shape validation을 통과한 뒤에만 사용한다.
   - `classification.domain`은 사용자 의도가 아니라 검색할 문서 영역이다. 장애 질문이어도 대상 object가 명확하면 object 중심 domain을 우선하고, `troubleshoot`는 `intent_labels`에 둔다.
     - `Node NotReady` → `domain=node_ops`, `intent_labels=[troubleshoot, check_status]`
     - `PVC Pending` → `domain=storage`, `intent_labels=[troubleshoot, check_status]`
     - `ImagePullBackOff` → `domain=registry`, `intent_labels=[troubleshoot, check_status]`

4. **질문 정규화와 검색 확장은 답변 생성이 아니다.**
   - 이 단계는 사용자에게 보여줄 답변을 만들지 않는다.
   - retrieval 후보를 더 잘 찾기 위한 구조화만 담당한다.

5. **fallback은 품질 보호 장치다.**
   - metadata filter search가 0건이면 unfiltered vector search fallback을 허용한다.
   - 하지만 fallback이 자주 발생하면 schema/reindex/filter policy 문제로 간주한다.

## 목표 구조

```text
User Question
  -> QuerySignalPipeline.one_shot()
       - single LLM call
       - typo/spacing/alias normalization
       - structured signal extraction
       - confidence scoring
       - 2~3 embedding queries
       - reranker candidate signals
  -> server-side validator
       - domain/intent/answer_shape/command_family allowlist
       - ocp_version/locale fixed
       - unsafe or unknown labels dropped
  -> metadata filter builder
       - qdrant hard filter policy
  -> BM25 search
  -> Qdrant vector search with hard filter
  -> fallback vector search if filtered result is empty
  -> hybrid fusion
  -> remote reranker model
  -> reranker
  -> grounded answer
```

## One-shot 출력 계약

`QuerySignalPipeline`은 아래 형태를 반환한다. 이 구조는 user-facing JSON이 아니라 내부 retrieval plan이다.

```json
{
  "raw_query": "PVC가 Pending이면 뭐부터 확인해야 해?",
  "normalized_query": "PVC가 Pending이면 무엇부터 확인해야 해?",
  "correction_notes": [
    {
      "type": "spacing_or_typo",
      "from": "뭐부터",
      "to": "무엇부터"
    }
  ],
  "classification": {
    "domain": "storage",
    "subdomains": ["pvc", "storageclass"],
    "platform": "any_platform",
    "ocp_version": "4.20",
    "locale": "ko",
    "book_slug_candidates": ["storage"]
  },
  "search_signals": {
    "primary_topics": ["PVC", "StorageClass"],
    "secondary_topics": ["volume binding", "storage provisioning"],
    "objects": ["PVC", "PV", "StorageClass"],
    "operators": [],
    "components": ["CSI Driver", "scheduler"],
    "commands": ["oc get pvc", "oc describe pvc"],
    "command_families": ["oc_get", "oc_describe"],
    "error_states": ["Pending"],
    "intent_labels": ["check_status", "troubleshoot"],
    "answer_shapes": ["checklist", "command", "troubleshooting_flow"],
    "cluster_phase": ["day2", "incident"],
    "execution_target": ["cluster_admin_cli"]
  },
  "confidence": {
    "domain": 0.95,
    "objects": 0.97,
    "commands": 0.86,
    "error_states": 0.96,
    "intent_labels": 0.92,
    "answer_shapes": 0.88,
    "execution_target": 0.84
  },
  "embedding_queries": [
    "PVC Pending 상태 확인 StorageClass provisioning",
    "PVC Pending troubleshooting oc get pvc oc describe pvc",
    "PersistentVolumeClaim Pending volume binding storage provisioning"
  ],
  "metadata_filter": {
    "must": [
      {"key": "source.enabled_for_chat", "match": {"value": true}},
      {"key": "source.review_status", "match": {"value": "approved"}},
      {"key": "source.citation_eligible", "match": {"value": true}},
      {"key": "classification.locale", "match": {"value": "ko"}},
      {"key": "classification.ocp_version", "match": {"value": "4.20"}},
      {"key": "chunk.navigation_only", "match": {"value": false}},
      {"key": "classification.domain", "match": {"value": "storage"}}
    ]
  }
}
```

## 질문 정규화 범위

v0.1.5의 정규화는 위험한 의미 변환을 하지 않는다. 검색 recall을 높이는 보정만 한다.

### 허용

- 대소문자 통일: `ocp`, `OCP`, `openshift` → `OpenShift Container Platform` 신호 추가
- 한글/영문 객체명 alias:
  - `피브이씨`, `pvc`, `PersistentVolumeClaim` → `PVC`
  - `파드`, `pod` → `Pod`
  - `라우트`, `route` → `Route`
- 흔한 상태값 표기:
  - `이미지풀백오프`, `Image Pull Back Off` → `ImagePullBackOff`
  - `not ready`, `NotReady`, `노트레디` → `NotReady`
- 조사/어미 제거 기반 매칭:
  - `PVC가`, `Pending인데`, `UPI랑`
- 검색용 동의어 추가:
  - `설치` → `install`, `installation`
  - `백업` → `backup`
  - `확인` → `check`, `verify`, `status`

### 금지

- 사용자가 말하지 않은 platform을 확정하지 않는다.
- 실제 명령을 모르면 command를 invent하지 않는다.
- book slug를 hard filter로 확정하지 않는다.
- 답변 문장을 생성하지 않는다.

## Embedding 검색 문장 확장 규칙

기본적으로 2~3개만 만든다. 너무 많이 만들면 latency와 false positive가 늘어난다.

1. **Normalized intent query**
   - 사용자 원문 + 핵심 객체 + 상태 + domain term
   - 예: `PVC Pending 상태 확인 StorageClass provisioning`

2. **Command/troubleshooting query**
   - 명령 요청/장애/상태 확인 intent가 있으면 command family와 대표 명령을 포함
   - 예: `PVC Pending troubleshooting oc get pvc oc describe pvc`

3. **English/cross-lingual query**
   - 공식문서가 영어 keyword를 많이 포함하므로 주요 객체/상태를 영어 표현으로 확장
   - 예: `PersistentVolumeClaim Pending volume binding storage provisioning`

질문이 단순 개념 설명이면 2개만 만든다.

```text
OCP가 뭐야?
  1. OpenShift Container Platform overview concept
  2. OCP Kubernetes platform architecture
```

## Metadata filter policy

항상 hard filter로 넣는 값:

- `source.enabled_for_chat = true`
- `source.review_status = approved`
- `source.citation_eligible = true`
- `classification.locale = ko`
- `classification.ocp_version = 4.20`
- `chunk.navigation_only = false`

confidence가 높을 때만 넣는 값:

- `classification.domain` when `confidence.domain >= 0.85`
- `classification.platform` when `confidence.platform >= 0.90`

hard filter 금지:

- `classification.book_slug`
- `classification.book_slug_candidates`
- `search_signals.objects`
- `search_signals.commands`
- `search_signals.command_families`
- `search_signals.error_states`
- `search_signals.intent_labels`
- `search_signals.answer_shapes`
- `search_signals.cluster_phase`
- `search_signals.execution_target`

금지 이유: 이 값들은 chunk마다 누락될 수 있고, 너무 강하게 걸면 정답 문서를 검색 전에 제거할 수 있다. 대신 query expansion과 reranker 후보 구성에만 사용한다.

## 구현 작업

### Step 1. QuerySignalPlan 모델 추가

새 내부 모델을 추가한다.

후보 파일:

- `src/play_book_studio/retrieval/query_signal_pipeline.py`

핵심 dataclass:

- `QuerySignalPlan`
- `QueryCorrection`
- `EmbeddingQuery`

기존 `StructuredQuerySignals`는 유지하되, v0.1.5에서는 `QuerySignalPlan`이 더 넓은 상위 계약이 된다.

### Step 2. LLM one-shot builder 구현

`build_query_signal_plan(query, context)`를 추가한다.

담당:

- LLM one-shot 호출로 typo/alias normalization, structured signal extraction, `embedding_queries` 2~3개를 한 번에 받는다.
- LLM output은 JSON object만 허용한다.
- LLM이 실패하거나 invalid JSON을 반환하면 기존 deterministic `understand_query_signals()` + rule-based enrichment를 fallback으로 사용한다.
- metadata filter는 LLM output을 그대로 쓰지 않고 server-side policy로 생성한다.

이 함수는 `llm_client`가 있으면 LLM을 호출하고, 없으면 deterministic fallback만 사용한다.

### Step 3. retrieval pipeline 연결

현재 vector search는 `rewritten_queries`를 순회한다. v0.1.5에서는 `rewritten_queries`와 `embedding_queries`를 명확히 구분한다.

- BM25:
  - `normalized_query`
  - 필요하면 기존 rewritten query 유지
- Vector:
  - `embedding_queries`
  - 각 query에 같은 metadata filter 적용
- Reranker:
  - fusion 결과를 10개 후보 chunk로 맞추고 remote BGE reranker가 최종 top-5를 고른다.

### Step 4. trace 강화

retrieval trace에 아래를 남긴다.

- `normalized_query`
- `correction_notes`
- `embedding_queries`
- `metadata_filter_applied`
- `metadata_filter_fallback`
- `reranker_trace_summary`

사용자에게 그대로 노출하지 않아도, 운영 디버깅에는 보여야 한다.

### Step 5. 신호 추출 테스트

다음 질문을 fixture로 고정한다.

1. `PVC가 Pending인데 뭐 확인해야 해?`
   - domain: `storage`
   - objects: `PVC`, `StorageClass`
   - error_states: `Pending`
   - intent_labels: `check_status`, `troubleshoot`
   - embedding query 2개 이상

2. `etcd 백업은 어느 노드에서 실행해?`
   - domain: `etcd` 또는 `backup_restore`
   - objects/topics: `etcd`
   - intent_labels: `backup`, `identify_execution_target`
   - execution_target: `control_plane_node`

3. `UPI랑 agent-based 설치 차이 알려줘`
   - domain: `install`
   - platform 후보: `bare_metal`, `agent_based`
   - intent_labels: `install`, `compare_options`
   - answer_shapes: `decision_guide`

4. `이미지풀백오프 뜨는데 pull secret 어디 봐?`
   - domain: `registry` 또는 `troubleshooting`
   - objects: `Pod`, `Secret`
   - error_states: `ImagePullBackOff`
   - commands: `oc describe pod`, pull secret 관련 command 후보

5. `노드가 노트레디면 처음에 뭐 봐야 함?`
   - domain: `node_ops`
   - objects: `Node`
   - error_states: `NotReady`
   - commands: `oc get nodes`, `oc describe node`

### Step 6. retrieval 품질 검증

34건 corpus merge 이후 실행한다.

검증 항목:

- Qdrant payload에 nested metadata 존재
- filter-first vector search가 0건 fallback 없이 최소 80% 이상 동작
- fallback 발생 시 trace에 이유가 남음
- top-5 안에 기대 book/document가 포함
- top citation이 질문 intent와 맞음
- command 질문에서는 command-bearing chunk가 citation에 포함

### Step 7. tuning

실제 결과를 보고 다음 값을 조정한다.

- `confidence.domain` threshold
- object match boost
- error state boost
- command family boost
- answer shape boost
- book candidate boost
- embedding query 개수

## Acceptance Criteria

1. `build_query_signal_plan()`이 한 번의 호출로 normalized query, correction notes, classification, search signals, 2~3 embedding queries, metadata filter, metadata filter를 반환한다.
2. 별도 Intent Agent runtime/service 없이 RAG pipeline 내부에서 LLM one-shot extraction으로 동작한다.
3. 기존 `understand_query_signals()` 테스트는 유지되며, v0.1.5 query signal plan 테스트가 추가된다.
4. vector search는 `embedding_queries`를 사용하고, Qdrant metadata filter를 적용한다.
5. filtered vector search 0건 fallback은 유지하되 trace로 관측 가능하다.
6. 34건 corpus 기준 주요 질문 5개에서 신호 추출이 기대값과 맞는다.
7. Qdrant 재색인 후 주요 질문의 top-5 retrieval에 기대 문서가 들어온다.
8. PowerShell/Windows 작업 시 UTF-8 출력과 파일 인코딩 정책을 유지한다.
9. LLM output은 allowlist validation을 거치며, unknown domain/intent/answer_shape/command_family는 hard filter나 reranker candidate signal로 사용하지 않는다.

## Out of Scope

- 별도 LLM Intent Agent 서비스 구현
- multi-turn query planner
- 답변 생성 프롬프트 대규모 개편
- 새로운 외부 dependency 추가
- dev/prod 배포 자동화 구조 변경

## 검증 명령

초기 구현 후:

```powershell
chcp 65001 | Out-Null
pytest tests/test_query_understanding.py tests/test_chat_grounding_quality.py tests/test_vector_retriever.py
```

v0.1.5 테스트 추가 후:

```powershell
chcp 65001 | Out-Null
pytest tests/test_query_signal_pipeline.py tests/test_retriever_pipeline.py
```

OCP 배포 manifest 변경이 생기면:

```powershell
chcp 65001 | Out-Null
kubectl kustomize deploy/openshift
```

## 작업 순서

1. `QuerySignalPlan` dataclass와 LLM one-shot builder 추가
2. LLM JSON prompt와 output validator 추가
3. deterministic fallback 유지
4. metadata filter/reranker candidate signal builder 분리
5. retrieval vector search가 `embedding_queries`를 쓰도록 연결
6. trace에 query signal plan 요약 추가
7. unit test 추가
8. 34건 corpus merge 이후 Qdrant reindex + retrieval smoke

## 현재 결정

- v0.1.5 브랜치: `feat/v0.1.5/rag-query-signal-pipeline`
- v0.1.5는 `dev` 최신 기준에서 진행한다.
- 다른 사용자의 `data` 폴더 정리 merge는 v0.1.5에서 pull/merge 후 반영한다.
- Query understanding은 "Agent"가 아니라 "RAG pipeline 내부 LLM one-shot signal processing"으로 부른다.

## 진행 로그

- 2026-05-15: `QuerySignalPlan` one-shot builder를 추가했다. 기존 `understand_query_signals()`를 deterministic baseline으로 사용하고, 그 위에서 alias/오타 정규화, domain-specific enrichment, 2~3개 embedding query 생성, metadata filter, reranker candidate signal projection을 한 번에 만든다.
- 2026-05-15: vector search가 단일 `vector_query` 대신 `QuerySignalPlan.embedding_queries`를 순회하도록 연결했다. 각 embedding query는 같은 metadata filter를 쓰며, filtered search 0건 fallback과 trace metadata는 유지한다.
- 2026-05-15: 대표 질문 5개(PVC Pending, etcd backup 실행 위치, UPI vs agent-based 설치 비교, ImagePullBackOff, Node NotReady)를 `tests/test_query_signal_pipeline.py`로 고정했다.
- 2026-05-15: focused verification 통과: `pytest tests/test_query_signal_pipeline.py tests/test_query_understanding.py tests/test_vector_retriever.py tests/test_chat_grounding_quality.py` → 58 passed.
- 2026-05-15: 요구사항을 반영해 v0.1.5 기본 방향을 deterministic 중심에서 LLM one-shot 중심으로 수정했다. 질문 정규화, 오타/별칭 보정, 신호 추출, query expansion은 한 번의 LLM 호출로 처리하고, deterministic logic은 fallback으로 둔다.
- 2026-05-15: LLM prompt와 validator에 domain policy를 추가했다. `classification.domain`은 troubleshooting intent가 아니라 metadata filter용 문서 영역으로 취급하며, Node NotReady는 `node_ops`, PVC Pending은 `storage`, ImagePullBackOff는 `registry`를 우선한다.
## 2026-05-15 Reranker Revision

Latest v0.1.5 direction:

- Do not build or expose follow-up `rank_signals`.
- Do not use object/error/command/answer-shape metadata boosts after fusion.
- Query understanding still extracts normalized query, correction notes, classification, search signals, and 2-3 embedding queries in one shot.
- Metadata filtering remains server-side policy. LLM output only provides validated hints.
- Node NotReady queries scope both `classification.domain=node_ops` and `classification.domain=troubleshooting` so node operations docs and troubleshooting docs can both be retrieved.
- Upstream retrieval should produce about 10 candidate chunks.
- Remote BGE reranker receives those candidates and returns the final top 5 chunks for answer generation.
- `RERANKER_BASE_URL` must point to a real reranker endpoint. It must not silently fall back to the embedding endpoint.

Updated flow:

```text
User Question
  -> QuerySignalPipeline.one_shot()
       - normalize typo/alias
       - extract classification/search signals
       - expand 2-3 embedding queries
       - build server-side metadata filter
  -> BM25 + vector retrieval
  -> fusion output: 10 candidate chunks
  -> remote BGE reranker
  -> top 5 grounded chunks
  -> grounded RAG answer
```

