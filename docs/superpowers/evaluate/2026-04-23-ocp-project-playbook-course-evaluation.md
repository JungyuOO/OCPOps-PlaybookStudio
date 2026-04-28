# OCP Project Playbook Course — Evaluation (2026-04-23)

Date: 2026-04-23
Scope: `/course` 레일 구현 현황 평가 (코드 수정 금지, 관측 결과만 정리)
Reference:
- `docs/superpowers/specs/2026-04-23-ocp-project-playbook-course-design.md`
- `docs/superpowers/plans/plan.md`

이 문서는 현 시점에서 구현된 파이프라인/데이터/API의 상태를 spec·plan과 대조해 정리한 기준선이다.
다음 개선 사이클의 우선순위 판단에만 사용하고, 본 평가 자체가 구현 지시서는 아니다.

---

## 1. 데이터 기준 현황 수치

| 항목 | 값 | 비고 |
|---|---|---|
| chunks 파일 수 | 1,010 | plan 문서의 570에서 증가 |
| DSGN-005 chunks | 52 | PPT 설계ID와 대체로 일치 |
| TEST-UN-OCP chunks | 720 | 동일 test_id에 중복 해시 존재 (`plan-00425e74`, `plan-2001d0ff`) |
| PERF- chunks | 159 | |
| CH- chunks | 6 | 완료보고서 챕터 단위 — spec 기대와 일치 |
| ITG- chunks | 다수 | 대부분 `ITG-<hash>-slide-NNN` (spec 위반 형태) |
| slide_graphs | 10 deck | 존재하지만 chunk와 분리된 독립 계층으로 쓰이지 않음 |
| course API | 6종 (manifest/stage/chunk/slide/search/chat) | 스모크 레벨 동작 |
| 프런트엔드 페이지 | timeline/stage/chunk 3종 | 기능 정합성 미검증 |

---

## 2. Spec 위반 항목 (구조적)

### 2.1 chunk_id 규격이 spec과 다름

- Spec 섹션 6: `{family}:{design_id}:{variant}:{part}:{chunk_kind}:{local_key}`
  - 예: `architecture:DSGN-005-202:default:none:design_summary`
- 현재: `DSGN-005-002--d7bef343` — 해시 suffix만
- spec이 허용한 "파일명 축약"은 OK, 하지만 `native_id`, `bundle_id`, `chunk_kind`, `variant`, `part_no/part_total` 로 semantic shape을 보존해야 함.
- 실제 chunk를 보면 `bundle_id` 필드 없음, `chunk_kind` 있는 chunk와 없는 chunk 혼재, `part_no/part_total` 대부분 null.

### 2.2 slide_graph와 chunk가 실질적으로 분리돼 있지 않음

- Spec 섹션 3: "slide_graph는 중간 artifact, 검색/인덱스 계층이 아니다", "chunk가 검색 단위"
- 현실: TEST-UN-OCP-01-01 chunk 본체에 `semantic_zones`(23개), `zone_relations`(26개)가 통째로 박혀있음. DSGN-005-209 chunk는 단일 JSON이 53K 토큰 초과로 읽기조차 불가한 크기.
- 결과: chunk가 무거워져서 재인덱싱/네트워크 전송 비용 급증. 구조적으로 가장 큰 문제.

### 2.3 parent/child 분해 불완전

| 패밀리 | 상태 |
|---|---|
| unit_test | 부모 + method/expected/verification 자식 ✓ |
| architecture (DSGN) | design_id 하나당 flat 1개. `chunk_kind`(design_summary/step/mapping_row/table_row) 분할 없음 ❌ |
| integration | `ITG-<hash>-slide-NNN` 슬라이드 1:1 placeholder. scenario/test_case 단위 묶음 아님 ❌ |
| perf | 슬라이드 1:1 placeholder 비중 큼 ❌ |
| completion | 챕터 단위 6개 ✓ |

Spec 섹션 7의 layout_type → chunk_kind 매핑 테이블이 architecture/integration/perf 파서에 아직 반영되지 않았다.

