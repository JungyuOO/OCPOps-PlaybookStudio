# 회사 OpenShift Lightspeed 연동 준비

## 상태

| 항목 | 값 |
|---|---|
| 단계 | PBS 연동 검증 완료 |
| 선행 조건 | PBS pgvector 수용 기준 고정 |
| 대상 | MacBook OpenShift Lightspeed endpoint |
| 대체 실험 환경 | 회사 OpenShift 클러스터 |
| 현재 처리 | PBS 호출 경로 구현, 실제 endpoint auth/query/chat/source-meta/Viewer 통합 smoke 성공 |
| provider | `cywell-llm` |
| 모델 | `gemma-4-26b-a4b-it-awq-8bit` |
| TLS | self-signed chain으로 로컬 검증 시 TLS 검증 우회 필요 |

## 선행 조건

PBS RAG 기초는 독립 검증된 상태다.

| 항목 | 값 |
|---|---|
| vector backend | PostgreSQL pgvector |
| Qdrant active runtime | 없음 |
| RAG gate | `13/13 pass` |
| answer / Viewer audit | `8/8 pass` |

OpenShift Lightspeed 연동은 이 상태를 고정한 뒤 진행한다. 그래야 문제 발생 시 PBS 검색, 클러스터 인증, OpenShift Lightspeed 동작, 네트워크 경로를 분리해서 확인할 수 있다.

회사 OpenShift 클러스터의 OpenShift Lightspeed 설치를 다른 작업자가 진행 중이면, MacBook 32GB 환경의 OpenShift Lightspeed endpoint를 별도 실험 환경으로 사용한다. 이 경로는 회사 서버 작업을 방해하지 않고 PBS 연동 가능성만 검증하기 위한 용도다.

## 회사 클러스터 확인 항목

| 확인 | pass 조건 | 증거 |
|---|---|---|
| OpenShift Lightspeed 설치 | operator와 service pod가 실행 중 | namespace, pod, operator 상태 |
| 콘솔 표시 | OpenShift web console에서 assistant 진입점 표시 | console 화면 또는 route 확인 |
| 모델 연동 | 기본 OpenShift 질문에 응답 | console 질의 결과 |
| 모니터링 준비 | 필요한 monitoring 리소스가 ready | monitoring pod, alerting 리소스 |
| PBS 접근 경로 | PBS app container에서 필요한 endpoint 접근 가능 | container 내부 network test |
| 인증 범위 | service account 또는 user token 권한 범위 확인 | secret, role binding, namespace |
| 연동 경계 | 호출 가능한 API, route, tool 경계 중 하나 확인 | service, route, custom resource 점검 |

## MacBook CRC 실험 항목

| 확인 | pass 조건 | 증거 |
|---|---|---|
| CRC 실행 | MacBook에서 CRC가 정상 기동 | `crc status`, `oc get nodes` |
| 리소스 할당 | monitoring과 OpenShift Lightspeed 테스트에 필요한 메모리 확보 | CRC memory 설정값 |
| 모니터링 | monitoring 관련 pod가 ready | monitoring namespace pod 상태 |
| OpenShift Lightspeed 설치 | operator와 service pod가 ready | namespace, pod, custom resource 상태 |
| 콘솔 질의 | MacBook 브라우저에서 기본 질문 응답 | console 질의 결과 |
| 외부 접근 | Windows PBS에서 MacBook endpoint 또는 tunnel 접근 가능 | Windows에서 network test |
| 호출 경계 | PBS가 호출 가능한 route/API/service 확인 | route/service/custom resource 점검 |

## MacBook CRC 처리 원칙

| 항목 | 처리 |
|---|---|
| 목적 | 회사 서버 작업과 분리된 연동 가능성 검증 |
| PBS 위치 | Windows Docker 유지 |
| OpenShift Lightspeed 위치 | MacBook CRC |
| 연결 방식 | endpoint 직접 접근 또는 SSH tunnel |
| 메모리 | CRC에 16GB 이상 할당 검토 |
| CPU 조건 | `x86_64`면 설치 검증 진행. `arm64`면 OpenShift Lightspeed 지원 조건을 먼저 확인 |
| 모델 조건 | LLM Provider는 별도 준비. MacBook CRC에 모델까지 올리는 구성은 기본 검증 범위에서 제외 |
| 중단 기준 | MacBook 내부 콘솔 질의 실패 시 PBS 연동 진행하지 않음 |
| 주의 | CRC 주소가 MacBook 내부 전용이면 Windows에서 직접 접근되지 않을 수 있음 |

