# MacBook CRC OpenShift Lightspeed 실행 절차

## 목적

Windows는 PBS 실행 환경으로 유지하고, MacBook 32GB는 CRC와 OpenShift Lightspeed 실험 환경으로 분리한다.

이 문서는 회사 OpenShift 클러스터 작업과 충돌하지 않고 PBS 연동 가능성을 확인하기 위한 절차다.

## 역할 분리

| 구분 | 위치 | 역할 |
|---|---|---|
| PBS | Windows Docker | 현재 RAG, Viewer, pgvector 검증 상태 유지 |
| CRC | MacBook | OpenShift Local 클러스터 실행 |
| OpenShift Lightspeed | MacBook CRC | 콘솔 질의와 외부 호출 가능성 확인 |
| 연결 테스트 | Windows -> MacBook | endpoint 또는 SSH tunnel 접근 확인 |

## 1. MacBook 준비

| 확인 | 명령 또는 방법 | pass 조건 |
|---|---|---|
| CPU architecture | `uname -m` | `x86_64`면 OpenShift Lightspeed 검증 진행. `arm64`면 CRC 기동까지만 확인하고 OpenShift Lightspeed 설치 가능 여부를 먼저 확인 |
| memory | `sysctl hw.memsize` | 32GB 장비 확인 |
| disk | `df -h` | CRC와 image pull에 충분한 여유 공간 |
| crc | `crc version` | 명령 실행 가능 |
| oc | `oc version --client` | 명령 실행 가능 |

OpenShift Local은 MacBook에서 실행할 수 있지만, OpenShift Lightspeed는 OpenShift 4.16 이상과 x86 기반 클러스터 조건을 먼저 확인해야 한다. Apple Silicon 장비에서는 CRC 자체보다 OpenShift Lightspeed operator, image, custom resource 조건에서 막힐 가능성이 있다.

이 단계의 목적은 MacBook에 운영 환경을 만드는 것이 아니라, PBS가 호출할 수 있는 OpenShift Lightspeed endpoint를 확보할 수 있는지 확인하는 것이다.

## 2. CRC 리소스 설정

```bash
crc config set preset openshift
crc config set cpus 6
crc config set memory 18432
crc setup
```

| 확인 | pass 조건 |
|---|---|
| preset | `openshift` |
| cpu | 6 이상 |
| memory | 16GB 이상 |
| setup | 오류 없이 완료 |

메모리 부족이 반복되면 `crc config set memory 20480`까지 검토한다. MacBook에서 다른 무거운 앱은 종료한다.

## 3. CRC 기동

```bash
crc start
eval "$(crc oc-env)"
oc login -u kubeadmin -p <crc-kubeadmin-password> https://api.crc.testing:6443
oc get nodes
```

| 확인 | pass 조건 | 증거 |
|---|---|---|
| CRC status | `crc status` | Running |
| node | `oc get nodes` | Ready |
| console | `crc console --url` | URL 확인 |
| login | `oc whoami` | 사용자 확인 |

## 4. 모니터링 확인

```bash
oc get pods -n openshift-monitoring
oc get co monitoring
```

| 확인 | pass 조건 |
|---|---|
| monitoring operator | available |
| prometheus 관련 pod | ready |
| alertmanager 관련 pod | ready |

OpenShift Lightspeed 설치가 monitoring을 요구하면 이 단계가 먼저 통과해야 한다.

## 5. OpenShift Lightspeed 설치 확인

설치 방식은 실제 OperatorHub 또는 팀 문서 기준을 따른다. 설치 후 아래 상태를 확인한다.

OpenShift Lightspeed는 별도 LLM Provider가 필요하다. MacBook CRC 안에 모델까지 올리는 구성은 기본 검증 범위에서 제외한다. 이미 접근 가능한 사내 모델, 외부 테스트 모델, 회사 OpenShift AI endpoint 중 하나가 준비되지 않으면 설치 확인은 endpoint 확보 단계까지만 진행한다.

```bash
oc get ns | grep -i lightspeed
oc get pods -A | grep -i lightspeed
oc get csv -A | grep -i lightspeed
oc get route -A | grep -i lightspeed
oc get svc -A | grep -i lightspeed
```

