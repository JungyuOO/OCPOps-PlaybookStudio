# 2026-04-23 Playbook Unified Surface Strategy

## Ref Stamp

- branch: `feat/book-kugnus`
- head: `60915cd6bf19bb30c8f8bef6d885cb55a770d09e`
- base: `origin/main`
- merge-base: `10574bffa0a7e53b8c06533eba73f8eb946a9563`

## 이번 문서의 목적

이번 업그레이드의 목표를 헷갈리지 않게 잠근다.
핵심은 특정 확장자 대응이 아니라, 서로 다른 포맷으로 들어온 문서들이 같은 플레이북 생태계에 합류하고 서로 연계되게 만드는 것이다.

## 목표

모든 문서는 포맷별 전처리를 거친 뒤 공통 플레이북 그래프에 승급되어야 한다.
승급된 뒤에는 공식 매뉴얼, 고객 커스텀 문서, 내부 운영 문서가 서로 연결되어야 하며, 같은 진실 소스에서 다음 산출물이 함께 파생되어야 한다.
특히 고객이 제공한 PPT 사내문서들은 OCP 공식 매뉴얼과 함께 Playbook으로 통합되어야 하며, UI에서는 출처 종류가 구분되어야 하지만 내부적으로는 하나의 LLM Wiki에 종속되어 챗봇이 함께 학습하고 반응할 수 있어야 한다.

- Wiki Book
- Ops Playbook
- Viewer surface
- Chatbot corpus
- Study asset

## 완료 조건

다음이 모두 성립하면 이번 방향 정리는 완료로 본다.

1. 포맷별 파서와 플레이북 공통 계약이 분리되어 있다.
2. PPT, HWP/HWPX, DOCX, PDF, HTML 등은 입구만 다르고 승급 후 구조는 같다.
3. 뷰어는 단일 HTML 문서만 보는 구조가 아니라 포맷별 표면을 렌더링할 수 있다.
4. `single` / `multi` 모드는 같은 원본 패킷에서 동작한다.
5. 챗봇 코퍼스와 책 산출물은 같은 truth packet에서 파생된다.
6. 모든 플레이북은 relation graph 위에서 서로 연결된다.
7. UI에서는 `OCP 공식 매뉴얼`과 `고객사 커스텀 문서`가 구분되어 보이되, 챗봇과 검색은 둘을 함께 참조할 수 있다.
8. 고객사 PPT 자료는 업로드 후 플레이북으로 승급되어 공식 매뉴얼과 함께 LLM Wiki 지식 기반에 합류한다.

## 하지 않을 것

- 확장자마다 완전히 다른 제품처럼 따로 설계하지 않는다.
- PPT를 억지로 긴 문서 HTML 하나로 평탄화해서 원본 의미를 잃게 만들지 않는다.
- 뷰어와 코퍼스를 서로 다른 진실 소스에서 따로 만들지 않는다.
- 쉬운 문서만 우선 승급시키고 복잡한 문서를 예외로 남겨두지 않는다.

## 우리가 잠그는 핵심 판단

### 1. 모든 플레이북은 연계 플레이가 되어야 한다

공식 매뉴얼, 고객 문서, 내부 운영 가이드는 별개의 결과물이 아니다.
서로 다른 출처의 문서라도 승급 후에는 같은 그래프에 올라가야 하며, 개념, 절차, 정책, 장애 대응, 표, 그림, 근거 링크가 서로 연결되어야 한다.

즉 구조는 다음과 같다.

`포맷별 입구 -> 공통 플레이북 그래프 -> 다중 산출물 -> 상호 참조/검색/학습/운영`

### 2. 뷰어도 공통 계약 위에 올라가야 한다

지금까지 놓친 핵심은 "파싱할 수 있느냐"만 보고 "표현할 수 있느냐"를 늦게 본 점이다.
앞으로는 문서 수집과 파싱의 기준이 아니라, 최종적으로 뷰어가 그 문서를 온전히 표현할 수 있는지까지 포함해 계약을 잡아야 한다.

### 3. PPT는 HTML 뷰어 안에서 슬라이드로 본다

PPT를 보기 위해 별도 전용 앱을 만드는 것이 아니다.
현재 HTML 뷰어를 확장해서 PPT를 `slide_deck` surface로 렌더링한다.

즉 해석은 다음과 같다.

- 브라우저가 PPT 파일 자체를 직접 여는 것이 아니다.
- 파이프라인이 PPT에서 슬라이드 패킷을 만든다.
- HTML 뷰어가 그 슬라이드 패킷을 렌더링한다.

그래서 다음이 가능해야 한다.

- `single`: 슬라이드 1장 집중 보기
- `multi`: 슬라이드 연속 보기
- `outline`: PPT 목차/제목 기반 탐색
- `asset view`: 이미지/도표/표를 원본 의미에 가깝게 표시

