# v0.2.2 - Corpus Audit and LLM Enrichment Prototype Planner

## Goal

v0.2.2의 목표는 v0.2.1에서 정의한 RAG 데이터 개선 방향을 실제 도구와 샘플 산출물로 검증하는 것이다. 이 버전에서는 production corpus를 교체하지 않는다. 기존 공식 문서 `chunks.jsonl`의 문제를 수치화하고, 일부 sample chunk에 LLM 기반 enrichment를 적용해서 `embedding_text`, `normalized_text`, `search_signals`, `best_for_questions`가 retrieval 품질을 개선할 수 있는지 확인한다.

## Background

현재 official corpus는 citation/viewer 연결에는 필요한 출처 정보가 있지만, RAG 검색에 필요한 의미 메타데이터가 부족하다.

- 원본 `chunks.jsonl`에 `embedding_text`가 없다.
- 원본 `chunks.jsonl`에 `normalized_text`가 없다.
- `intent_labels`, `best_for_questions`, `primary_topics`, `answer_shapes`가 없다.
- `cli_commands`에는 `oc\n[/CODE]` 같은 오염값이 반복된다.
- official docs와 `manual_synthesis`가 같은 corpus에 섞여 있다.

v0.2.2은 이 문제를 바로 대규모 재구축으로 해결하지 않고, 먼저 작은 범위에서 audit/enrichment/eval loop를 만든다.

## Scope

### Included

- 공식 `chunks.jsonl` 품질 audit CLI
- dirty command/text cleanup prototype
- LLM enrichment batch runner prototype
- enriched chunk JSON schema validator
- 200~500개 sample chunk enrichment
- before/after retrieval 품질 비교 리포트
- full rebuild 필요 여부 판단 리포트

### Excluded

- production Qdrant collection 교체
- 전체 official corpus enrichment
- 공식 문서 원본 재수집
- runtime OCP context 수집
- UI 변경
- terminal/dashboard 분석 답변

## Work Items

### 1. Corpus Audit CLI

`chunks.jsonl`을 입력받아 다음 항목을 JSON/Markdown report로 출력한다.

- total row count
- field coverage
- empty `embedding_text` / `normalized_text`
- empty `semantic_role`
- dirty command count
- source_url/viewer_path validity
- source_lane/source_type 분포
- official/manual synthesis mixing ratio
- token count mismatch
- duplicate chunk id
- top repeated sections/anchors

Expected command shape:

```bash
python -m play_book_studio.evals.corpus_audit \
  --chunks corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl \
  --output reports/v021_official_corpus_audit.json \
  --markdown reports/v021_official_corpus_audit.md
```

### 2. Cleanup Prototype

LLM enrichment 전 deterministic cleanup을 수행한다.

- `[CODE]`, `[/CODE]`, orphan marker 제거
- `oc\n[/CODE]` 같은 dirty command 제거
- HTML/Markdown link 제거
- table delimiter 정리
- 중복 문장 제거
- 불필요한 docs URL 제거
- 명령어 의미를 가진 `-`, `--`, `/`, `.`, `:`는 보존

Output fields:

```json
{
  "raw_text": "...",
  "clean_text": "...",
  "normalized_text_seed": "...",
  "detected_dirty_values": [],
  "cleanup_warnings": []
}
```

### 3. LLM Enrichment Batch Runner Prototype

sample chunks를 대상으로 LLM metadata를 생성한다.

Input:

- `chunk_id`
- `book_slug`
- `section_path`
- `chunk_type`
- `source_url`
- `viewer_path`
- `clean_text`
- deterministic 후보: commands, objects, operators, error strings

Output:

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

LLM은 원문에 없는 운영 지식을 새로 만들지 않는다. 역할은 검색용 metadata와 question 표현 생성으로 제한한다.

### 4. Enriched Chunk Schema Validator

LLM output을 바로 신뢰하지 않고 validator를 통과시킨다.

Validation rules:

- valid JSON
- required keys present
- `source_url`, `viewer_path`, `chunk_id` 보존
- `embedding_text` length min/max
- `best_for_questions` max count
- `commands`에 dirty marker 없음
- 원문 근거 없는 command 제거 또는 warning
- 너무 일반적인 topic 제거
- hallucination 의심 항목 warning

### 5. Sample Enrichment Dataset

다음 유형을 섞어서 200~500개 sample을 만든다.

- storage/PVC/PV/StorageClass
- networking/Ingress/Route/NetworkPolicy
- nodes/MachineConfig/MCP
- operators/OLM/Operator install
- troubleshooting/Error state
- backup/restore/etcd
- monitoring/alert

sample은 전체 corpus 분포와 운영 질문 빈도를 함께 고려한다.

### 6. Before/After Retrieval Evaluation

기존 chunks와 enriched sample을 비교한다.

Metrics:

- top-1 hit
- top-5 hit
- top-10 hit
- citation source correctness
- command/object match
- no-answer rate
- dirty command exposure
- manual review score

Evaluation questions:

- 기존 benchmark 질문
- v0.1.x에서 실패한 질문
- OpenShift Lightspeed-style 질문
- Pod/Event/Alert 운영 질문 후보

### 7. Rebuild Decision Report

v0.2.2 마지막 산출물로 다음 중 하나를 결정한다.

```text
A. 기존 chunks.jsonl 보강으로 충분
B. 원본 official docs부터 재수집 필요
C. official docs는 유지하고 manual_synthesis는 별도 corpus로 분리
D. 일부 book_slug만 재수집하고 나머지는 enrichment
```

## Deliverables

- `reports/v021_official_corpus_audit.json`
- `reports/v021_official_corpus_audit.md`
- `reports/v021_enrichment_sample_report.json`
- `reports/v021_retrieval_before_after.md`
- `corpus/.../samples/enriched_sample.jsonl`
- rebuild decision report

## Acceptance Criteria

- audit CLI가 현재 `chunks.jsonl` 문제를 재현 가능한 수치로 보여준다.
- sample enriched chunks가 schema validation을 통과한다.
- dirty command가 enrichment output에 남지 않는다.
- sample benchmark에서 기존 대비 top-k retrieval 개선 여부를 확인한다.
- v0.2.3에서 full enrichment 또는 rebuild 중 무엇을 할지 결정할 수 있다.

## Risks

| Risk | Mitigation |
| --- | --- |
| LLM enrichment 비용이 예상보다 큼 | 200개 이하 dry run으로 비용 추정 후 확대 |
| LLM이 원문에 없는 항목을 생성 | validator와 manual review sample 적용 |
| sample만 좋아지고 전체 corpus에 일반화 안 됨 | book_slug/type별 stratified sample 사용 |
| cleanup이 명령어 의미를 손상 | command-preserving cleanup rule 적용 |

## Completion Check

v0.2.2은 production behavior를 바꾸는 버전이 아니다. 완료 기준은 audit/enrichment/eval loop가 작동하고, v0.2.3의 corpus 전략을 결정할 수 있는 증거가 확보되는 것이다.
