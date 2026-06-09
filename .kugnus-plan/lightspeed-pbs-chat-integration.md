# OpenShift Lightspeed PBS Chat 연동

## 목표

PBS 챗봇에서 OpenShift 운영 질문을 받으면 OpenShift Lightspeed를 호출한다.

OpenShift Lightspeed 답변은 OpenShift 공식 기준 답변으로 사용한다.
PBS는 고객사 문서, 사내 운영 문서, 사용자 업로드 문서, 작업 이력, citation, Wiki Viewer, 화면 형식을 반영해 최종 답변을 만든다.

최종 목표는 OpenShift 일반 지식 답변이 아니라 고객 환경이 반영된 OpenShift 대응 가이드다.

## 역할

| 구분 | 역할 |
| --- | --- |
| OpenShift Lightspeed | OpenShift 공식 기준 답변 제공 |
| PBS Backend | OpenShift 운영 질문 판별, Lightspeed 호출, PBS RAG 검색, 답변 재구성 |
| PBS RAG | 고객사 문서, 사내 문서, 업로드 문서, 공식 문서 중 관련 근거 검색 |
| PBS Wiki Viewer | PBS citation이 가리키는 문서와 chunk 표시 |
| PBS UI | 최종 답변 표시, citation, Viewer 이동, PBS 화면 형식 유지 |

## 처리 흐름

1. 사용자가 PBS 챗봇에 질문한다.
2. PBS Backend가 OpenShift 운영 질문인지 판별한다.
3. OpenShift 운영 질문이면 OpenShift Lightspeed API를 호출한다.
4. PBS RAG가 같은 질문으로 관련 문서를 검색한다.
5. PBS는 OpenShift Lightspeed 답변과 PBS RAG 근거를 함께 사용해 최종 답변을 작성한다.
6. 최종 답변의 citation은 PBS RAG 검색 결과로만 만든다.
7. citation은 기존 PBS Wiki Viewer에서 열려야 한다.
8. OpenShift Lightspeed가 사용되면 답변과 관련 문서 영역에 `Lightspeed` 배지를 표시한다.
9. OpenShift Lightspeed 응답은 PBS Viewer에서 외부 공식 답변 artifact로 열 수 있어야 한다.
10. OpenShift Lightspeed가 미설정 또는 실패 상태이면 답변에 PBS 내부 근거로 답변했다는 상태 문구를 표시한다.

## 확인된 runtime 값

| 항목 | 값 |
| --- | --- |
| provider | `cywell-llm` |
| model | `gemma-4-26b-a4b-it-awq-8bit` |
| TLS | self-signed chain으로 로컬 검증 시 TLS 검증 우회 필요 |
| 주의 | model만 지정하면 HTTP 422. provider와 model을 함께 지정해야 함 |

## 선행 확인

회사 SNO OpenShift 서버의 OpenShift Lightspeed API 호출 가능 여부를 먼저 확인한다.

| 순서 | 확인 |
| --- | --- |
| 1 | OpenShift Lightspeed operator, pod, service, route 상태 확인 |
| 2 | OpenShift Lightspeed가 provider/model 설정까지 완료되어 답변 가능한 상태인지 확인 |
| 3 | host에서 `POST /v1/query` 단독 호출 확인 |
| 4 | PBS app container 안에서 같은 endpoint 호출 확인 |
| 5 | PBS `.env` 또는 OpenShift ConfigMap/Secret에 endpoint와 token을 설정하고 `/api/chat/stream` 연동 확인 |

이 단계가 없으면 PBS 코드 문제, 네트워크 문제, 인증 문제, OpenShift Lightspeed 설치 문제를 분리하기 어렵다.

### 로컬 mock 확인

회사 endpoint 없이 PBS 호출 경로만 확인할 때 사용한다.

```powershell
.venv\Scripts\python.exe scripts\mock_lightspeed_server.py --port 18080
```

이 경우 PBS 설정에는 `http://host.docker.internal:18080`을 넣고 smoke를 실행한다.

### SNO 단독 호출 확인

PowerShell:

```powershell
$env:OPENSHIFT_LIGHTSPEED_BASE_URL="https://<lightspeed-route-or-service>"
$env:OPENSHIFT_LIGHTSPEED_API_TOKEN="<token-if-required>"
$headers = @{ "Content-Type" = "application/json" }
if ($env:OPENSHIFT_LIGHTSPEED_API_TOKEN) {
  $headers["Authorization"] = "Bearer $env:OPENSHIFT_LIGHTSPEED_API_TOKEN"
}
$body = @{ query = "Pod Pending 상태면 무엇을 먼저 확인해야 해?" } | ConvertTo-Json
Invoke-RestMethod -Uri "$($env:OPENSHIFT_LIGHTSPEED_BASE_URL.TrimEnd('/'))/v1/query" `
  -Method Post `
  -Headers $headers `
  -Body $body `
  -TimeoutSec 30
```

