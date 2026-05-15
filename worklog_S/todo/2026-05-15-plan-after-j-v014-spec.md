# 2026-05-15 plan after J v0.1.4 spec review

Date: 2026-05-15
Source reviewed: `spec/v0.1.4/`

## Current Judgment

J가 작성한 v0.1.4 spec은 "챗봇이 개같이 답한다" 문제를 단순 prompt 문제가 아니라 corpus schema 문제로 본다.

핵심은 다음이다.

- parsing layer와 corpus layer를 분리한다.
- parsing은 원본 보존 계층이다.
- corpus는 검색/답변 truth다.
- chunk 본문을 markdown blob 하나로 들고 있지 않고, ordered typed segments로 나눈다.
- 명령어는 텍스트가 아니라 first-class row로 뽑는다.
- 환경 의존 명령은 session/platform 조건 없이 무차별 노출하지 않는다.
- 다음 단계/후속질문은 jsonb 안에 숨기지 않고 `corpus_chunk_refs`, `corpus_question_candidates`로 격상한다.

따라서 오늘 S 쪽 일은 새 기능 추가가 아니라, S가 맡은 데이터/코퍼스 생산 라인을 이 계약에 맞게 정렬하는 것이다.

## J Spec Summary

Files:

- `spec/v0.1.4/planner.md`
- `spec/v0.1.4/db-parsing-schema.md`
- `spec/v0.1.4/db-corpus-schema.md`

Latest check: 2026-05-15 09:58 파일 기준으로 재확인.

J의 v0.1.4 in-scope:

- parsing schema 정의
- corpus schema 정의
- official JSON, PPT-OCR, user upload PDF가 같은 corpus shape으로 들어오는 dry-run mapping
- chunk segment 모델
- command/env scope 모델
- refs/followup 모델
- Qdrant payload projection 계약
- text 4계층 계약: `raw_text` / `markdown` / `normalized_text` / `embedding_text`
- UTF-8/encoding 계약: mojibake 방지, 명시 encoding, `ensure_ascii=False`
- v0.1.5 적용 시 Qdrant drop & rebuild 전제

J의 v0.1.4 out-of-scope:

- SQL migration 작성
- reranker/scoring 변경
- 평가셋/report 처리
- course runtime 재설계
- `document_chunks` 즉시 삭제

Spec consistency note:

- `planner.md`에는 `Text 4계층 계약`, `Encoding Contract`, `Reindex Plan` 참조가 추가됐다.
- 현재 확인 시점의 `db-corpus-schema.md`에는 위 제목의 상세 섹션이 아직 보이지 않는다.
- 오늘 작업에서는 이 세 항목을 gap audit에 포함하고, J에게 "planner 원칙은 확인했는데 corpus schema 상세 섹션도 추가될 예정인지" 확인해야 한다.

## Important Correction To Our Plan

기존 S 계획의 `Metadata Spine`은 방향은 맞았지만, 이제 별도 독자 구조로 만들면 안 된다.

수정된 해석:

- `topic`, `semantic_role`, `k8s_objects`, `cli_commands`, `error_strings`, `verification_hints`, `answerable_questions`는 v0.1.4 corpus schema의 컬럼/segments/commands/refs/question_candidates로 매핑되어야 한다.
- `metadata jsonb`에 검색·답변용 값을 숨기면 J spec과 충돌한다.
- S가 해야 하는 일은 metadata를 많이 만드는 것이 아니라, parsing 결과를 corpus truth로 변환할 때 어떤 값이 컬럼/segment/command/ref가 되는지 검증하는 것이다.

## Today Goal

오늘 목표:

1. `corpus/` 폴더 정리 마무리
2. S/J v0.1.4 책임 경계 문서화
3. 현재 데이터가 v0.1.4 schema로 어떻게 dry-run 매핑되는지 확인
4. 현재 pipeline/gold/reader 문제가 v0.1.4에서 어느 계층 문제인지 분류
5. 이후 SQL/구현 phase로 넘어가기 전에 S가 제공해야 할 corpus evidence를 확정

## Locked Execution Order

오늘 작업 순서는 아래로 고정한다.

0. 완료: J `spec/v0.1.4` 읽기
   - `planner.md`
   - `db-parsing-schema.md`
   - `db-corpus-schema.md`

1. 완료: 현재 데이터 인벤토리 baseline 고정
   - official source docs: 29
   - Gold Ready: 23
   - Repair Needed: 11
   - official candidates: 84
   - official catalog total: 113
   - KMSC/customer package 위치와 문서 수
   - user upload 현재 상태
   - DB/Qdrant/storage 중 어느 값이 runtime truth인지 표시
   - 결과 문서: `worklog_S/todo/2026-05-15-inventory-baseline.md`

2. 완료: corpus 폴더 구조 정리
   - `corpus/sources/official`
   - `corpus/sources/kmsc`
   - `corpus/manifests`
   - `corpus/data`
   - legacy `imported-gold`
   - 목적: 폴더를 예쁘게 만드는 것이 아니라 v0.1.4 source/import/evidence 경계를 사람이 바로 이해하게 만드는 것

