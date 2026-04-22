# 현재 리포지토리 화면명세서

## 1. 문서 목적

이 문서는 현재 프론트엔드 화면을 기준으로 각 화면의 역할, 선행조건, 주요 상태, 호출 API, 화면 출력 요소를 정리한다.  
다른 프로젝트에 UI를 이식하거나, 기능 단위로 화면을 재배치할 때 참조하는 문서다.

## 2. 전역 라우트

| Route | 화면명 | 역할 |
| --- | --- | --- |
| `/workspaces` | Workspaces | workspace 생성 및 active 선택 |
| `/connections` | Connections | OCP 연결 프로필 생성/검증 |
| `/models` | Models | workspace 기본 모델 설정 |
| `/overview` | Overview | cluster overview 및 추천 |
| `/resources` | Resources | namespace/resource 탐색 및 YAML 상세 |
| `/library` | Library | 문서 카탈로그 및 batch reindex |
| `/chat` | Chat | Copilot 대화 및 artifact 후속 작업 |
| `/actions` | Actions | preview/request/approve/execute/audit |
| `/scm` | SCM | OAuth, SCM 연결, repo delivery profile, deployment plan |

## 3. 공통 화면 규칙

- active workspace는 앱 전역 컨텍스트다.
- chat 화면을 제외한 모든 화면은 상단 navigation 기준 페이지 전환을 사용한다.
- chat session은 별도 rail로 관리된다.
- loading 상태는 앱 shell 전역 overlay 메시지에 반영될 수 있다.

## 4. 화면별 명세

### 4.1 Workspaces

목적:

- workspace 생성과 active workspace 선택

선행조건:

- 없음

주요 상태:

- `items`
- `selectedWorkspaceId`
- `form.name`
- `form.environment`

주요 UI:

- workspace 목록
- active 표시
- clear active workspace 버튼
- create workspace form

호출 API:

- `GET /api/v1/workspaces`
- `POST /api/v1/workspaces`

출력:

- workspace name
- environment
- slug
- active 여부

### 4.2 Connections

목적:

- OpenShift 클러스터 연결 생성과 검증

선행조건:

- workspace 선택 권장

주요 상태:

- `profile`
- `testResult`
- `schedulerStatus`
- `savedProfiles`
- `submitState`

주요 UI:

- cluster URL 입력
- auth mode 선택
- token 또는 username/password 입력
- verify SSL / save profile 체크박스
- 연결 생성 버튼
- 연결 테스트 버튼
- lease 메타데이터 갱신 버튼
- 로그아웃 버튼
- saved profiles 카드 목록

호출 API:

- `POST /api/v1/auth/ocp/connect`
- `GET /api/v1/auth/ocp/status/{connection_id}`
- `POST /api/v1/auth/ocp/test`
- `POST /api/v1/auth/ocp/lease/refresh`
- `GET /api/v1/auth/ocp/lease/status`
- `POST /api/v1/auth/ocp/disconnect`

출력:

- user
- cluster
- roles
- namespace
- secret ref
- expires at

### 4.3 Models

목적:

- workspace 기본 모델 설정 조회/저장

선행조건:

- active workspace 필요

주요 상태:

- model form 전체
- `loading`
- `error`
- `message`

주요 UI:

- chat provider/model/base URL
- embedding provider/model/base URL
- API key mode 입력
- save 버튼

호출 API:

- `GET /api/v1/workspaces/{workspace_id}/models/default`
- `PUT /api/v1/workspaces/{workspace_id}/models/default`

### 4.4 Overview

목적:

- cluster overview와 workspace recommendation 표시

선행조건:

- OCP 연결 필요
- recommendation은 workspace 필요

주요 상태:

- `overview`
- `recommendations`
- `loading`
- `recoLoading`

주요 UI:

- nodes/namespaces/pods/services metric 카드
- access posture 카드
- namespace sample 카드
- resource density 차트형 리스트
- recommendations 카드 목록

호출 API:

- `GET /api/v1/ocp/overview/{connection_id}`
- `GET /api/v1/workspaces/{workspace_id}/recommendations`
- `POST /api/v1/workspaces/{workspace_id}/recommendations/refresh`

### 4.5 Resources

목적:

- namespace별 리소스 탐색과 YAML manifest 확인

선행조건:

- OCP 연결 필요

주요 상태:

- `resource`
- `namespace`
- `namespaces`
- `resourceData`
- `selectedItem`
- `resourceDetail`
- `editorOpen`

주요 UI:

