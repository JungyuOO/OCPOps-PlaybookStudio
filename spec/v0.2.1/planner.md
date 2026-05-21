# v0.2.1 - RAG Data Foundation Planning

## Goal

v0.2.1의 목표는 현재 RAG 품질 저하의 원인이 되는 공식 문서 데이터 문제를 정리하고, v0.2.2 이후 구현할 corpus audit, LLM enrichment, official corpus rebuild, enriched retrieval 작업의 기준을 확정하는 것이다.

이 버전에서는 production 동작을 바꾸지 않는다. Qdrant 재색인, full corpus enrichment, OCP runtime collector, Pod/Alert 분석 답변은 v0.2.2 이후 버전에서 처리한다.

## Current Problem

현재 PlaybookStudio RAG는 일반적인 chatbot RAG와 다르게 데이터 자체의 검색 준비도가 낮다. 공식 문서 chunk가 retrieval-ready하지 않기 때문에, 후단에서 keyword boost, book_slug boost, hard-coded matcher로 recall을 보정하고 있다.

문제의 핵심은 다음과 같다.

- 질문이 사전에 정의된 keyword/boost list에 없으면 적절한 chunk를 찾기 어렵다.
- 원본 `chunks.jsonl`은 viewer/citation 중심 metadata는 있으나 검색용 metadata가 부족하다.
- `embedding_text`, `normalized_text`, `intent_labels`, `best_for_questions`, `primary_topics`, `answer_shapes`가 부족하거나 없다.
- `cli_commands`에는 dirty command가 포함되어 있다.
- official docs와 manual synthesis가 같은 corpus에 섞여 있어 source routing과 trust policy가 불명확하다.
- OpenShift Lightspeed처럼 현재 resource, Alert, terminal context를 결합하는 구조는 아직 없다.

## Verified Data Findings

기준 파일:

```text
corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl
```

확인된 상태:

| Area | Finding | Impact |
| --- | --- | --- |
| Source metadata | `book_slug`, `source_id`, `source_url`, `viewer_path`, `section_id`는 존재 | citation/viewer 연결에는 사용 가능 |
| Embedding text | 원본 `chunks.jsonl`에 `embedding_text` 없음 | vector embedding 입력이 import 단계 임시 정제에 의존 |
| Normalized text | 원본 `chunks.jsonl`에 `normalized_text` 없음 | BM25/keyword 검색 품질이 약함 |
| Search signals | `intent_labels`, `best_for_questions`, `primary_topics`, `answer_shapes` 없음 | 운영 질문과 chunk 의미 매칭이 약함 |
| Semantic role | `semantic_role`이 비어 있음 | 절차/개념/경고/검증/명령 역할 구분이 약함 |
| Command metadata | `oc\n[/CODE]` 같은 dirty command 반복 | command boost와 search signal에 noise 유입 |
| Corpus mixing | official doc와 `manual_synthesis`가 섞임 | source scope/trust/citation 정책 불명확 |
| Fixed metadata | `product`, `version`, `locale`, `tenant_id`, `workspace_id` 등 대부분 고정 | 검색 품질에는 거의 기여하지 않음 |

## v0.2.1 Scope

### Included

1. 공식 corpus 품질 audit 기준 정의
2. enriched corpus schema 초안 정의
3. 기존 `chunks.jsonl` 보강 vs 공식 문서 원본 재수집 판단 기준 정의
4. LLM enrichment contract 초안 작성
5. deterministic validator 기준 정의
6. v0.2.x eval 기준 재정의
7. runtime context ERD에서 다룰 범위만 초안화

### Excluded

- audit CLI 구현
- LLM enrichment batch runner 구현
- full corpus enrichment
- 공식 문서 원본 재수집
- vector/BM25 retrieval index 재생성
- retrieval pipeline 교체
- OCP runtime collector 구현
- Pod/Event/Log/Alert 분석 답변 구현
- feedback loop 구현

## Work Items

### 1. Corpus Audit Criteria

v0.2.2에서 구현할 audit tool의 기준을 확정한다.

필수 audit 항목:

- row count
- field coverage
- duplicate chunk id
- empty `embedding_text`
- empty `normalized_text`
- empty `semantic_role`
- dirty command count
- source_url/viewer_path validity
- source_lane/source_type distribution
- official/manual synthesis mixing
- token count mismatch
- repeated section/anchor concentration
- navigation-only chunk ratio

### 2. Enriched Corpus Schema Draft

원본 chunk와 검색용 chunk를 분리한다.

```text
raw_chunk
  - 원문 보존
  - markdown/viewer/citation 용도
  - source_url, viewer_path, section_path 유지

retrieval_chunk
  - clean embedding_text
  - normalized_text
  - search_signals
  - best_for_questions
  - parent/child linkage
```

필수 schema 영역:

- `source`
- `chunk`
- `text_fields`
- `search_signals`
- `quality`

### 3. Rebuild Decision Criteria

v0.2.2 audit 결과를 보고 v0.2.3에서 어떤 전략을 선택할지 결정할 기준을 만든다.