3. 완료: v0.1.4 용어 브릿지 작성
   - 기존 S 용어와 J schema 용어를 연결한다.
   - `topic` → `domain`, `task_intent`, `lifecycle_phase`, `facets`
   - `semantic_role` → `chunk_type`, `chunk_role`, `segment_type`, `segment_role`
   - `cli_commands` → `corpus_chunk_commands`
   - `answerable_questions` → `corpus_question_candidates`
   - `topology/next` → `corpus_chunk_refs`
   - 기존 `chunk_text`/`markdown`/`original_text` 혼용 → `raw_text`, `markdown`, `normalized_text`, `embedding_text` 4계층으로 분해
   - 결과 문서: `docs/corpus/V014_TERM_BRIDGE.md`

4. 실제 데이터 3종 dry-run mapping
   - official JSON/OCP 문서 1개
   - KMSC/customer 문서 1개
   - user upload PDF 1개
   - 각 샘플을 `document_sources`부터 `corpus_question_candidates`까지 손으로라도 매핑한다.

5. 현재 구조와 v0.1.4 gap audit
   - `document_chunks`가 parser output과 retrieval truth를 동시에 책임하는지 확인
   - markdown blob 안에 prose/command/output/table/image가 섞이는 지점 확인
   - 이미지 asset 연결이 어디서 끊기는지 확인
   - Qdrant payload가 어떤 필드까지 가져야 하는지 확인
   - 현재 임베딩 입력에 code fence, `[CODE]` 마크업, URL, viewer path가 섞이는지 확인
   - 파일 I/O에서 `encoding="utf-8"` 누락과 mojibake 가능 지점 확인
   - Qdrant는 새 `embedding_text` 기준으로 재임베딩/drop & rebuild가 필요한지 확인

6. Metadata Spine 문서 재정렬
   - 독자 metadata 체계를 만들지 않는다.
   - v0.1.4 schema의 컬럼, segment, command, ref, question candidate로 흡수한다.

7. S/J handoff 계약 정리
   - S가 넘길 evidence와 J가 남길 trace를 정한다.
   - 실패를 corpus gap / retrieval gap / answer gap / citation gap으로 분류한다.

8. Wiki Library count/label fix
   - `29 official source docs`와 `23 Gold + 11 repair`를 같은 "권"처럼 보이지 않게 한다.

9. Upload pipeline / Gold quality 검증 재개
   - 오늘 핵심 1~7이 정리된 뒤 이어간다.
   - schema 합의 없이 Gold 자동수리나 topology 확장을 새로 벌리지 않는다.

## MVP Guardrails

Implementation guardrail:

- `worklog_S/todo/2026-05-15-v014-mvp-guardrails.md`

Interpretation:

- v0.1.4 전체 schema를 한 번에 구현하지 않는다.
- 먼저 metadata strategy가 반영되는 최소 경로만 구현 대상으로 본다.
- `corpus_chunk_refs`, `corpus_question_candidates`, full answer card renderer는 dry-run/gap 기록까지만 둔다.
- `DB migration 초안`은 가능하지만, 합의 전 실제 적용 migration으로 취급하지 않는다.

## Do Not Do Today

- SQL migration을 먼저 만들지 않는다.
- 새 topology 대형 구현을 다시 벌리지 않는다.
- reranker/scoring을 S가 건드리지 않는다.
- 문서 품질 고도화를 schema 합의 없이 혼자 밀어붙이지 않는다.
- `document_chunks`나 legacy table을 삭제하지 않는다.
- `corpus/` 안의 legacy seed를 근거 없이 물리 삭제하지 않는다.

## Work Plan

### P0. Corpus Folder Cleanup As Source Contract

Purpose:

`corpus/`는 runtime truth가 아니라 v0.1.4 parsing/corpus를 만들기 위한 source/import/evidence 영역임을 고정한다.

Tasks:

- `corpus/sources/official/`가 official source/import seed임을 README에 더 명확히 적는다.
- `corpus/sources/kmsc/parsed-preview/course_pbs/`를 clean customer/operations package reference로 유지한다.
- `corpus/data/`는 runtime truth가 아니라 sidecar/evidence임을 유지한다.
- `imported-gold`는 제품 Gold가 아니라 legacy official seed/evidence라고 명시한다.
- 폴더명과 README가 v0.1.4 용어와 충돌하는지 확인한다.

Acceptance:

- 팀원이 `corpus/`를 보고 "여기는 DB truth가 아니라 source/import/evidence다"라고 말할 수 있다.
- `official`, `kmsc`, `manifests`, `data` 역할이 분리된다.
- J가 schema 작업을 볼 때 `corpus/` 폴더 때문에 Gold/runtime truth를 오해하지 않는다.

### P0. S/J Boundary Memo

Purpose:

S가 데이터 생산을 맡고 J가 챗봇/Ops를 맡는 역할을 v0.1.4 schema 기준으로 합의한다.

S owns:

- source 수집/정리
- parsing input 품질
- official/KMSC/user upload dry-run sample 제공
- corpus field mapping evidence
- metadata extraction rule 초안
- quality blocker 분류
- handoff report

