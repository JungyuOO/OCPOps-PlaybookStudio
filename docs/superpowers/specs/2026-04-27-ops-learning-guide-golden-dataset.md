# Study-docs Operational Learning Guide Golden Dataset Spec

Date: 2026-04-27  
Status: Draft baseline for implementation  
Related:
- `docs/superpowers/specs/2026-04-23-ocp-project-playbook-course-design.md`
- `docs/superpowers/evaluate/2026-04-23-ocp-project-playbook-course-evaluation.md`
- `data/course_pbs/manifests/course_v1.json`
- `manifests/course_qa_cases.accepted.jsonl`

## 1. Purpose

This spec defines a new Study-docs based operational learning guide layer.

The goal is not to replace the existing `course_chunk_v1` dataset. The existing PPT/PDF-derived chunks remain the source evidence layer for retrieval, citations, slide viewing, OCR, and image evidence.

The new layer provides a beginner-facing, operations-oriented guided curriculum on top of those source chunks.

The user should be able to learn practical operation flow without knowing internal document IDs such as `DSGN-005-001`, `TEST-UN-OCP-12-01`, `CH-05`, `KMSC-*`, or raw slide numbers.

## 2. Problem Statement

The current course route is useful for source lookup, but it is not yet a reliable operational learning guide.

Observed issues:

- Route order is mostly derived from `tour_stop.next_chunk_id` and stage stop order.
- Suggested questions are generated from chunk titles and technologies.
- Many golden QA queries contain internal IDs directly.
- Some questions validate anchor retrieval rather than beginner learning behavior.
- A slide or document section is treated too often as a learning step.
- The current `next step` can mean "next chunk in the manifest", not "next meaningful operational learning action".

Measured baseline as of 2026-04-27:

- `course_v1.json` has 5 stages and 166 route stops.
- `data/course_pbs/chunks` has 523 chunks.
- `manifests/course_qa_cases.accepted.jsonl` has 300 accepted cases.
- 226 of 300 accepted cases include ID-like terms in the user-facing query.
- Existing QA therefore over-validates document-anchor retrieval and under-validates beginner guided learning.

## 3. Non-Goals

Do not rewrite or flatten the source PPT/PDF content into a new synthetic document.

Do not remove internal IDs from source metadata. IDs are required for traceability, citations, QA, and rebuild reproducibility.

Do not discard source chunks because their title or slide order is not ideal for learning. Fix learning order in the guide layer, not by mutating source evidence.

Do not treat generated guide text as ground truth unless it is backed by source chunks, slide/page references, image evidence, or official documentation.

Do not replace the official OpenShift/PBS documentation corpus or vector collection. Official docs remain a separate evidence lane and must be linked where relevant.

## 4. Core Design

The course system should have three layers.

1. Source Evidence Layer
   - `course_chunk_v1`
   - slide/page references
   - OCR text
   - image attachments
   - semantic zones
   - related official docs
   - Qdrant/BM25 searchable text

2. Operational Guide Layer
   - beginner-facing guide routes
   - curated step order
   - step questions
   - current/next step edges
   - learning objectives
   - required source anchors
   - expected evidence types

3. Golden Evaluation Layer
   - beginner queries
   - hidden expected source anchors
   - expected answer terms
   - required citation behavior
   - required next step behavior
   - official-doc companion expectations
   - image evidence expectations

The guide layer must reference source chunks, not copy them wholesale.

## 5. Guide Schema

Canonical model: `ops_learning_guide_v1`

Recommended file:

```text
data/course_pbs/manifests/ops_learning_guides_v1.json
```

Top-level shape:

```json
{
  "canonical_model": "ops_learning_guide_v1",
  "generated_at": "2026-04-27",
  "source_manifest": "data/course_pbs/manifests/course_v1.json",
  "guides": []
}
```

Guide object:

```json
{
  "guide_id": "perf_bottleneck_review",
  "stage_id": "perf_test",
  "title": "성능 테스트 병목 분석 흐름",
  "audience": "beginner_operator",
  "learning_goal": "성능 테스트 결과에서 병목, 근거 화면, 개선 포인트를 순서대로 확인한다.",
  "entry_step_id": "perf_goal_and_context",
  "step_ids": [
    "perf_goal_and_context",
    "perf_result_bottleneck",
    "perf_evidence_review",
    "perf_improvement_actions"
  ],
  "quality": {
    "status": "draft",
    "reason": "generated_from_existing_chunks"
  }
}
```

Guide step object:

```json
{
  "step_id": "perf_result_bottleneck",
  "guide_id": "perf_bottleneck_review",
  "stage_id": "perf_test",
  "card_text": "병목과 개선 포인트 확인하기",
  "user_query": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
  "learning_objective": "DB SQL 응답 지연, DB Connection Pool, worker-thread, HPA, HAProxy 지표를 순서대로 본다.",
  "answer_outline": [
    "먼저 전체 응답시간 지연 구간을 확인한다.",
    "DB SQL 응답 지연과 DB Connection Pool 대기 여부를 확인한다.",
    "worker-thread 수와 DB Connection Pool max 설정을 비교한다.",
    "HPA scale-out과 HAProxy/Router 자원 지표를 보조 확인한다."
  ],
  "source_anchors": [
    {
      "chunk_id": "perf-test--4--default--none--perf-section-summary--summary--10bd6950",
      "native_id": "4",
      "hidden_from_user": true,
      "anchor_role": "primary"
    }
  ],
  "official_refs": [
    {
      "book_slug": "monitoring",
      "required": false,
      "match_reason": "성능 지표와 모니터링 해석을 보조하는 공식 문서"
    }
  ],
  "evidence_requirements": {
    "requires_citation": true,
    "requires_next_step": true,
    "image_roles": [
      "dashboard_metric",
      "command_result_evidence",
      "expected_state_indicator"
    ]
  },
  "next_step_ids": [
    "perf_evidence_review"
  ],
  "quality": {
    "status": "draft",
    "needs_review": [
      "source_anchor_relevance",
      "official_mapping_relevance"
    ]
  }
}
```