PBS app container:

```powershell
docker compose exec app python -m play_book_studio.cli lightspeed-auth-smoke --root-dir /app
docker compose exec app python -m play_book_studio.cli lightspeed-smoke --root-dir /app
docker compose exec app python -m play_book_studio.cli lightspeed-chat-smoke --ui-base-url http://127.0.0.1:8765
docker compose exec app python -m play_book_studio.cli lightspeed-integration-smoke --root-dir /app --ui-base-url http://127.0.0.1:8765
```

TLS 인증서가 사내 Route 인증서 문제로 막히는 경우에만 `OPENSHIFT_LIGHTSPEED_INSECURE_SKIP_TLS_VERIFY=true`를 사용한다.

### SNO 연결 실행 순서

| 순서 | 작업 | 확인 |
| --- | --- | --- |
| 1 | OpenShift Lightspeed route 또는 내부 service URL 확인 | `POST /v1/query` 응답 |
| 2 | token 필요 여부 확인 | bearer token 필요 여부 |
| 3 | PBS 설정 반영 | `OPENSHIFT_LIGHTSPEED_BASE_URL` |
| 4 | PBS app 재시작 | app pod ready |
| 5 | app container 권한 smoke | `lightspeed-auth-smoke` `status=success` |
| 6 | app container endpoint smoke | `lightspeed-smoke` `status=success` |
| 7 | PBS chat stream smoke | `lightspeed-chat-smoke` `status=success` |
| 8 | 통합 smoke | `lightspeed-integration-smoke` `status=success` |
| 9 | 화면 확인 | `Lightspeed` 배지와 Viewer link 표시 |

`lightspeed-chat-smoke`는 PBS chat stream까지 확인한다.

`lightspeed-auth-smoke`는 endpoint와 token 권한만 확인한다.

`lightspeed-integration-smoke`는 auth, query, chat, source-meta, Viewer API를 한 번에 확인한다.

| exit | 의미 |
| --- | --- |
| 0 | PBS 최종 payload가 OpenShift Lightspeed를 사용함 |
| 1 | PBS chat stream 호출 실패 |
| 2 | PBS chat은 성공했지만 OpenShift Lightspeed를 사용하지 않음 |

`lightspeed-auth-smoke`는 권한이 없으면 exit `3`과 `not_authorized`를 반환한다.

## 공식 API 기준

| 항목 | 기준 |
| --- | --- |
| 안정 경로 | OpenShift Lightspeed REST API는 `/v1` path를 사용 |
| 질의 endpoint | `POST /v1/query` |
| 필수 필드 | `query` |
| 선택 필드 | `conversation_id`, `provider`, `model`, `attachments` |
| 인증 | protected endpoint는 bearer token 필요 |
| 권한 | API 사용자 또는 service account에 OpenShift Lightspeed 사용자 권한 필요 |
| 장애 코드 | 401 인증 실패, 403 권한 부족, 413 payload 과대, 503 service 초기화 또는 불가 |

공식 문서:

- https://docs.redhat.com/en/documentation/red_hat_openshift_lightspeed/1.0/html/operate/ols-interacting-with-the-api
- https://raw.githubusercontent.com/openshift/lightspeed-service/main/docs/openapi.json

## 구현 범위

| 항목 | 작업 |
| --- | --- |
| 설정 | OpenShift Lightspeed endpoint, token, provider, model을 환경변수로 분리 |
| API client | `POST /v1/query` 호출과 응답 정규화. `response`, `referenced_documents`, `conversation_id`, token 수, quota, tool call/result 수를 분리 |
| 질문 판별 | OpenShift, Kubernetes, Pod, Node, Route, Operator, Event, YAML, `oc` 명령 등 운영 질문 감지 |
| 답변 조립 | OpenShift Lightspeed 답변을 공식 기준 답변으로 프롬프트에 포함 |
| 근거 연결 | PBS RAG citation만 최종 source로 사용 |
| 응답 표시 | 기존 `/api/chat` 응답에 `answer_source` 추가 |
| 배지 | OpenShift Lightspeed 성공 시 답변 헤더와 related link에 `Lightspeed` 표시 |
| Viewer | OpenShift Lightspeed 응답 artifact를 PBS Viewer에서 표시 |
| 실패 처리 | OpenShift Lightspeed 호출 실패 시 PBS RAG 답변으로 계속 동작 |

## 하지 않을 것

