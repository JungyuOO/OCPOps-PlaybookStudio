# v0.0.1 — Document-Scoped RAG Workspace Stabilization

## 목표

PlayBookStudio를 어제 시연 가능한 상태에서 v0.0.1 기준으로 안정화한다.

핵심 목표는 **Repository 기반 문서 관리 + 특정 문서 단위 RAG + OCP 실습 Terminal + Live Cluster 패널**이 같은 Workspace 안에서 일관되게 동작하도록 만드는 것이다.

v0.0.1은 신규 대형 기능을 추가하는 버전이 아니라, 이미 구현된 PostgreSQL/Qdrant/Library/Terminal/OCP 기능을 운영 데모 기준으로 정리하고 회귀 테스트로 고정하는 버전이다.

---

## 범위

### Core (P0 — v0.0.1 릴리스 기준)

- [x] `active_document_id` 기반 document-scoped RAG 회귀 테스트
- [x] private repository retrieval firewall 검증
- [x] BM25 / Qdrant hydrated hit metadata 검증
- [x] Library category를 DB metadata 기반으로 정리
- [x] `Ask this document` → Workspace route/state 전달 검증
- [x] Workspace 상단 scoped RAG 상태바 검증
- [x] 작동하지 않는 Library placeholder category 제거 또는 비노출
- [x] 비어 있는 legacy runtime 폴더 정리
- [x] Terminal Session demo 품질 점검
- [x] Signals projection smoke 검증
- [x] frontend production build
- [x] backend focused test
- [x] docker compose smoke

### Extras (P1 — 여유 있으면 포함)

- [ ] Library 문서 viewer와 `Ask this document` 흐름 분리
- [ ] 문서 category별 이전/다음 문서 추천 구조
- [ ] ingestion status polling UX 보강
- [ ] Terminal PTY 기반 전환 검토
- [ ] Dashboard unavailable 상태 UX 정리

### 비범위 (v0.0.2 이후로 연기)

- full auth / SSO
- multi-user permission admin console
- Terminal production hardening 전체 구현
- cluster credential 영구 저장소 설계 완료
- Qdrant 제거 및 pgvector 단일화
- HWP/HWPX/HWPML 지원
- 별도 NotebookLM형 Library 내부 chat UI

---

## 배경

현재 프로젝트는 파일/데모 QA 기반 RAG에서 PostgreSQL 중심 운영형 RAG로 전환 중이다.

| 영역 | 현재 상태 | v0.0.1 목표 |
|---|---|---|
| 문서 저장 | PostgreSQL `document_sources`, `parsed_documents`, `document_chunks` | document-scoped retrieval 검증 |
| Vector index | Qdrant 재생성 가능 index | PostgreSQL metadata hydrate 검증 |
| Library | upload/repository API 연결 | DB metadata 기반 category 정리 |
| Chat | `active_repository_id`, `active_document_id` payload 전달 | UI 상태와 retrieval scope 일치 검증 |
| Terminal | xterm.js + WebSocket + oc/kubectl image install | demo 품질 점검 |
| Live Cluster | Ops API 재사용 | Dashboard/Outline/Signals smoke 검증 |
| 배포 구조 | seed/runtime 경계 정리 중 | 빈 legacy 폴더 제거 및 runtime 의존 축소 |

---

## 도메인 기준

### Repository Scope

```text
global_shared      공식 문서
workspace_shared   사내 Study/Internal 문서
private_user       사용자 업로드 문서
```

### Chat Scope

```text
chat_session.active_repository_id
chat request.active_repository_id
chat request.active_document_id
SessionContext.active_repository_id
SessionContext.active_document_id
```

### Citation Metadata

다음 값은 chunk 본문에 섞지 않고 metadata로 유지한다.

```text
section_number
heading_title
source_anchor
toc_path
asset_ids
repository_id
document_source_id
owner_user_id
visibility
source_scope
```

---

## 아키텍처

### 재사용 모듈

```text
src/play_book_studio/retrieval/access_scope.py
src/play_book_studio/retrieval/chunk_hydration.py
src/play_book_studio/retrieval/bm25.py
src/play_book_studio/retrieval/vector.py
src/play_book_studio/http/server_chat.py
src/play_book_studio/db/document_repository.py
src/play_book_studio/http/document_status_api.py
src/play_book_studio/http/signals_api.py
src/play_book_studio/http/terminal_ws.py
apps/web/src/pages/PlaybookLibraryPage.tsx
apps/web/src/pages/WorkspacePage.tsx
apps/web/src/pages/workspace/TerminalSessionPanel.tsx
apps/web/src/lib/runtimeApi.ts
apps/web/src/lib/opsConsoleApi.ts
```