## 6. Golden Dataset Schema

Canonical model: `ops_learning_golden_case_v1`

Recommended file:

```text
manifests/course_ops_learning_golden_cases.jsonl
```

Case shape:

```json
{
  "id": "guide-perf-bottleneck-001",
  "canonical_model": "ops_learning_golden_case_v1",
  "category": "beginner_performance",
  "guide_id": "perf_bottleneck_review",
  "step_id": "perf_result_bottleneck",
  "query": "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?",
  "expected": {
    "stage_id": "perf_test",
    "chunk_ids": [
      "perf-test--4--default--none--perf-section-summary--summary--10bd6950"
    ],
    "terms": [
      "DB SQL 응답 지연",
      "DB Connection Pool",
      "worker-thread",
      "HPA",
      "HAProxy"
    ],
    "must_include_citation": true,
    "must_include_next_step": true,
    "must_not_expose_internal_ids": true
  },
  "source": {
    "native_ids": [
      "4"
    ],
    "hidden_doc_anchor": true
  }
}
```

## 7. User-Facing Query Rules

User-facing query text must be beginner-guided.

Allowed:

- "CI/CD 주요 변경사항은 어떤 순서로 보면 돼?"
- "운영 배포 승인 흐름은 어떻게 이해하면 돼?"
- "파이프라인이 성공했다는 건 화면에서 뭘 보면 돼?"
- "실패하면 어떤 로그와 상태부터 확인해야 해?"
- "성능 테스트 결과에서 병목과 개선 포인트는 어디부터 보면 돼?"
- "배포 환경과 테스트 환경은 어떤 기준으로 나눠서 보면 돼?"

Not allowed for beginner guide cases:

- "DSGN-005-001 아키텍처 구성도 기준으로 설명해줘"
- "TEST-UN-OCP-12-01 다음에 뭐 봐?"
- "CH-05 공식문서 기준도 같이 알려줘"
- "KMSC-COCP-RTER-003 결과서 설명해줘"

Internal IDs may appear only in hidden expected metadata, citations metadata, source anchors, logs, and reviewer/debug views.

## 8. Guide Categories

Initial categories:

- `beginner_stage_entry`
- `beginner_concept`
- `beginner_guided_step`
- `beginner_operational_flow`
- `beginner_verification`
- `beginner_troubleshooting`
- `beginner_performance`
- `official_compare`
- `image_evidence`
- `slide_viewer`

The existing anchor-style cases should remain available as regression tests, but they must not be used as the main proof that the beginner guided course works.

## 9. Required Initial Guides

Create the first guide set from source chunks and reviewable evidence.

Required guide candidates:

1. Architecture Overview
   - goal: understand OCP project architecture from external, DMZ, internal, DB, storage, and CI/CD areas.

2. Service Flow and Network Reading
   - goal: follow service request/response, HAProxy, router, ingress, service mesh, and URL mapping.

3. CI/CD Change and Approval Flow
   - goal: understand source change, MR, approval gate, staging validation, GitOps/ArgoCD, pipeline success.

4. Unit Test Verification Flow
   - goal: learn how platform configuration, components, PV/PVC, routes, storage, and service checks were verified.

5. Integration Test CI/CD Flow
   - goal: learn pipeline trigger, clone, S2I/build, deployment rollout, service access, rollback/failure checks.

6. Performance Bottleneck Review
   - goal: learn how to read performance goals, environment, results, bottlenecks, metrics, and improvements.

7. Completion Report Reading Path
   - goal: learn how to read project background, architecture outcome, migration result, test result, and final deliverables.

## 10. Answer Behavior

When a guide step is selected or matched:

- Use guide `answer_outline` as the answer plan.
- Ground each major claim in source chunks or official docs.
- Insert normal citation tokens such as `[1]`, `[2]`.
- Provide the next meaningful guide step from `next_step_ids`.
- Include image evidence only when it helps the user's intent.
- Do not expose internal IDs in the visible answer unless the user explicitly asks for source/debug detail.
- Keep source anchors available in citation metadata and viewer links.

## 11. Image Evidence Rules

Images are not judged as standalone assets only.

Small status captures can be important operational evidence when the step is about verification, expected state, failure state, or command result.

The guide layer should reference image roles from the source chunks:

- `diagram`
- `table`
- `console_output`
- `command_result_evidence`
- `expected_state_indicator`
- `success_state`
- `failure_state`
- `progress_state`
- `dashboard_metric`
- `ui_navigation_evidence`

Blank, solid, decorative, or unreadable images may be excluded from default display, but they must not be deleted from the source evidence layer without a separate data cleanup decision.

## 12. Quality Gates

A generated guide step starts as `draft`.

It can become `approved` only if all conditions are met:

- The user-facing card/query has no internal ID leakage.
- The source anchor exists and is relevant.
- The answer outline is supported by source chunks.
- The next step is meaningful as an operational learning continuation.
- Official docs are relevant or explicitly marked optional.
- Required image evidence roles are available when the step depends on screen verification.
- A golden case verifies retrieval, answer terms, citation behavior, and next-step behavior.

## 13. Implementation Principle

The pipeline may generate a first draft automatically, but automatic generation is not truth.

The system should label uncertain links as draft/needs_review and prefer a smaller approved guide set over a large but misleading route.

