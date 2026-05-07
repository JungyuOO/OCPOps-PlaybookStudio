# PlayBookStudio / OCP RAG 개편 계획

작성일: 2026-05-07  
원칙: 구현 코드를 수정하기 전에 현재 repository를 분석하고, 이미 구현된 기능을 최대한 재사용한다.

## 1. 현재 이미 구현된 기능

### 1.1 PostgreSQL 중심 문서/채팅 런타임

- PostgreSQL ingestion foundation schema가 존재한다.
  - `db/migrations/0001_ingestion_foundation.sql:20` `document_sources`
  - `db/migrations/0001_ingestion_foundation.sql:47` `parse_jobs`
  - `db/migrations/0001_ingestion_foundation.sql:76` `document_blocks`
  - `db/migrations/0001_ingestion_foundation.sql:92` `document_assets`
  - `db/migrations/0001_ingestion_foundation.sql:113` `document_chunks`
  - `db/migrations/0001_ingestion_foundation.sql:141` `qdrant_index_entries`
- repository/session scope migration이 존재한다.
  - `db/migrations/0004_repository_session_scope.sql:5` repository owner/visibility
  - `db/migrations/0004_repository_session_scope.sql:45` `chat_sessions`
  - `db/migrations/0004_repository_session_scope.sql:52` `active_repository_id`
  - `db/migrations/0004_repository_session_scope.sql:60` `chat_messages`
- chat request에서 `active_repository_id`를 이미 받는다.
  - `src/play_book_studio/http/session_flow.py:69`
  - `src/play_book_studio/http/server_chat.py:270`
  - `src/play_book_studio/http/server_chat.py:414`
- frontend chat payload도 `active_repository_id`를 전송한다.
  - `apps/web/src/lib/runtimeApi.ts:1119`
  - `apps/web/src/lib/runtimeApi.ts:1163`

### 1.2 Repository / upload ingestion

- upload ingestion API가 이미 있다.
  - `src/play_book_studio/http/server_handler_factory.py:298` `/api/uploads/ingest`
  - `src/play_book_studio/http/upload_api.py:109` `DATABASE_URL` 기반 upload 처리
  - `src/play_book_studio/http/upload_api.py:114` parsed upload persistence
  - `src/play_book_studio/http/upload_api.py:143` pending chunks indexing
- repository document listing API가 이미 있다.
  - `src/play_book_studio/http/server_handler_factory.py:237`
  - `src/play_book_studio/http/server_handler_factory.py:393`
  - `src/play_book_studio/db/document_repository.py:664`
- Playbook Library는 upload/repository API를 이미 사용한다.
  - `apps/web/src/pages/PlaybookLibraryPage.tsx:830` `uploadDocumentIngestion`
  - `apps/web/src/lib/runtimeApi.ts:1255` upload client
  - `apps/web/src/lib/runtimeApi.ts:1301` document repository client

### 1.3 Qdrant hydration / access scope

- Qdrant hit을 PostgreSQL chunk/source metadata로 hydrate하는 흐름이 있다.
  - `src/play_book_studio/retrieval/chunk_hydration.py:14`
  - `src/play_book_studio/retrieval/chunk_hydration.py:66`
  - `src/play_book_studio/retrieval/vector.py:149`
- owner/repository scope filter가 존재한다.
  - `src/play_book_studio/retrieval/access_scope.py:6`
  - `src/play_book_studio/retrieval/access_scope.py:33`
- citation metadata에 section/toc/assets를 보존하는 모델과 context 코드가 있다.
  - `src/play_book_studio/answering/models.py:20`
  - `src/play_book_studio/answering/context.py:1662`

### 1.4 DB-backed chat history

- DB-backed chat history API가 이미 연결되어 있다.
  - `src/play_book_studio/http/server_handler_factory.py:203` `/api/chat-history/sessions`
  - `src/play_book_studio/http/server_handler_factory.py:206` `/api/chat-history/messages`
  - `src/play_book_studio/http/server_handler_factory.py:283` `/api/chat-history/archive`
