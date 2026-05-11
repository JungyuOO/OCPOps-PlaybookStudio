# v0.1.0 RAG 품질 재구축 및 초보자 질의 대응

## 목표

PlayBookStudio의 챗봇을 “정해진 추천 질문을 누르면 그럴듯하게 답하는 UI”가 아니라, 사용자가 짧고 모호하게 물어도 OpenShift Container Platform 문서와 KMSC 실운영 문서를 근거로 자세하고 이해 가능한 답변을 제공하는 RAG 시스템으로 재구축한다.

v0.1.0의 핵심 목표는 **초보자 자연어 질의 대응 + 문서 근거 기반 답변 품질 + 데이터 기반 추천 질문 + 스트리밍 Chat UX + 사용자 질의 로그 기반 개선 루프**를 하나의 품질 기준으로 묶는 것이다.

예를 들어 사용자가 `OCP 설치 어떻게 해`, `Secret 컨피그가 계속 오류뜨는데 왜이래`, `네임스페이스 확인하는 명령어 뭐야`처럼 짧게 물어도, 단순 clarification으로 빠지지 않고 먼저 의도를 해석하고, 관련 공식/운영 문서를 찾고, 설치 방식/상황/확인 명령/다음 질문까지 초보자 기준으로 설명해야 한다.

하드코딩된 질문-답변 매핑은 금지한다. 단, “OCP = OpenShift Container Platform” 같은 일반 동의어 정규화, 질의 재작성, retrieval query expansion, 답변 구조화, citation 검증, 사용자 로그 분석은 RAG 품질을 높이는 시스템 구성요소로 허용한다.

---

## 범위

### Core (P0 - v0.1.0 릴리스 기준)

- [x] v0.1.0 브랜치 생성 및 planner 작성
- [x] 현재 RAG 파이프라인 구조 분석
- [x] 현재 청킹 방식과 실제 임베딩 데이터 품질 검증
- [x] `OCP` 축약어와 `OpenShift` 질의가 동일하게 retrieval 되는지 1차 검증 및 개선
- [x] 짧고 초보적인 설치 질의가 low-confidence clarification으로 과도하게 빠지는 문제 1차 개선
- [x] 초보자 troubleshooting/command 질의를 위한 query understanding 레이어 1차 추가
- [x] query understanding 결과를 answer prompt의 구조 지시로 연결
- [x] 공식 문서 기반 설치 개요 답변 품질 개선
- [x] KMSC 실운영 문서 답변이 정규화된 outline이 아니라 원본 chunk/이미지/운영 근거를 충분히 활용하도록 개선
- [x] 자주 묻는 질문, 학습용 단계별 질문, 실운영 질문이 고정 질문처럼 보이는 구조 분석
- [x] 추천 질문을 문서 chunk, 사용자 질의 로그, retrieval 실패 로그 기반의 동적 후보로 전환하는 설계 및 1차 구현
- [x] operations 추천 질문의 `step.user_query` 직접 노출을 제거하거나 fallback으로 강등
- [x] course guide 답변의 `answer_outline` 직접 사용을 제거하고 source chunk 기반 answer planner로 대체
- [ ] 채팅 답변 스트리밍 UX를 ChatGPT처럼 자연스럽게 표시
- [x] RAG 진행 중 상단 빈 박스 제거
- [x] 채팅 답변의 명령어 copy 후 터미널 paste가 동작하도록 UI/터미널 입력 흐름 수정
- [x] 라이트 모드에서 추천 질문 버튼 텍스트가 보이지 않는 스타일 문제 수정
- [x] 사용자별 질문/답변 DB 저장 상태 확인 및 부족하면 schema/API 보강
- [x] 저장된 사용자 질의/답변/무응답/low-confidence 로그를 분석해 품질 개선 후보를 만드는 기반 추가
- [x] 사용자 질문 로그가 RAG 답변/추천 질문에 직접 투입되지 않도록 경계 테스트 추가
- [ ] OCP 배포 환경에서 app/web 재배포 후 smoke 검증

### Extras (P1 - 가능하면 포함)

- [ ] Intent classification agent 도입 여부 평가 및 최소 구현
- [ ] Ontology / topology RAG처럼 개념 관계 기반 답변이 잘 나오도록 graph/metadata 활용 강화
- [ ] 추천 질문을 난이도별로 초보자/운영자/관리자 관점으로 분리
- [ ] 답변 평가용 golden set 확장
- [ ] 실서비스 질문 로그 기반 “자주 막히는 질문” 대시보드 초안
- [ ] 응답 품질 회귀 테스트를 Playwright smoke와 연결