### 버전별 작업 규칙

앞으로 기능 단위 작업은 다음 방식으로 계획한다.

```text
spec/
  v0.0.1/
    planner.md
  v0.0.2/
    planner.md
```

브랜치도 가능한 한 같은 버전 이름을 포함한다.

```text
feat/v0.0.1/metadata-improve
feat/v0.0.2/terminal-hardening
```

---

## 데이터 흐름

```text
[Library document click]
        │
        ▼
localStorage / route state
active_repository_id
active_document_id
active_document_title
        │
        ▼
[Workspace Chat]
        │
        ▼
POST /api/chat or /api/chat/stream
        │
        ▼
SessionContext
        │
        ▼
Qdrant + BM25 retrieval
        │
        ▼
PostgreSQL hydration
        │
        ▼
access_scope filter
        │
        ▼
answer citations + chat history
```

---

## 구현 계획

### Step 1. Document Scope 회귀 테스트

- `tests/test_retrieval_access_scope.py`
  - shared hit도 `active_document_id`가 다르면 제외
  - private hit은 document match뿐 아니라 owner/repository match도 필요
  - vector payload에서 `document_source_id` 보존 확인

### Step 2. Metadata Hydration 테스트 보강

- `tests/test_chunk_hydration.py`
- `tests/test_bm25_postgres.py`
- `tests/test_answer_context_metadata.py`

확인 항목:

- `document_source_id`
- `repository_id`
- `visibility`
- `source_scope`
- `section_number`
- `heading_title`
- `source_anchor`
- `toc_path`
- `asset_ids`

### Step 3. Library Category 정리

- `PlaybookLibraryPage.tsx`의 category inference를 DB metadata 우선으로 변경한다.
- metadata 우선순위:
  1. `metadata.category`
  2. `metadata.category_key`
  3. `metadata.book_slug`
  4. `source_scope`
  5. `toc_path`
  6. keyword fallback
- 작동하지 않는 placeholder category는 UI에서 제거하거나 disabled로 명확히 표시한다.

### Step 4. Document-Specific Chat 검증

- `Ask this document` 클릭 시 다음 값이 유지되어야 한다.
  - `workspace.activeSourceId`
  - `workspace.activeDocumentId`
  - `workspace.activeDocumentTitle`
- Workspace chat payload에 다음 값이 포함되어야 한다.
  - `active_repository_id`
  - `active_document_id`
- Workspace 상단에 현재 scope label이 표시되어야 한다.

### Step 5. Legacy Folder Cleanup

- 비어 있는 root legacy runtime 폴더를 제거한다.
  - `data/`
  - `tmp_source/`
  - `.pytest-tmp/`
- 새 runtime 의존으로 root `data/`, `study-docs`, `manifests`를 다시 추가하지 않는다.
- seed/import 입력은 `corpus/**`와 compose seed profile 기준으로 관리한다.

### Step 6. Terminal / Signals Smoke

- Terminal WebSocket 연결
- `oc whoami`, `oc get pods` 계열 명령 실행
- `oc apply`, `oc delete`, `oc rollout`, `oc scale` 등 operation command 감지
- Signals 탭 자동 전환 또는 signal feed 반영

### Step 7. Build / Docker Smoke

- frontend build
- backend focused tests
- compose config
- app/web health
- OCP overview/status API

---

## API 확인 목록

| API | 목적 | v0.0.1 상태 |
|---|---|---|
| `/api/uploads/ingest` | Library upload ingestion | 유지 |
| `/api/repositories/documents` | repository/document 목록 | 검증 |
| `/api/documents/ingest-status` | repository ingestion 상태 | 검증 |
| `/api/documents/{document_source_id}/status` | 문서 단건 상태 | 검증 |
| `/api/chat` | document-scoped chat | 검증 |
| `/api/chat/stream` | streaming document-scoped chat | 검증 |
| `/api/chat-history/*` | DB-backed history | 유지 |
| `/api/signals` | Terminal event projection | smoke |
| `/api/v1/ocp/*` | OCP status/overview/resources | smoke |