| 확인 | pass 조건 | 증거 |
|---|---|---|
| operator | installed 또는 succeeded | CSV 상태 |
| pod | ready | pod 상태 |
| LLM Provider | 접근 가능한 모델 endpoint 확인 | secret, config, test response |
| console | assistant 진입점 표시 | 화면 확인 |
| 기본 질의 | OpenShift 질문에 응답 | 질의 결과 |
| 호출 경계 | route, service, API 중 하나 확인 | 리소스 조회 결과 |

## 6. MacBook 내부 호출 가능성 확인

호출 가능한 route 또는 service가 확인된 경우에만 진행한다.

```bash
curl -k <lightspeed-endpoint>/health
curl -k <lightspeed-endpoint>
```

| 확인 | pass 조건 |
|---|---|
| health 또는 기본 응답 | HTTP 응답 확인 |
| 인증 요구 | 인증 방식 확인 |
| 응답 형식 | PBS에서 저장 가능한 text 또는 JSON 확인 |

콘솔 내부 기능만 있고 외부 호출 경계가 확인되지 않으면 PBS 연동 구현으로 넘어가지 않는다.

## 7. Windows에서 MacBook 접근 확인

MacBook IP를 확인한다.

```bash
ipconfig getifaddr en0
```

Windows PowerShell에서 확인한다.

```powershell
Test-NetConnection <macbook-ip> -Port <port>
curl.exe -k https://<macbook-ip>:<port>/
```

직접 접근이 막히면 SSH tunnel을 사용한다.

```powershell
ssh -N -L 9443:<macbook-local-endpoint-host>:<macbook-local-endpoint-port> <mac-user>@<macbook-ip>
curl.exe -k https://127.0.0.1:9443/
```

| 확인 | pass 조건 |
|---|---|
| direct access | Windows에서 MacBook endpoint 응답 |
| tunnel access | Windows `127.0.0.1:9443` 응답 |
| 인증 | token 또는 session 처리 방식 확인 |

## 8. PBS 연동 전 고정값

| 항목 | 값 |
|---|---|
| endpoint | `<confirmed-endpoint>` |
| auth method | `<confirmed-auth-method>` |
| read-only test question | `<basic-openshift-question>` |
| expected response shape | `<text-or-json>` |
| timeout | `<seconds>` |
| error handling | unreachable, unauthorized, no_answer 분리 |

이 값이 채워지기 전에는 실제 OpenShift Lightspeed 연동 완료로 보지 않는다.

PBS 코드는 endpoint 미설정, 호출 실패, 빈 응답을 분리해 표시하고 내부 답변 경로를 유지한다.

## 중단 조건

| 조건 | 처리 |
|---|---|
| CRC가 안정적으로 running 상태가 아님 | OpenShift Lightspeed 설치 전 중단 |
| Apple Silicon에서 OpenShift Lightspeed 설치 조건이 맞지 않음 | 회사 서버 또는 x86 환경으로 전환 |
| monitoring ready 실패 | OpenShift Lightspeed 설치 전 중단 |
| LLM Provider 미확보 | OpenShift Lightspeed 질의 검증 전 중단 |
| OpenShift Lightspeed 콘솔 질의 실패 | PBS 연동 전 중단 |
| 호출 가능한 endpoint 미확인 | PBS 연동 설계 재검토 |
| Windows에서 MacBook 접근 실패 | network 또는 tunnel 먼저 해결 |
| 인증이 cluster-admin 전제 | 읽기 전용 권한 재설계 |

## PBS 연동 시작 조건

| 조건 | 필요 여부 |
|---|---|
| PBS RAG gate `go` | 필수 |
| MacBook CRC running | 필수 |
| OpenShift Lightspeed 설치 조건 확인 | 필수 |
| LLM Provider 연결 확인 | 필수 |
| OpenShift Lightspeed console 질의 성공 | 필수 |
| 호출 가능한 endpoint 확인 | 필수 |
| Windows에서 endpoint 접근 가능 | 필수 |
| read-only 인증 방식 확인 | 필수 |

## 관련 문서

- `pgvector-acceptance-check.md`
- `rag-foundation/05-go-no-go.md`
- `company-openshift-lightspeed-next.md`
