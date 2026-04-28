# Study-docs Operational Learning Guide Implementation Plan

Date: 2026-04-27  
Status: Active plan  
Reference spec: `docs/superpowers/specs/2026-04-27-ops-learning-guide-golden-dataset.md`

## 1. Objective

Create a new operational learning guide and golden dataset for Study-docs based course chat.

The goal is to make the course feel like a practical internal operations guide, not a raw PPT/document-ID search interface.

The source PPT/PDF-derived chunks remain intact. The new work adds a guide/golden layer that maps beginner-facing questions to hidden source anchors.

## 2. Current Baseline

As of 2026-04-27:

- `data/course_pbs/manifests/course_v1.json` has 5 stages and 166 route stops.
- `data/course_pbs/chunks` has 523 chunk files.
- `manifests/course_qa_cases.accepted.jsonl` has 300 accepted cases.
- 226 of 300 accepted cases include ID-like terms in the user-facing query.
- Current guided tour behavior is still strongly tied to chunk title, native ID, and `tour_stop.next_chunk_id`.

Conclusion:

The current QA set should remain as an anchor retrieval regression set, but it is not enough to prove beginner operational learning quality.

## 3. Workstream Overview

Implement this in six phases.

1. Audit and select source anchors.
2. Generate guide manifest draft.
3. Generate beginner golden dataset.
4. Add guide-first backend resolution.
5. Update guided cards and suggested queries.
6. Run semantic and UI verification.

## 4. Phase 1 - Source Anchor Audit

Goal:

Identify which existing chunks are reliable enough to support operational learning steps.

Tasks:

- Read `course_v1.json` stage routes.
- Read chunk metadata for title, summary, body, structured fields, facets, slide refs, image roles, and official mappings.
- Classify chunks into learning usefulness:
  - `primary_learning_anchor`
  - `supporting_evidence`
  - `source_only`
  - `needs_review`
- Flag poor anchors:
  - thin content
  - weak title
  - source-only cover/table-of-contents slides
  - no useful body/search text
  - official mapping too broad
  - image evidence required but missing or unreadable

Deliverables:

- `data/course_pbs/manifests/ops_learning_anchor_audit_v1.json`
- audit summary in the terminal/final report

Completion criteria:

- At least one reliable guide path can be built for architecture, CI/CD, performance, and completion.
- Weak anchors are not promoted into beginner guide entry cards.

## 5. Phase 2 - Guide Manifest Draft

Goal:

Create the first `ops_learning_guide_v1` manifest.

Tasks:

- Create `data/course_pbs/manifests/ops_learning_guides_v1.json`.
- Add required initial guides:
  - Architecture Overview
  - Service Flow and Network Reading
  - CI/CD Change and Approval Flow
  - Unit Test Verification Flow
  - Integration Test CI/CD Flow
  - Performance Bottleneck Review
  - Completion Report Reading Path
- For each guide, define:
  - `guide_id`
  - `stage_id`
  - `title`
  - `audience`
  - `learning_goal`
  - `entry_step_id`
  - ordered `steps`
- For each step, define:
  - beginner-facing `card_text`
  - beginner-facing `user_query`
  - `learning_objective`
  - source-grounded `answer_outline`
  - hidden `source_anchors`
  - optional `official_refs`
  - `evidence_requirements`
  - `next_step_ids`
  - `quality.status`

Rules:

- Do not expose internal IDs in `card_text` or `user_query`.
- Keep internal IDs in `source_anchors`.
- Mark generated/uncertain guide links as `draft` or `needs_review`.
- Prefer fewer meaningful steps over many noisy slide-derived steps.

Completion criteria:

- Guide cards read like operational learning actions.
- Every guide step has at least one source anchor.
- Every next step is a meaningful learning continuation.

## 6. Phase 3 - Golden Dataset Generation

Goal:

Create a new beginner-guided golden dataset.

Tasks:

- Create `manifests/course_ops_learning_golden_cases.jsonl`.
- Add cases for:
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
- Add hidden expected metadata:
  - `guide_id`
  - `step_id`
  - `stage_id`
  - `chunk_ids`
  - `native_ids`
  - `terms`
  - citation requirements
  - next-step requirements
  - image role requirements

Rules:

- Beginner cases must not put internal IDs in `query`.
- Existing ID-based cases remain in `course_qa_cases.accepted.jsonl`.
- New cases validate guided learning, not only retrieval.

Target size:

- First pass: 80-120 high-signal cases.
- Expanded pass: 200-300 cases after guide behavior stabilizes.

Completion criteria:

- 0 beginner guide queries with ID leakage.
- Each guide step has at least one positive golden case.
- Verification/troubleshooting/performance cases include expected evidence behavior.