- Workspace는 DB history를 먼저 시도하고 legacy fallback을 둔다.
  - `apps/web/src/pages/WorkspacePage.tsx:1133`

### 1.5 Terminal Session / xterm.js / command check

- frontend에 xterm.js 기반 Terminal Session panel이 이미 있다.
  - `apps/web/src/pages/workspace/TerminalSessionPanel.tsx:29` learning context prop
  - `apps/web/src/pages/workspace/TerminalSessionPanel.tsx:54` context normalization
  - `apps/web/src/pages/workspace/TerminalSessionPanel.tsx:120` WebSocket 생성
  - `apps/web/src/pages/workspace/TerminalSessionPanel.tsx:156` `command_check_result` 수신
- Workspace 오른쪽 패널에 Terminal 렌더링 분기가 이미 있다.
  - `apps/web/src/pages/WorkspacePage.tsx:99` Terminal import
  - `apps/web/src/pages/WorkspacePage.tsx:1018` 현재 default는 `viewer`
  - `apps/web/src/pages/WorkspacePage.tsx:3013` Viewer/Terminal toggle
  - `apps/web/src/pages/WorkspacePage.tsx:3885` Terminal 렌더링
- backend Terminal WebSocket도 이미 있다.
  - `src/play_book_studio/http/terminal_ws.py:53` learning context 추출
  - `src/play_book_studio/http/terminal_ws.py:99` terminal session DB 생성
  - `src/play_book_studio/http/terminal_ws.py:147` terminal event 기록
  - `src/play_book_studio/http/terminal_ws.py:186` command check 평가
  - `src/play_book_studio/http/terminal_ws.py:305` `command_check_result` emit
- command check 결과 schema/repository가 존재한다.
  - `db/migrations/0003_terminal_learning_runtime.sql:44` `command_check_results`
  - `src/play_book_studio/db/terminal_learning_repository.py:460` upsert

### 1.6 Ops Console / OCP client / cluster resource

- Ops Console API client가 이미 있다.
  - `apps/web/src/lib/opsConsoleApi.ts:451` OCP connect
  - `apps/web/src/lib/opsConsoleApi.ts:458` OCP status
  - `apps/web/src/lib/opsConsoleApi.ts:500` overview
  - `apps/web/src/lib/opsConsoleApi.ts:504` metrics
  - `apps/web/src/lib/opsConsoleApi.ts:512` resources
  - `apps/web/src/lib/opsConsoleApi.ts:517` resource detail
- backend Ops Console handler가 실제 OCP API 호출과 simulated fallback을 지원한다.
  - `src/play_book_studio/http/ops_console_api.py:214` real OCP config
  - `src/play_book_studio/http/ops_console_api.py:304` real OCP request
  - `src/play_book_studio/http/ops_console_api.py:364` resource payload
  - `src/play_book_studio/http/ops_console_api.py:408` manifest YAML 생성
  - `src/play_book_studio/http/ops_console_api.py:501` pod metrics
  - `src/play_book_studio/http/ops_console_api.py:2583` GET handler
  - `src/play_book_studio/http/ops_console_api.py:3040` POST handler
- Ops Console page에는 connection modal, dashboard cards, resource/YAML viewer가 이미 있다.
  - `apps/web/src/pages/OpsConsolePage.tsx:1493` connection UI
  - `apps/web/src/pages/OpsConsolePage.tsx:1810` YAML/resource detail viewer
  - `apps/web/src/pages/OpsConsolePage.tsx:1858` metric cards
  - `apps/web/src/pages/OpsConsolePage.tsx:1903` resource list/detail

## 2. 재사용 가능한 모듈

