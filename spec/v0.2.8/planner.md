# v0.2.8 - Feedback Loop and Continuous Evaluation Planner

## Goal

v0.2.8의 목표는 사용자 피드백, 실패 질문, low-grounding 답변을 지속적으로 수집하여 corpus enrichment와 retrieval 개선으로 되돌리는 feedback/eval loop를 구축하는 것이다. 이 버전은 v0.2.1~v0.2.7에서 만든 데이터/RAG/runtime assistant 구조를 운영하면서 품질을 계속 개선하기 위한 기반이다.

## Scope

### Included

- answer feedback schema
- failed retrieval case 저장
- no-answer/low-grounding case 저장
- benchmark dataset 자동 업데이트 후보 생성
- regression eval runner 확장
- dashboard/report 생성
- next enrichment queue 생성

### Excluded

- 자동 fine-tuning
- 자동 production corpus 변경
- 사용자 피드백을 즉시 답변 정책에 반영
- 외부 analytics 제품 연동

## Work Items

### 1. Feedback Data Model

답변 품질 평가를 저장한다.

Fields:

- answer_id
- session_id
- user_id/workspace_id
- query
- route
- selected sources
- citations
- runtime evidence ids
- rating positive/negative
- free text feedback
- reason tags
- created_at

Reason tags:

- wrong_answer
- missing_source
- irrelevant_source
- hallucinated_command
- outdated_context
- permission_issue
- too_slow
- unclear
- helpful

### 2. Failed Retrieval Case Store

retrieval 실패를 별도 저장한다.

Signals:

- no hits
- low score hits
- source scope mismatch
- top result manually rejected
- citation missing
- answer no_grounding
- command drift

Stored evidence:

- query analyzer output
- retrieved chunk ids
- scores
- reranker decisions
- final citations
- user feedback

### 3. No-answer and Low-grounding Queue

답변 생성 단계에서 다음 케이스를 queue에 넣는다.

- no_answer
- clarification overuse
- low citation confidence
- runtime context missing
- stale snapshot
- LLM refused due insufficient evidence
- user negative feedback

Queue item should point to:

- candidate corpus issue
- candidate query analyzer issue
- candidate runtime collector issue
- candidate prompt issue

### 4. Benchmark Candidate Generation

실패 질문을 바로 benchmark에 넣지 않고 후보로 만든다.

Candidate fields:

- original query
- normalized query
- expected source type
- expected object/command/error
- human review status
- linked failure case
- suggested gold notes

Review states:

- pending
- approved
- rejected
- needs_gold_answer

### 5. Regression Eval Runner Extension

eval runner는 다음 축을 분리해서 평가한다.

- retrieval hit
- citation correctness
- answer usefulness
- command correctness
- runtime evidence usage
- no-answer appropriateness
- latency

Regression report should compare:

- previous release
- current branch
- legacy retrieval
- enriched retrieval
- docs-only vs runtime-assisted

### 6. Quality Dashboard/Report

초기에는 dashboard UI가 아니라 Markdown/JSON report로 충분하다.

Report sections:

- pass/fail trend
- top failed intents
- top missed book_slugs
- top hallucinated commands
- negative feedback examples
- low-grounding examples
- enrichment candidates
- runtime collector issues

### 7. Next Enrichment Queue

feedback을 다음 corpus enrichment 작업으로 연결한다.

Queue categories:

- missing best_for_questions
- weak embedding_text
- missing intent_labels
- dirty command
- wrong source scope
- stale official doc
- need manual playbook

This queue does not automatically mutate production corpus. It creates reviewed work items for the next version.

## Deliverables

- feedback schema
- failure case schema
- benchmark candidate schema
- eval runner extension plan or implementation
- quality report
- enrichment queue report

## Acceptance Criteria

- 사용자는 답변에 positive/negative feedback과 이유를 남길 수 있다.
- retrieval miss와 answer hallucination이 별도 case로 저장된다.
- 실패 질문이 benchmark 후보로 남는다.
- eval report가 retrieval/citation/answer/runtime evidence를 분리해서 보여준다.
- 다음 enrichment 작업 후보가 자동으로 생성된다.

## Risks

| Risk | Mitigation |
| --- | --- |
| feedback에 민감정보 포함 | feedback text redaction |
| 실패 질문이 바로 production 데이터에 반영 | human review queue 필수 |
| eval이 답변 표현 차이를 과도하게 실패 처리 | retrieval/citation/command/usefulness 분리 평가 |
| 데이터가 너무 많이 쌓임 | retention and sampling |
| negative feedback 원인 추적 불가 | trace ids and selected source ids 저장 |

## Completion Check

v0.2.8이 끝나면 PlaybookStudio는 실패한 질문을 그냥 로그로 버리지 않고, 다음 corpus enrichment와 retrieval 개선을 위한 구조화된 작업 후보로 축적할 수 있어야 한다.
