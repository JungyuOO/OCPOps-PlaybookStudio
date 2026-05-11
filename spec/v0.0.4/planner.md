# v0.0.4 Planner - PBS Chat Grounding & Adaptive Guidance

Date: 2026-05-09
Branch: `feat/v0.0.4/adaptive-install-guide`

## Correction From User Feedback

The v0.0.4 scope is not a special fix for one bootstrap/install question.

The real problem is broader: PBS Chat can return weak or unrelated answers for normal operational questions, such as "네임스페이스 확인하는 명령어가 뭐야?" The work must analyze and improve the chatbot structure, retrieval behavior, answer grounding, citation quality, document chunking, and adaptive suggested questions across all PBS Chat questions.

Hardcoded expected-question-to-fixed-answer tables are not acceptable. Deterministic tests and fallback rules are allowed, but the product behavior must remain retrieval-grounded and generative from the corpus, current context, and validated operational patterns.

## Current Symptoms

- Simple command questions can retrieve unrelated chunks and produce unrelated answers.
- Some guided answers behave like document locators instead of useful operational guidance.
- Suggested questions in Studio Chat are still too fixed and do not adapt to the retrieved content or current user state.
- Citation cards can expose raw chunk text, English fragments, and markup such as `[CODE ...]`.
- Chunk structure may be mixing procedure text, code blocks, surrounding navigation text, and related-document content in ways that hurt retrieval and preview quality.
- Existing command-answer unit tests cover some formatting behavior, but they do not prove the full chat path retrieves the right evidence.

## Product Goal

PBS Chat should answer operational questions by:

1. Understanding the user's intent.
2. Retrieving the right evidence from the corpus.
3. Producing a concise, actionable answer grounded in citations.
4. Offering adaptive next questions generated from the retrieved chunks and current conversation context.
5. Showing clean citations and document cards that help the user inspect the source.

Example target behavior:

User: `네임스페이스 확인하는 명령어가 뭐야?`

Expected answer shape:

- Direct answer first: `oc get namespaces` or `oc get ns`.
- If the user means the current namespace/project: include `oc project` or `oc project -q`.
- If namespace-scoped resources are involved: mention `-n <namespace>` as the next concept.
- Cite relevant OpenShift/project/namespace documentation or a validated command chunk.
- Suggested questions should be generated from that evidence, for example:
  - `현재 터미널이 어느 프로젝트에 있는지 확인하려면?`
  - `특정 namespace 안의 pod만 보려면?`
  - `namespace가 Terminating이면 무엇부터 확인해?`

These suggestions must not be a static Q&A table.

## Target Files And Surfaces

- Chat answer orchestration: `src/play_book_studio/answering/answerer.py`
- Retrieval context assembly: `src/play_book_studio/answering/context.py`
- Retrieval and scoring: `src/play_book_studio/retrieval/retriever.py`, `src/play_book_studio/retrieval/scoring_postprocess.py`, `src/play_book_studio/retrieval/vector.py`
- Chunk hydration and metadata: `src/play_book_studio/retrieval/chunk_hydration.py`
- Starter/suggested questions: `src/play_book_studio/http/starter_questions.py`, `src/play_book_studio/http/server_support.py`
- Course/guided chat APIs: `src/play_book_studio/http/course_api.py`
- Chunking and normalization: `src/play_book_studio/ingestion/chunking.py`, `src/play_book_studio/course/pipeline/chunk_normalization.py`
- Corpus validation/audit: `src/play_book_studio/ingestion/validation.py`
- Studio Chat UI: `apps/web/src/pages/WorkspacePage.tsx`, `apps/web/src/pages/workspace/WorkspaceAnswer.tsx`
- Course Chat UI: `apps/web/src/pages/CourseChatWorkspaceAnswer.tsx`, `apps/web/src/pages/CourseStagePage.tsx`
- Existing tests to extend: `tests/test_answer_text_commands.py`, `tests/test_bm25_postgres.py`, `tests/test_chunk_hydration.py`, `tests/test_answer_context_metadata.py`, `src/play_book_studio/evals/studio_live_smoke.py`

## Non-Negotiables

- Do not build a static expected-question to fixed-answer database.
- Do not hardcode one-off answers for "namespace", "bootstrap", or any other single user phrase.
- Use intent categories, retrieval features, source metadata, and generated answer contracts instead.
- Tests may use golden prompts, but production answers must be grounded in retrieved evidence.
- Any chunking change must be backed by audit evidence.
- When retrieval confidence is low, the answer should say what evidence is missing instead of confidently answering from unrelated chunks.

## P0 Scope

### 1. Build A Chat Quality Baseline

Create a small but broad eval set that exercises actual PBS Chat behavior, not only formatter helpers.

Seed categories:

- Command lookup: namespace, pods, events, logs, routes, PVCs, cluster operators.
- Troubleshooting: Pending pod, CrashLoopBackOff, namespace Terminating, route timeout.
- Install guidance: bootstrap wait, install-complete, post-install checks.
- Concept clarification: namespace vs project, OpenShift vs Kubernetes, operator vs deployment.
- Navigation/document lookup: "이 내용은 어느 문서에 있어?"