| 목적 | 재사용 대상 | 비고 |
| --- | --- | --- |
| 우측 CLI 패널 | `TerminalSessionPanel`, `terminal_ws.py`, `terminal_session.py` | 새 터미널 구현 금지. default panel만 Terminal 중심으로 전환 |
| 학습 context 전달 | `TerminalLearningContext`, terminal WS context parser | `learning_path_id`, `learning_step_id`, `lab_task_id`, `learner_id` 유지 |
| command check | `command_check_results`, `terminal_learning_repository.py` | CLI 결과와 learning step 체크 연결 |
| cluster status/connect | `opsConsoleApi.ts`, `ops_console_api.py` | 새 cluster client 작성 대신 thin wrapper 또는 직접 재사용 |
| resource list/YAML | `loadResources`, `loadResourceDetail`, OpsConsole YAML modal | Outline 탭 Resource Explorer로 이식 |
| dashboard metrics | Ops Console overview/metrics/resource summary | 별도 Ops tab 제거 후 Workspace modal로 이동 |
| repository upload/list | `uploadDocumentIngestion`, `loadDocumentRepositories`, `repository_api.py` | Playbook Library 구조 변경 시 유지 |
| DB chat history | `chat_history_api.py`, `chat_repository.py` | legacy file session은 fallback 전용 |
| RAG scope | `access_scope.py`, `chunk_hydration.py`, `server_chat.py` | private/shared visibility 유지 |
| document viewer | `/api/viewer-document`, `loadViewerDocument` | Library 문서 클릭/Chat citation viewer에서 재사용 |

## 3. 새로 구현해야 하는 부분

### 3.1 Workspace / Chat

- 우측 패널 기본값을 `Wiki Viewer`에서 `Terminal Session`으로 전환한다.
- 기존 viewer는 citation/document 확인용 secondary panel 또는 toggle로 남긴다.
- `currentMode: "document" | "live_cluster"` state를 명확히 추가한다.
- cluster 연결이 없으면 Live Cluster toggle을 disabled 처리한다.
- chat request metadata에 `active_document_id`가 필요하면 optional field로 확장한다.
- upload ingestion 상태 banner를 Workspace 상단에 표시한다.

### 3.2 Outline -> Live Cluster Resource Explorer

- 기존 Outline의 문서/category 목록 UI를 cluster resource explorer로 교체한다.
- kind dropdown: pod, service, deployment, route, event 등 기존 API가 지원하는 범위 우선.
- resource item 클릭 시 YAML modal을 표시한다.
- 연결이 없으면 명확한 empty/disabled state를 보여준다.

### 3.3 Signals

- 초기 구현은 command pattern 기반 감지로 충분하다.
- 감지 대상:
  - `oc create`, `oc apply`, `oc delete`, `oc edit`, `oc patch`, `oc rollout`, `oc scale`, `oc expose`, `oc set image`, `oc adm`
  - `kubectl create`, `kubectl apply`, `kubectl delete`, `kubectl rollout`, `kubectl scale`, `kubectl expose`, `kubectl set image`
- signal item 필드:
  - timestamp
  - operation type
  - resource kind
  - resource name
  - namespace
  - status
  - source command
- Terminal command에서 operation 감지 시 frontend가 Signals 탭으로 자동 전환한다.
- durable persistence가 필요하면 `terminal_events` 확장 또는 신규 `signal_events` table/API를 추가한다.

### 3.4 Dashboard 전환

- 상단 `Ops Console` 탭/route 노출을 제거한다.
- 기존 Ops Console 기능은 Workspace 내부 Dashboard modal/panel로 이식한다.
- Dashboard는 cluster health, node/pod/deployment/service summary, metrics, recent signals를 표시한다.
- metric API가 unavailable이면 mock을 만들지 말고 unavailable 상태를 표시한다.

### 3.5 Playbook Library 병합

- Operational Wiki / Repository 상단 toggle을 제거하고 좌측 sidebar category 구조로 병합한다.
- category 구조:
  - Wiki: Install, Operations, Storage, Observability, Security, Networking, Troubleshooting
  - Repository: My Uploads, Shared Workspace Docs, Recent Imports