실행 절차는 `macbook-crc-lightspeed-runbook.md`를 따른다.

## 첫 연동 범위

| 항목 | 처리 |
|---|---|
| 호출 방향 | endpoint 확인 후 PBS에서 OpenShift Lightspeed 호출 |
| 권한 | 읽기 전용 우선 |
| 사용자 흐름 | PBS chat에서 OpenShift 운영 질문 전달, 답변 히스토리 저장 |
| Viewer | PBS 문서는 기존 Viewer 방식 유지, OpenShift Lightspeed 응답은 외부 공식 답변 artifact로 Viewer 표시 |
| 답변 표시 | OpenShift Lightspeed 사용 시 답변과 관련 문서 영역에 `Lightspeed` 배지 표시 |
| 실행 작업 | 자동 apply, update, delete 없음 |

## 확인된 API 설정

| 항목 | 값 |
|---|---|
| provider/model 미지정 | 성공. OpenShift Lightspeed 기본 설정 사용 |
| model만 지정 | 실패. HTTP 422, provider 필요 |
| provider=`openai` + model 지정 | 실패. 유효 provider 아님 |
| provider=`cywell-llm` + model 지정 | 성공 |

## SNO 연결 실행 순서

| 순서 | 작업 | 확인 |
|---|---|---|
| 1 | OpenShift Lightspeed route 또는 내부 service URL 확인 | `POST /v1/query` 호출 가능 |
| 2 | token 필요 여부 확인 | bearer token 또는 무인증 조건 확인 |
| 3 | PBS `playbookstudio-config`에 endpoint 설정 | `OPENSHIFT_LIGHTSPEED_BASE_URL` 값 반영 |
| 4 | 필요한 경우 secret에 token 설정 | `OPENSHIFT_LIGHTSPEED_API_TOKEN` 값 반영 |
| 5 | PBS app 재시작 | `oc rollout status deploy/app -n pbs-ocpops` |
| 6 | PBS app container에서 권한 smoke 실행 | `python -m play_book_studio.cli lightspeed-auth-smoke --root-dir /app` |
| 7 | PBS app container에서 endpoint smoke 실행 | `python -m play_book_studio.cli lightspeed-smoke --root-dir /app` |
| 8 | PBS app container에서 chat stream smoke 실행 | `python -m play_book_studio.cli lightspeed-chat-smoke --ui-base-url http://127.0.0.1:8765` |
| 9 | PBS app container에서 통합 smoke 실행 | `python -m play_book_studio.cli lightspeed-integration-smoke --root-dir /app --ui-base-url http://127.0.0.1:8765` |
| 10 | PBS chat 질문 검증 | `/api/chat/stream` 최종 payload에 `answer_source=lightspeed_with_pbs_rag` |
| 11 | 화면 검증 | 답변 헤더와 관련 문서에 `Lightspeed` 배지 표시 |

## 중단 조건

| 조건 | 이유 |
|---|---|
| 콘솔 내부 기능만 확인되고 호출 경로가 없음 | 연동 방식 재검토 필요 |
| cluster-admin 권한만 허용됨 | 고객 사용 흐름에 부적합 |
| 모니터링 또는 모델 연동이 ready가 아님 | 답변 품질 평가 불가 |
| PBS container에서 회사 클러스터 route 접근 불가 | network 경로 선해결 필요 |
| 답변 source metadata 확인 불가 | Viewer/source 표시는 분리 유지 필요 |

## 공식 문서 기준

| 기준 | 내용 |
|---|---|
| OpenShift Lightspeed 설치 문서 | OpenShift Lightspeed Operator 설치 전 LLM Provider 준비가 필요함 |
| OpenShift Lightspeed 요구사항 | OpenShift 4.16 이상과 x86 기반 클러스터 조건을 확인해야 함 |
| OpenShift Local 문서 | MacBook에서 CRC 실행은 가능하지만 개발/검증용 로컬 클러스터로 다룸 |

Sources:

- https://docs.redhat.com/en/documentation/red_hat_openshift_lightspeed/1.0/html/install/ols-installing-lightspeed
- https://docs.redhat.com/en/documentation/red_hat_openshift_lightspeed/1.0/pdf/about/Red_Hat_OpenShift_Lightspeed-1.0-About-en-US.pdf
- https://docs.redhat.com/ko/documentation/red_hat_openshift_local/2.16/html-single/getting_started_guide/index
