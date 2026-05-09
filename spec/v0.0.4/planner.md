# v0.0.4 Planner - Adaptive Install Guide & Chunk-Grounded Questions

Date: 2026-05-09
Branch: `feat/v0.0.4/adaptive-install-guide`

## Current Problem

Playbot can retrieve the right Gold Playbook section, but the answer shape is still too close to a document locator:

- It says which document to open first, but does not convert the section into a usable beginner guide.
- Related document cards show raw chunk text, English fragments, and markup such as `[CODE ...]`, which makes the Studio Chat answer feel noisy.
- The Studio Chat guided questions are still mostly fixed templates from `starter_questions.py`, so they do not adapt to the actual retrieved chunk or the user's current step.
- The chunk shape may be contributing to the problem because procedure text, code blocks, section titles, and long snippets can be merged into one citation preview.

The v0.0.4 goal is to turn this into an adaptive guided-install experience: answers should explain the next three operational steps, and recommended questions should be generated from the relevant chunk/route instead of being hardcoded.

## Reference Flow To Support

For the document route:

`Chapter 1. Installing a cluster on any platform > Waiting for the bootstrap process to complete`

The beginner answer should summarize the installation flow as:

1. Confirm the current install stage.
   Run the bootstrap wait command from the same installation directory:

   ```shell
   ./openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info
   ```

2. If it waits or fails, diagnose the bootstrap stage before moving on.
   Use the command output and installer log to identify whether the blocker is bootstrap host reachability, Ignition/RHCOS startup, DNS/API reachability, or cluster operator progress. The answer should ask for the exact failing line before recommending a fix.

3. After bootstrap completes, move to the next install completion and post-install path.
   The answer should point the user to the next command/check and only then suggest related Gold Playbook documents such as installation overview or post-install configuration.

The answer must not stop at "open this document first." It must provide the actionable three-step guide first, then cite the source document.

## Target Files

- Backend starter questions: `src/play_book_studio/http/starter_questions.py`
- Answer routing and deterministic fallbacks: `src/play_book_studio/answering/answerer.py`
- Retrieval context assembly: `src/play_book_studio/answering/context.py`
- Course/guided route APIs: `src/play_book_studio/http/course_api.py`
- Chunking and normalization: `src/play_book_studio/ingestion/chunking.py`, `src/play_book_studio/course/pipeline/chunk_normalization.py`
- Studio Chat rendering: `apps/web/src/pages/WorkspacePage.tsx`, `apps/web/src/pages/workspace/WorkspaceAnswer.tsx`
- Course chat rendering: `apps/web/src/pages/CourseChatWorkspaceAnswer.tsx`, `apps/web/src/pages/CourseStagePage.tsx`
- Quality/eval coverage: `src/play_book_studio/course/quality_eval.py`, `src/play_book_studio/evals/studio_live_smoke.py`, related tests

## P0 Scope

### 1. Define The Guided Install Answer Contract

Add a backend answer contract for guided learning/install questions:

- `현재 단계`: identify the relevant Gold Playbook section.
- `3단계 실행 흐름`: beginner-oriented ordered actions.
- `확인 명령`: commands only when grounded in retrieved docs or existing validated ops knowledge.
- `막히면 물어볼 것`: one concrete follow-up question that asks for the next missing evidence.
- `출처`: clean citations after the actionable guide.

Acceptance:

- For the bootstrap example, the answer starts with a three-step guide, not with "먼저 문서를 여세요."
- The answer includes `wait-for bootstrap-complete` when the cited section contains that command.
- The answer does not expose raw `[CODE language=...]` markup in the visible citation preview.

### 2. Demote Document-Locator Responses For Guided Questions

Current behavior in `answerer.py` can route locator-like questions to `_build_doc_locator_answer`. In guided learning mode, this must be limited to explicit "which document/path should I open?" intent.

Implementation notes:

- Keep `_build_doc_locator_answer` for direct navigation questions.
- Bypass it when the query asks "어떻게", "순서", "가이드", "설치 흐름", "막힘", "다음 할 일".
- Route those queries through the guided answer prompt/contract even when the top hit is a perfect document match.

Acceptance:

- A query like "부트스트랩 기다리는 단계에서 뭘 해야 돼?" produces a guide answer.
- A query like "이 내용은 어느 문서에 있어?" can still produce a locator answer.

### 3. Generate Adaptive Beginner Questions From Chunks

Replace the fixed guided starter question behavior with chunk-grounded question generation.

Proposed schema:

```json
{
  "question": "부트스트랩 완료 대기 단계에서 먼저 확인할 로그는 뭐야?",
  "learning_goal": "bootstrap_wait_diagnosis",
  "difficulty": "beginner",
  "source_document_id": "installing-platform-agnostic",
  "source_chunk_id": "...",
  "stage_order": 1,
  "reason": "The chunk contains the bootstrap wait command and procedure text.",
  "seed": "session-or-route-seed"
}
```

Generation rules:

- Use retrieved chunk text, section path, commands, and learning metadata as grounding.
- Generate 3-5 beginner questions per route or answer context.
- Randomize by stable seed so the same user/session has consistency, while route refreshes can rotate questions.
- Validate every generated question has a source chunk and a learning goal.
- Fall back to deterministic questions only when LLM generation is unavailable.

Acceptance:

- Guided starter questions are not just the current fixed templates.
- At least three generated questions are visibly tied to the current install section or route.
- A question click preserves `chunk_id`, route metadata, and learning context into the next chat request.

### 4. Clean Citation Preview Text

The citation cards should be readable evidence, not raw import text.

Changes:

- Strip code fence metadata and `[CODE ...]` wrappers from preview text.
- Cap previews to a short Korean-first summary when translated text exists.
- Separate `command_preview` from `summary_preview` so command blocks can render as commands instead of paragraph snippets.
- Prefer section path/title over long raw chunk text in related document cards.

Acceptance:

- The example citation card no longer displays raw `[CODE language="shell-session" caption=...]`.
- Related docs show concise title, section path, and a short reason why it is relevant.

### 5. Audit Chunk Size And Structure

Before changing chunking defaults, add a chunk audit pass for Gold Playbook docs.

Audit metrics:

- token count and character count distribution
- code block density
- section path depth
- command count
- raw markup leakage
- chunks where procedure text and unrelated related-doc navigation are merged

Decision gate:

- If the poor answer is mostly answer-shaping and citation preview, keep chunking stable.
- If chunks are too coarse or contaminated, split procedure/code/troubleshooting blocks into structured child chunks while preserving parent section metadata.

Acceptance:

- Produce a repeatable report or test fixture that identifies oversized/noisy chunks.
- Do not reimport the whole corpus unless the audit shows chunk quality is the root cause.

## P1 Scope

- Add persona controls for generated questions: `초보`, `운영자`, `실습`.
- Allow "다른 질문 추천" to rotate generated questions by seed without losing grounding.
- Add answer-side next-step buttons: "로그 붙여넣기", "다음 설치 단계", "관련 문서 열기".
- Add offline cache for generated route questions so Playwright and local tests remain deterministic.

## Out Of Scope For v0.0.4

- Rebuilding the whole document ingestion pipeline without audit evidence.
- Adding new external dependencies.
- Replacing the whole Studio Chat UI.
- Implementing a full training/course authoring system.

## Execution Plan

1. Baseline the failing behavior.
   Add a fixture or smoke case for the bootstrap question and current citation card shape.

2. Add guided answer tests.
   Lock the required three-step answer structure before changing routing.

3. Implement answer routing changes.
   Restrict document-locator fallback and add a guided-install answer contract/prompt path.

4. Implement adaptive question generation.
   Build a backend generator that consumes chunk metadata and produces validated beginner questions with fallback.

5. Wire generated questions into Studio Chat.
   Replace fixed guided question cards for route-aware contexts and preserve source metadata on click.

6. Clean citation previews.
   Normalize citation summary fields and update UI rendering to avoid raw markup.

7. Run chunk audit.
   Use the report to decide whether chunk splitting changes are required in v0.0.4 or deferred with evidence.

8. Verify with tests and Playwright.
   Run backend tests, frontend build, and a Playwright smoke that asks the bootstrap question and checks answer structure, suggested questions, and citation card cleanliness.

## Test Plan

- Unit tests for guided question generation validation and fallback.
- Unit tests for document-locator bypass on guided/install queries.
- Golden answer test for the bootstrap-complete route.
- Citation preview normalization tests for `[CODE]` and shell-session snippets.
- Frontend test or Playwright smoke for:
  - visible three-step guide
  - at least three adaptive suggested questions
  - no raw code markup in citation cards

## Risks

- LLM-generated questions can hallucinate unless they are validated against chunk IDs and source text.
- Randomization can make tests flaky unless seeded.
- Chunking changes can affect retrieval quality across unrelated docs.
- Too much answer structure can become rigid; keep deterministic structure only for guided/install mode.

## Done Criteria

- The provided bootstrap example returns a useful Korean three-step guide.
- Guided suggested questions are AI/chunk-grounded and rotate by seed.
- Citation previews are clean and beginner-readable.
- The implementation has regression tests and a Playwright-quality smoke path.
- Any chunking changes are backed by an audit report, not guesswork.
