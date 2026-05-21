# v0.2.4 - Enriched Retrieval Pipeline Replacement Planner

## Goal

v0.2.4의 목표는 v0.2.3에서 만든 enriched official corpus를 실제 검색 경로에 연결하여, keyword boost와 hard-coded matcher 의존도를 줄이는 것이다. 이 버전에서는 vector backend를 Qdrant에 고정하지 않고, Qdrant와 pgvector를 비교할 수 있는 backend-neutral retrieval path를 설계한다.

## Background

현재 retrieval은 데이터가 부족한 상태를 후단 scoring으로 보정한다.

- 질문이 특정 keyword list에 걸려야 좋은 chunk를 찾는다.
- metadata filter보다 book_slug/keyword boost가 품질을 좌우한다.
- embedding target text가 운영 질문 표현을 충분히 포함하지 않는다.
- command/object/error intent가 query와 chunk 양쪽에서 일관된 schema로 비교되지 않는다.

v0.2.4에서는 enriched corpus의 `embedding_text`, `normalized_text`, `search_signals`, `best_for_questions`를 검색의 중심 데이터로 사용한다.

## Scope

### Included

- enriched corpus 기반 vector payload upsert
- Qdrant vs pgvector A/B benchmark
- `normalized_text` 기반 BM25 재생성
- query analyzer 개편
- metadata filter/soft scoring 개편
- reranker 입력 정리
- source scope routing 정리
- benchmark/eval 자동화

### Excluded

- official corpus full enrichment 생성
- OCP runtime context 수집
- Pod/Event/Log/Alert 분석 답변
- feedback loop 저장소
- UI redesign

## Work Items

### 1. Enriched Vector Payload Upsert

Vector payload를 enriched schema 기준으로 만든다. 초기에는 기존 Qdrant 경로를 유지하되, pgvector 후보와 같은 payload contract를 쓰도록 backend-neutral shape를 만든다.

Required payload sections:

```json
{
  "source": {
    "corpus_scope": "official_docs",
    "source_type": "official_doc",
    "book_slug": "storage",
    "source_url": "...",
    "viewer_path": "..."
  },
  "chunk": {
    "chunk_type": "troubleshooting",
    "semantic_role": "diagnosis",
    "chunk_role": "leaf",
    "parent_chunk_id": ""
  },
  "search_signals": {
    "objects": [],
    "operators": [],
    "commands": [],
    "command_families": [],
    "error_states": [],
    "intent_labels": [],
    "answer_shapes": [],
    "best_for_questions": []
  },
  "text_fields": {
    "embedding_text": "...",
    "normalized_text": "..."
  }
}
```

Indexing rule:

- vector embedding target = `text_fields.embedding_text`
- payload text for display/citation = clean text or parent context
- raw markdown remains available for viewer/citation
- backend-specific storage must not change retrieval semantics

Candidate backends:

```text
QdrantVectorBackend
PgVectorBackend
```

### 1a. Qdrant vs pgvector Benchmark

PostgreSQL is already the system of record. This version must compare whether pgvector can replace Qdrant as the default backend.

Benchmark dimensions:

- top-1/top-5/top-10 retrieval hit
- source scope correctness
- metadata filtering correctness
- p50/p95 latency
- index build time
- deploy complexity
- backup/restore complexity
- operational failure modes

Decision outputs:

```text
keep_qdrant_default
use_pgvector_default
support_both_backends
defer_decision
```

### 2. BM25 Index Rebuild

BM25는 raw markdown이 아니라 `normalized_text`를 기준으로 만든다.

Index inputs:

- `normalized_text`
- title/heading
- section_path
- commands
- objects
- error_states
- best_for_questions

BM25 should not index:

- raw HTML
- docs URLs
- code markers
- repeated boilerplate
- dirty commands

### 3. Query Analyzer Refactor

사용자 질문을 enriched schema와 같은 형태로 분석한다.

Output:

```json
{
  "intent": "troubleshooting",
  "objects": ["Pod"],
  "operators": [],
  "commands": ["oc logs"],
  "error_states": ["CrashLoopBackOff"],
  "answer_shape": "checklist",
  "needs_runtime_context": true,
  "source_preferences": ["official_docs", "playbook"]
}
```