- 공식 문서와 사용자 업로드 문서는 PostgreSQL repository/document API 기준으로 조회한다.
- 문서 클릭은 Library 내부에 새 chat을 만들기보다 Workspace Chat route로 연결한다.
- route/state로 `active_repository_id`, `active_document_id`, `source_scope`, `selected_category`를 넘긴다.

### 3.6 Ingestion status

- 현재 upload API는 parse/index 결과를 응답하지만, 장기 job 상태 polling API는 부족하다.
- 우선 `parse_jobs`, `document_sources`, `qdrant_index_entries` 기반 조회 API를 추가한다.
- 비동기 worker가 아닌 현재 동기 처리 구간에서는 frontend lifecycle banner를 함께 사용한다.
- 이후 background worker 도입 시 같은 status API를 유지한다.

## 4. 위험한 변경 지점

### 4.1 Terminal은 production-safe로 간주하면 안 됨

- 현재 terminal은 실제 shell을 WebSocket으로 붙이는 구조다.
- 운영 배포 전 owner/session auth, timeout, kill control, audit, namespace 격리가 필요하다.
- 이번 리팩토링에서는 UI/학습 연결과 signal hook을 붙이되, 보안 경계는 TODO로 명확히 남긴다.

### 4.2 cluster credential 저장

- frontend localStorage에 kubeconfig/token/password를 저장하면 안 된다.
- 기존 OpsConsolePage에는 active connection/session 상태를 localStorage로 쓰는 흐름이 있다.
  - `apps/web/src/pages/OpsConsolePage.tsx:351`
  - `apps/web/src/pages/OpsConsolePage.tsx:514`
- connection id/status 수준은 가능하지만 credential은 backend boundary에만 둔다.

### 4.3 Ops Console 제거 시 route 호환성

- 현재 routing에 Ops Console route가 여러 개 남아 있다.
  - `apps/web/src/routing/AppRoutes.tsx:42`
  - `apps/web/src/routing/routes.ts:15`
- 단번에 삭제하면 기존 링크/테스트가 깨질 수 있다.
- 1차로 nav 노출 제거 및 Dashboard modal 이식, 2차로 route 정리 순서가 안전하다.

### 4.4 WorkspacePage 단일 파일 비대화

- `WorkspacePage.tsx`에 chat, source, upload, panel, viewer 로직이 이미 집중되어 있다.
- 새 기능을 모두 같은 파일에 붙이면 유지보수성이 악화된다.
- 단, 사용자 요구대로 폴더를 깊게 만들지 말고 `workspace/` 내부 얕은 파일 분리만 수행한다.

### 4.5 PlaybookLibraryPage 비대화

- `PlaybookLibraryPage.tsx`가 upload, repository search, wiki/repository toggle, viewer를 모두 가진다.
- Library 병합은 먼저 state/API 재사용을 유지하고, UI 블록만 얕게 분리한다.

### 4.6 private_user 문서 노출

- `owner_user_id`, `visibility`, `source_scope`, `active_repository_id` filter를 우회하면 안 된다.
- 새 Library query, chat route, document-specific chat 모두 기존 access scope를 재사용해야 한다.

### 4.7 HWP/HWPX/HWPML

- 현재 범위 밖이다.
- 새 parsing/UI 문구에서 HWP/HWPX/HWPML 지원을 암시하지 않는다.

## 5. 단계별 작업 계획

### Step 0. Baseline 고정

- 현재 branch/status 확인.
- frontend build/backend focused tests/docker compose config 기준선을 확인한다.
- 구현 전 `PLAN.md`만 먼저 커밋 대상으로 분리 가능하게 둔다.

### Step 1. Chat 우측 Terminal 기본화

