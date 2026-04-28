# OCP Project Playbook Course Implementation Plan

Date: 2026-04-23  
Status: Active  
Reference spec: `docs/superpowers/specs/2026-04-23-ocp-project-playbook-course-design.md`

이 문서는 실제 구현 진행용 계획 문서입니다.  
설계 결정은 spec을 기준으로 하고, 구현 우선순위와 완료 상태는 이 plan을 기준으로 관리합니다.

## 1. 목표

`study-docs/*.pptx` 기반의 실제 프로젝트 산출물을 단계형 코스로 재구성해 `/course` 레일을 만든다.

핵심 목표:

- 실제 사업 진행 순서 중심 학습 UX
- PPT를 자연 ID 단위의 text-first chunk로 정규화
- 이미지 shape는 보조 자산으로 부착
- 공식문서 `gold_manualbook_ko`를 보조 참조로 연결
- 기존 PBS/Ops 기능과 충돌 없이 독립 동작

## 2. 구현 원칙

- 기존 `_pptx_to_structured_text()`는 건드리지 않는다
- 신규 `course` 경로와 신규 모듈로만 붙인다
- chunk 본체는 텍스트/구조화 데이터다
- full-slide render는 주 데이터가 아니라 보조/검수용이다
- 이미지 전체가 아니라 slide 내부 image shape만 attachment로 다룬다
- VLM은 보조 설명용이며 chunk 본문을 대체하지 않는다
- official docs는 별도 collection 유지, 검색은 병렬 merge

## 3. 현재 진행 상태

### 완료

#### Phase 0. 코드베이스 매핑

완료.

확인된 재사용 지점:

- PPT 텍스트 추출 참고 경로
  - `src/play_book_studio/intake/normalization/builders.py`
- Qdrant upsert 참고 경로
  - `src/play_book_studio/ingestion/qdrant_store.py`
- retriever 재사용 후보
  - `src/play_book_studio/retrieval/retriever.py`
- viewer/HTML 서빙 재사용 후보
  - `src/play_book_studio/app/server_routes_viewer.py`
- 기존 슬라이드 렌더 자산
  - `tmp/render_ppts.ps1`
  - `tmp/ppt-render/_index.csv`

#### Phase 1. 스파이크 구현

완료.

실제 수행 결과:

- `.venv`에 `python-pptx` 설치
- `unit_test` family PPT 1개를 end-to-end 처리
- 생성 결과:
  - `data/course_pbs/manifests/course_v1.json`
  - `data/course_pbs/chunks/*.json`
- `slide_refs.png_path`도 기존 `tmp/ppt-render` 자산과 연결됨

실행 결과 예:

- `deck_count = 1`
- `chunk_count = 90`

### 진행 중

#### Phase 2. 파이프라인 확장

부분 완료.

현재 된 것:

- family classifier 확장
- parser 뼈대 추가
  - architecture
  - unit_test
  - integration_test
  - perf_test
  - completion_report
- offline official-doc matcher 스캐폴드 추가
- incremental checkpoint 스캐폴드 추가
- 전체 12개 PPT family 분류 성공
- 전체 실행 결과:
  - `deck_count = 12`
  - `chunk_count = 570`

아직 부족한 점:

- `integration/perf/completion`은 아직 coarse한 slide-level placeholder 비중이 큼
- official-doc matcher는 현재 token overlap 기반 임시 버전
- image-shape attachment 중심 구조로 완전히 정렬되지 않음

#### Phase 3. 백엔드 API

부분 완료.

현재 추가된 것:

- `GET /api/v1/course/manifest`
- `GET /api/v1/course/stages/{stage_id}`
- `GET /api/v1/course/chunks/{chunk_id}`
- `GET /api/v1/course/slides/{chunk_id}/{slide_no}.png`
- `GET /api/v1/course/search`
- `POST /api/v1/course/chat`
- `POST /api/v1/course/chat/stream`

현재 상태:

- manifest / stage / chunk / search / basic chat 스모크 확인
- 아직 기존 retriever/Qdrant 병렬 merge 기반의 최종 course chat은 아님

### 미착수

#### Phase 4. 프런트엔드

- `/course`
- `/course/stages/:stageId`
- chunk detail drawer/page

#### Phase 5. 검증 및 회귀

- course 전용 회귀
- 수동 QA
- 기존 PBS/Ops 회귀

## 4. 단계별 계획

### Phase 2. 파이프라인 품질 보정

목표:

- “전체 family가 돈다” 상태에서 “chunk 품질이 맞다” 상태로 올린다

필수 작업:

1. architecture
   - `DSGN-005-XXX` 기준 chunk 정교화
   - 텍스트 본문 + 이미지 attachment + visual summary
2. unit_test
   - 2×2 구조 정확도 보정
   - 결과/계획 variant 분리 전략 정리
3. integration / perf
   - slide-per-chunk 임시 구조 제거
   - 시나리오/결과 묶음 단위 chunk로 재설계
4. completion
   - chapter/section 단위 내러티브 chunk로 재구성
5. image handling
   - full-slide render 의존도 낮추기
   - image shape attachment 중심으로 정렬
6. official-doc matching
   - 현재 token overlap 임시 로직을 고도화할지 판단
7. checkpoints
   - 실제 incremental rebuild에 쓰일 수준으로 보정

완료 기준:

- slide 단위 placeholder chunk를 자연 ID/챕터 단위 chunk로 대체
- 이미지가 chunk 본문이 아니라 attachment로 들어감

### Phase 3. 백엔드 완성

목표:

- `/course` read/search/chat를 프런트가 붙을 수 있는 수준으로 마감

필수 작업:

1. `/course/slides` path traversal 방어 재점검
2. `/course/chat`
   - 기존 retriever/Qdrant 재사용 전략으로 재정렬
   - `course_pbs_ko + gold_manualbook_ko` 병렬 merge
   - `source_kind` 명확화
3. stage/chunk 응답 shape 정리
4. 스모크 테스트 추가

완료 기준:

- `/course/chat`이 project artifact + official doc를 같이 반환
- 프런트에서 그대로 소비 가능한 응답 shape 확보

### Phase 4. 프런트엔드

목표:

- 코스 UX 3페이지 구현

작업:

1. `/course` timeline
2. `/course/stages/:stageId`
3. chunk detail drawer/page
4. 카드 접기/펼치기
5. source_kind 뱃지
6. 기존 chat/citation 재사용

완료 기준:

- timeline -> stage -> chunk 흐름이 실제 UI에서 동작

### Phase 5. 검증

목표:

- 신규 기능 추가 후 기존 PBS/Ops 경로가 안 깨졌는지 보장

작업:

- 프런트 build
- course API smoke
- course manual QA
- 기존 PBS/Ops regression

## 5. 우선순위

실행 순서:

1. Phase 2 품질 보정
2. Phase 3 백엔드 완성
3. Phase 4 프런트엔드
4. Phase 5 검증

즉 다음 집중 대상은 **UI가 아니라 chunk 품질 보정**이다.

## 6. 체크리스트

### Phase 2

- [x] family classifier 5종 분류
- [x] parser 골격 추가
- [x] offline matcher 스캐폴드
- [x] incremental checkpoint 스캐폴드
- [ ] architecture chunk 정교화
- [ ] unit_test parser 품질 보정
- [ ] integration chunk granularity 재설계
- [ ] perf chunk granularity 재설계
- [ ] completion chapter/section chunk화
- [ ] image-shape attachment 구조 정착

### Phase 3

- [x] manifest API
- [x] stage API
- [x] chunk API
- [x] slide API
- [x] search API
- [x] basic course chat scaffold
- [ ] retriever/Qdrant 병렬 merge chat
- [ ] stream 결과 정교화
- [ ] route 스모크 보강

### Phase 4

- [ ] timeline 페이지
- [ ] stage 페이지
- [ ] chunk drawer/page
- [ ] 카드 접기/펼치기
- [ ] source_kind 뱃지

### Phase 5

- [ ] 프런트 build
- [ ] course API smoke
- [ ] 수동 QA
- [ ] 기존 PBS/Ops 회귀 확인

## 7. 리스크 메모

- `study-docs`는 실제 사내 자료이므로 로컬/비공개 환경 전제로만 사용
- full-slide render가 현재 spike에서 일부 쓰이고 있으나 최종 구조에서는 보조 수단이어야 함
- completion report는 narrative chunking 품질이 핵심
- course chat은 지금 placeholder 성격이 있으므로 retriever/Qdrant merge로 반드시 교체 필요

## 7.1 Evaluation-Derived Required Work

The following items are promoted from evaluation notes into the active implementation backlog.

### A. Path normalization

Must fix:

- absolute local paths in persisted JSON
- machine-specific `png_path`, `source_pptx`, and attachment asset paths

Required outcome:

- persisted artifacts store relative paths only
- runtime resolves local absolute paths privately when needed

### B. Title extraction quality

Must improve:

- avoid `Slide N` fallback as the common title path
- promote semantic title extraction into parser completion criteria