## 제품 구조

### 1. Intake Lane

입구는 포맷별로 다르다.

- PPTX
- HWP / HWPX
- DOCX
- PDF
- HTML
- Markdown
- 기타 확장 문서

각 포맷은 여기서 전처리, 정제, 자산 추출, 메타 파악을 한다.

### 2. Promotion Lane

입구가 다르더라도 승급 후에는 공통 구조로 맞춘다.
문서를 단순 텍스트가 아니라 플레이북 유닛으로 승급시킨다.

공통 유닛 예시:

- `section`
- `slide`
- `page`
- `table`
- `figure`
- `procedure`
- `policy`
- `signal`
- `citation`
- `relation`

### 3. Truth Packet

모든 산출물은 같은 truth packet에서 파생된다.

권장 공통 키:

- `doc_id`
- `surface_kind`
- `unit_id`
- `anchor`
- `asset_ref`
- `relation_ids`

### 4. Output Lane

같은 truth packet에서 다음 결과가 동시에 나와야 한다.

- viewer용 `book json`
- chatbot용 `jsonl`
- wiki/book용 승급 결과
- 학습용 study asset

## Viewer Contract

현재 뷰어는 사실상 `html document payload` 중심이다.
이번 업그레이드에서는 이를 `surface-aware viewer contract`로 올린다.

권장 필드:

- `surface_kind`
- `title`
- `outline`
- `units`
- `assets`
- `semantic_blocks`
- `relations`
- `viewer_modes`

`surface_kind` 예시:

- `document`
- `slide_deck`
- `paged_document`
- `sheet_grid`
- `image_canvas`

## PPT 전용 해석

PPT는 별도 예외가 아니라 가장 대표적인 검증 대상이다.
고객 문서 `P` 같은 자료는 슬라이드 중심 구조를 잃지 않아야 한다.

PPT 승급 기준:

1. 원본 슬라이드 수를 유지한다.
2. 슬라이드 제목과 agenda를 outline으로 반영한다.
3. 이미지, 표, 다이어그램은 viewer에서 보인다.
4. 텍스트 추출은 챗봇/검색용 semantic lane으로 보낸다.
5. 뷰어와 코퍼스는 같은 slide packet을 참조한다.

## 저장 계약

기존 합의는 유지하되 의미를 명확히 한다.

- `json`: viewer/book/playbook용 truth packet
- `jsonl`: chatbot/retrieval용 semantic corpus

중요한 점은 포맷이 아니라 연결성이다.
둘은 서로 다른 결과물이지만 같은 원본 단위 id를 공유해야 한다.

공유 키 예시:

- `doc_id`
- `slide_id`
- `page_id`
- `anchor`
- `asset_ref`

코퍼스 메타 최소 계약:

- `surface_kind`
- `source_unit_kind`
- `source_unit_id`
- `source_unit_anchor`
- `origin_method`
- `ocr_status`
- `lineage_viewer_path`
- `graph_relations`

청크 계열:

- `section chunk`
- `relation chunk`
- `table chunk`
- `visual/ocr chunk`

## Acceptance Criteria

### A. 공통 구조

- pass/fail: 모든 포맷이 공통 truth packet으로 승급되는가
- 측정 방법: 포맷별 산출물에 `doc_id`, `surface_kind`, `units`, `relations`가 존재하는지 확인
- evidence: 각 포맷 샘플의 packet JSON
- 현재 gap: 포맷별 수집은 되지만 뷰어 표현 계약은 아직 문서 HTML 중심

### B. PPT viewer fidelity

- pass/fail: PPT 슬라이드가 `single` / `multi`로 표현되는가
- 측정 방법: 원본 슬라이드 수와 viewer unit 수 비교, 슬라이드 제목/이미지/표 표시 확인
- evidence: `P` 샘플의 슬라이드 packet과 viewer 캡처
- 현재 gap: 슬라이드가 row/section으로 평탄화되어 원형 보존이 부족함

### C. 연계 플레이

- pass/fail: 고객 문서와 공식 매뉴얼이 relation graph로 연결되는가
- 측정 방법: 한 플레이북 유닛에서 관련 공식 문서/관련 운영 문서/관련 절차가 조회되는지 확인
- evidence: relation payload와 UI 링크
- 현재 gap: 출처별 목록은 있으나 공통 그래프 기반 연결은 아직 약함

### D. 챗봇 연계

- pass/fail: 챗봇 답변이 정확한 원본 단위로 돌아가는가
- 측정 방법: 답변 citation이 `slide_id` 또는 `page anchor`로 복귀하는지 확인
- evidence: retrieval result + viewer deep link
- 현재 gap: semantic 결과와 viewer fidelity packet의 연결 키가 더 강해져야 함

### E. 통합 플랫폼 목표

