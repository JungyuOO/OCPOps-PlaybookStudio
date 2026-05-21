# v0.2.3 - Official Corpus Rebuild and Full Enrichment Planner

## Goal

v0.2.3의 목표는 v0.2.2에서 검증한 audit/enrichment 결과를 바탕으로 production에 투입 가능한 official corpus artifact를 만드는 것이다. 이 버전에서는 기존 `chunks.jsonl`을 전량 보강하거나, 품질이 부족하다고 판단되면 공식 문서 원본부터 다시 수집하여 새로운 official corpus를 만든다.

## Decision Input

v0.2.3는 v0.2.2의 rebuild decision report를 시작점으로 삼는다.

가능한 결정:

- 기존 `chunks.jsonl` 유지 + full LLM enrichment
- 공식 문서 원본 재수집 + 새 chunking + LLM enrichment
- official docs와 manual synthesis corpus 분리
- 특정 book_slug만 재수집

## Scope

### Included

- official corpus acquisition/rebuild 경로 확정
- full corpus cleanup
- full LLM enrichment
- parent-child chunk linkage
- enriched corpus artifact 생성
- corpus quality gate
- DB import 경로 연결

### Excluded

- retrieval ranking 알고리즘 교체
- production Qdrant collection 전환
- OCP runtime context ERD 구현
- Pod/Event/Log/Alert 수집
- UI 변경

## Work Items

### 1. Official Source Strategy Finalization

v0.2.2 결과에 따라 source strategy를 확정한다.

Evaluation criteria:

- 기존 source text의 encoding/translation 품질
- section_path/source_url/viewer_path 신뢰도
- command metadata 오염도
- manual_synthesis 혼입 영향
- source 재수집 비용
- citation linkage 유지 가능성

Output:

```text
source_strategy:
  mode: enrich_existing | rebuild_from_source | partial_rebuild
  included_book_slugs: []
  excluded_book_slugs: []
  manual_synthesis_policy: separate | keep | drop
```

### 2. Full Corpus Cleanup

전체 official corpus에 deterministic cleanup을 적용한다.

Cleanup targets:

- code/table/markdown marker
- dirty command
- HTML/docs URL noise
- duplicated title/body prefix
- navigation-only chunk
- broken placeholder
- repeated boilerplate

Artifacts:

- `cleaned_chunks.jsonl`
- cleanup report
- rejected/flagged row report

### 3. Full LLM Enrichment

전체 또는 선택된 official corpus에 LLM enrichment를 실행한다.

Batch requirements:

- resumable batch run
- idempotent output
- per-row status
- failed row retry
- cost/time tracking
- prompt version tracking
- model/provider tracking

Output fields:

- `embedding_text`
- `normalized_text`
- `search_signals`
- `best_for_questions`
- `semantic_role`
- `summary`
- `quality_warnings`

### 4. Parent-Child Chunk Linkage

검색과 답변 근거를 분리하기 위해 parent-child 구조를 만든다.

```text
leaf chunk
  - small retrieval target
  - enriched embedding_text

parent chunk
  - section-level answer context
  - citation display
  - child_chunk_ids
```

Rules:

- 같은 `source_id + section_id + anchor` 기준으로 parent 구성
- parent text는 중복 block 제거
- navigation-only leaf는 답변 context에서 제외 가능
- child chunk는 source citation을 parent와 공유

### 5. Enriched Corpus Artifact Layout

production import가 사용할 산출물 구조를 확정한다.

```text
corpus/sources/official/enriched-v020/
  raw_chunks.jsonl
  cleaned_chunks.jsonl
  retrieval_chunks.jsonl
  parent_chunks.jsonl
  text_layers.jsonl
  corpus_quality_report.json
  enrichment_manifest.json
```

`enrichment_manifest.json` includes:

- source input path
- source strategy
- schema version
- prompt version
- model
- generated_at
- row counts
- warning counts
- rejected counts

### 6. Corpus Quality Gate

full artifact는 import 전에 quality gate를 통과해야 한다.

Minimum checks:

- `embedding_text` coverage >= 98%
- `normalized_text` coverage >= 98%
- `search_signals` coverage >= target threshold
- dirty command count = 0 for blocked patterns
- source_url/viewer_path preserved
- duplicate chunk id = 0
- JSON schema validation pass
- sample manual review pass

### 7. Import Path Connection

기존 `official-gold-import` 또는 새 import command가 enriched artifact를 읽을 수 있게 한다.

Requirements:

- 기존 production seed와 병행 가능
- dry-run import 지원
- import count report
- DB `document_chunks.embedding_text`에 enriched `embedding_text` 저장
- DB 및 backend-neutral retrieval payload에 `search_signals` 저장
- original raw text와 citation metadata 보존

## Deliverables

- enriched official corpus artifact
- enrichment manifest
- corpus quality report
- import dry-run report
- rebuild strategy decision record
- updated seed/import plan

## Acceptance Criteria

- full corpus artifact가 재현 가능한 명령으로 생성된다.
- enriched artifact가 schema validation과 quality gate를 통과한다.
- `embedding_text`, `normalized_text`, `search_signals`가 production import 가능한 형태로 존재한다.
- dirty command가 차단된다.
- source_url/viewer_path/citation linkage가 유지된다.
- v0.2.4에서 vector/BM25 retrieval index 교체를 진행할 수 있다.

## Risks

| Risk | Mitigation |
| --- | --- |
| full LLM run 비용 증가 | resumable batch와 per-book rollout |
| source rebuild로 기존 citation 깨짐 | viewer_path/source_url preservation gate |
| manual_synthesis 분리로 기존 답변 품질 하락 | separate collection으로 비교 후 전환 |
| parent chunk가 너무 커짐 | max token budget과 child retrieval 유지 |
| quality gate가 너무 엄격해 완료 지연 | blocking warning과 non-blocking warning 분리 |

## Completion Check

v0.2.3가 끝나면 official corpus는 검색용 artifact로 재생성되어 있어야 한다. 아직 production retrieval을 교체하지는 않지만, v0.2.4에서 새 vector/BM25 retrieval index를 만들 수 있는 데이터가 준비되어야 한다.