| 항목 | 이유 |
| --- | --- |
| OpenShift Lightspeed URL 하드코딩 | Route URL과 내부 Service URL을 설정만 바꿔 교체해야 함 |
| OpenShift Lightspeed 응답을 Viewer citation으로 직접 사용 | PBS 문서 ID와 chunk ID가 없을 수 있음 |
| OpenShift Lightspeed 문서 저장소를 PBS가 미러링 | 오늘 목표는 호출 연동과 PBS 근거 결합 |
| 새 화면 구조 추가 | 오늘 목표는 기존 PBS 챗봇 흐름 유지 |
| OpenShift 콘솔 연결 | 이번 구현 이후 별도 단계 |

## 완료 조건

| 기준 | pass | fail |
| --- | --- | --- |
| SNO 단독 호출 | 회사 SNO OpenShift Lightspeed가 `POST /v1/query`에 답변 | route는 있으나 답변 실패 |
| PBS container 호출 | PBS app container에서 같은 endpoint 호출 성공 | host에서는 되지만 container에서는 실패 |
| 환경변수 | 코드에 endpoint 하드코딩 없음 | URL이 코드에 고정됨 |
| 비활성 상태 | endpoint 미설정 시 기존 PBS RAG 답변 정상 | endpoint 없어서 `/api/chat` 실패 |
| 질문 판별 | OpenShift 운영 질문에서만 호출 시도 | 일반 질문에서도 호출 |
| API 호출 | 설정된 endpoint로 `POST /v1/query` 호출 | 호출 경로가 고정되어 교체 불가 |
| 답변 결합 | 최종 답변이 OpenShift Lightspeed 답변과 PBS 근거를 함께 반영 | Lightspeed 원문만 노출 |
| citation | 최종 citation은 PBS 문서와 chunk 기준 | Lightspeed 응답을 근거 ID 없이 citation 처리 |
| Viewer | citation 클릭 시 기존 Viewer 열림 | source는 있으나 Viewer 미연결 |
| Lightspeed 배지 | 성공 시 답변 헤더와 관련 문서에 `Lightspeed` 표시 | 연동 여부가 화면에서 보이지 않음 |
| Lightspeed Viewer | 관련 문서의 Lightspeed 카드를 열면 PBS Viewer에 응답 표시 | 외부 응답을 클릭해도 열 수 없음 |
| 실패 처리 | Lightspeed 실패 시 PBS RAG로 답변 지속 | 외부 호출 실패로 챗봇 중단 |
| 미연결 표시 | 운영 질문에서 Lightspeed 미설정/실패 이유가 답변에 표시 | 내부 답변인지 연동 답변인지 구분 불가 |

## 검증 방법

| 검증 | 방법 |
| --- | --- |
| 설정 로드 | 환경변수 없이 설정 객체 생성, endpoint 설정 후 값 확인 |
| health | `/api/health`의 `runtime.openshift_lightspeed.configured` 확인 |
| 단독 호출 | `python -m play_book_studio.cli lightspeed-smoke --root-dir /app` 실행 |
| 권한 호출 | `python -m play_book_studio.cli lightspeed-auth-smoke --root-dir /app` 실행 |
| chat stream 호출 | `python -m play_book_studio.cli lightspeed-chat-smoke --ui-base-url http://127.0.0.1:8765` 실행 |
| 통합 호출 | `python -m play_book_studio.cli lightspeed-integration-smoke --root-dir /app --ui-base-url http://127.0.0.1:8765` 실행 |
| client | 테스트용 HTTP 응답으로 `response`, `conversation_id`, `referenced_documents`, token 수, quota, tool call/result 수 파싱 확인 |
| classifier | OpenShift 운영 질문과 일반 질문 호출 여부 비교 |
| `/api/chat` | endpoint 미설정 상태에서 기존 테스트 통과 |
| `/api/chat/stream` | 최종 result payload에 `answer_source`, `Lightspeed` related link 포함 |
| 결합 경로 | fake Lightspeed client로 최종 `answer_source=lightspeed_with_pbs_rag` 확인 |
| 배지 경로 | related link 첫 항목에 `boundary_badge=Lightspeed` 확인 |
| Viewer 경로 | `/external/lightspeed/{artifact_id}`가 Viewer payload로 열리는지 확인 |
| Viewer | 반환 citation의 `viewer_path`와 serialized citation 유지 확인 |

## 현재 리스크

| 리스크 | 처리 |
| --- | --- |
| 실제 OpenShift Lightspeed endpoint가 아직 없을 수 있음 | fake client와 환경변수 비활성 경로로 먼저 검증 |
| PBS RAG가 고객 문서를 못 찾는 질문이 있음 | citation은 만들지 않고 검색 품질 문제로 분리 |
| OpenShift Lightspeed 답변과 PBS 근거가 충돌할 수 있음 | OpenShift 공식 기준과 고객사 기준을 답변에서 구분해 표시 |
| 응답 시간이 늘어날 수 있음 | timeout을 설정하고 실패 시 PBS RAG로 계속 진행 |