### 비범위 (v0.1.1 이후)

- full auth / SSO
- 관리자용 피드백 라벨링 UI 전체 구현
- 완전한 RLHF 또는 자동 fine-tuning 파이프라인
- 외부 SaaS 분석 도구 연동
- 모든 KMSC 원본 문서의 재OCR/재파싱 전면 재처리

---

## 배경

현재 시스템은 공식 문서, KMSC 실운영 문서, course runtime, learning path, Qdrant, PostgreSQL 기반 구조를 갖추고 있다. 하지만 실제 사용자 경험에서는 다음 문제가 드러났다.

| 영역 | 현재 증상 | v0.1.0 목표 |
|---|---|---|
| 축약어 질의 | `OpenShift`는 이해하지만 `OCP`는 low-confidence로 빠짐 | OCP/OpenShift/OpenShift Container Platform 동의어를 retrieval 전에 의미 정규화 |
| 초보자 질문 | `OCP 설치 어떻게 해` 같은 질문에 구체 답변 대신 추천 질문만 반환 | 개요형 질문을 설치 방식 비교/준비물/다음 단계로 답변 |
| 추천 질문 | 자주 묻는 질문/학습 질문/운영 질문이 정규화된 고정 질문처럼 보임 | 문서 chunk와 사용자 로그 기반의 동적 추천 질문 |
| 운영 문서 답변 | KMSC outline만 요약되어 실제 사용자에게 도움이 부족 | 원본 chunk, source terms, 이미지 근거, 운영 판단 기준을 함께 제공 |
| 이미지 근거 | `[1]` 클릭 시 이미지 대신 OCR 요약만 보이는 경우 있음 | DB asset path와 viewer image endpoint 안정화 |
| 스트리밍 UX | 답변이 한 번에 표시되거나 loading 박스가 어색함 | 자연스러운 answer_delta 표시 |
| 터미널 paste | 채팅 명령어 복사 후 터미널 Ctrl+V가 동작하지 않음 | xterm paste/input 이벤트 처리 개선 |
| 라이트 모드 | 추천 질문 버튼 텍스트가 보이지 않음 | 색상 토큰/contrast 수정 |
| 품질 개선 루프 | chat DB 저장은 있으나 답변 품질 개선에 활용 부족 | chat_turns, no_answer, low-confidence 로그를 분석 입력으로 활용 |

---

## 현재 구조 메모

### RAG / Chat

```text
/api/chat 또는 /api/chat/stream
        ↓
server_chat.py
        ↓
answerer.answer(...)
        ↓
query rewrite / retrieval / rerank / low-confidence guard
        ↓
build_chat_payload(...)
        ↓
SessionStore + chat DB persist
```

확인된 파일:

```text
src/play_book_studio/http/server_chat.py
src/play_book_studio/answering/answerer.py
src/play_book_studio/http/server_support.py
src/play_book_studio/db/chat_repository.py
db/migrations/0004_repository_session_scope.sql
```

### 추천 질문

현재 추천 질문은 `starter_questions.py`에서 lane별로 생성된다.

```text
faq         공식 문서 manifest / DB entry 기반
learning    STARTER_CATEGORY_RULES + manifest 기반
operations  ops_learning_guides / learning_paths 기반
```

이 구조는 완전한 Q-A 하드코딩은 아니지만, 사용자 질문 분포나 실제 retrieval 실패를 반영하지 못하고 “정해진 질문 목록”처럼 보인다. v0.1.0에서는 질문 후보를 문서 chunk와 사용자 로그에서 생성하고, 고정 lane은 fallback/seed 역할로 축소한다.

### 정적 guide/outline 의존 진단

추가 확인 결과, 사용자가 지적한 “추천 질문이 JSON에 정해진 질문/답변을 뽑아오는 것 아니냐”는 우려는 일부 경로에서 맞다.

```text
src/play_book_studio/http/starter_questions.py
  operations lane
    -> postgres.learning_paths 또는 ops_learning_guides_v1.json
    -> step.user_query를 그대로 추천 질문으로 노출

src/play_book_studio/course/learning_path_seed.py
  ops_learning_guides_to_seed(...)
    -> step.answer_outline을 lesson_markdown으로 저장

src/play_book_studio/http/course_api.py
  _public_ops_guide_answer_lines(...)
    -> guide_step.answer_outline을 답변 줄로 직접 사용
```

