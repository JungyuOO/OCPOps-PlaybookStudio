# 현재 리포지토리 API 명세서

## 1. 문서 범위

이 문서는 현재 프론트엔드가 실제로 호출하는 API만 정리한 명세서다.  
구현은 있으나 현재 UI에서 직접 사용하지 않는 엔드포인트는 마지막 제외 목록에 분리했다.

기준 경로:

- 백엔드 base: `/api/v1`

## 2. Workspace / Recommendation / Model APIs

### `GET /api/v1/workspaces`

설명:

- workspace 목록 조회

응답:

```json
{
  "items": [
    {
      "workspace_id": "ws_123",
      "name": "Demo Workspace",
      "slug": "demo-workspace",
      "industry": "",
      "environment": "dev",
      "created_at": "2026-04-22T10:00:00Z",
      "updated_at": "2026-04-22T10:00:00Z"
    }
  ]
}
```

### `POST /api/v1/workspaces`

설명:

- workspace 생성

요청:

```json
{
  "name": "Demo Workspace",
  "slug": "",
  "industry": "",
  "environment": "dev"
}
```

응답:

- `WorkspaceRecord`

### `GET /api/v1/workspaces/{workspace_id}/models/default`

설명:

- workspace 기본 모델 설정 조회

응답 핵심 필드:

- `workspace_id`
- `chat_provider`
- `chat_base_url`
- `chat_model`
- `chat_api_key_mode`
- `embedding_provider`
- `embedding_base_url`
- `embedding_model`
- `embedding_api_key_mode`
- `updated_at`

### `PUT /api/v1/workspaces/{workspace_id}/models/default`

설명:

- workspace 기본 모델 설정 저장

요청:

```json
{
  "chat_provider": "openai-compatible",
  "chat_base_url": "http://llm.internal/v1",
  "chat_model": "gpt-4o-mini",
  "chat_api_key_mode": "managed",
  "embedding_provider": "tei",
  "embedding_base_url": "http://tei.internal",
  "embedding_model": "bge-m3",
  "embedding_api_key_mode": "managed"
}
```

### `GET /api/v1/workspaces/{workspace_id}/recommendations?limit=10`

설명:

- workspace 추천 목록 조회

응답:

```json
{
  "items": [
    {
      "recommendation_id": "reco_123",
      "workspace_id": "ws_123",
      "connection_id": "conn_123",
      "namespace": "default",
      "resource_kind": "Deployment",
      "resource_name": "payments-api",
      "recommendation_type": "deployment_health",
      "risk_level": "high",
      "summary": "payments-api has only 1/3 ready replicas.",
      "rationale": "Ready replica count is lower than desired replicas.",
      "created_at": "2026-04-22T10:00:00Z"
    }
  ]
}
```

### `POST /api/v1/workspaces/{workspace_id}/recommendations/refresh`

설명:

- workspace 추천 재생성

요청:

```json
{
  "connection_id": "conn_123"
}
```

응답:

- `RecommendationListResponse`

## 3. OCP 연결 APIs

### `POST /api/v1/auth/ocp/connect`

설명:

- OCP 연결 프로필 생성

요청 예시 1: token

```json
{
  "workspace_id": "ws_123",
  "cluster_url": "https://api.cluster.example.com:6443",
  "auth_mode": "token",
  "verify_ssl": true,
  "default_namespace": "default",
  "display_name": "dev-cluster",
  "save_profile": true,
  "token": "sha256~...",
  "username": "",
  "password": null
}
```

요청 예시 2: password

```json
{
  "workspace_id": "ws_123",
  "cluster_url": "https://api.cluster.example.com:6443",
  "auth_mode": "password",
  "verify_ssl": true,
  "default_namespace": "default",
  "display_name": "dev-cluster",
  "save_profile": true,
  "token": null,
  "username": "developer",
  "password": "secret"
}
```

성공 응답:

```json
{
  "connected": true,
  "connection": {
    "workspace_id": "ws_123",
    "connection_id": "conn_123",
    "display_name": "dev-cluster",
    "cluster_url": "https://api.cluster.example.com:6443",
    "auth_mode": "token",
    "verify_ssl": true,
    "default_namespace": "default",
    "username_hint": "",
    "secret_ref": "secret_ref",
    "save_profile": true,
    "status": "connected",
    "last_verified_at": "",
    "expires_at": ""
  },
  "message": "Connection profile created."
}
```