### 2.4 title 추출 실패

- 현재 다수 chunk의 `title`이 `"Slide 7"`, `"Slide 11"` 같은 slide_no 원문
- 실제 슬라이드엔 `zone_role: "label"`로 한글 섹션 제목이 존재 (예: "OCP 전체 Node 이중화 및 상태 점검")
- 파서 후처리에서 대표 title을 고르는 로직이 빠져있음
- 영향: UI 카드/타임라인/citation 전반에서 "Slide 7"만 노출되어 학습 효과 대폭 저하

### 2.5 VLM이 파이프라인에 연결되지 않음

- 모든 chunk의 `visual_summary: null`, `visual_text: ""`
- spec/brainstorm에서 합의된 "Qwen3.5 9B VLM으로 이미지 보조 캡션" 기능이 인덱스 빌드에 미연결
- `pipeline/` 디렉토리에 VLM annotator 모듈 없음
- 영향: 이미지 중심 슬라이드(architecture 다이어그램, 통합/성능 스크린샷) 검색 불가

---

## 3. 품질 저하 (동작하지만 신뢰도 낮음)

### 3.1 공식문서 매칭이 거의 헛됨

- TEST-UN-OCP-01-01 (노드 헬스체크) → `IBM Z/LinuxONE 다중 아키텍처 컴퓨팅 머신` 3개 변종 매칭 (score 0.64)
- ITG-14ee498d-slide-011 → `2.15.2. GPU 할당 오브젝트 정보` (score 0.42)
- 현재 token overlap 기반 임시 로직 (plan도 인정)
- 현 상태로 citation 노출하면 "PBS가 엉터리"라는 첫인상을 먼저 받을 가능성
- 최소한 score 임계치(예: 0.7) 하한 또는 dense embedding 기반 재매칭 필요

### 3.2 search_text가 비어있는 chunk 다수

- ITG slide chunk: `search_text: "Slide 11\nslide-011"` — 사실상 검색 불가
- 이미지만 있는 슬라이드는 VLM 없이는 인덱스에서 dead weight

### 3.3 body_md 여전히 shape-order

- TEST-UN-OCP-01-01 body_md: "사업명 → 섹션 → 테스트ID → CLI명령 → master 3대 → No-Pass → Web Console … Pass" 식 shape 등록 순서
- Spec 섹션 2가 명시적으로 금지한 방식 (reading order 단독 의존)
- structured.method/expected/verification는 heuristic 부분 성공이지만 Pass/No-Pass 라벨이 expected 내부에 섞여 들어감

### 3.4 중복 chunks

- 동일 `TEST-UN-OCP-01-01--plan`이 hash `00425e74`, `2001d0ff` 두 버전 존재 (plan deck과 결과 deck 양쪽에서 들어온 것으로 추정)
- manifest는 `2001d0ff`만 참조, 나머지는 고아 파일
- `/api/v1/course/chunks/{id}`가 고아 파일도 제공해서 혼선 가능

---

## 4. 배포·보안 관련

### 4.1 절대 경로 박제 (심각)

- chunk JSON의 `slide_refs.pptx`, `png_path`, `image_attachments.asset_path`, `source_pptx` 가 전부 Windows 절대경로 (`C:\Users\KJungyu\OneDrive\…`)
- 다른 머신/컨테이너에서 그대로 사용 불가
- CI·스테이징·프로덕션 어디로 옮겨도 깨짐
- `study-docs/...` 같은 저장소 상대경로로 정규화 필요
- 이 문제가 다른 모든 개선보다 먼저 해결돼야 나머지 결과물이 재사용 가능

### 4.2 `/course/slides` path traversal 방어

- 현재 `Path(png_path).resolve().exists()` 만 체크
- resolved가 `data/course_pbs/` 밖을 벗어나도 그대로 서빙됨
- 입력 png_path는 인덱스 산출이라 악용 가능성 낮지만, 방어-심층화 관점에서 root prefix 검사 필요
- plan에도 이미 TODO로 있음