즉 일반 `/api/chat`은 retrieval/LLM 경로를 타지만, Studio 추천 질문의 operations lane과 일부 course guide 답변은 `user_query`/`answer_outline` seed에 지나치게 의존한다. 이 경로는 RAG 품질 평가에서 분리해야 하며, v0.1.0에서는 다음 원칙으로 재구성한다.

- `user_query`는 운영 문서 탐색용 예시 메타데이터로만 사용하고, 추천 질문의 주 소스로 쓰지 않는다.
- `answer_outline`은 테스트/검증용 기대 포인트 또는 guide authoring 메타데이터로만 유지하고, 사용자 답변 본문에는 직접 복사하지 않는다.
- 추천 질문 클릭도 일반 사용자 질문과 동일하게 query understanding + retrieval + answer planning 경로를 타게 한다.
- 운영 문서 답변은 `ops_learning_chunks`, 원본 KMSC chunk, 이미지 evidence, 공식 문서 보조 근거를 기반으로 생성한다.
- 정적 seed를 완전히 삭제하기 전까지는 fallback임을 코드와 테스트에서 명확히 제한한다.

### 사용자 질문 저장

DB migration 기준으로 다음 테이블이 존재한다.

```text
chat_sessions
chat_turns
```

`server_chat.py`는 `persist_chat_turn`을 통해 query, answer, response_kind, rewritten_query, citations, metadata를 저장한다. v0.1.0에서는 이 데이터를 분석해 다음 항목을 추출한다.

```text
frequent_queries
low_confidence_queries
no_answer_queries
successful_answer_patterns
source_coverage_gaps
```

---

## 아키텍처 방향

### 1. Query Understanding Layer

단순 키워드 분기만 늘리지 않는다. 다음 순서로 질의를 해석한다.

```text
raw user query
  ↓
normalization
  - OCP → OpenShift Container Platform
  - ocp 설치 → OpenShift Container Platform 설치
  - Secret 컨피그 → Secret / ConfigMap / configuration 문맥 후보
  ↓
intent classification
  - install_overview
  - command_lookup
  - troubleshooting
  - concept_explanation
  - operations_guide
  - topology_or_architecture
  - ambiguous_but_answerable
  ↓
retrieval query expansion
  - user wording
  - official terminology
  - beginner explanation wording
  - command/document terms
```

구현 후보:

```text
src/play_book_studio/answering/query_understanding.py
src/play_book_studio/answering/query_expansion.py
src/play_book_studio/answering/intent_classifier.py
```

LLM 기반 intent classifier는 필요할 경우 도입하되, 실패 시 deterministic fallback을 둔다. 목표는 하드코딩 답변이 아니라 retrieval query를 더 잘 만드는 것이다.

### 2. Retrieval Quality Layer

현재 chunk/embedding 품질을 검증한다.

```text
official_docs
study_docs
course_pbs
ops_learning_chunks
course_assets
```

검증 항목:

- 짧은 질의가 어떤 query로 rewrite 되는가
- top-k에 실제 관련 문서가 오는가
- `OCP 설치`와 `OpenShift 설치`의 hit 차이가 있는가
- 설치 개요/Assisted Installer/SNO/Agent-based/IPI/UPI 문서가 같은 질문군에서 함께 검색되는가
- KMSC 문서의 source chunk와 learning chunk가 같은 운영 질문에서 같이 검색되는가
- 이미지 asset path와 chunk citation이 viewer에서 연결되는가

### 3. Answer Planning Layer

답변은 “문서 요약 나열”이 아니라 사용자가 이해할 수 있는 구조로 만든다.

개요형 질문 예:

```text
1. 먼저 결론
2. 선택 가능한 방식 비교
3. 초보자 기준 추천
4. 설치 전 준비물
5. 실제 설치 흐름
6. 확인 명령어
7. 다음에 물어볼 질문
```

문제 해결형 질문 예:

```text
1. 증상 분류
2. 먼저 확인할 리소스
3. 명령어
4. 정상/비정상 판단 기준
5. 다음 분기
6. 관련 문서 근거
```