### `GET /api/v1/auth/ocp/status/{connection_id}`

설명:

- 연결 프로필 존재 여부 및 상태 조회

### `POST /api/v1/auth/ocp/test`

설명:

- OCP 연결 검증

요청:

```json
{
  "connection_id": "conn_123"
}
```

응답 핵심 필드:

- `success`
- `resolved_user`
- `resolved_groups`
- `resolved_roles`
- `identity_source`
- `permission_hints`
- `rbac_evidence`
- `secret_backend`
- `secret_lease_ttl_seconds`
- `secret_lease_expires_at`
- `resolved_namespace`
- `expires_at`
- `message`
- `error`

### `POST /api/v1/auth/ocp/lease/refresh`

설명:

- secret lease 메타데이터 갱신

요청:

```json
{
  "connection_id": "conn_123"
}
```

응답:

- `OcpConnectionTestResult`

### `GET /api/v1/auth/ocp/lease/status`

설명:

- lease scheduler 상태 조회

응답 핵심 필드:

- `enabled`
- `running`
- `interval_seconds`
- `last_run_at`
- `last_success_at`
- `last_failure_at`
- `last_error`
- `consecutive_failures`
- `profiles_checked`
- `renewals_applied`
- `recent_failures`

### `POST /api/v1/auth/ocp/disconnect`

설명:

- 현재 연결 해제

요청:

```json
{
  "connection_id": "conn_123"
}
```

## 4. OCP Live 조회 APIs

### `GET /api/v1/ocp/overview/{connection_id}`

설명:

- cluster overview 조회

응답 핵심 필드:

- `connection_id`
- `cluster_url`
- `default_namespace`
- `namespace_count`
- `namespace_sample`
- `resource_counts`
- `message`

### `GET /api/v1/ocp/namespaces/{connection_id}`

설명:

- namespace 목록 조회

응답:

```json
{
  "connection_id": "conn_123",
  "cluster_url": "https://api.cluster.example.com:6443",
  "count": 12,
  "items": ["default", "openshift-monitoring"]
}
```

### `GET /api/v1/ocp/resources/{connection_id}?resource=pods&namespace=default`

설명:

- resource 목록 조회

허용 resource:

- `pods`
- `deployments`
- `services`
- `routes`
- `events`

응답 item 필드:

- `name`
- `namespace`
- `kind`
- `created_at`
- `phase`
- `node_name`
- `ready_replicas`
- `replicas`
- `type`
- `cluster_ip`
- `host`
- `to`

### `GET /api/v1/ocp/resource-detail/{connection_id}?resource=deployments&namespace=default&name=app`

설명:

- resource 상세 manifest 조회

응답:

```json
{
  "connection_id": "conn_123",
  "cluster_url": "https://api.cluster.example.com:6443",
  "resource": "deployments",
  "namespace": "default",
  "name": "app",
  "kind": "Deployment",
  "manifest_yaml": "apiVersion: apps/v1\n...",
  "manifest_json": {}
}
```

## 5. Library / Indexing APIs

### `GET /api/v1/library/summary?workspace_id=ws_123`

설명:

- library 요약 조회

응답 핵심 필드:

- `workspace_id`
- `source_root`
- `extract_root`
- `corpus_files`
- `manifest_entries`
- `extracted_artifacts`
- `indexed_documents`
- `indexed_chunks`
- `batch_jobs`
- `latest_batch_status`
- `source_breakdown`
- `indexed_samples`
- `message`

### `GET /api/v1/library/catalog?workspace_id=ws_123`

설명:

- 문서 카탈로그 조회

응답 document 필드:

- `workspace_id`
- `document_key`
- `title`
- `relative_path`
- `source_type`
- `group`
- `indexed`
- `chunk_count`
- `original_kind`
- `original_key`
- `description`

### `GET /api/v1/library/chunks?document_key=...&workspace_id=ws_123`

설명:

- 문서 chunk 목록 조회

응답:

- `document_key`
- `title`
- `chunk_count`
- `chunks[]`

`chunks[]` 필드:

- `chunk_id`
- `chunk_order`
- `page_number`
- `section_title`
- `block_types`
- `preview_text`

