# 현재 리포지토리 기능명세서

## 1. 문서 목적

이 문서는 현재 리포지토리에서 **실제로 사용 중인 기능만** 기준으로 정리한 기능명세서다.  
다른 프로젝트에 기능을 삽입할 때 무엇을 가져와야 하는지, 어떤 선행 모듈이 필요한지, 어느 범위까지가 현재 제품 범위인지 빠르게 판단할 수 있도록 작성했다.

판단 기준:

- `apps/web/src/app/App.tsx`에 등록된 실제 화면
- 각 화면이 호출하는 실제 프론트 API 클라이언트
- `apps/api/app_factory.py`에 등록된 실제 백엔드 라우트

## 2. 시스템 범위

현재 제품은 다음 기능 묶음으로 구성된다.

1. Workspace 관리
2. OpenShift 연결 관리
3. Workspace 모델 설정
4. 클러스터 개요 및 운영 추천
5. 리소스 탐색 및 YAML 수정
6. 문서 라이브러리 및 배치 색인
7. Copilot 채팅
8. 승인 기반 액션 실행
9. SCM 연결 및 Repo-driven 배포 계획

## 3. 기능 명세

### 3.1 Workspace 관리

목적:

- 고객/환경 단위의 작업 컨텍스트를 생성하고 선택한다.
- 이후 모델, 연결, 라이브러리, SCM 설정의 상위 스코프로 사용한다.

사용자 시나리오:

1. 사용자가 workspace 목록을 본다.
2. 새 workspace를 생성한다.
3. 생성된 workspace를 active 상태로 선택한다.
4. 이후 화면은 active workspace 기준으로 동작한다.

선행조건:

- 없음

입력:

- `name`
- `environment`

처리 규칙:

- `name`은 필수다.
- `slug`는 서버에서 생성한다.
- active workspace는 프론트 로컬 상태에 저장한다.

성공 결과:

- workspace가 생성된다.
- 생성된 workspace를 선택할 수 있다.

현재 범위:

- 목록 조회
- 생성
- active 선택
- active 해제

현재 제외:

- 수정
- 삭제

### 3.2 OpenShift 연결 관리

목적:

- 선택된 workspace 기준으로 OpenShift 클러스터 연결 프로필을 생성하고 검증한다.

사용자 시나리오:

1. 사용자가 cluster URL과 인증정보를 입력한다.
2. 시스템이 연결 프로필을 생성한다.
3. 사용자가 연결 테스트를 수행한다.
4. 시스템이 사용자, 그룹, 역할, secret backend, lease 정보를 반환한다.
5. 사용자는 연결을 유지하거나 해제한다.

선행조건:

- workspace 선택 권장

입력:

- `cluster_url`
- `auth_mode`
- `verify_ssl`
- `default_namespace`
- `display_name`
- token 또는 username/password

처리 규칙:

- `auth_mode=token`이면 `token`이 필수다.
- `auth_mode=password`이면 `username`, `password`가 필수다.
- 연결 프로필은 서버에 생성되고, 프론트는 세션 정보를 복원한다.
- 저장 프로필은 현재 UI에서 재연결 실행이 아니라 입력값 재사용 용도다.

성공 결과:

- `connection_id` 발급
- 연결 테스트 성공 시 `resolved_user`, `resolved_roles`, `resolved_namespace`, lease 상태 반환

현재 범위:

- 연결 프로필 생성
- 연결 상태 조회
- 연결 테스트
- lease 메타데이터 갱신
- scheduler 상태 조회
- 연결 해제

현재 제외:

- 실제 OCP OAuth 연결 플로우

### 3.3 Workspace 모델 설정

목적:

- workspace별 기본 chat/embedding 설정을 저장한다.

사용자 시나리오:

1. 사용자가 active workspace를 선택한다.
2. 현재 모델 설정을 불러온다.
3. chat/embedding provider 정보를 수정한다.
4. 저장한다.

선행조건:

- active workspace 필요

입력:

- `chat_provider`
- `chat_base_url`
- `chat_model`
- `chat_api_key_mode`
- `embedding_provider`
- `embedding_base_url`
- `embedding_model`
- `embedding_api_key_mode`

성공 결과:

- workspace 기본 모델 프로필이 저장된다.

현재 제외:

- 연결 테스트
- 유효성 검증 UI

### 3.4 클러스터 개요 및 운영 추천

목적:

- 연결된 클러스터의 개략 상태를 보여주고 운영 추천을 생성한다.

사용자 시나리오:

1. 사용자가 연결된 클러스터 overview를 조회한다.
2. namespace 수, 주요 resource count, 샘플 namespace를 본다.
3. workspace 기준 추천 목록을 확인한다.
4. 추천 재생성을 실행한다.

선행조건:

- OCP 연결 프로필 존재
- 추천 조회/생성은 workspace 존재 필요

처리 규칙:

- 추천 재생성은 연결된 profile과 namespace를 기준으로 수행한다.
- deployment의 `ready_replicas < replicas`이면 high risk 추천을 생성한다.
- 긴급 이슈가 없으면 info 추천 1건을 생성한다.

성공 결과:

- cluster overview 반환
- recommendation list 반환

현재 범위:

- overview 조회
- recommendation 조회
- recommendation refresh

현재 제외:

- 프론트에서 metrics 시계열 직접 시각화

### 3.5 리소스 탐색 및 YAML 수정

목적:

- namespace 기준 리소스를 탐색하고 live manifest를 확인/수정한다.

사용자 시나리오:

1. 사용자가 namespace를 선택한다.
2. resource type을 선택한다.
3. 리소스 목록과 상세 YAML을 확인한다.
4. YAML editor를 연다.
5. preview를 만든다.
6. request 생성 및 승인/실행을 거쳐 적용한다.

선행조건:

- OCP 연결 프로필 존재

지원 리소스:

- `pods`
- `deployments`
- `services`
- `routes`
- `events`

편집 가능 리소스:

- `deployments`
- `services`
- `routes`

처리 규칙:

- deployment에서 root `spec.replicas`만 바뀐 경우 `scale_deployment`로 처리한다.
- 그 외 수정은 `yaml_apply`로 처리한다.
- field ownership conflict 발생 시 force apply 재시도가 가능하다.

성공 결과:

- 리소스 목록 반환
- 상세 YAML 반환
- 적용 후 최신 manifest 재조회

현재 범위:

- namespace 조회
- 리소스 목록 조회
- 리소스 상세 조회
- YAML 복사
- YAML preview/apply

### 3.6 문서 라이브러리 및 배치 색인

목적:

- 문서 카탈로그를 조회하고 chunk/original view를 열며, batch indexing job을 관리한다.

사용자 시나리오:

1. 사용자가 library summary와 catalog를 조회한다.
2. 특정 문서를 chunk 또는 원문으로 확인한다.
3. batch reindex job을 생성한다.
4. 진행 상태를 polling으로 본다.
5. 실패 항목 재시도 또는 job 취소를 수행한다.

선행조건:

- 없음

입력:

- `root_path`
- `source_type`
- `document_group`
- `locale`
- `max_files`
- `include_subdirectories`

처리 규칙:

- 배치 색인은 비동기 job으로 실행된다.
- 프론트는 job 상태를 주기적으로 조회한다.

성공 결과:

- summary, catalog, chunks, content 조회 가능
- batch job 생성/조회/재시도/취소 가능

현재 제외:

- 단건 색인
- 전체 reset
- 동기 batch reindex

### 3.7 Copilot 채팅

목적:

- 문서 기반 답변과 live cluster 결과를 하나의 채팅 인터페이스에서 제공한다.

사용자 시나리오:

1. 사용자가 질문을 입력한다.
2. 시스템이 스트리밍으로 응답을 반환한다.
3. 사용자는 source snippet과 citation을 확인한다.
4. live artifact가 있으면 리소스/YAML 후속 작업으로 이어간다.

선행조건:

- 문서 질의는 연결 없이도 가능
- live 질의는 OCP 연결이 필요

처리 규칙:

- 최근 6개 turn만 history로 전달한다.
- 응답은 NDJSON 스트리밍으로 수신한다.
- 응답에는 `lane`, `mode`, `sources`, `artifacts`, `citation_map`이 포함될 수 있다.

성공 결과:

- 채팅 응답 표시
- source drawer 표시
- artifact 기반 후속 작업 가능

현재 범위:

- 스트리밍 채팅
- source preview
- artifact 기반 YAML editor 연동

현재 제외:

- 프론트에서 `/chat/live` 직접 호출하는 별도 live-only 채팅

### 3.8 승인 기반 액션 실행

목적:

- 위험 작업을 preview -> request -> approve/reject -> execute -> audit 흐름으로 수행한다.

사용자 시나리오:

1. 사용자가 액션 종류와 대상 리소스를 입력한다.
2. preview를 만든다.
3. approval request를 생성한다.
4. 승인 또는 반려한다.
5. 실행한다.
6. executions/audit 이력을 확인한다.

선행조건:

- OCP 연결 프로필 존재

직접 선택 액션:

- `scale_deployment`
- `rollout_restart`
- `log_bundle`

간접 사용 액션:

- `yaml_apply`

성공 결과:

- preview 반환
- request 상태 변화
- execution 결과 기록
- audit 이벤트 기록

### 3.9 SCM 연결 및 Repo-driven 배포 계획

목적:

- 직접 클러스터 수정 대신 repository 변경 계획을 생성한다.

사용자 시나리오:

1. 사용자가 GitHub/GitLab OAuth를 시작하거나 수동 connection을 생성한다.
2. repository delivery profile을 등록한다.
3. 특정 운영 변경을 repo deployment plan으로 변환한다.
4. 파일 수정 포인트와 commit 메시지 제안을 확인한다.

선행조건:

- active workspace 필요

입력:

- provider
- host URL
- auth type
- repo full name
- default branch
- config path
- delivery mode
- manifest kind
- target cluster URL
- target namespace

성공 결과:

- SCM connection 저장
- repository delivery profile 저장
- deployment plan 생성

현재 범위:

- OAuth 시작
- callback 후 프론트 복귀
- connection/repository profile 관리
- deployment plan 생성

현재 제외:

- 실제 repository write
- PR 생성
- SCM webhook/pipeline 실행

## 4. 이식 단위 권장안

다른 프로젝트에 기능을 삽입할 때는 아래 단위로 가져가는 것이 가장 안전하다.

1. Workspace + Models
2. OCP Connection + OCP Live
3. Library + Chat + Docs Preview
4. Actions + YAML Editor
5. SCM + OAuth + Deployment Plan

## 5. 현재 범위에서 제외한 구현

구현은 있으나 현재 실사용 기능 범위에서 제외한 항목:

- `POST /api/v1/chat/live`
- `GET /api/v1/ocp/metrics/{connection_id}`
- `POST /api/v1/index/source`
- `POST /api/v1/index/reset`
- `POST /api/v1/index/batch/reindex`
- `GET /api/v1/workspaces/{workspace_id}`
- `PATCH /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/metrics/snapshots`
