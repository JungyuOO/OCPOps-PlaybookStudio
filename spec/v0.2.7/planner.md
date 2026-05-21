# v0.2.7 - Operations Assistant Answer Flow Planner

## Goal

v0.2.7의 목표는 enriched official docs RAG와 OCP runtime context pack을 함께 사용하여 Pod, Alert, terminal 실습 질문에 운영 절차형 답변을 제공하는 것이다. 이 버전부터 PlaybookStudio는 단순 문서 Q&A를 넘어, 사용자의 실제 namespace 상태를 근거로 문제 원인과 확인/조치 방법을 제안한다.

## Scope

### Included

- docs-only / resource-analysis / alert-analysis / terminal-help routing
- runtime context pack + official docs context 결합
- Pod 문제 분석 답변 포맷
- Alert 대응 답변 포맷
- terminal 실습 오류 분석 답변 포맷
- runtime evidence와 official citation 분리 표시
- failure/feedback log 저장 준비

### Excluded

- collector 자체 구현
- full feedback dashboard
- automatic remediation 실행
- cluster-wide admin troubleshooting
- 사용자 대신 위험한 명령 실행

## Work Items

### 1. Operations Query Router

사용자 질문을 다음 route로 분류한다.

```text
docs_only
resource_analysis
alert_analysis
terminal_help
mixed_docs_runtime
clarification_required
```

Routing signals:

- selected namespace
- selected resource kind/name
- active terminal session
- recent command/error
- active alert
- question intent
- docs-only conceptual wording

### 2. Runtime + Docs Context Assembly

답변 생성 전 context를 두 종류로 분리한다.

```text
official citations
  - official docs
  - playbook docs
  - uploaded docs

runtime evidence
  - resource snapshot
  - events
  - logs
  - alerts
  - terminal command output
```

LLM prompt에는 두 evidence type을 명확히 구분해서 넣는다.

### 3. Pod Analysis Answer Format

Pod 질문 답변은 다음 구조를 따른다.

```text
1. 현재 상태 요약
2. 가능성 높은 원인
3. 확인 근거
4. 바로 확인할 명령
5. 조치 방향
6. 관련 공식 문서 근거
7. 추가로 필요한 정보
```

Example inputs:

- Pod Pending
- CrashLoopBackOff
- ImagePullBackOff
- OOMKilled
- FailedScheduling
- Terminating

### 4. Alert Analysis Answer Format

Alert 질문 답변은 다음 구조를 따른다.

```text
1. Alert 의미
2. 영향 범위
3. 현재 연결된 리소스
4. 확인할 metric/event/log
5. 조치 방향
6. 관련 공식 문서/Playbook
```

Alert가 문서 근거만으로 부족하면 runtime evidence 부족을 명시한다.

### 5. Terminal Help Answer Format

terminal 실습 질문은 명령 실행 맥락을 고려한다.

Inputs:

- last command
- exit code
- stderr/stdout summary
- current namespace
- related resource snapshot

Answer rules:

- 위험한 명령은 바로 실행하라고 하지 않는다.
- destructive command는 주의 문구를 포함한다.
- 사용자의 namespace 범위에서 가능한 확인 명령을 우선 제시한다.
- 근거 없는 command를 생성하지 않는다.

### 6. Evidence Display Contract

응답 payload에서 source citation과 runtime evidence를 분리한다.

```json
{
  "citations": [
    {"type": "official_doc", "title": "...", "viewer_path": "..."}
  ],
  "runtime_evidence": [
    {"type": "event", "resource": "Pod/demo", "reason": "FailedScheduling"}
  ]
}
```

UI가 아직 완성되지 않았더라도 API contract는 먼저 정의한다.

### 7. Failure and Feedback Logging

운영 답변 실패를 추적한다.

Log categories:

- no_runtime_context
- no_relevant_docs
- permission_denied
- stale_snapshot
- insufficient_logs
- unsafe_action_blocked
- low_grounding

## Deliverables

- operations query router
- context assembly contract
- Pod answer format
- Alert answer format
- terminal help answer format
- runtime evidence payload contract
- operations smoke/eval cases

## Acceptance Criteria

- "이 Pod 왜 안 떠?" 질문에서 Pod status, events/logs, official docs를 함께 사용한다.
- Alert 질문에서 의미, 영향, 확인 대상, 조치 방향을 분리해 답한다.
- runtime evidence와 official citation이 응답 payload에서 구분된다.
- 권한 부족이나 context 부족을 hallucination 없이 설명한다.
- terminal command 오류에 대해 namespace 범위 확인 명령을 제안한다.

## Risks

| Risk | Mitigation |
| --- | --- |
| runtime evidence를 공식 문서처럼 인용 | payload type 분리 |
| LLM이 위험한 조치 제안 | safety guard and destructive command policy |
| stale data로 잘못된 진단 | collected_at/stale warning 표시 |
| context가 너무 길어짐 | context pack summarization |
| docs와 runtime evidence 충돌 | 현재 상태 우선, 문서는 절차 근거로 사용 |

## Completion Check

v0.2.7이 끝나면 사용자는 문서 질문뿐 아니라 본인 namespace의 Pod/Alert/terminal 상태에 대해 질문하고, PlaybookStudio는 현재 상태와 공식 문서 근거를 분리해서 답할 수 있어야 한다.