### `GET /api/v1/library/document-content?document_key=...&workspace_id=ws_123`

설명:

- markdown 원문 조회

응답:

```json
{
  "workspace_id": "ws_123",
  "document_key": "doc_123",
  "title": "OpenShift Routes",
  "content": "# Routes\n..."
}
```

### `GET /api/v1/library/document-file?document_key=...&workspace_id=ws_123`

설명:

- 원본 파일 스트림 반환

### `POST /api/v1/index/batch/jobs`

설명:

- batch index job 생성

요청:

```json
{
  "workspace_id": "ws_123",
  "root_path": "data",
  "explicit_source_paths": [],
  "source_type": "generated-manual",
  "document_group": "official_ocp",
  "locale": "",
  "max_files": 3,
  "include_subdirectories": true
}
```

응답 핵심 필드:

- `job_id`
- `task_type`
- `status`
- `request`
- `result`
- `error`
- `progress_pct`
- `current_file`
- `created_at`
- `updated_at`

### `GET /api/v1/index/batch/jobs/{job_id}`

설명:

- 단일 batch job 상태 조회

### `GET /api/v1/index/batch/jobs?limit=10`

설명:

- 최근 batch job 목록 조회

### `POST /api/v1/index/batch/jobs/{job_id}/retry-failed`

설명:

- 실패 항목만 재시도

### `POST /api/v1/index/batch/jobs/{job_id}/cancel`

설명:

- batch job 취소

## 6. Chat / Docs Preview APIs

### `POST /api/v1/chat/query/stream`

설명:

- 현재 프론트의 주 채팅 진입점

요청:

```json
{
  "message": "deployment 목록 보여줘",
  "connection_id": "conn_123",
  "namespace": "default",
  "history": [
    {
      "role": "user",
      "text": "이전 질문",
      "lane": "rag",
      "sourcePaths": [],
      "resourceNames": [],
      "namespace": "default"
    }
  ]
}
```

응답 형식:

- `Content-Type: application/x-ndjson`

이벤트 종류:

```json
{ "type": "stage", "stage": { "key": "retrieve", "label": "검색", "detail": "...", "status": "running" } }
{ "type": "answer_delta", "delta": "부분 응답" }
{ "type": "result", "response": { "...": "CopilotChatResponse" } }
{ "type": "error", "status_code": 502, "message": "..." }
```

최종 `response` 핵심 필드:

- `lane`
- `mode`
- `fallback_used`
- `preview_ready`
- `answer`
- `sources`
- `artifacts`
- `citation_map`

### `POST /api/v1/chat/query`

설명:

- 비스트리밍 fallback 응답

### `GET /api/v1/docs-preview/snippet?source_path=...&chunk_id=...`

설명:

- source snippet 조회

응답 핵심 필드:

- `source_path`
- `relative_source_path`
- `repo_relative_path`
- `repo_locator`
- `file_name`
- `chunk_id`
- `source_type`
- `title`
- `section_title`
- `section_path`
- `page_number`
- `line_start`
- `line_end`
- `snippet`
- `lines`

## 7. Guarded Action APIs

### `POST /api/v1/actions/preview`

설명:

- guarded action preview 생성

요청 예시: scale

```json
{
  "connection_id": "conn_123",
  "actor_id": "alice",
  "actor_roles": ["operator"],
  "action_type": "scale_deployment",
  "namespace": "default",
  "resource_name": "payments-api",
  "replicas": 3,
  "reason": "scale out"
}
```

요청 예시: yaml apply

```json
{
  "connection_id": "conn_123",
  "actor_id": "alice",
  "actor_roles": ["operator"],
  "action_type": "yaml_apply",
  "namespace": "default",
  "resource_name": "payments-api",
  "reason": "edit resource yaml",
  "manifest_yaml": "apiVersion: apps/v1\n...",
  "resource_version": "12345"
}
```

응답 핵심 필드:

- `allowed`
- `risk_level`
- `summary`
- `preview_command`
- `required_approvals`
- `approval_strategy`
- `approval_rules`
- `policy_checks`
- `blocked_reasons`
- `validation_messages`
- `diff_unified`
- `dry_run_status`
- `dry_run_messages`
- `next_step`

### `POST /api/v1/actions/requests`

설명:

- approval request 생성

응답 핵심 필드:

- `request_id`
- `status`
- `preview`
- `requested_by`
- `requested_roles`
- `required_approvals`
- `approval_count`
- `approver_ids`
- `approver_role_map`
- `decision_note`

### `GET /api/v1/actions/requests?limit=20`

설명:

- request 목록 조회

### `POST /api/v1/actions/requests/{request_id}/approve`

설명:

- request 승인

요청:

```json
{
  "actor_id": "alice",
  "actor_roles": ["operator"],
  "decision_note": "approved from UI"
}
```

### `POST /api/v1/actions/requests/{request_id}/reject`

설명:

- request 반려

### `POST /api/v1/actions/requests/{request_id}/execute`

설명:

- request 실행

요청:

```json
{
  "actor_id": "alice",
  "actor_roles": ["operator"],
  "execution_note": "requested from UI",
  "force": false
}
```

응답 핵심 필드:

- `execution_id`
- `request_id`
- `status`
- `execution_mode`
- `simulated`
- `summary`
- `preflight_checks`
- `output_lines`
- `error`

### `GET /api/v1/actions/executions?limit=20`

설명:

- execution 목록 조회

### `GET /api/v1/actions/audit?limit=20`

설명:

- audit 이벤트 목록 조회

## 8. SCM / OAuth APIs

### `POST /api/v1/oauth/{provider}/start?workspace_id=ws_123`

설명:

- GitHub/GitLab OAuth 시작

허용 provider:

- `github`
- `gitlab`

응답:

```json
{
  "provider": "github",
  "authorize_url": "https://github.com/login/oauth/authorize?...",
  "state": "opaque-state"
}
```

### `GET /api/v1/oauth/{provider}/callback?...`

설명:

- OAuth callback 처리 후 `/scm` 화면으로 redirect

프론트 복귀 예:

- `/scm?oauth_status=connected&provider=github&connection_id=...`
- `/scm?oauth_status=error&message=...`

### `GET /api/v1/workspaces/{workspace_id}/scm/connections`

설명:

- SCM connection 목록 조회

### `POST /api/v1/workspaces/{workspace_id}/scm/connections`

설명:

- SCM connection 생성

요청:

```json
{
  "provider": "github",
  "host_url": "https://github.com",
  "auth_type": "token",
  "account_label": "customer-admin"
}
```

### `GET /api/v1/workspaces/{workspace_id}/scm/repositories`

설명:

- repository delivery profile 목록 조회

### `POST /api/v1/workspaces/{workspace_id}/scm/repositories`

설명:

- repository delivery profile 생성

요청:

```json
{
  "scm_connection_id": "scm_conn_123",
  "repo_full_name": "org/project",
  "default_branch": "main",
  "config_path": "config.yaml",
  "delivery_mode": "gitops_commit",
  "manifest_kind": "config_yaml",
  "target_cluster_url": "https://api.cluster.example.com:6443",
  "target_namespace": "payments",
  "auto_deploy_enabled": true
}
```

### `PATCH /api/v1/workspaces/{workspace_id}/scm/repositories/{repository_id}`

설명:

- repository delivery profile 수정

### `POST /api/v1/workspaces/{workspace_id}/scm/repositories/{repository_id}/deployment-plan`

설명:

- repo-driven deployment plan 생성

요청:

```json
{
  "resource_kind": "Deployment",
  "resource_name": "payments-api",
  "target_namespace": "payments",
  "replicas": 3,
  "image_tag": "v2.4.1",
  "config_key": "replicas",
  "reason": "scale out"
}
```

응답 핵심 필드:

- `files_to_change`
- `suggested_updates`
- `trigger_kind`
- `summary`
- `commit_title`
- `commit_body`
- `requires_pull_request`
- `next_step`

## 9. 현재 UI 실사용 범위에서 제외한 API

- `POST /api/v1/chat/live`
- `GET /api/v1/ocp/metrics/{connection_id}`
- `POST /api/v1/index/source`
- `POST /api/v1/index/reset`
- `POST /api/v1/index/batch/reindex`
- `GET /api/v1/workspaces/{workspace_id}`
- `PATCH /api/v1/workspaces/{workspace_id}`
- `GET /api/v1/workspaces/{workspace_id}/metrics/snapshots`
