# v0.0.7 — Corpus Chunk Quality & Strict Cluster Terminal

## 목표

PlayBookStudio v0.0.7은 PBS Chat의 RAG 품질을 corpus 입력 단계부터 다시 점검하고, 실제 OpenShift 학습 Terminal이 클러스터 연결 실패를 로컬 shell로 숨기지 않도록 안정화한다.

핵심 목표는 **공식 문서 corpus 청크 품질 검증 + 사용자/강의 문서 청크 품질 검증 + 문서 유형별 재청킹 정책 + 필요 시 intent classification agent + strict cluster terminal**을 같은 기준으로 묶어 v0.0.6 이후의 학습형 챗봇 품질을 끌어올리는 것이다.

v0.0.7은 특정 질문과 답변을 하드코딩하는 버전이 아니다. 사용자가 어떤 질문을 하더라도 문서 기반으로 잘 답변할 수 있도록 retrieval 입력 품질, chunk boundary, metadata, intent routing을 개선하는 버전이다.

---

## 범위

### Core (P0 — v0.0.7 릴리스 기준)

- [x] `spec/v0.0.7/planner.md`를 v0.0.1 planner 형식과 동일한 구조로 작성
- [x] 실제 official corpus `chunks.jsonl` 청크 품질 감사
- [x] 실제 사용자/강의 문서 `chunks.jsonl` 청크 품질 감사
- [x] official/user corpus별 chunk size, overlap, split boundary 기준 정리
- [x] `command`, `procedure`, `troubleshooting`, `concept`, `reference` chunk profile 분리
- [x] code/table/image/heading block 경계가 RAG에 유리하도록 사용자 문서 chunking 개선
- [ ] 변경 전/후 chunk quality audit report 생성
- [ ] v0.0.6 command-learning eval 또는 focused smoke 재실행
- [ ] intent classification agent 필요성 판단
- [ ] 필요 시 intent classification agent를 retrieval policy 생성기로 구현
- [x] Terminal local shell fallback 제거
- [x] `oc login` 성공 시에만 interactive shell 진입
- [x] 클러스터 연결 실패 시 terminal에 재연결 필요 메시지 출력
- [x] 관련 backend focused tests 통과

### Extras (P1 — 여유 있으면 포함)

- [ ] Studio Chat 추천 질문을 고정 질문에서 chunk/context 기반 질문 생성으로 전환
- [ ] short command query 전용 retrieval evaluation case 추가
- [ ] official corpus 재청킹 명령을 CLI로 명확히 문서화
- [ ] generated corpus artifact 갱신 여부 판단 및 필요한 경우 별도 커밋 단위로 분리
- [ ] Terminal UI에서 cluster reconnect 안내 상태를 더 명확히 표시
- [ ] Playwright로 Studio Chat/Terminal 사용자 흐름 smoke 검증

### 비범위 (v0.0.8 이후로 연기)

- 사용자 질문별 예상 답변 하드코딩
- 고정 Q/A 데이터셋을 production 답변으로 직접 사용
- OpenShift token 영구 저장소 설계
- 원격 OCP 인증/권한 관리 UI 전체 구현
- Qdrant 제거 또는 검색 엔진 교체
- 전체 official corpus 대규모 재수집 자동화
- multi-agent workflow를 사용자 화면에 노출하는 기능

---

## 배경

v0.0.6에서는 사용자가 실제 명령어를 치면서 OCP를 학습할 수 있는지 검증하기 위해 command-learning eval을 추가했다.

하지만 `네임스페이스 확인하는 명령어가 뭐야?` 같은 짧은 명령어 질문에서도 엉뚱한 답변이 나올 수 있고, bootstrap 문서 질문에서도 추천 질문과 답변이 문서 기반 가이드로 충분히 작동하지 않는 문제가 남아 있다.

이 문제는 단순 프롬프트 수정만으로 해결하기 어렵다. PBS Chat이 보는 청크가 너무 크거나, 절차와 관련 링크가 섞여 있거나, code block이 답변에 부적절하게 노출되거나, 사용자 문서의 slide/page/heading 단서가 embedding text에 잘 반영되지 않으면 retrieval부터 흔들린다.