답변 구조는 code heuristic으로 고정 답변을 만드는 것이 아니라, intent와 retrieved evidence에 맞춰 LLM prompt와 deterministic guard를 조합한다.

### 4. Recommendation Layer

추천 질문은 다음 소스를 조합한다.

```text
retrieved_chunks
ops_learning chunks
official manifest sections
```

기존 starter question은 삭제 후보가 아니라, 다음 기준으로 재설계한다.

- 고정 질문 문구를 그대로 노출하지 않기
- 실제 문서 chunk에서 질문 후보를 생성
- 사용자들이 자주 묻는 표현은 직접 노출하지 않고 품질 분석/평가셋 후보로만 반영
- 초보자 질문처럼 짧고 자연스럽게 만들기
- 클릭 시 실제 RAG 경로를 타게 하기

`chat_turns`, `no_answer logs`, `low_confidence logs`는 RAG 입력이나 추천 질문 소스가 아니다. 이 로그는 “무엇을 못 답했는지”를 찾고, 문서 청킹/검색/평가셋/golden case를 개선하는 운영 품질 분석 데이터로만 쓴다.

---

## 구현 계획

### Step 1. v0.1.0 작업 기준 확정

- `feat/v0.1.0/rag-quality-rebuild` 브랜치 생성
- `spec/v0.1.0/planner.md` 작성
- UTF-8 기준 유지
- 작업 메모를 planner에 누적

### Step 2. RAG 현황 진단

- `OCP 설치 어떻게 해`
- `OpenShift 설치 어떻게 해`
- `Secret 컨피그가 계속 오류뜨는데 왜이래`
- `네임스페이스 확인하는 명령어 뭐야`
- `성능 테스트 목표와 조건은 뭐부터 확인해`

위 질문을 기준으로 다음을 기록한다.

```text
rewritten_query
intent
top hybrid hits
top vector hits
selected citations
low-confidence 여부
answer shape
```

### Step 3. OCP 축약어 / 초보자 질의 개선

- `OCP`를 OpenShift Container Platform 동의어로 query normalization
- 설치 개요 질문이 install overview, Assisted Installer, SNO, Agent-based, IPI, UPI 문서를 찾도록 expansion
- low-confidence guard가 “짧지만 답변 가능한 개요 질문”을 막지 않도록 조정
- 테스트 추가:

```text
tests/test_query_understanding.py
tests/test_low_confidence_guard.py
tests/test_answer_quality_install_overview.py
```

### Step 4. 청킹/임베딩 품질 검증

- 공식 문서 chunk 크기, title/path metadata, section granularity 확인
- KMSC chunk의 body/search_text/visual_text/image_attachments 품질 확인
- ops_learning chunk가 원본 chunk를 충분히 참조하는지 확인
- 필요하면 split 전략 변경:
  - overview 문서는 큰 개념 chunk 유지
  - procedure 문서는 단계/명령어 단위 chunk
  - troubleshooting 문서는 symptom/cause/action 단위 chunk
  - 이미지가 중요한 문서는 image evidence chunk 연결 강화

### Step 5. 답변 생성 품질 개선

- intent별 answer plan 추가
- 설치 개요형 답변은 문서 근거 기반 비교표/흐름/준비물/명령어 포함
- command lookup은 바로 명령어와 판단 기준 제공
- troubleshooting은 “먼저 확인할 것 → 명령어 → 판단 기준 → 다음 분기”로 구성
- KMSC 운영문서는 원본 chunk와 image evidence를 함께 반영

### Step 6. 추천 질문 재설계

- `starter_questions.py` 분석 후 고정 질문 노출 최소화
- `chat_turns` 기반 후보 생성 API 설계
- no_answer/low-confidence 질문을 다시 retrieval 가능한 질문으로 변환
- 문서 chunk 기반 초보자 질문 생성
- lane 이름은 유지하되 내부 후보 생성은 RAG 데이터 기반으로 전환
- operations lane의 `step.user_query` 직접 노출 제거 또는 fallback 강등
- `answer_outline` 직접 답변 경로 제거 및 source chunk 기반 answer planner 대체
- 사용자 질문 로그는 starter question에 직접 섞지 않고 품질 분석 리포트로 분리

### Step 7. Chat UI 스트리밍 및 로딩 UX

- RAG 진행 중 상단 빈 박스 제거
- answer_delta를 자연스럽게 누적 렌더링
- result payload가 도착했을 때 기존 answer를 덮어쓰며 깜빡이지 않게 처리
- Playwright로 desktop/mobile 확인