## 7. Phase 4 - Backend Guide-First Resolution

Goal:

Make course chat resolve guide steps before generic chunk retrieval when the query is beginner-guided.

Tasks:

- Add loader for `ops_learning_guides_v1.json`.
- Add guide-step matcher:
  - exact match on card/query text
  - guide/stage context match
  - semantic/lexical fallback against beginner query and learning objective
- Add response grounding:
  - load source chunks from `source_anchors`
  - add official docs from `official_refs` and existing `related_official_docs`
  - build answer from guide outline plus source summaries
  - attach citations
  - attach next guide step cards from `next_step_ids`
- Keep existing chunk retrieval as fallback.

Rules:

- Guide-first should apply to beginner learning intent.
- Direct internal ID queries should still resolve through source chunks.
- Official document vector/search collection must remain untouched.

Completion criteria:

- Clicking a guide card sends its `user_query`.
- The answer cites the expected source chunk.
- Suggested next cards come from guide `next_step_ids`, not raw `tour_stop.next_chunk_id`.

## 8. Phase 5 - UI Guide Card Integration

Goal:

Make the frontend look and behave like a guided learning flow.

Tasks:

- Load guide cards for course/stage entry views.
- Render guide cards as question-execution cards, not only document links.
- On card click, send course chat query with guide/stage context.
- Render next guide cards below answers through existing PBS-style answer components.
- Keep source viewer citations clickable.
- Keep slide viewer as source evidence, not the main learning navigation.

Completion criteria:

- User can start from a beginner card and continue through next step cards.
- Visible cards do not show internal IDs.
- Citations and source viewer still preserve source traceability.

## 9. Phase 6 - Verification

Goal:

Prove the feature works as guided operational learning.

Tasks:

- Run existing course QA to protect anchor retrieval regression.
- Run new ops learning golden cases.
- Add checks:
  - no internal IDs in beginner visible answer/cards unless explicitly requested
  - expected chunk citation exists
  - next step is guide-derived
  - answer includes expected operational terms
  - image evidence appears for verification/troubleshooting questions
  - official docs appear when expected
- Use Playwright to manually verify representative flows:
  - architecture entry
  - CI/CD change flow
  - pipeline success evidence
  - failure/troubleshooting evidence
  - performance bottleneck review
  - completion report reading path

Completion criteria:

- Existing anchor QA remains green or documented.
- New beginner guide QA reaches at least 90% first-pass pass rate.
- No accepted beginner guide query contains internal ID leakage.
- Playwright confirms card click -> answer -> citation -> next card flow.

## 10. Execution Order

Recommended order:

1. Build anchor audit.
2. Generate a small guide manifest with 2-3 guides.
3. Generate 40-60 golden cases for those guides.
4. Implement backend guide-first resolution.
5. Wire frontend guide cards.
6. Verify with API and Playwright.
7. Expand to all required guides.
8. Expand golden cases to 200-300.

## 11. Risk Register

Risk: Generated guide order may look plausible but be operationally wrong.  
Mitigation: keep `quality.status=draft`, require source anchors, and approve only small high-confidence routes first.

Risk: Beginner answers may hide too much traceability.  
Mitigation: hide IDs in visible prose, keep IDs in citation/source metadata.

Risk: Official docs may attach too broadly.  
Mitigation: mark official refs optional unless match reason is specific and relevant.

Risk: Existing route/search behavior may regress.  
Mitigation: keep ID-based QA as a separate regression lane.

Risk: Slide evidence may dominate the answer.  
Mitigation: answer from guide outline and source text; show images only when they serve verification, state, failure, metric, or diagram intent.

## 12. Checklist

### Spec and Data

- [x] Create anchor audit manifest.
- [x] Create `ops_learning_guides_v1.json`.
- [x] Create `course_ops_learning_golden_cases.jsonl`.
- [x] Keep existing `course_chunk_v1` unchanged.
- [x] Keep existing official docs collection unchanged.

### Backend

- [x] Add guide manifest loader.
- [x] Add guide-first matcher.
- [x] Add guide-grounded answer builder.
- [x] Add guide-derived suggested next cards.
- [x] Preserve fallback to existing chunk retrieval.

### Frontend

- [ ] Render guide cards as question-execution cards.
- [ ] Use guide next cards below answers.
- [ ] Keep citations clickable.
- [ ] Keep source slide viewer focused on evidence.

### Verification

- [ ] Run existing course QA.
- [ ] Run new beginner guide QA.
- [ ] Run no-ID-leak checks.
- [ ] Run Playwright representative flows.
- [ ] Review failures before expanding dataset.