| 영역 | 현재 상태 | v0.0.7 목표 |
|---|---|---|
| Official corpus | `gold_corpus_ko/chunks.jsonl` 기반 검색 | 실제 청크 품질 감사 후 role별 split 정책 조정 |
| 사용자 문서 | `build_document_chunks()` block 기반 split | heading/code/table/image 경계와 context 보존 개선 |
| Command 질문 | v0.0.6 eval로 일부 검증 | short command query가 command/procedure chunk로 안정 라우팅 |
| Intent 처리 | keyword/heuristic 중심 보강 가능성 | 필요 시 intent agent로 retrieval policy만 생성 |
| 추천 질문 | 일부 고정 질문/의미 약한 질문 존재 | chunk 기반 초보자 질문 생성 방향으로 전환 |
| Terminal | `oc login` 실패 후 local shell fallback 가능 | cluster login 성공 시에만 shell open |

---

## 도메인 기준

### Corpus Scope

```text
official_docs      Red Hat/OpenShift 공식 문서 corpus
study_docs         사내/강의/학습 문서 corpus
user_upload        사용자 업로드 문서 corpus
ops_learning       단계별 실습 학습 chunk
```

### Chunk Role

```text
command            oc/kubectl 명령어 중심 chunk
procedure          단계 수행 절차 chunk
troubleshooting    에러 문자열, 원인, 조치 chunk
concept            개념 설명 chunk
reference          API/reference/부록 성격 chunk
warning            note/warning/caution 성격 chunk
```

### Intent Policy

intent classification agent를 도입하더라도 답변을 생성하지 않는다.

```text
user query
  -> intent classification
  -> retrieval policy
  -> chunk search / rerank / context selection
  -> grounded answer
```

허용되는 intent 출력은 검색 전략에 필요한 metadata로 제한한다.

```text
intent
resource_hint
preferred_chunk_types
preferred_source_scopes
requires_terminal_practice
requires_step_by_step
```

### Terminal Policy

```text
oc login success      /bin/bash -i 진입 허용
oc login failure      재연결 안내 후 exit 1
missing token/api     재연결 안내 후 exit 1
network/tls/auth fail 재연결 안내 후 exit 1
local shell fallback  금지
```

---

## 아키텍처

### 재사용 모듈

```text
src/play_book_studio/ingestion/chunking.py
src/play_book_studio/ingestion/document_parsing.py
src/play_book_studio/ingestion/official_gold_import.py
src/play_book_studio/config/corpus_policy.py
src/play_book_studio/evals/chunk_quality_audit.py
src/play_book_studio/course/qdrant_course.py
src/play_book_studio/course/quality_eval.py
src/play_book_studio/http/course_api.py
src/play_book_studio/http/ops_console_api.py
src/play_book_studio/http/terminal_ws.py
src/play_book_studio/http/terminal_session.py
deploy/scripts/terminal-entrypoint.sh
tests/test_chunk_quality_audit.py
tests/test_terminal_session.py
```

### Corpus 입력 경로

```text
Official HTML/AsciiDoc
        │
        ▼
canonical AST
        │
        ▼
NormalizedSection
        │
        ▼
chunk_sections()
        │
        ▼
official chunks.jsonl
        │
        ▼
BM25 / Qdrant / PostgreSQL import
```

```text
User upload / Study docs
        │
        ▼
parse_upload_document()
        │
        ▼
DocumentBlock
        │
        ▼
build_document_chunks()
        │
        ▼
document_chunks / course chunks
        │
        ▼
retrieval / Studio Chat
```

### 브랜치 규칙

v0.0.7 작업 브랜치는 다음 이름을 사용한다.

```text
feat/v0.0.7/chunk-quality-and-strict-terminal
```

---

## 데이터 흐름

```text
[User question]
        │
        ▼
query normalization / optional intent classification
        │
        ▼
retrieval policy
preferred chunk_type / source_scope / route hints
        │
        ▼
BM25 + Vector search
        │
        ▼
chunk hydration
        │
        ▼
rerank / context selection
        │
        ▼
grounded answer + citations
```

```text
[Terminal Session click]
        │
        ▼
terminal WebSocket
        │
        ▼
deploy/scripts/terminal-entrypoint.sh
        │
        ├── oc login success
        │       ▼
        │   /bin/bash -i
        │
        └── oc login failure / missing config
                ▼
            reconnect notice + exit 1
```

---

## 구현 계획

### Step 1. Planner 형식 정리

- `spec/v0.0.7/planner.md`를 v0.0.1과 같은 릴리스 planner 형식으로 재작성한다.
- 한국어/UTF-8 기준을 유지한다.
- Core, Extras, 비범위, 도메인 기준, 아키텍처, 데이터 흐름, 구현 계획, 테스트, DoD, 작업 메모를 포함한다.

### Step 2. Strict Terminal 적용