- namespace dropdown
- resource type button group
- resource summary 카드
- resource list
- YAML preview panel
- YAML copy 버튼
- YAML editor modal 진입 버튼

호출 API:

- `GET /api/v1/ocp/namespaces/{connection_id}`
- `GET /api/v1/ocp/resources/{connection_id}`
- `GET /api/v1/ocp/resource-detail/{connection_id}`

연결 모달:

- `ResourceYamlEditorModal`

### 4.6 Library

목적:

- 문서 카탈로그 탐색과 batch reindex job 운영

선행조건:

- 없음

주요 상태:

- `summary`
- `catalog`
- `activeDocumentKey`
- `detailMode`
- `detailOpen`
- `chunkData`
- `contentData`

주요 UI:

- summary 탭
- catalog 탭
- chunk 보기 다이얼로그
- markdown 원문 보기
- PDF iframe 보기
- batch reindex panel
- recent jobs table

호출 API:

- `GET /api/v1/library/summary`
- `GET /api/v1/library/catalog`
- `GET /api/v1/library/chunks`
- `GET /api/v1/library/document-content`
- `GET /api/v1/library/document-file`
- `POST /api/v1/index/batch/jobs`
- `GET /api/v1/index/batch/jobs/{job_id}`
- `GET /api/v1/index/batch/jobs`
- `POST /api/v1/index/batch/jobs/{job_id}/retry-failed`
- `POST /api/v1/index/batch/jobs/{job_id}/cancel`

### 4.7 Chat

목적:

- 문서와 live cluster 결과를 함께 다루는 작업형 대화 화면

선행조건:

- 문서 질의는 연결 없이 가능
- live 질의는 OCP 연결 필요

주요 상태:

- `draft`
- `isSending`
- `pendingAssistant`
- `selection`
- `editorTarget`
- chat session 목록/active session

주요 UI:

- session rail
- transcript
- stage detail block
- source drawer
- artifact block
- composer
- YAML editor modal

artifact 렌더링 종류:

- resource list
- resource relations
- resource editor
- command template
- follow-up suggestions

호출 API:

- `POST /api/v1/chat/query/stream`
- fallback `POST /api/v1/chat/query`
- `GET /api/v1/docs-preview/snippet`
- `GET /api/v1/ocp/resource-detail/{connection_id}`

### 4.8 Actions

목적:

- 승인 기반 액션 흐름을 별도 화면에서 관리

선행조건:

- OCP 연결 필요

주요 상태:

- `actorId`
- `actorRolesInput`
- `actionType`
- `resourceName`
- `namespace`
- `replicas`
- `reason`
- `preview`
- `requests`
- `executions`
- `auditItems`

주요 UI:

- action request builder form
- preview dialog
- requests tab
- executions tab
- audit tab

호출 API:

- `POST /api/v1/actions/preview`
- `POST /api/v1/actions/requests`
- `GET /api/v1/actions/requests`
- `POST /api/v1/actions/requests/{request_id}/approve`
- `POST /api/v1/actions/requests/{request_id}/reject`
- `POST /api/v1/actions/requests/{request_id}/execute`
- `GET /api/v1/actions/executions`
- `GET /api/v1/actions/audit`

### 4.9 SCM

목적:

- SCM 연결과 repo delivery profile 관리

선행조건:

- active workspace 필요

주요 상태:

- `connections`
- `repositories`
- `connectionForm`
- `repositoryForm`
- `drafts`
- `planForm`
- `deploymentPlan`

주요 UI:

- GitHub/GitLab OAuth connect 버튼
- manual connection form
- connection list
- repository delivery profile create form
- repository delivery profile edit form
- deployment plan builder form
- deployment plan result panel

호출 API:

- `POST /api/v1/oauth/{provider}/start`
- `GET /api/v1/workspaces/{workspace_id}/scm/connections`
- `POST /api/v1/workspaces/{workspace_id}/scm/connections`
- `GET /api/v1/workspaces/{workspace_id}/scm/repositories`
- `POST /api/v1/workspaces/{workspace_id}/scm/repositories`
- `PATCH /api/v1/workspaces/{workspace_id}/scm/repositories/{repository_id}`
- `POST /api/v1/workspaces/{workspace_id}/scm/repositories/{repository_id}/deployment-plan`

## 5. 이식 우선순위 관점 정리

화면 단위 이식 난이도:

- 낮음: Workspaces, Models
- 중간: Overview, Library, Actions
- 높음: Connections, Resources, Chat, SCM

이유:

- Connections/Resources/Chat/SCM은 상태 의존성과 API 묶음이 많다.