### Step 8. 터미널 paste UX

- 채팅 answer code block copy 버튼 동작 확인
- xterm terminal panel에서 Ctrl+V / paste event 처리 확인
- 브라우저 clipboard 권한과 fallback paste 처리
- 명령어 복사 후 터미널 입력까지 Playwright 또는 수동 smoke로 검증

### Step 9. 라이트 모드 스타일 수정

- 추천 질문 버튼, FAQ 버튼, lane chip의 foreground/background contrast 확인
- CSS token 기반으로 수정
- light/dark screenshot 검증

### Step 10. 사용자 로그 기반 개선 루프

- `chat_turns` 저장 필드 확인
- response_kind, warnings, retrieval_trace 일부 metadata 저장 여부 확인
- 부족한 경우 migration 추가
- 집계 함수/API 후보:

```text
GET /api/chat-quality/query-insights
```

반환 후보:

```text
frequent_queries
low_confidence_queries
unanswered_queries
top_retrieval_gaps
starter_question_candidates
```

단, `starter_question_candidates`는 바로 노출할 질문 목록이 아니라 “어떤 문서/청킹/질의 이해가 부족한지”를 나타내는 리뷰 후보로 취급한다. 실제 사용자에게 보이는 추천 질문은 반드시 문서 chunk/manifest/source evidence에서 생성한다.

### Step 11. 배포

- dev merge 후 GHCR publish
- OCP app/web rollout
- seed가 필요한 변경인지 확인
- live smoke:
  - `OCP 설치 어떻게 해`
  - `Secret 컨피그가 계속 오류뜨는데 왜이래`
  - `네임스페이스 확인하는 명령어 뭐야`
  - KMSC 성능 테스트 질문
  - 이미지 citation click
  - 터미널 paste

---

## API 확인 목록

| API | 목적 | v0.1.0 상태 |
|---|---|---|
| `/api/chat` | 일반 chat RAG | 개선 대상 |
| `/api/chat/stream` | streaming chat RAG | UX 개선 대상 |
| `/api/studio/starter-questions` | 추천 질문 | 동적 후보화 대상 |
| `/api/chat-history/sessions` | 사용자별 세션 목록 | 유지/분석 활용 |
| `/api/chat-history/messages` | 사용자별 메시지 | 유지/분석 활용 |
| `/api/repositories/documents` | 문서 scope 확인 | 유지 |
| `/api/v1/course/chat` | KMSC 운영문서 chat | 개선 대상 |
| `/api/v1/course/assets` | KMSC 이미지 asset | 검증 대상 |
| `/api/v1/course/manifest` | course runtime | 유지 |
| 신규 후보 `/api/chat-quality/query-insights` | 질문 로그 분석 | 설계 대상 |

---

## 테스트 계획

### Python

```powershell
pytest tests/test_low_confidence_guard.py
pytest tests/test_course_api.py
pytest tests/test_starter_questions.py
pytest tests/test_chat_repository.py
pytest tests/test_answer_context_metadata.py
```

### Frontend

```powershell
npm --prefix apps/web run build
```

### Browser / Playwright

```text
Studio Chat:
- OCP 설치 어떻게 해
- Secret 컨피그가 계속 오류뜨는데 왜이래
- 네임스페이스 확인하는 명령어 뭐야
- 답변 streaming 표시
- 추천 질문 light mode contrast
- code copy 후 Terminal paste
```

### OCP Smoke

```bash
oc rollout restart deployment/app deployment/web -n pbs-ocpops
oc rollout status deployment/app -n pbs-ocpops
oc rollout status deployment/web -n pbs-ocpops
```

---

## 완료 기준 (DoD)

