# v0.2.5 - Runtime Context ERD and Storage Planner

## Goal

v0.2.5의 목표는 사용자의 OCP namespace, resource, event, log, alert 데이터를 안전하게 저장하고 갱신/삭제할 수 있는 데이터 모델을 확정하는 것이다. 이 버전에서는 아직 collector나 답변 flow를 만들지 않고, runtime context를 저장하기 위한 ERD, 권한 경계, retention, redaction 정책을 설계한다.

## Background

PlaybookStudio가 OpenShift Lightspeed보다 나은 운영 assistant가 되려면 공식 문서 RAG만으로는 부족하다. 사용자가 terminal에서 Pod를 실행하거나 dashboard에서 이상 상태를 봤을 때, assistant는 현재 namespace의 실제 리소스 상태, Event, Log, Alert, Metric summary를 함께 보고 답해야 한다.

이 데이터는 계속 생성/수정/삭제된다. 따라서 단순히 문서처럼 영구 저장할 수 없고, snapshot과 retention 정책이 필요하다.

## Scope

### Included

- runtime context ERD
- cluster connection/session model
- namespace/resource snapshot model
- event/log/alert retention policy
- user namespace isolation model
- redaction/security policy
- migration plan

### Excluded

- 실제 OCP API collector 구현
- terminal command 실행 분석
- answer prompt 변경
- dashboard UI 변경
- feedback loop 구현

## Work Items

### 1. Runtime Context Boundary Definition

저장할 runtime context 범위를 명확히 정의한다.

In scope:

- cluster connection
- user workspace
- namespace ownership
- Kubernetes resource snapshot
- Pod status
- Events
- Logs tail
- Alerts
- Metric summary
- collection run status

Out of scope:

- Secret raw value
- full log indefinite archive
- cluster-wide admin data without explicit permission
- other users' namespaces

### 2. ERD Draft

초기 ERD 후보:

```text
ocp_clusters
ocp_user_workspaces
ocp_namespace_bindings
ocp_resource_snapshots
ocp_pod_snapshots
ocp_events
ocp_log_segments
ocp_alerts
ocp_metric_summaries
ocp_context_collection_runs
ocp_context_packs
```

Each row must carry:

- tenant/workspace/user boundary
- namespace
- collected_at
- expires_at where applicable
- source collector version
- redaction status

### 3. Namespace Isolation Rules

사용자는 본인에게 할당된 namespace만 볼 수 있어야 한다.

Rules:

- terminal user namespace와 app user mapping을 저장한다.
- collector query는 namespace-scoped 권한으로 제한한다.
- cluster-wide list는 허용하지 않는다.
- shared admin namespace는 별도 feature flag가 있을 때만 허용한다.
- deleted namespace는 archived binding으로 남긴다.

### 4. Snapshot and Deletion Model

Kubernetes resource는 계속 변하므로 current state와 historical evidence를 분리한다.

Model:

```text
current snapshot
  - latest known object summary
  - overwritten by next collection

historical event/log
  - append-only within retention period
  - expires by policy

context pack
  - answer generation 시점에 사용한 evidence bundle
  - answer audit를 위해 짧은 기간 보존
```

### 5. Retention Policy

권장 기본값:

- resource snapshot: latest + 24h history
- events: 7 days
- log tail: 24h or max bytes per Pod
- alerts: 14 days
- context packs: 14 days
- failed collection runs: 14 days

Secret, token, env value, kubeconfig content는 저장하지 않는다.

### 6. Redaction Policy

저장 전 redaction 대상:

- Secret values
- tokens
- passwords
- bearer headers
- kubeconfig
- image pull secrets
- env var values matching sensitive names
- private registry credentials

Redaction result should be tracked:

```json
{
  "redaction_status": "applied",
  "redacted_fields": ["env.DB_PASSWORD"],
  "warnings": []
}
```

### 7. Migration Plan

DB migration은 collector 구현 전 단계에서 준비한다.

Requirements:

- tables can exist unused
- no production behavior change
- idempotent migration
- indexes for namespace/user/time lookup
- cleanup job compatibility

## Deliverables

- runtime context ERD document
- migration design notes
- retention/redaction policy
- namespace isolation policy
- context pack schema draft

## Acceptance Criteria

- 사용자별 namespace/resource 접근 경계가 명확하다.
- 삭제/갱신되는 OCP 객체를 snapshot으로 다루는 전략이 있다.
- Event/Log/Alert 보존 기간과 삭제 조건이 정의되어 있다.
- 민감정보 redaction 대상이 명확하다.
- v0.2.6 collector 구현자가 바로 DB model을 만들 수 있다.

## Risks

| Risk | Mitigation |
| --- | --- |
| 민감정보 저장 위험 | 저장 전 redaction, Secret raw value 금지 |
| namespace isolation 실패 | namespace binding table과 scoped query 강제 |
| 로그 데이터 폭증 | max bytes, retention, sampling |
| runtime evidence와 docs citation 혼동 | context pack schema에서 evidence type 분리 |

## Completion Check

v0.2.5는 runtime data를 실제로 수집하지 않는다. 완료 기준은 ERD와 정책이 충분히 구체적이어서 v0.2.6에서 collector와 migration을 구현할 수 있는 상태다.