---

## 보안 고려사항

1. private upload는 `owner_user_id`와 `active_repository_id`가 모두 맞아야 retrieval 가능하다.
2. `active_document_id`만으로 private repository 접근을 허용하지 않는다.
3. cluster credential은 frontend localStorage에 저장하지 않는다.
4. Terminal Session은 production-safe로 간주하지 않는다.
5. Signals는 audit log가 아니라 demo/operation feed로 취급한다. 운영 감사 목적이면 별도 durable schema가 필요하다.
6. Qwen image description은 generated metadata로 취급하고 원본 asset과 model/status/error metadata를 보존한다.

---

## 회귀 / 스모크 테스트

### Python

```powershell
python -m pytest tests/test_retrieval_access_scope.py
python -m pytest tests/test_chunk_hydration.py tests/test_bm25_postgres.py tests/test_answer_context_metadata.py
```

### Frontend

```powershell
npm --prefix apps/web run build
```

### Docker

```powershell
docker compose config
docker compose up -d --build app web
docker compose ps app web
```

### HTTP Smoke

```text
GET /api/health
GET /api/repositories/documents
GET /api/documents/ingest-status
GET /api/signals
GET /api/v1/ocp/profiles
GET /api/v1/ocp/overview/{profile_id}
```

---

## 완료 기준 (DoD)

1. 특정 문서에서 `Ask this document` 클릭 후 Workspace 질문이 해당 문서 chunk만 검색한다.
2. private upload 문서는 owner와 active repository가 맞지 않으면 검색되지 않는다.
3. official/study shared 문서는 document mode에서도 정상 검색된다.
4. citation metadata에 section/toc/asset 정보가 보존된다.
5. Library category 클릭이 실제 DB 문서 목록과 연결된다.
6. 작동하지 않는 Library placeholder가 노출되지 않는다.
7. 비어 있는 legacy runtime 폴더가 제거되어 있다.
8. Terminal panel이 WebSocket으로 연결되고 demo 명령이 실행된다.
9. oc/kubectl operation command가 Signals feed에 반영된다.
10. frontend production build가 성공한다.
11. backend focused tests가 성공한다.
12. docker compose smoke가 성공한다.

---

## 작업 메모

- 2026-05-08: `PLAN.md`를 UTF-8 한국어로 재작성했다.
- 2026-05-08: `tests/test_retrieval_access_scope.py`에 `active_document_id` 회귀 테스트를 추가했고 focused test가 통과했다.
- 2026-05-08: BM25/Qdrant payload와 answer citation metadata 테스트를 보강했고, `qdrant_payload_from_row`가 `document_source_id`를 보존하도록 수정했다.
- 2026-05-08: `python -m pytest tests/test_retrieval_access_scope.py tests/test_chunk_hydration.py tests/test_bm25_postgres.py tests/test_answer_context_metadata.py` 통과.
- 2026-05-08: `data/`, `tmp_source/`, `.pytest-tmp/` 빈/임시 잔재 폴더를 제거했다.
- 2026-05-08: Library category inference를 `category_key`, `category`, `book_slug`, `source_scope`, `toc_path` metadata 우선으로 변경했다.
- 2026-05-08: Library placeholder label 잔여 검색과 `npm --prefix apps/web run build` 통과.
- 2026-05-08: `Ask this document`가 repository/document/category state를 Workspace로 전달하고, Workspace scoped 상태바가 category label을 표시하도록 보강했다.
- 2026-05-08: category state 보강 후 `npm --prefix apps/web run build` 통과.
- 2026-05-08: `/api/documents/ingest-status` datetime JSON 직렬화 오류를 수정했다.
- 2026-05-08: Terminal WebSocket 연결과 실제 command output smoke를 확인했다.
- 2026-05-08: `oc apply --dry-run=client -f /dev/null` 기반 Signals projection smoke를 확인했고, file path를 resource kind로 오인하지 않도록 parser를 보정했다.
- 2026-05-08: `docker compose config --quiet`, `docker compose ps app web`, `/api/health`, `/api/repositories/documents`, `/api/documents/ingest-status`, `/api/signals`, `/api/v1/auth/ocp/profiles`, `/api/v1/ocp/overview/env_ocp` smoke 통과.
