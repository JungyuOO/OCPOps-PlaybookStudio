# 오리은행 디지털뱅킹 OCP 운영 점검 기준

문서 구분: PBS 시연용 가상 고객 데이터
작성일: 2026-06-10
고객사: 오리은행(Ori Bank)
업종: 금융/디지털뱅킹
대상 환경: OpenShift 4.20 기반 디지털뱅킹 운영 클러스터

이 문서는 PBS 시연을 위해 만든 가상 고객사 내부자료입니다. 실제 고객사, 계정, 도메인, 토큰, 비밀번호는 포함하지 않습니다. 업로드 RAG, 고객문서 citation, OpenShift Lightspeed 공식 답변과 고객 환경값 결합 여부를 검증하기 위한 더미 데이터입니다.

## 1. 운영 환경 요약

오리은행은 디지털뱅킹 결제 API와 모바일 조회 API를 OpenShift에서 운영한다. 운영팀은 장애 대응 시 공식 OpenShift 절차를 따르되, 고객 내부 기준에 따라 먼저 확인해야 하는 namespace와 리소스 이름을 정해 두었다.

| 구분 | 고객 환경값 | 설명 |
|---|---|---|
| 결제 API namespace | ori-pay-prod | 외부 결제 요청을 처리하는 핵심 업무 namespace |
| 모바일 API namespace | ori-mobile-prod | 모바일 앱 조회/인증 API namespace |
| 배치 namespace | ori-batch-prod | 정산/마감 CronJob과 배치 Pod가 실행되는 namespace |
| CI/CD namespace | ci-pipelines | PipelineRun, Repository CR, PAC 연동 리소스를 확인하는 namespace |
| Controller namespace | openshift-pipelines | Pipelines as Code controller 로그를 확인하는 namespace |
| 스토리지 namespace | openshift-storage | PVC/스토리지 이슈가 지속될 때 ODF/LVM 상태를 확인하는 namespace |
| 모니터링 namespace | banking-monitoring | 업무 알림, Warning 이벤트 대시보드, SLO 점검 기준 namespace |

## 2. CI/CD 연결 기준

오리은행은 GitHub Push 이벤트가 발생하면 Pipelines as Code가 Repository CR을 기준으로 PipelineRun을 자동 생성해야 한다. PipelineRun이 생성되지 않을 때는 GitHub Webhook, smee.io relay, Repository CR, controller log 순서로 확인한다.

| 항목 | 고객 환경값 | 점검 목적 |
|---|---|---|
| GitHub 조직 | ori-bank-demo | 시연용 가상 조직 |
| 업무 repository | ori-payments-api | 결제 API 애플리케이션 repository |
| Repository CR | ori-payments-api-repository | Pipelines as Code가 참조하는 Repository Custom Resource |
| Repository CR namespace | ci-pipelines | Repository CR과 PipelineRun을 조회하는 namespace |
| Webhook relay URL | https://smee.io/ori-bank-pac-demo-webhook | 외부 GitHub webhook을 내부 OpenShift PAC controller로 전달하는 relay |
| Webhook secret 이름 | ori-pac-webhook-secret | GitHub Webhook secret과 OpenShift Secret 일치 여부 확인용 더미 이름 |
| Controller namespace | openshift-pipelines | controller 로그 확인 위치 |

### PipelineRun이 생성되지 않을 때 우선 확인 순서

1. GitHub Webhook Delivery에서 HTTP Status가 200인지 확인한다.
2. smee.io relay 화면에서 이벤트가 실제로 수신되는지 확인한다.
3. ci-pipelines namespace에서 Repository CR이 Ready인지 확인한다.
4. ci-pipelines namespace에서 PipelineRun이 생성되었는지 확인한다.
5. openshift-pipelines namespace에서 controller 로그에 signature validation, repository match, RBAC 오류가 있는지 확인한다.

복붙용 운영 명령:

```bash
oc get repository -n ci-pipelines
```

```bash
oc describe repository ori-payments-api-repository -n ci-pipelines
```

```bash
oc get pipelinerun -n ci-pipelines
```

```bash
oc get events -n ci-pipelines --sort-by=.lastTimestamp
```

```bash
oc logs -n openshift-pipelines deployment/pipelines-as-code-controller
```

## 3. 결제 API 장애 점검 기준

오리은행 결제 API 장애는 ori-pay-prod namespace를 먼저 본다. 고객 내부 기준에서는 "결제 요청 지연" 또는 "Route 503" 알림이 발생하면 Pod 상태, Service endpoint, Route, 최근 이벤트를 같은 namespace에서 이어서 확인한다.