Analyzer principles:

- keyword list만으로 결정하지 않는다.
- LLM analyzer 또는 hybrid analyzer를 사용할 수 있다.
- deterministic guard는 routing fallback과 validation에만 사용한다.
- unknown term은 버리지 말고 query expansion 후보로 유지한다.

### 4. Metadata Filter and Soft Scoring

hard filter는 최소화하고 soft scoring을 중심으로 한다.

Score inputs:

- vector score
- BM25 score
- object overlap
- command family overlap
- error state overlap
- intent label match
- answer shape match
- book_slug prior
- source trust
- citation eligibility

Penalty inputs:

- platform conflict
- source scope mismatch
- dirty/invalid payload
- navigation-only chunk
- manual_synthesis when official-only requested

### 5. Reranker Input Cleanup

reranker에는 raw chunk가 아니라 비교에 필요한 필드만 넣는다.

Reranker input:

- user query
- heading/title
- summary
- embedding_text excerpt
- search_signals
- source type
- commands/errors

Avoid:

- long raw markdown
- HTML/table noise
- repeated source boilerplate
- unrelated parent section overload

### 6. Source Scope Routing

official, manual synthesis, user upload, study docs를 명확히 분리한다.

Routing principles:

- official starter questions -> official docs
- user uploaded document question -> selected document first
- study/course question -> study docs/course collection
- generic OCP operation question -> official docs + playbook if enabled
- manual_synthesis should be identifiable and not silently treated as pure official doc

### 7. Benchmark and Regression Automation

v0.1.x에서 수집한 질문과 새 Lightspeed-style 질문을 함께 평가한다.

Metrics:

- retrieval top-1/top-5/top-10 hit
- grounded answer rate
- citation correctness
- source scope correctness
- command correctness
- no-answer rate
- clarification overuse rate
- latency impact

Reports:

- before/after v0.2.3 corpus
- old retrieval vs enriched retrieval
- keyword boost enabled/disabled comparison
- failure case list

## Deliverables

- enriched vector indexing path
- Qdrant vs pgvector benchmark report
- enriched BM25 index path
- query analyzer output schema
- metadata scoring implementation plan/report
- source routing report
- benchmark report

## Acceptance Criteria

- enriched `embedding_text` is the vector embedding source.
- vector retrieval is not hard-coded to a single backend's assumptions.
- Qdrant and pgvector are compared before changing the default backend.
- BM25 uses `normalized_text` and structured search signals.
- retrieval quality does not depend primarily on hard-coded keyword boosts.
- official/manual/user upload scopes are separated in retrieval traces.
- benchmark report shows top-k retrieval and grounded answer comparison.
- fallback to old retrieval is possible during rollout.

## Rollout Plan

1. Create separate enriched Qdrant collection or pgvector candidate table.
2. Run benchmark against old Qdrant, enriched Qdrant, and pgvector candidate where available.
3. Enable enriched retrieval behind config flag.
4. Compare production-like smoke results.
5. Switch default backend only after regression and operations review.

Suggested flags:

```text
RAG_USE_ENRICHED_OFFICIAL_CORPUS=false
RAG_ENRICHED_QDRANT_COLLECTION=openshift_docs_enriched
RAG_VECTOR_BACKEND=qdrant
RAG_PGVECTOR_ENABLED=false
RAG_USE_ENRICHED_BM25=false
RAG_DISABLE_LEGACY_KEYWORD_BOOST=false
```

## Risks

| Risk | Mitigation |
| --- | --- |
| New retrieval reduces known benchmark quality | dual collection and rollback flag |
| Enriched metadata overfits sample questions | broad benchmark and failure review |
| Reranker latency increases | candidate budget and timing trace |
| Source scope confusion persists | trace every selected citation source |
| Removing boost too early hurts recall | staged boost reduction, not immediate deletion |

## Completion Check

v0.2.4 is complete when enriched corpus is actually used by retrieval in a controlled path, benchmark evidence exists, and legacy keyword boost can be reduced without major regression.