Acceptance:

- Each case records expected intent, required command/evidence, forbidden unrelated topics, and citation expectations.
- The eval can flag wrong retrieval separately from wrong answer formatting.
- "네임스페이스 확인하는 명령어가 뭐야?" is included as a first-class regression case.

### 2. Add Intent-Aware Retrieval Guardrails

Introduce lightweight intent classification before final answer generation.

Initial intent families:

- `command_lookup`
- `troubleshooting`
- `install_guidance`
- `concept_explanation`
- `document_locator`
- `guided_learning`

Implementation notes:

- Use intent to shape retrieval query variants and reranking features.
- For command lookup, boost chunks with matching `cli_commands`, command-like text, k8s object metadata, and exact nouns.
- For troubleshooting, boost chunks with error strings, symptoms, and diagnostic command metadata.
- For document locator, allow section-path answers.
- For all other intents, demote locator-only answers.

Acceptance:

- Command questions retrieve command-bearing chunks in the top context.
- If top hits are unrelated to the intent, the system asks for clarification or says it could not find grounded evidence.
- This is implemented as reusable routing/scoring logic, not per-question hardcoding.

### 3. Improve Answer Contracts By Intent

Different question types need different answer shapes.

Contracts:

- Command lookup: direct command, when to use it, one example, source citation.
- Troubleshooting: symptoms to check, diagnostic commands, likely branch points, ask for missing log/output.
- Install guidance: current stage, 3-step flow, command/check, next source document.
- Concept explanation: short definition, practical impact, related command or object if useful.
- Document locator: exact document/section path and why it matches.

Acceptance:

- "네임스페이스 확인하는 명령어가 뭐야?" starts with the command, not a document recommendation.
- "bootstrap 기다리는 단계에서 뭘 해야 돼?" starts with operational steps, not only "open this document."
- "어느 문서에 있어?" can still produce a document locator answer.

### 4. Replace Static Suggested Questions With Grounded Generation

Suggested questions should be generated from:

- retrieved chunks
- section path
- command hints
- conversation intent
- learning route metadata
- current workspace/session seed

Proposed item schema:

```json
{
  "question": "현재 터미널이 어느 프로젝트에 있는지 확인하려면?",
  "intent": "command_lookup",
  "learning_goal": "namespace_project_context",
  "source_chunk_id": "...",
  "source_command": "oc project -q",
  "difficulty": "beginner",
  "reason": "Generated from a chunk that describes project/namespace context commands.",
  "seed": "session-or-route-seed"
}
```

Rules:

- Generate 3-5 candidate questions per answer context.
- Validate each generated question against a source chunk or command hint.
- Rotate by stable seed so UI variety does not make tests flaky.
- Keep deterministic fallback templates only as degraded behavior when generation is unavailable.
- Avoid global hardcoded starter cards that ignore the current context.

Acceptance:

- Suggested questions change when retrieved evidence changes.
- Clicking a suggestion preserves source chunk/intent metadata into the next chat request.
- Playwright can verify at least three grounded suggestions without depending on exact wording.

### 5. Clean Citation And Related Document Previews

Citation cards should help the user inspect evidence.

Changes:

- Strip raw `[CODE ...]` wrappers and import markup from previews.
- Separate command preview from summary preview.
- Prefer title, section path, and a short relevance reason over long raw chunk text.
- Avoid showing English fragments when an approved Korean display text exists.

Acceptance:

- Citation cards do not show raw parser markup.
- Related docs are concise and relevant.
- The source remains inspectable through the document viewer.

### 6. Audit Chunk Quality Before Rechunking

Add a repeatable chunk audit for the active corpus.

Metrics:

- token and character count distribution
- command count per chunk
- code block density
- raw markup leakage
- Hangul/display-language ratio
- section path depth
- chunks with mixed procedure, navigation, and unrelated related-doc text
- retrieval misses for the eval set

Decision gate:

- If wrong answers come mostly from answer routing/scoring, keep chunking stable.
- If retrieval misses are caused by noisy or oversized chunks, split procedure/code/troubleshooting blocks into structured child chunks while preserving parent section metadata.

Acceptance:

- The plan produces a report that explains whether chunking must change.
- Any rechunking work includes before/after retrieval evidence for the eval set.

## P1 Scope

- Add UI controls for beginner/operator/lab question style.
- Add "다른 질문 추천" rotation using a stable seed.
- Add low-confidence answer UI state that explains why the bot is asking for more context.
- Add score/debug view for dev mode showing intent, top chunks, and why a chunk was selected.
- Expand eval set with real user transcripts after v0.0.4 baseline is stable.

## Out Of Scope For v0.0.4