Required outcome:

- parent chunks should surface meaningful business/design/test labels by default

### C. slide_graph vs chunk separation

Must enforce:

- `slide_graph_v1` owns semantic layout detail
- `ppt_chunk_v1` owns retrieval/display payload

Required outcome:

- chunk payloads stop carrying unnecessary graph/debug bulk

### D. Conservative child-chunk emission

Must enforce:

- child chunks only when retrieval/drilldown benefit is real
- parent chunks stay the default stage exploration unit

Required outcome:

- stage pages remain learnable and not over-fragmented

### E. Retrieval quality hardening

Must preserve:

- exact-anchor friendliness
- sparse/BM25-style searchable terms
- embedding-backed official-doc matching

Required outcome:

- course search/chat can answer both semantic and exact operational queries

### F. Layout-aware parsing, not global reading-order flattening

Must enforce:

- no parser family should treat top-left -> bottom-right as the primary interpretation strategy
- step markers, table structure, same-row/same-column relations, and caption proximity must win before geometric fallback

Required outcome:

- flow, mapping, table, and lane/process slides preserve their semantic structure in chunking

### G. Group-zone preservation and discarded-zone accounting

Must enforce:

- treat group shapes as semantic zone candidates before full flattening
- preserve repeated header/footer/decorative text as `discarded_zones`
- store discard reasons for later QA/debugging

Required outcome:

- reduced graph noise and easier investigation when expected text is not searchable

### H. Bundle-aware retrieval assembly

Must implement:

- child hit -> parent enrichment
- child hit -> adjacent sibling enrichment when helpful
- parent remains the default stage exploration unit

Required outcome:

- exact row/step hits still return enough slide-level context for educational answers

### I. Intentional search text and facets population

Must populate:

- `index_texts.dense_text`
- `index_texts.sparse_text`
- `index_texts.visual_text`
- exact-anchor `facets`

Required outcome:

- dense retrieval, sparse/exact-anchor retrieval, and filter-based lookup all have stable inputs

## 8. 참조 우선순위

구현 중 판단 우선순위:

1. `docs/superpowers/specs/2026-04-23-ocp-project-playbook-course-design.md`
2. `docs/superpowers/plans/plan.md`
3. 현재 코드베이스 제약

설계와 구현이 충돌하면:

- spec을 먼저 기준으로 판단
- 현실 제약이 있으면 plan에 반영
- spec도 필요 시 같이 갱신

## 9. 다음 액션

다음 구현 액션:

- `integration/perf/completion`의 slide-level placeholder chunk 제거 방향으로 parser 재설계
- image-shape attachment 중심으로 데이터 모델 정렬
- 그 뒤 `/course/chat`을 retriever/Qdrant merge 기반으로 교체

Immediate next implementation backlog:

1. Normalize persisted course paths away from absolute local filesystem paths
2. Improve semantic title extraction in all parser families
3. Continue moving parser input from raw slide rows to `slide_graph_v1`
4. Stop relying on global reading-order flattening in parser heuristics
5. Preserve group-zone semantics and `discarded_zones` consistently across parser families
6. Add bundle-aware retrieval assembly for child-hit responses
7. Reduce child chunk emission where it does not improve retrieval quality
8. Populate `dense_text` / `sparse_text` / `visual_text` and exact-anchor facets intentionally
9. Keep `/course` stage UX parent-first even as child chunks increase internally

## 10. Current Implementation Snapshot

As of the latest implementation round:

- `/course`, `/course/stages/:stageId`, and `/course/chunks/:chunkId` are all connected to generated course data
- `slide_graph_v1` is persisted under `data/course_pbs/slide_graphs/`
- all five stage families are emitted into parent-first chunk sets
- course APIs are live for manifest, stage, chunk, search, chat, and slide image access
- guided learning routes now exist per stage
- route overrides can be curated in `manifests/course_learning_routes_overrides.json`
- image attachments are annotated via the internal VLM endpoint and persisted into both graph/chunk artifacts

Current dataset status:

- not fully gold
- but **gold-ready**

Meaning:

- the dataset is strong enough to support route-first learning
- it still needs explicit review/approval to be called a final gold dataset

## 11. Remaining Work To Reach “Gold”

1. Review and approve stage-level learning routes rather than relying only on generated ordering
2. Stabilize chunk-level `approved / needs_review` review metadata and expose it consistently
3. Verify the route-first UI visually with browser captures
4. Spot-clean noisy attachment descriptions and weak OCR outputs where they reduce learning value
5. Freeze reviewed route/review overrides as the authoritative curated layer