- `WorkspacePage.tsx`의 `rightPanelMode` 기본값을 `terminal`로 변경한다.
- 기존 Wiki Viewer는 citation/document 확인용 toggle로 유지한다.
- `TerminalSessionPanel`의 `onCommandCheckResult` callback을 Workspace state와 연결해 command check 결과 표시 경로를 확인한다.
- 검증:
  - Workspace 진입 시 Terminal panel이 기본 노출된다.
  - WebSocket 연결 상태가 UI에 표시된다.
  - Viewer toggle로 문서 viewer를 열 수 있다.

### Step 2. Live Cluster mode / cluster status 연결

- `opsConsoleApi.loadOcpStatus`, profile/connection API를 Workspace에서 재사용한다.
- `currentMode` state를 추가한다.
- connected 상태가 아니면 Live Cluster toggle disabled.
- 연결이 없어도 document mode chat은 정상 유지.
- 필요 시 backend thin alias:
  - `GET /api/cluster/status` -> 기존 OCP status handler 재사용

### Step 3. Outline Resource Explorer

- left `outline` tab의 의미를 Live Cluster Resource 목록으로 변경한다.
- `loadResources`와 `loadResourceDetail`을 재사용한다.
- kind dropdown과 namespace 선택을 최소 구현한다.
- resource click 시 YAML modal 표시.
- 연결이 없으면 “Cluster가 연결되어 있지 않습니다” 상태 표시.
- 필요 시 backend thin alias:
  - `GET /api/cluster/resources?kind=...`
  - `GET /api/cluster/resources/{kind}/{namespace}/{name}/yaml`

### Step 4. Signals event feed

- command pattern detector를 추가한다.
- `TerminalSessionPanel`에서 command submit/event를 Workspace로 올릴 hook을 추가한다.
- operation 감지 시 signal event를 생성하고 left tab을 `signals`로 전환한다.
- 1차는 frontend session state + existing terminal event 기록 재사용.
- 2차 durable 필요 시:
  - `signal_events` table 추가 또는 `terminal_events`를 signal projection source로 사용
  - `GET /api/signals?session_id=...`
  - `POST /api/signals`

### Step 5. Dashboard modal 전환

- Workspace header에서 Ops Console nav를 제거하고 Dashboard button/modal로 대체한다.
- OpsConsolePage의 overview/metrics/resources logic을 최소 이식한다.
- 기존 standalone Ops route는 1차로 숨기고, 테스트 통과 후 제거 여부를 결정한다.
- Dashboard unavailable 상태를 명확히 표시한다.

### Step 6. Library 구조 병합

- Playbook Library 상단 Operational Wiki / Repository toggle 제거.
- 좌측 sidebar category 중심으로 재구성한다.
- 기존 `searchRepositories`, `loadDocumentRepositories`, `loadViewerDocument`, `uploadDocumentIngestion` 재사용.
- 문서 click은 Workspace route로 이동하며 active repository/document/category state를 전달한다.
- active document/category 표시와 이전/다음 문서 fallback 구조를 추가한다.

### Step 7. Ingestion status banner

- status API를 추가한다.
  - `GET /api/documents/ingest-status?repository_id=...`
  - `GET /api/documents/{document_source_id}/status`
- frontend는 Library upload 이후 상태를 polling하거나 Workspace 진입 시 active repository 기준으로 조회한다.
- banner 문구:
  - 문서 인식중입니다.
  - 문서 파싱중입니다.
  - 임베딩 생성중입니다.
  - 인덱싱중입니다.
  - 문서 준비가 완료되었습니다.
  - 문서 처리에 실패했습니다.

### Step 8. Tests / build / docker smoke

- backend focused tests:
  - terminal learning events
  - ops console API
  - repository API
  - retrieval access scope
  - ingestion status 신규 테스트
- frontend:
  - production build
  - 필요한 경우 focused unit/smoke
- docker:
  - `docker compose config`
  - app/web/postgres health 확인

## 6. API 변경 계획