1. `OCP 설치 어떻게 해`가 low-confidence clarification이 아니라 설치 방식/추천/준비물/흐름을 문서 근거와 함께 답한다.
2. `OCP`와 `OpenShift` 질의의 retrieval 품질 차이가 허용 범위 안으로 줄어든다.
3. 초보자 질문이 짧아도 intent classification/query expansion을 거쳐 답변 가능한 경우 답변한다.
4. `Secret 컨피그가 계속 오류뜨는데 왜이래` 같은 비정형 troubleshooting 질문에 확인 명령과 판단 기준을 제공한다.
5. 추천 질문이 고정 문구처럼 반복되지 않고 문서/사용자 로그 기반 후보로 생성된다.
6. 운영 문서 답변이 KMSC 원본 chunk, source terms, image evidence를 함께 반영한다.
7. `[1]` 클릭 시 관련 이미지가 정상 표시된다.
8. Chat streaming이 자연스럽게 표시되고 RAG 진행 중 빈 상단 박스가 사라진다.
9. 채팅 명령어 copy 후 터미널 Ctrl+V가 동작한다.
10. 라이트 모드에서 추천 질문 버튼 텍스트가 읽힌다.
11. chat DB 저장 데이터가 품질 분석에 활용 가능하다.
12. backend focused tests가 통과한다.
13. frontend production build가 통과한다.
14. OCP 배포 smoke가 통과한다.

---

## 작업 메모

- 2026-05-11: v0.1.0 작업 브랜치 `feat/v0.1.0/rag-quality-rebuild`를 생성했다.
- 2026-05-11: `starter_questions.py` 확인 결과 FAQ/learning/operations 추천 질문은 문서 DB/manifest/learning_paths에서 파생되지만, 사용자 질의 로그와 retrieval 실패를 반영하지 못해 고정 질문처럼 보이는 구조임을 확인했다.
- 2026-05-11: `server_chat.py` 확인 결과 `/api/chat`와 `/api/chat/stream` 모두 `persist_chat_turn`으로 DB 저장 경로가 존재한다. v0.1.0에서는 이 데이터를 품질 개선 후보 생성에 활용한다.
- 2026-05-11: `test_low_confidence_guard.py` 기준 low-confidence guard가 현재 guided learning 질문 일부는 허용하지만, `OCP 설치 어떻게 해` 같은 짧은 개요형 질문은 별도 보호 장치가 필요하다.
- 2026-05-11: `OCP 설치 어떻게 해`가 `OpenShift Container Platform`, 설치 개요, Assisted Installer, Agent-based Installer, Single Node OpenShift, IPI/UPI 등 설치 문서군으로 확장되도록 retrieval query term을 보강했다.
- 2026-05-11: 설치 개요형 질문에 대해 `installation_overview`, `install_modes`, platform/agent/bare-metal 설치 문서군을 boost하고 release notes/API overview/CLI-only 문서가 상위로 올라오는 것을 줄였다.
- 2026-05-11: 설치 관련 citation이 잡혔을 때 low-confidence guard가 초보자 설치 질문을 clarification으로 막지 않도록 예외를 추가했다. 검증: `pytest tests/test_query_understanding.py tests/test_low_confidence_guard.py -q --basetemp tmp/pytest`.
- 2026-05-11: 사용자 질문 로그는 RAG 입력이 아니라 분석 전용 데이터로 분리했다. `/api/chat-quality/query-insights`는 `analysis_only_not_rag_input` 용도이며, starter question에는 직접 섞지 않는다.
- 2026-05-11: `retrieval/query_understanding.py`를 추가해 intent label과 retrieval term을 구조화했다. 현재 범위는 `install_overview`, `command_lookup`, `troubleshooting`, `secret_config_troubleshooting`, `namespace_or_project`이며, 답변 본문을 만들지 않고 retrieval shaping에만 사용한다.
- 2026-05-11: `Secret config error keeps happening` 같은 짧은 troubleshooting 질의가 Secret/ConfigMap/events/describe 근거를 찾도록 확장하고, 관련 citation이 있을 때 low-confidence clarification으로 과도하게 빠지지 않도록 조정했다. 검증: `pytest tests/test_query_understanding.py tests/test_low_confidence_guard.py tests/test_chat_grounding_quality.py tests/test_answer_eval_quality.py tests/test_course_api.py -q --basetemp tmp/pytest`.
- 2026-05-11: query understanding 결과를 `answering/prompt.py`의 shape hint에 연결했다. 설치 개요는 비교/준비물/흐름/확인 명령, Secret/ConfigMap 오류는 확인 명령/정상·비정상 판단/다음 분기, 명령어 조회는 핵심 명령 우선 구조를 요구한다. 검증: `pytest tests/test_prompt_answer_shapes.py tests/test_query_understanding.py tests/test_low_confidence_guard.py tests/test_chat_grounding_quality.py tests/test_answer_eval_quality.py tests/test_course_api.py -q --basetemp tmp/pytest`.
- 2026-05-11: Studio Chat streaming 중 빈 assistant bubble과 별도 thinking indicator가 동시에 보이는 문제를 수정했다. 빈 assistant stream placeholder는 content가 생길 때까지 숨기고, 첫 `answer_delta` 이후 thinking indicator를 제거한다. 검증: `npm --prefix apps/web run build`.
- 2026-05-11: Terminal Session panel에 paste fallback을 추가했다. xterm이 이미 처리한 paste는 `defaultPrevented`로 중복 전송을 막고, 브라우저가 막지 않은 Ctrl+V/clipboard paste는 WebSocket input으로 직접 전달한다. 검증: `npm --prefix apps/web run build`.
- 2026-05-11: 라이트 모드에서 suggested query chip, welcome question card, lane badge 텍스트가 밝은 배경 위에서 사라지는 문제를 수정했다. light theme 전용 foreground/background/border를 분리했다. 검증: `npm --prefix apps/web run build`.
- 2026-05-11: 코퍼스 청크 품질 검증을 위해 `corpus-quality-audit` CLI와 단위 테스트를 추가했다. 로컬 감사 기준 official 27,907개, KMSC course 523개, ops learning 18개 청크가 존재하며, missing text/id 중복은 없었다. KMSC course는 4,000자 초과 청크 8개, ops learning은 4,000자 초과 청크 7개와 직접 asset path 없는 image evidence 13개가 확인되어 다음 작업에서 KMSC 이미지/청크 연결 품질을 개선한다.
- 2026-05-11: ops learning chunk 생성 시 원본 KMSC chunk의 이미지 asset metadata를 `image_evidence_assets`로 보존하도록 변경하고 `ops_learning_chunks_v1.jsonl`을 재생성했다. 감사 결과 ops learning의 `asset_reference_count`가 0개에서 84개로 증가했고 `image_without_direct_asset_count`는 13개에서 0개로 줄었다. 검증: `pytest tests/test_course_ops_learning.py tests/test_corpus_quality_audit.py tests/test_course_api.py -q --basetemp tmp/pytest`.

