# Corpus Cleanup Audit

작성일: 2026-05-15
작업 브랜치: `feat/dev-ui`
HEAD: `5c780c8`

## Current Judgment

KMSC `course_pbs`가 현재 가장 깔끔한 패키지 모델이다.
공식 문서 `imported-gold`는 아직 legacy 이름과 중복 산출물이 섞여 있다.
따라서 지금은 삭제보다 역할 문서화와 경로 계약 고정이 우선이다.

## KMSC Reference Model

Path: `corpus/sources/kmsc/parsed-preview/course_pbs`

- `chunks.jsonl`: 523 lines
- `assets/`: 775 files
- `manifests/`: 3 files
  - `course_v1.json`
  - `ops_learning_chunks_v1.jsonl`
  - `ops_learning_guides_v1.json`

좋은 점:

- chunk, asset, manifest가 같은 package boundary 안에 있다.
- 이미지 evidence가 chunk와 guide에 연결된다.
- 사람이 봐도 이 데이터가 무엇을 위한 것인지 추적 가능하다.

## Official Imported Gold State

Path: `corpus/sources/official/imported-gold`

- `gold_candidate_books/`: candidate manifest
- `gold_corpus_ko/`: retrieval seed JSONL
- `gold_manualbook_ko/`: manualbook/playbook seed
- `silver_ko/`: translation draft/cache

주의:

- 여기서 `Gold`는 제품 Gold gate 통과 의미가 아니다.
- `gold_manualbook_ko/playbooks/*.json`은 29개이고 `playbook_documents.jsonl`도 29 line이다.
- 두 산출물은 book slug 기준 1:1이다.
- 하지만 `playbooks/` 경로는 현재 코드와 테스트에서 아직 참조된다.

## Do Not Delete Yet

- `corpus/sources/official/imported-gold/gold_manualbook_ko/playbooks/**`
- `corpus/sources/official/imported-gold/gold_manualbook_ko/playbook_documents.jsonl`
- `corpus/sources/official/imported-gold/gold_corpus_ko/**`
- `corpus/sources/official/imported-gold/silver_ko/translation_drafts/**`
- `corpus/data/wiki_assets/**`
- `corpus/data/wiki_relations/**`
- `corpus/data/wiki_runtime_books/**`
- `corpus/manifests/**`

## Cleanup Direction

1. KMSC `course_pbs` 모델을 공식 데이터에도 적용한다.
2. 공식 데이터 package README를 먼저 만든다.
3. `gold_*` legacy 이름은 제품 Gold와 다르다고 명확히 표시한다.
4. `playbook_documents.jsonl`을 canonical entry로 삼고, per-book JSON은 legacy sidecar/fallback으로 낮춘다.
5. 코드 참조를 `corpus_paths.py` 또는 settings resolver로 모은다.
6. 참조가 0개인 legacy 파일만 삭제한다.

## Resolver Contract

2026-05-15 기준으로 공식 문서 seed 경로는 `play_book_studio.config.corpus_paths`에서 우선순위를 고정한다.

우선순위:

1. `corpus/sources/official/imported-gold/**`
2. legacy fallback `data/gold_*`

이 규칙은 파일을 지금 삭제하기 위한 것이 아니다.
J의 backend/retrieval 작업과 충돌하지 않게, 먼저 읽기 경로를 한 곳으로 모은 뒤 물리 삭제/이동을 별도 단계로 판단하기 위한 안전장치다.

## Current Gap

- 공식 문서에는 KMSC처럼 `assets/ + manifests/ + chunks`가 한 package boundary에 깔끔하게 보이지 않는다.
- translation cache가 corpus source 아래에 있어 J 입장에서는 완료 코퍼스와 중간 산출물을 헷갈릴 수 있다.
- `data/wiki_*`는 sidecar인데 이름만 보면 runtime truth처럼 보일 수 있다.
- 일부 코드가 root `data/gold_manualbook_ko/playbooks` legacy 경로도 참조한다.

## Next Actions

1. resolver 중심으로 공식 문서 active path를 고정한다.
2. code references를 active/candidate/deprecated로 분류한다.
3. official package manifest를 추가한다.
4. 삭제 후보는 `rg`와 테스트로 참조 0개를 확인한 뒤 별도 PR에서 제거한다.