기존 API를 우선 재사용하고, 새 endpoint는 thin wrapper로만 추가한다.

| API | 상태 | 구현 방향 |
| --- | --- | --- |
| `/api/uploads/ingest` | 기존 있음 | 유지, status 조회와 연결 |
| `/api/chat-history/*` | 기존 있음 | 유지, DB-first |
| `/api/repositories/search` | 기존 있음 | Library 병합에서 재사용 |
| `/api/document-repositories` | 기존 있음 | user/shared repository 목록 재사용 |
| `/api/viewer-document` | 기존 있음 | citation/document viewer 재사용 |
| `/api/cluster/status` | 신규 후보 | 기존 Ops status thin wrapper |
| `/api/cluster/resources` | 신규 후보 | 기존 Ops resource thin wrapper |
| `/api/cluster/resources/{kind}/{namespace}/{name}/yaml` | 신규 후보 | 기존 resource detail/YAML thin wrapper |
| `/api/dashboard/cluster-summary` | 신규 후보 | 기존 Ops overview/metrics 조합 |
| `/api/signals` | 신규 후보 | signal persistence 결정 후 추가 |
| `/api/documents/{document_source_id}/status` | 신규 후보 | parse/index status 조회 |

## 7. DB schema 변경 후보

필수 여부는 구현 단계에서 다시 확인한다.

- `signal_events`
  - 필요한 경우에만 추가.
  - terminal command operation을 durable feed로 보여줘야 하면 추가한다.
  - 1차 구현은 `terminal_events` 기반 projection으로 충분한지 먼저 검토한다.
- `document_sources` / `parse_jobs` status 확장
  - 현재 status만으로 banner 표현이 부족하면 최소 컬럼 또는 view query만 추가한다.
- `chat_messages` metadata
  - `active_document_id`, `mode=document|live_cluster` 저장이 필요하면 metadata JSON 활용 우선.

## 8. 검증 기준

- frontend production build 성공.
- backend focused tests 성공.
- API route import error 없음.
- docker compose config 성공.
- Chat:
  - cluster 미연결 시 Live toggle disabled.
  - document mode RAG 정상.
  - Terminal WebSocket 연결 및 output 표시.
  - oc/kubectl operation 감지 시 Signals 탭 자동 전환.
- Outline:
  - kind dropdown 표시.
  - 미연결 상태 empty/disabled.
  - 연결 시 resource list 조회와 YAML modal 표시.
- Library:
  - 공식 문서 category 표시.
  - 사용자 repository 문서 목록 표시.
  - 문서 클릭 시 Workspace Chat으로 active repository/document 전달.
  - private_user 문서가 다른 owner에게 노출되지 않음.
- Ingestion:
  - upload 후 status banner 표시.
  - 완료 후 repository 기반 질문 가능.

## 9. 작업 중 지켜야 할 금지 사항

- 프로젝트를 처음부터 다시 만들지 않는다.
- root `data/`, `study-docs/`, `manifests/` runtime 의존을 새로 추가하지 않는다.
- Qdrant payload만 source of truth로 사용하지 않는다.
- private upload를 shared/global 문서처럼 노출하지 않는다.
- cluster credential을 frontend localStorage에 평문 저장하지 않는다.
- Terminal Session을 production-safe하다고 표현하지 않는다.
- Ops Console을 별도 상단 탭으로 계속 유지하지 않는다.
- Library에서 Operational Wiki와 Repository를 상단 탭으로 계속 분리하지 않는다.
- HWP/HWPX/HWPML 지원을 새 범위에 포함하지 않는다.

## 10. 즉시 다음 작업

1. `PLAN.md` 저장 후 현재 상태를 확인한다.
2. Step 1부터 최소 변경으로 진행한다.
3. 각 Step은 작게 구현하고 focused test/build로 검증한다.
4. 변경이 누적되면 Lore Commit Protocol에 맞춰 커밋한다.