가능한 결정:

```text
A. 기존 chunks.jsonl 유지 + full enrichment
B. 공식 문서 원본 재수집 + 새 chunking + enrichment
C. official docs와 manual_synthesis corpus 분리
D. 특정 book_slug만 partial rebuild
```

판단 기준:

- source text 품질
- translation/review status
- source_url/viewer_path 신뢰도
- command metadata 오염도
- chunk boundary 품질
- manual_synthesis 혼입 영향
- 재수집 비용과 citation 유지 가능성

### 4. LLM Enrichment Contract

LLM은 새 지식을 만드는 용도가 아니라 검색용 metadata와 질문 표현을 생성하는 용도로만 사용한다.

입력:

- chunk id
- book slug
- section path
- chunk type
- source URL
- viewer path
- cleaned text
- deterministic 후보 commands/objects/operators/errors

출력:

- summary
- primary_topics
- secondary_topics
- objects
- operators
- commands
- error_states
- intent_labels
- answer_shapes
- best_for_questions
- embedding_text
- quality_warnings

금지 사항:

- 원문에 없는 command 생성
- 위험한 조치 생성
- source_url/viewer_path 변경
- unsupported object/operator를 확정값처럼 생성
- answer text를 chunk metadata에 과도하게 포함

### 5. Deterministic Validator Criteria

LLM output은 validator를 통과해야 한다.

검증 기준:

- JSON schema valid
- required keys present
- `source_url`, `viewer_path`, `chunk_id` 보존
- `embedding_text` 길이 제한
- `commands` dirty marker 제거
- 원문 근거 없는 command warning 또는 제거
- 너무 일반적인 topic 제거
- `best_for_questions` 개수 제한
- quality warning 기록

### 6. Evaluation Criteria Redefinition

기존 pass/fail만으로는 RAG 품질을 설명하기 어렵다. v0.2.x에서는 평가 축을 분리한다.

평가 축:

- retrieval top-1/top-5/top-10 hit
- citation correctness
- source scope correctness
- answer usefulness
- command correctness
- no-answer appropriateness
- clarification overuse
- dirty metadata exposure
- latency impact

### 7. Runtime Context ERD Boundary

v0.2.5에서 상세 설계할 runtime context ERD의 범위만 v0.2.1에서 정한다.

포함 후보:

- OCP cluster connection
- user workspace
- namespace binding
- resource snapshot
- Pod snapshot
- Event
- Log segment
- Alert
- Metric summary
- context collection run
- context pack

저장 금지 후보:

- Secret raw value
- token/password
- kubeconfig raw content
- 다른 사용자 namespace data
- 무기한 full logs

## Deliverables

v0.2.1에서 남길 문서:

- `spec/v0.2.1/planner.md`
- `spec/v0.2.1/enriched-corpus-schema.md`
- `spec/v0.2.1/rag-data-audit.md`
- `spec/v0.2.1/llm-enrichment-contract.md`
- `spec/v0.2.1/runtime-context-erd-draft.md`

현재 파일은 전체 v0.2.x 로드맵이 아니라 v0.2.1 작업 범위만 정의한다. 이후 구현 계획은 각 버전 planner를 따른다.

## Follow-up Version References

- [v0.2.2 Corpus Audit and LLM Enrichment Prototype](../v0.2.2/planner.md)
- [v0.2.3 Official Corpus Rebuild and Full Enrichment](../v0.2.3/planner.md)
- [v0.2.4 Enriched Retrieval Pipeline Replacement](../v0.2.4/planner.md)
- [v0.2.5 Runtime Context ERD and Storage](../v0.2.5/planner.md)
- [v0.2.6 OCP Runtime Context Collector](../v0.2.6/planner.md)
- [v0.2.7 Operations Assistant Answer Flow](../v0.2.7/planner.md)
- [v0.2.8 Feedback Loop and Continuous Evaluation](../v0.2.8/planner.md)
- [v0.2.9 Operation Watcher and Notifications](../v0.2.9/planner.md)

## Acceptance Criteria

- v0.2.1의 범위가 계획/스키마/판단 기준으로 제한되어 있다.
- 구현 작업은 v0.2.2 이후로 분리되어 있다.
- 기존 `chunks.jsonl`의 문제와 audit 기준이 명확하다.
- enriched corpus가 어떤 구조를 가져야 하는지 초안이 있다.
- LLM enrichment와 validator의 역할이 분리되어 있다.
- official corpus 재사용/재수집 판단 기준이 존재한다.

## Non-goals

- production RAG behavior 변경
- corpus artifact 생성
- Qdrant collection 변경
- OpenShift runtime data 수집
- terminal/Pod/Alert 분석 답변
- UI 변경

## Completion Check

v0.2.1은 구현 버전이 아니라 준비 버전이다. 완료 기준은 v0.2.2 구현자가 audit tool과 enrichment prototype을 만들 수 있을 정도로 기준, schema, contract, 판단 조건이 정리되는 것이다.