- Full corpus reimport without audit evidence.
- New external dependencies unless explicitly approved.
- Static FAQ bot behavior.
- Replacing the whole chat UI.
- Solving every OpenShift command from memory without source grounding.

## Execution Plan

1. Baseline failing chat cases.
   Capture actual PBS Chat outputs for command lookup, troubleshooting, install, concept, and document-locator prompts.

2. Build eval fixtures.
   Add intent, required command/evidence, forbidden unrelated terms, and citation expectations.

3. Add intent classification.
   Keep it lightweight and explainable. Use it to select answer contract and retrieval/rerank features.

4. Improve retrieval/reranking.
   Boost command metadata, exact object nouns, symptom strings, section role, and source trust. Penalize unrelated high-score chunks.

5. Implement answer contracts.
   Route answer generation by intent. Demote document-locator fallback unless the user really asks for a document path.

6. Implement grounded suggested-question generation.
   Generate from current retrieved chunks and validate against source metadata. Keep only a degraded deterministic fallback.

7. Clean citation previews.
   Normalize preview text and command rendering before it reaches the UI where possible.

8. Run chunk audit.
   Use the eval failures to decide whether chunk splitting or metadata enrichment is necessary.

9. Verify end to end.
   Run backend tests, frontend build, and Playwright/studio smoke against representative questions.

## Test Plan

- Unit tests for intent classification.
- Retrieval tests proving command lookup boosts command-bearing chunks.
- Answer contract tests for command lookup, troubleshooting, install guidance, concept explanation, and document locator.
- Suggested question generation tests with seeded output and source validation.
- Citation preview normalization tests for `[CODE]`, shell-session snippets, and mixed-language text.
- End-to-end smoke cases:
  - `네임스페이스 확인하는 명령어가 뭐야?`
  - `pod가 Pending이면 뭐부터 확인해?`
  - `route timeout은 어디를 봐야 해?`
  - `bootstrap 기다리는 단계에서 뭘 해야 돼?`
  - `이 내용은 어느 문서에 있어?`

## Risks

- Retrieval scoring changes can improve command questions while hurting concept questions unless eval coverage is broad enough.
- LLM-generated suggestions can hallucinate unless every item is source-validated.
- Randomization can make tests flaky without stable seeds.
- Chunking changes can invalidate existing indexes and require careful migration.
- Low-confidence handling may feel less helpful if it asks too often; tune thresholds with eval evidence.

## Done Criteria

- PBS Chat answers common operational command questions with relevant commands and citations.
- The namespace command regression returns a namespace/project command answer, not unrelated content.
- Guided/install answers are actionable but are only one subset of the broader chat improvement.
- Suggested questions are generated from retrieved evidence and current context, not static global cards.
- Citation previews are clean and source-inspectable.
- Chunking changes, if any, are justified by an audit and before/after retrieval evidence.

## Progress Log

- 2026-05-09: Created the v0.0.4 plan on `feat/v0.0.4/adaptive-install-guide`.
- 2026-05-09: Re-scoped the plan from a bootstrap-only fix to broader PBS Chat quality work after user clarification.
- 2026-05-09: Added command intent detection, command-bearing chunk scoring, citation command previews, and grounded follow-up suggestions for command citations.
- 2026-05-09: Added namespace/current-project/bootstrap regression cases to eval manifests and live smoke validation for missing command grounding/raw code preview leakage.
- 2026-05-10: Fixed live command/install regressions through retrieval query expansion, context selection, command extraction, and low-confidence guard tuning. Verified `namespace`, `current project/namespace`, and `bootstrap wait` live `/api/chat/stream` cases as `rag` with warnings cleared.
- 2026-05-10: Added readable v0.0.4 eval manifests for Pending pod, route timeout, project-vs-namespace concept, install troubleshooting document lookup, and unsupported Helm/nginx ingress command requests.
- 2026-05-10: Replaced citation follow-up generation with source-grounded command/section templates and stable seed rotation. Playwright verified Studio renders grounded bootstrap suggestions from the cited `openshift-install ... wait-for bootstrap-complete` command.
- 2026-05-10: Added repeatable chunk quality audit code and generated `spec/v0.0.4/chunk_quality_audit.md` plus JSON. Current audit recommends `audit_before_rechunking`: fix retrieval/metadata/preview paths first, and only split/reimport chunks with before/after eval evidence.

## Current Status

P0 baseline is implemented for the representative regression path:

- command lookup guardrails
- install guidance answer shape
- grounded command/section suggestions
- citation preview cleanup
- expanded eval fixtures
- chunk audit report
- backend, frontend build, live stream, and Playwright UI smoke verification

Known follow-up beyond this v0.0.4 baseline:

- Run the full extended eval manifest against the live answerer and tune failures by bucket.
- Add source metadata to suggestion click events if the UI later needs to preserve `source_chunk_id` separately from the suggested question text.
- Rechunk only after a focused before/after retrieval experiment on the audit-flagged `raw_code_markup`, `command_dense_chunk`, and `mixed_procedure_navigation` samples.
