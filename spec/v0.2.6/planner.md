# v0.2.6 - OCP Runtime Context Collector Planner

## Goal

v0.2.6의 목표는 v0.2.5에서 정의한 ERD와 정책을 기반으로 사용자의 OCP namespace 상태를 수집하고, 질문 답변에 사용할 수 있는 context pack으로 변환하는 것이다. 이 버전은 아직 최종 operations answer flow를 완성하지 않고, 안전한 수집/저장/조회 기반을 만든다.

## Scope

### Included

- namespace-scoped resource collector
- Pod status / describe summary / events 수집
- log tail 수집과 retention 적용
- Alert 수집 모델 연결
- context pack builder
- 권한 오류/접근 불가 상태 처리
- collector smoke test

### Excluded

- full answer prompt integration
- terminal command semantic diagnosis
- UI dashboard redesign
- cross-namespace admin analysis
- feedback loop

## Work Items

### 1. Collector Permission Model

collector는 사용자 namespace 범위에서만 실행한다.

Requirements:

- service account 또는 user-bound token 사용 경계 정의
- namespace-scoped list/get/watch만 허용
- forbidden 에러는 사용자에게 설명 가능한 상태로 저장
- 다른 사용자 namespace 접근 금지

Collection targets:

- Pods
- Deployments
- ReplicaSets
- Services
- Routes/Ingress
- PVC/PV reference summary
- ConfigMaps metadata only
- Events
- Alerts if available

### 2. Resource Snapshot Collector

주요 resource의 current state를 저장한다.

Snapshot fields:

- apiVersion
- kind
- namespace
- name
- uid
- labels/annotations allowlist
- phase/status
- conditions
- ownerReferences
- selected spec summary
- collected_at
- resource_version

Do not store:

- Secret data
- full ConfigMap data by default
- full env values

### 3. Pod Diagnostics Collector

Pod 문제 분석을 위해 필요한 최소 진단 정보를 수집한다.

Fields:

- phase
- conditions
- container statuses
- restart count
- waiting reason
- terminated reason
- image
- nodeName
- recent events
- log tail reference

Common states to preserve:

- CrashLoopBackOff
- ImagePullBackOff
- ErrImagePull
- Pending
- FailedScheduling
- OOMKilled
- Completed
- Terminating

### 4. Event and Log Collection

Event/log는 폭증 가능성이 있으므로 보존 정책을 강제한다.

Event:

- involved object
- reason
- message
- type
- count
- firstTimestamp
- lastTimestamp

Log:

- Pod/container
- tail lines or byte limit
- collected_at
- redaction status
- expiration time

### 5. Alert Collection

가능한 경우 Monitoring Alert를 수집한다.

Fields:

- alert name
- severity
- state
- namespace
- labels
- annotations summary
- startsAt/endsAt
- related resource hints

Alert raw payload는 필요한 필드만 저장한다.

### 6. Context Pack Builder

답변 생성에 넘길 evidence bundle을 만든다.

```json
{
  "context_pack_id": "...",
  "namespace": "user-a",
  "resource_focus": {
    "kind": "Pod",
    "name": "demo-pod"
  },
  "snapshots": [],
  "events": [],
  "logs": [],
  "alerts": [],
  "collection_warnings": []
}
```

Context pack은 docs citation과 구분되는 runtime evidence다.

### 7. Smoke Tests

테스트 범위:

- namespace without permission
- empty namespace
- healthy Pod
- CrashLoopBackOff-like Pod
- Pending Pod with FailedScheduling event
- log tail redaction
- deleted resource stale snapshot

## Deliverables

- collector implementation plan or implementation
- context pack schema
- smoke test cases
- collection run report
- retention cleanup plan

## Acceptance Criteria

- 사용자는 본인 namespace 리소스만 수집한다.
- Pod/Event/Log/Alert가 context pack으로 묶인다.
- 권한 오류가 실패가 아니라 설명 가능한 collection warning으로 저장된다.
- Secret/token 등 민감정보가 저장되지 않는다.
- 삭제된 리소스는 stale/deleted 상태로 구분된다.

## Risks

| Risk | Mitigation |
| --- | --- |
| cluster 권한 부족 | forbidden 상태를 collection warning으로 처리 |
| log 저장량 증가 | tail limit, byte limit, retention |
| 민감정보 노출 | redaction and denylist |
| 수집 지연 | on-demand collection과 cached snapshot 분리 |
| resource schema 다양성 | core resources first, unknown kind summary fallback |

## Completion Check

v0.2.6는 OCP runtime data를 안전하게 모으고 context pack으로 만들 수 있으면 완료다. 답변 생성에서 이 context pack을 적극 활용하는 작업은 v0.2.7에서 진행한다.