## 2026-05-11 추가 작업 메모

- 특정 질문 전용 보정이 아니라 `install_overview`, `command_lookup`, `troubleshooting`, `secret_config_*`, `concept_explanation` 의도 전체에 적용되는 beginner grounded answer shaping 레이어를 추가했다.
- 사용자 질문 로그는 RAG 입력으로 쓰지 않고, query understanding 결과와 검색된 citation/cli_commands만 사용해서 약한 답변을 구조화한다.
- 검증 예시는 `OCP 설치 어떻게 해?`, `네임스페이스 확인 명령어가 뭐야?`, `Secret 컨피그가 계속 오류뜨는데 왜 이래?`이지만, 구현은 고정 Q/A가 아니라 의도와 근거 기반 shape만 적용한다.
- 검증 명령: `pytest tests/test_beginner_grounded_answer_shape.py tests/test_query_understanding.py tests/test_low_confidence_guard.py tests/test_chat_grounding_quality.py tests/test_prompt_answer_shapes.py -q --basetemp tmp/pytest`.
- 2026-05-11: planner의 완료 상태를 실제 반영 기준으로 갱신했다. 완료 처리한 항목은 RAG 파이프라인 분석, 코퍼스/청크 품질 감사, 공식 설치 개요 답변 shaping, starter question 구조 분석, operations lane의 `step.user_query` 직접 노출 제거, chat quality 분석 API와 사용자 로그 경계 테스트다. 아직 남은 핵심 항목은 KMSC course guide 답변의 `answer_outline` 잔존 경로 제거/확인, KMSC 실운영 답변 품질 고도화, 이미지 citation click smoke, OCP 재배포 smoke다.
- 2026-05-11: KMSC course guide 답변 rewrite 입력에서 `guide_step.answer_outline`을 제거했다. 이제 public guide 답변과 rewrite evidence는 `ops_learning_chunks`, source chunk summary/detail, official docs, tour/image evidence를 중심으로 구성한다.
- 2026-05-11: KMSC 실운영 deterministic 답변에 `what_to_look_for` 기반 결론 문장과 `source_summary` 기반 판단 기준 섹션을 추가했다. LLM rewrite가 비활성/실패해도 원본 chunk, 운영 순서, 확인 항목, 판단 기준이 함께 노출되도록 보강했다.