- `deploy/scripts/terminal-entrypoint.sh`에서 마지막 unconditional `exec /bin/bash -i`를 제거한다.
- `oc login` 성공 branch 내부에서만 `/bin/bash -i`를 실행한다.
- 실패 branch에서는 다음 정보를 출력한다.
  - failure type
  - redacted login log tail
  - 클러스터 재연결 필요 안내
  - local shell fallback disabled 안내
- `tests/test_terminal_session.py`에 fallback 금지 회귀 테스트를 추가한다.

### Step 3. 실제 Corpus 청크 품질 감사

- official corpus:
  - `corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl`
- 사용자/강의 문서:
  - `corpus/sources/kmsc/parsed-preview/course_pbs/chunks.jsonl`
  - 필요 시 DB-backed document chunks hydrate 경로
- `chunk_quality_audit` 기준을 v0.0.7 용도로 확장한다.
- 감사 결과를 `spec/v0.0.7/` 또는 `reports/`에 저장한다.

확인 항목:

- chunk count
- token/char p50, p90, p95, max
- oversized chunk
- raw `[CODE]` markup
- code/navigation 혼합
- command dense chunk
- high latin ratio Korean chunk
- section depth
- chunk type 분포
- 대표 issue sample

### Step 4. Official Chunk Profile 개선

- `src/play_book_studio/config/corpus_policy.py`에 role-aware chunk profile을 도입한다.
- `src/play_book_studio/ingestion/chunking.py`에서 section semantic role, cli command, error string, block kind를 profile 선택에 반영한다.
- command/procedure/troubleshooting chunk는 작고 검색 가능한 단위로 유지한다.
- concept/overview chunk는 맥락을 잃지 않도록 과도하게 쪼개지 않는다.
- reference-heavy book은 기존 작은 chunk 정책을 유지하되 command/navigation 혼합을 줄인다.

### Step 5. User/Study Document Chunking 개선

- `src/play_book_studio/ingestion/document_parsing.py`의 `build_document_chunks()`를 문서 형식과 block type에 더 민감하게 조정한다.
- heading context를 embedding text에 유지한다.
- code/table/image block은 주변 설명과 묶되 oversized면 분리한다.
- slide/page metadata, source anchor, block ordinals를 유지한다.
- 사용자 문서 default chunk size는 official과 별도로 조정한다.

### Step 6. 재청킹 및 비교 리포트

- 변경 전 audit 결과를 저장한다.
- 변경 후 가능한 corpus를 재청킹한다.
- generated artifact가 큰 경우, 무조건 커밋하지 않고 재생성 명령과 비교 리포트를 먼저 남긴다.
- 변경 전/후 issue rate를 비교한다.

### Step 7. Intent Classification Agent 판단 및 구현

- chunk 개선 후에도 짧은 command query가 잘못 라우팅되면 intent classification agent를 도입한다.
- agent는 답변 문장을 만들지 않고 retrieval policy만 만든다.
- 하드코딩된 질문-답변 매핑은 금지한다.

판단 기준:

- command lookup 질문이 concept/reference chunk로 반복 라우팅되는가
- troubleshooting 질문이 설치 절차 문서로 반복 라우팅되는가
- 단계별 학습 질문이 단일 reference chunk만 가져오는가
- chunk 품질 개선 후에도 v0.0.6 eval 실패가 구조적으로 남는가

### Step 8. Studio Chat 추천 질문 개선

- 가능하면 고정 질문을 chunk/context 기반 생성으로 전환한다.
- 추천 질문은 현재 선택된 문서/청크의 절차, 명령어, 오류, 개념을 반영해야 한다.
- 초보자가 다음에 물을 만한 질문이어야 하며, 문서와 무관한 일반 질문은 제외한다.

### Step 9. 회귀 / 스모크

- terminal focused tests
- chunk quality audit tests
- official/user chunking focused tests
- v0.0.6 command-learning smoke 재실행
- 필요 시 Studio Chat/Terminal Playwright smoke

---

## API 확인 목록

| API | 목적 | v0.0.7 상태 |
|---|---|---|
| `/api/chat` | RAG 답변 품질 확인 | 검증 |
| `/api/chat/stream` | streaming RAG 답변 품질 확인 | 검증 |
| `/api/course/*` | 학습/추천 질문/guide chunk 확인 | 검증 |
| `/api/repositories/documents` | 사용자/공유 문서 목록 | 유지 |
| `/api/documents/ingest-status` | 문서 ingestion 상태 | 유지 |
| `/api/v1/ocp/*` | OCP cluster 상태 | smoke |
| Terminal WebSocket | cluster terminal 연결 | strict login 검증 |

---

## 보안 고려사항