J owns:

- chatbot retrieval/hydration
- answer card renderer
- prompt contract
- session/env-based command filtering
- reranker/scoring
- Ops integration

Shared:

- `RetrievalHit`/`Citation` compatibility
- Qdrant payload contract
- golden questions
- failure classification

Acceptance:

- 챗봇이 틀렸을 때 `S corpus gap`, `J retrieval/answer gap`, `shared citation gap`으로 나눌 수 있다.

### P0. v0.1.4 Dry-Run Mapping

Purpose:

SQL 없이도 현재 데이터가 새 구조로 갈 수 있는지 검증한다.

Dry-run samples:

1. Official JSON/OCP 문서 한 챕터
2. KMSC/customer PPT-OCR 또는 course package 한 슬라이드
3. User upload PDF 한 페이지

For each sample, map:

- source → `document_sources`
- version → `document_versions`
- parser run → `parse_jobs`
- parsed output → `parsed_documents`
- blocks/assets → `document_blocks`, `document_assets`
- corpus doc → `corpus_documents`
- chunk → `corpus_chunks`
- prose/command/output/table/image → `corpus_chunk_segments`
- commands → `corpus_chunk_commands`
- next/verify/env/related → `corpus_chunk_refs`
- starter/followup → `corpus_question_candidates`

Acceptance:

- 각 sample마다 "현재 구조에서 어디가 부족한지"가 보인다.
- official JSON, KMSC/PPT, user upload PDF가 같은 `corpus_chunks` shape으로 도달 가능한지 판단할 수 있다.

### P0. Current Gap Audit Against J Spec

Purpose:

현재 제품이 왜 답변/Reader/Gold에서 허접해 보이는지 J spec 기준으로 원인 분류한다.

Likely gaps:

- `document_chunks`가 parser output과 retrieval truth를 동시에 책임한다.
- 본문이 markdown blob이라 prose/command/output/table/image가 섞인다.
- `[CODE]` 같은 inline workaround가 남아 있다.
- command/env scope가 first-class가 아니라 검색과 답변에서 섞인다.
- image asset이 Reader/Corpus/Chat citation에 연결되지 않는다.
- question/followup/next refs가 corpus truth가 아니라 산발적 metadata다.

Acceptance:

- "품질이 왜 나쁜지"를 감정이 아니라 schema gap으로 설명할 수 있다.
- 오늘 이후 수리 작업이 code patch가 아니라 어떤 layer를 고치는 일인지 보인다.

### P1. Wiki Library Count Label Fix

Purpose:

29개 vs 34권 혼동을 UI에서 다시 만들지 않는다.

Action:

- `official source documents`: 29
- `Gold Ready`: 23
- `Repair Needed`: 11
- `Official Candidates`: 84
- `Official Catalog Total`: 113

Acceptance:

- 화면이 공식 원천 문서 수와 운영 위키 산출물 수를 같은 "권"처럼 보여주지 않는다.

Detailed task:

- `worklog_S/todo/2026-05-15-wiki-library-count-mismatch.md`

### P1. Metadata Strategy Rewrite To v0.1.4 Terms

Purpose:

기존 `Metadata Spine` 문서를 J spec과 합친다.

Rewrite:

- `topic` → `domain`, `task_intent`, `lifecycle_phase`, `facets`
- `semantic_role` → `chunk_type`, `chunk_role`, `segment_type`, `segment_role`
- `cli_commands` → `corpus_chunk_commands`
- `k8s_objects` → `corpus_chunks.k8s_objects`, `resource_kinds`, `api_groups`
- `verification_hints` → `corpus_chunks.verification_hints` + verification segments/refs
- `answerable_questions` → `corpus_question_candidates`
- `topology/next` → `corpus_chunk_refs`

Acceptance:

- S의 metadata strategy가 J spec과 다른 병렬 체계를 만들지 않는다.
- J가 retrieval/hydration에 바로 쓸 수 있는 필드명으로 대화할 수 있다.

### P2. Upload Pipeline / Gold Quality Continue Later

Purpose:

업로드 pipeline 정상화는 계속 중요하지만, 오늘 schema 합의 없이 더 뜯으면 협업 범위를 넘어간다.

오늘 할 수 있는 것:

- current upload quality issue를 v0.1.4 gap으로 분류
- image/code/table/command가 어떤 segment로 가야 하는지 sample evidence 남기기
- Gold blocker가 parsing 문제인지 corpus conversion 문제인지 나누기

오늘 하지 않을 것:

- Gold 자동수리 확장 구현
- 대형 topology 구현
- DB migration

## Acceptance For Today

오늘 완료 조건:

- `corpus/` 구조와 README가 v0.1.4 source contract와 충돌하지 않는다.
- S/J boundary memo가 문서화된다.
- dry-run mapping template 또는 sample 1개 이상이 준비된다.
- 기존 Metadata Spine 문서가 v0.1.4 schema 용어로 재정렬된다.
- 29 vs 34 count issue는 할 일로 남거나 UI fix scope가 확정된다.
- 다음 구현 phase에서 SQL부터 칠지, dry-run을 더 할지 판단 가능하다.