### 4.3 Gitignore 경계

- `study-docs/*` 는 .gitignore 처리됨 ✓
- `data/course_pbs/` 는 절대경로가 박제된 JSON을 포함 — 저장소에 커밋되면 사용자 로컬 경로가 그대로 노출됨. gitignore 경계 확인 권장

---

## 5. 현 상태에서 이미 잘 된 것

- unit_test parent/child 분해 (method/expected/verification) 구조가 spec 취지와 맞음
- CH- 챕터 단위 chunk 6개는 완료보고서 I~VI와 자연스럽게 대응 — spec narrative 규칙과 일치
- `search_course_and_official` 병렬 호출 + 파일 기반 fallback — spec 섹션 10 방향과 일치
- sources 배열에 `source_kind: "project_artifact" | "official_doc"` 필드 존재 — 프런트 뱃지 구분 준비됨
- `image_attachments[]` 필드 분리 저장 — spec 섹션 8 방향과 일치 (파이프라인 정렬은 아직)
- `related_official_docs` 인라인 pre-compute — 런타임 재조회 없이 노출 가능
- 기존 `_pptx_to_structured_text()` 경로와 `gold_manualbook_ko` 컬렉션을 건드리지 않음 — 원칙 유지

---

## 6. 우선순위 제안 (관찰 기반)

다음 사이클에서 손볼 순서 제안. 실제 구현 여부·일정은 별도 결정.

1. **절대경로 정규화 (§4.1)** — 나머지 개선이 이 머신 전용이 되는 것을 방지
2. **title 추출 수정 (§2.4)** — 한 줄 수정 수준이지만 UX 체감 가장 큼
3. **slide_graph와 chunk 분리 (§2.2)** — DSGN chunk 크기 블로킹 해결
4. **architecture/integration/perf의 chunk_kind 분할 (§2.3)** — retrieval 품질 핵심
5. **공식문서 매칭 품질 (§3.1)** — 최소 임계치 하한부터
6. **VLM 연결 (§2.5)** — 이미지 중심 슬라이드 살리기
7. 중복 chunk 정리 (§3.4) / path traversal 방어 (§4.2) / body_md 재정렬 (§3.3)

---

## 7. plan.md 체크리스트 대조

plan.md가 이미 인정하고 있는 항목:

- Phase 2: `architecture chunk 정교화`, `unit_test parser 품질 보정`, `integration/perf chunk granularity 재설계`, `completion chapter/section chunk화`, `image-shape attachment 구조 정착`
- Phase 3: `retriever/Qdrant 병렬 merge chat`, `stream 결과 정교화`, `route 스모크 보강`, `/course/slides path traversal 방어`
- Phase 4: 전부 미착수 (timeline/stage/chunk 페이지, 카드 접기/펼치기, source_kind 뱃지)

plan에 **추가 권장**되는 항목:

- 4.1 절대경로 정규화 (현재 plan에 해당 작업 없음)
- 2.1 chunk_id 규격 spec 준수 (현재 plan에 명시 없음)
- 2.2 slide_graph ↔ chunk 책임 분리 (plan은 "slide_graph 존재"만 언급)
- 2.4 title 추출 (plan의 parser 품질 보정에 묵시적으로 포함되나 단독 항목으로 분리 권장)
- 3.4 중복 chunk 정리 (plan에 없음)

---

## 8. 이 평가의 범위 밖

- 프런트엔드 3페이지의 실제 렌더링 품질은 이번 평가에서 확인하지 않음 (코드 열람만, 동작 검증 안 함)
- 기존 PBS/Ops 회귀 상태 (README 최소 검증 명령 결과) 이번 평가에서 수행하지 않음
- Qdrant 컬렉션 실제 상태(벡터 수, 필드 매핑)는 이번 평가에서 확인하지 않음

이 세 가지는 다음 평가 사이클에서 별도 체크 대상.
