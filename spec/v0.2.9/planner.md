# v0.2.9 - Operation Watcher and Notifications Planner

## Goal

v0.2.9의 목표는 사용자가 챗봇 또는 terminal에서 시작한 작업을 PlaybookStudio가 계속 추적하고, 상태 변화와 실패 원인을 알림으로 제공하는 Operation Watcher를 구현하는 것이다.

Lightspeed가 "질문하면 답하는 assistant"에 가깝다면, Operation Watcher는 "사용자가 실행한 작업이 끝날 때까지 지켜보고 알려주는 assistant"가 된다.

## User Experience

예시 흐름:

```text
1. 사용자가 챗봇에서 배포를 요청하거나 terminal에서 oc apply 실행
2. 시스템이 실행 명령과 관련 리소스를 감지
3. operation run 생성
4. Deployment/ReplicaSet/Pod/Event/Log를 watch target으로 등록
5. 상태 변화가 생기면 챗봇에 알림
6. 실패하면 원인 분석과 조치 방향 제공
```

진행 알림 예:

```text
nginx Deployment 생성이 시작되었습니다.
현재 상태: 0/1 replicas available
Pod nginx-xxx가 ContainerCreating 상태입니다.
이미지 pull을 기다리는 중입니다.
```

실패 알림 예:

```text
배포가 실패했습니다.

현재 상태:
- Pod: ImagePullBackOff
- Event: Failed to pull image "nginx:wrong-tag"

원인 후보:
- 이미지 태그가 존재하지 않거나 registry 접근 권한이 없습니다.

확인 명령:
- oc describe pod nginx-xxx -n user-a
- oc get events -n user-a --sort-by=.lastTimestamp
```

## Scope

### Included

1. operation run/watch ERD
2. terminal/chat command trigger 감지
3. related resource resolver
4. namespace-scoped watcher/poller
5. state transition detector
6. failure diagnosis mapper
7. chatbot notification stream/API

### Excluded

- 자동 remediation 실행
- cluster-wide watch
- 다른 사용자 namespace watch
- 위험 명령 자동 실행
- 장기 full log archive
- external notification integration

## Work Items

### 1. Operation ERD and Migration

v0.2.0에서 정의한 migration 규칙에 맞춰 operation watcher 테이블을 만든다.

Candidate tables:

```text
operation_runs
operation_steps
operation_watch_targets
operation_events
operation_notifications
operation_diagnoses
```

Required concepts:

- trigger source: chat, terminal, API
- command text or action id
- namespace
- owner user
- watch target resources
- current status
- started/completed/failed timestamps
- notification history

### 2. Command Trigger Detection

watcher는 다음 이벤트에서 시작될 수 있다.

- chatbot이 사용자의 요청으로 작업을 제안/실행
- terminal에서 `oc apply`, `oc rollout`, `oc create`, `oc delete`, `helm install` 감지
- 사용자가 특정 리소스 watch를 명시 요청

Trigger result:

```json
{
  "operation_type": "deployment_rollout",
  "namespace": "user-a",
  "command": "oc apply -f deployment.yaml",
  "watch_hints": []
}
```

### 3. Related Resource Resolver

명령과 apply output에서 관련 리소스를 추론한다.

Targets:

- Deployment
- ReplicaSet
- Pod
- Job
- Service
- Route/Ingress
- PVC
- ConfigMap/Secret metadata only

Resolver input:

- command
- stdout/stderr
- namespace
- labels/selectors if available
- resource names from apply output

### 4. Watcher / Poller

초기 구현은 watch stream보다 polling 중심으로 시작한다.

Polling targets:

- Deployment availability
- ReplicaSet ready count
- Pod phase/container status
- Event reason/message
- recent log tail
- PVC bound state
- Route admitted state

Polling stops when:

- success condition met
- failure condition detected
- timeout
- user cancels watch
- namespace access revoked

### 5. State Transition Detector

상태 변화 감지:

- Pending -> Running
- Running -> Ready
- Running -> CrashLoopBackOff
- ContainerCreating delay
- ImagePullBackOff
- FailedScheduling
- rollout timeout
- PVC Pending
- Job Failed/Succeeded

중요 상태 변화만 notification으로 보낸다. 같은 메시지를 반복 전송하지 않는다.

### 6. Failure Diagnosis Mapper

Event/Pod status/log tail을 기반으로 원인 후보를 만든다.

Initial mappings:

- ImagePullBackOff / ErrImagePull
- CrashLoopBackOff
- FailedScheduling
- OOMKilled
- PVC Pending / ProvisioningFailed
- Route not admitted
- Deployment ProgressDeadlineExceeded
- Permission denied / RBAC forbidden

Diagnosis output:

```json
{
  "summary": "이미지 pull 실패",
  "probable_causes": [],
  "evidence": [],
  "recommended_checks": [],
  "official_doc_queries": []
}
```

### 7. Chatbot Notification API

Operation watcher 결과를 챗봇/Workspace에 전달한다.

Notification types:

- info
- success
- warning
- error
- diagnosis
- action_required

API options:

- polling endpoint
- server-sent events
- existing chat stream event extension

Payload:

```json
{
  "operation_id": "op_123",
  "type": "diagnosis",
  "severity": "error",
  "message": "Pod가 ImagePullBackOff 상태입니다.",
  "evidence": [],
  "recommended_actions": []
}
```

## Deliverables

- operation watcher ERD/migration
- trigger detector
- related resource resolver
- watcher/poller
- state transition detector
- failure diagnosis mapper
- notification API contract
- smoke/eval cases

## Acceptance Criteria

- terminal에서 배포 명령을 실행하면 관련 리소스 watch target이 생성된다.
- Pod/Deployment 상태 변화가 operation notification으로 기록된다.
- 성공/실패/timeout 상태가 구분된다.
- 실패 시 Event/Pod status/log evidence를 기반으로 원인 후보를 제시한다.
- 사용자는 본인 namespace 작업만 watch할 수 있다.
- notification이 같은 상태를 계속 반복하지 않는다.

## Risks

| Risk | Mitigation |
| --- | --- |
| watch target 추론 실패 | 사용자가 수동 target을 선택할 수 있게 fallback |
| 너무 많은 알림 | state transition dedupe와 severity filter |
| 로그 민감정보 노출 | v0.2.0 redaction policy 적용 |
| long-running watcher 리소스 사용 증가 | timeout과 max active watcher 제한 |
| 자동 조치 오해 | watcher는 분석/알림만 제공하고 자동 remediation은 제외 |

## Completion Check

v0.2.9가 끝나면 PlaybookStudio는 사용자가 시작한 OCP 작업을 계속 추적하고, 생성 중/성공/실패/원인분석 상태를 챗봇 알림으로 제공할 수 있어야 한다.