| 점검 대상 | 고객 환경값 | 확인 이유 |
|---|---|---|
| 업무 namespace | ori-pay-prod | 결제 API Pod, Service, Route가 배치되는 위치 |
| Deployment | pay-api | 결제 API Deployment |
| Service | pay-api-svc | Route가 연결되는 내부 Service |
| Route | pay-api | 외부 결제 요청 진입점 |
| 상태 기준 | 5분 이상 5xx 증가 | banking-monitoring 알림 기준 |

복붙용 운영 명령:

```bash
oc get pods -n ori-pay-prod
```

```bash
oc describe deployment pay-api -n ori-pay-prod
```

```bash
oc get svc pay-api-svc -n ori-pay-prod
```

```bash
oc get route pay-api -n ori-pay-prod
```

```bash
oc describe route pay-api -n ori-pay-prod
```

```bash
oc get events -n ori-pay-prod --sort-by=.lastTimestamp
```

## 4. PVC Pending 점검 기준

결제 거래 임시 저장소는 ori-pay-prod namespace의 txn-ledger-pvc를 사용한다. PVC가 Pending이면 StorageClass, quota, node scheduling event를 순서대로 확인한다.

| 항목 | 고객 환경값 | 설명 |
|---|---|---|
| PVC 이름 | txn-ledger-pvc | 결제 거래 임시 저장소 |
| PVC namespace | ori-pay-prod | 결제 API namespace |
| 기본 StorageClass | ocs-storagecluster-ceph-rbd | 일반 블록 스토리지 기본값 |
| 경고 기준 | Pending 3분 이상 | 결제 API 배포 보류 기준 |

복붙용 운영 명령:

```bash
oc get pvc txn-ledger-pvc -n ori-pay-prod
```

```bash
oc describe pvc txn-ledger-pvc -n ori-pay-prod
```

```bash
oc get storageclass
```

```bash
oc get events -n ori-pay-prod --sort-by=.lastTimestamp
```

## 5. 이벤트와 로그 확인 기준

오리은행 운영팀은 장애 초기에 이벤트를 먼저 보고, 이벤트에서 대상 리소스를 좁힌 뒤 로그를 본다. 결제 API는 ori-pay-prod namespace 기준으로 확인한다.

| 순서 | 확인 항목 | 고객 기준 명령 |
|---|---|---|
| 1 | namespace 최근 이벤트 | oc get events -n ori-pay-prod --sort-by=.lastTimestamp |
| 2 | Pod 상세 이벤트 | oc describe pod <pod-name> -n ori-pay-prod |
| 3 | 현재 컨테이너 로그 | oc logs <pod-name> -n ori-pay-prod |
| 4 | 재시작 직전 로그 | oc logs <pod-name> -n ori-pay-prod --previous |
| 5 | 실시간 로그 | oc logs -f <pod-name> -n ori-pay-prod |

## 6. PBS 시연 질문 예시

아래 질문은 OpenShift Lightspeed 공식 답변과 오리은행 고객자료가 함께 반영되는지 확인하기 위한 테스트 질문이다.

1. 오리은행 기준으로 PipelineRun이 안 뜰 때 뭐부터 확인해?
2. 오리은행 결제 API Route가 503이면 어떤 namespace와 리소스부터 확인해?
3. 오리은행 기준으로 PVC Pending이면 어떤 PVC와 StorageClass를 봐야 해?
4. 오리은행 결제 API 장애에서 이벤트와 로그는 어떤 순서로 확인해?
5. 오리은행 기준으로 Pipelines as Code controller 로그는 어디서 봐?

## 7. 시연 기대 결과

PBS가 이 문서를 업로드 RAG로 사용하면 답변에는 다음 고객 환경값이 반영되어야 한다.

- PipelineRun과 Repository CR 관련 명령은 ci-pipelines namespace를 사용한다.
- Pipelines as Code controller 로그는 openshift-pipelines namespace를 사용한다.
- 결제 API 장애 질문은 ori-pay-prod namespace, pay-api Deployment, pay-api-svc Service, pay-api Route를 사용한다.
- PVC 질문은 txn-ledger-pvc와 ocs-storagecluster-ceph-rbd를 우선 언급한다.
- 공식 OpenShift 운영 절차는 Lightspeed 답변을 따르되, 명령어 placeholder는 고객 환경값으로 채워진다.