1. OpenShift token은 planner, report, test fixture, log에 기록하지 않는다.
2. terminal login log를 출력할 때 token 값은 redaction한다.
3. cluster 연결 실패 시 local container shell을 열지 않는다.
4. intent classification agent는 답변을 만들지 않고 retrieval policy만 만든다.
5. private/user upload 문서는 기존 repository visibility와 owner scope를 우회하지 않는다.
6. official/user corpus 재청킹 중 generated artifact에 민감 정보가 섞이지 않았는지 확인한다.

---

## 회귀 / 스모크 테스트

### Python

```powershell
python -m pytest tests/test_terminal_session.py
python -m pytest tests/test_chunk_quality_audit.py
```

### Chunk Audit

```powershell
python -m play_book_studio.evals.chunk_quality_audit `
  --chunks corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl `
  --output reports/v007_official_chunk_quality.json
```

### Command Learning Smoke

```powershell
python -m play_book_studio.evals.studio_live_smoke
```

### Frontend

```powershell
npm --prefix apps/web run build
```

### Docker / Terminal

```powershell
docker compose up -d --build app web
docker compose ps app web
```

Terminal 실패 케이스:

```text
missing OCP_API_TOKEN
expired OCP_API_TOKEN
unreachable OCP_API_BASE_URL
oc login auth/token failure
```

---

## 완료 기준 (DoD)

1. `spec/v0.0.7/planner.md`가 v0.0.1 planner 형식으로 작성되어 있다.
2. official corpus 실제 청크 품질 감사 결과가 남아 있다.
3. 사용자/강의 문서 실제 청크 품질 감사 결과가 남아 있다.
4. official/user 문서별 chunk size와 split 정책이 코드상 분리되어 있다.
5. command/procedure/troubleshooting chunk가 retrieval에 유리한 크기로 조정되어 있다.
6. 사용자 문서 chunk가 heading, code, table, image context를 보존한다.
7. 변경 전/후 chunk quality issue rate를 비교할 수 있다.
8. intent classification agent 필요 여부가 근거와 함께 결정되어 있다.
9. intent agent를 도입했다면 답변 하드코딩 없이 retrieval policy만 생성한다.
10. Terminal은 `oc login` 성공 시에만 interactive shell을 연다.
11. 클러스터 연결 실패 시 local `/app` shell fallback이 발생하지 않는다.
12. cluster reconnect 필요 안내가 terminal 출력으로 표시된다.
13. backend focused tests가 성공한다.
14. v0.0.6 command-learning smoke 또는 동등한 focused eval이 재실행되어 결과가 기록된다.
15. 하드코딩 Q/A 없이 문서 기반 RAG 개선 방향이 검증되어 있다.

---

## 작업 메모

- 2026-05-11: v0.0.7 브랜치 `feat/v0.0.7/chunk-quality-and-strict-terminal`에서 작업을 시작했다.
- 2026-05-11: `deploy/scripts/terminal-entrypoint.sh`의 local shell fallback 원인이 마지막 `exec /bin/bash -i`임을 확인했다.
- 2026-05-11: terminal entrypoint를 `oc login` 성공 branch에서만 bash로 진입하도록 수정했다.
- 2026-05-11: `tests/test_terminal_session.py`에 cluster config 누락 시 local shell fallback이 실행되지 않는 회귀 테스트를 추가했다.
- 2026-05-11: `pytest tests/test_terminal_session.py -q` 결과 `5 passed, 1 skipped`.
- 2026-05-11: v0.0.7 planner를 v0.0.1 형식에 맞춰 재작성했다.
- 2026-05-11: `chunk_quality_audit`에 CLI와 course chunk schema 대응을 추가했다.
- 2026-05-11: official/user baseline audit report를 `reports/v007_*_chunk_quality_baseline.*`로 생성했다.
- 2026-05-11: baseline 분석 결과를 `spec/v0.0.7/chunk_quality_findings.md`에 기록했다.
- 2026-05-11: official chunking/import 경로에서 `[CODE]`, `[TABLE]` 내부 markup을 retrieval-safe markdown으로 정규화하도록 수정했다.
- 2026-05-11: official chunk profile을 semantic role 기반으로 분리하고 prefix token을 chunk budget에 반영했다.
- 2026-05-11: 사용자 문서 chunk embedding text에 section path를 유지하도록 수정했다.
- 2026-05-11: `pytest tests/test_internal_markup.py tests/test_corpus_policy.py tests/test_document_repository.py tests/test_chunk_quality_audit.py tests/test_official_gold_import.py tests/test_terminal_session.py -q` 결과 `24 passed, 1 skipped`.