- pass/fail: 고객사 PPT와 OCP 공식 매뉴얼이 함께 챗봇의 참조 기반으로 동작하는가
- 측정 방법: 하나의 질문에 대해 공식 문서와 커스텀 문서 양쪽 citation이 반환되는지 확인
- evidence: 질의응답 로그 + source badge가 있는 citation 목록
- 현재 gap: UI상 구분은 일부 가능하지만 통합 retrieval 관점의 계약은 더 명확해져야 함

## 실행 순서

1. 공통 viewer contract를 잠근다.
2. PPT를 첫 검증 포맷으로 삼아 `slide_deck` truth packet을 만든다.
3. HTML 뷰어에서 `slide_deck`의 `single` / `multi` surface를 렌더링한다.
4. 같은 packet에서 `jsonl` 코퍼스를 파생한다.
5. relation graph를 붙여 공식 매뉴얼과 커스텀 문서를 연결한다.
6. 이후 HWP/HWPX, DOCX, PDF도 같은 승급 라인에 편입한다.

## 실행 유닛

### Unit 1. Source Boundary and Catalog

목표:
공식 매뉴얼과 고객사 커스텀 문서의 경계를 UI와 데이터 계약에서 명확히 한다.

작업:

- source kind를 `official` / `custom` / `uploaded draft` 기준으로 정리
- `/studio` 와 `/repository` 에서 공식/커스텀 표시 규칙 고정
- 업로드 문서가 커스텀 승급 후보로 이어지는 목록 계약 정의

완료 조건:

- UI에서 공식과 커스텀의 종류가 명확히 구분된다
- 커스텀 문서가 raw 노출 없이 목록화된다
- 이후 승급 파이프라인이 참조할 source id 체계가 정리된다

### Unit 2. Customer PPT Intake

목표:
고객사 PPT를 슬라이드 중심 원본으로 캡처하는 커스텀 intake를 만든다.

작업:

- PPT에서 slide/title/agenda/table/image 메타 추출
- 슬라이드별 stable id 부여
- 원본 슬라이드 렌더 또는 자산 추출 규칙 정의

완료 조건:

- 원본 슬라이드 수와 intake 결과 unit 수가 일치한다
- 주요 이미지/표/슬라이드 제목이 packet에 보존된다

### Unit 3. Slide Deck Viewer Surface

목표:
HTML 뷰어 안에서 `slide_deck` surface를 `single` / `multi` 로 렌더링한다.

작업:

- viewer contract에 `surface_kind` 확장
- `slide_deck` renderer 추가
- outline / slide navigation / asset render 연결

완료 조건:

- PPT가 문서형 section이 아니라 슬라이드형 surface로 보인다
- `single` / `multi` 가 같은 packet으로 동작한다

### Unit 4. Playbook Promotion and Corpus Split

목표:
같은 slide packet에서 플레이북용 JSON과 챗봇용 JSONL을 동시에 파생한다.

작업:

- slide packet -> playbook section/rich unit 승급
- slide packet -> retrieval chunk/jsonl 파생
- 공통 citation key 부여

완료 조건:

- viewer/book/chatbot 이 같은 truth packet 계열을 공유한다
- citation이 slide/page anchor로 돌아간다

### Unit 5. Official + Custom Relation Binding

목표:
고객사 커스텀 플레이북과 OCP 공식 매뉴얼을 relation graph로 연결한다.

작업:

- concept / procedure / policy / component 기준 relation 생성
- UI에서 관련 공식 문서 / 관련 커스텀 문서 링크 노출
- 챗봇 retrieval 에 relation hop 반영

완료 조건:

- 하나의 플레이북 유닛에서 공식/커스텀 연결 문서를 탐색할 수 있다
- 챗봇이 둘을 함께 참조할 수 있다

### Unit 6. Evaluation Harness

목표:
고객사 실전 문서에서도 품질이 무너지지 않는지 검증한다.

작업:

- `P` 를 대표 샘플로 smoke/eval 추가
- slide fidelity, outline, image presence, citation 복귀 검증
- relation retrieval 질의 세트 준비

완료 조건:

- 핵심 acceptance criteria가 자동 또는 반자동으로 검증된다
- 이후 다른 포맷에도 같은 평가틀을 재사용할 수 있다

## 오늘 기준 결론

이번 작업은 "PPT를 좀 더 잘 읽게 하자" 수준이 아니다.
정확한 목표는 "모든 포맷의 문서를 하나의 플레이북 그래프와 하나의 surface-aware viewer 체계로 승급시키자"이다.

따라서 앞으로의 질문은 이렇게 바뀌어야 한다.

- 이 파일을 읽을 수 있는가
- 이 파일을 공통 truth packet으로 승급시킬 수 있는가
- 이 파일을 뷰어에서 원본 의미에 가깝게 표현할 수 있는가
- 이 파일이 다른 플레이북과 연계되는가

이 네 가지를 동시에 만족해야 한다.
