# v0.1.6 RAG Quality Routing Plan

## 한 줄 요약

v0.1.5는 query signal pipeline과 reranker 기반 검색 구조를 붙였지만, 100건 live validation 결과에서 **질문과 무관한 답변, smalltalk 오분류, 과도한 clarification, 명령 누락/오염**이 확인됐다. v0.1.6에서는 사용자 질문에서 뽑은 metadata/search signal을 실제 retrieved chunk와 gold answer(`validation/ocp_*.json`) 비교에 연결해, router와 retrieval 가중치를 조정하고 “질문-청크-답변”이 의미적으로 맞는지 검증하는 품질 루프를 만든다.

## 배경

`validation/ocp_*.json` 100건을 실제 서비스 `/api/chat/stream`에 태워 `validation/real_loop_full.json`으로 저장했다. 서비스 요청에는 질문만 보냈고, gold answer는 서비스 호출 후 비교 단계에서만 사용했다.

최종 관측 결과:

- 총 100건 모두 서비스 호출 status는 `ok`
- `response_kind` 분포
  - `rag`: 68
  - `clarification`: 22
  - `smalltalk`: 8
  - `error`: 1
  - `no_answer`: 1
- 답변 존재율: 99/100
- 자동 유사도 기준은 `passed=0`, `review=100`

중요한 해석:

- `passed=0`은 실제 답변이 전부 실패라는 뜻이 아니다.
- 현재 유사도 비교기가 한국어 설명, 명령어 부분 일치, 같은 절차의 표현 차이를 충분히 반영하지 못한다.
- 다만 실제 샘플을 보면 라우팅/검색/답변 생성 품질 문제가 분명히 존재한다.

대표 실패 유형:

1. **smalltalk 오분류**
   - “추가 OAuth 클라이언트는 어떻게 등록해?”
   - “CSR 승인은 어떤 명령어로 진행해?”
   - “새 프로젝트는 어떻게 만들어?”
   - “새 애플리케이션은 어떻게 만들어?”
   - “현재 선택된 프로젝트는 어떻게 확인해?”
   - “현재 프로젝트 상태는 어떻게 확인해?”

2. **과도한 clarification**
   - “클러스터 이벤트는 어떻게 확인해?”
   - “Node Feature Discovery Operator 배포는 어떻게 확인해?”
   - “제거 예정 API 사용 여부는 어떻게 확인해?”
   - “클러스터 진단 데이터는 어떻게 수집해?”
   - Insights Operator / 원격 상태 보고 계열 다수

3. **질문과 무관한 chunk 기반 답변**
   - AWS/GCP/Azure 레지스트리 스토리지 질문이 RHOSP/Cinder 문서로 치우침
   - 빌드 입력 보안 질문에 OIDC 인증 명령이 섞임
   - etcd 수동 조각 모음 질문에 `lsblk` 디스크 확인 명령이 나옴
   - CA 제거 질문이 Compliance Operator 삭제 절차로 흐름

4. **답변 생성/명령 추출 품질 문제**
   - `oc 프로세스`
   - 확인 명령이 문장만 있고 코드블록이 비어 있음
   - 정확한 명령 대신 일반형 또는 다른 절차 명령이 섞임

## v0.1.6 목표

1. **질문 라우팅을 RAG-safe하게 바꾼다.**
   - OCP/Kubernetes/OpenShift 리소스, 명령, 운영 행위가 보이면 smalltalk로 보내지 않는다.
   - low confidence여도 명령/리소스/운영 intent가 있으면 RAG 후보 검색을 먼저 수행한다.

2. **query signal을 검색 가중치에 더 직접적으로 연결한다.**
   - 질문에서 뽑은 `domain`, `subdomains`, `objects`, `components`, `operators`, `commands`, `command_families`, `intent_labels`, `answer_shapes`, `platform`, `cluster_phase`를 soft scoring에 반영한다.
   - hard filter는 계속 보수적으로 유지하고, 대부분은 soft boost/penalty로 둔다.

3. **gold answer 기반 품질 판정을 개선한다.**
   - 현재 단순 token/char/command similarity를 보완한다.
   - gold answer의 핵심 command, object, expected action, forbidden drift를 추출해 generated answer와 비교한다.
   - “답변이 존재함”이 아니라 “질문 의도와 gold answer 핵심을 만족함”을 판정한다.

4. **답변 생성은 retrieved chunk 근거에만 묶는다.**
   - 답변 LLM이 검색 근거 밖의 일반론을 섞지 않게 한다.
   - 명령형 질문이면 근거 chunk에서 실제 명령을 추출해 우선 배치한다.
   - 명령이 없으면 억지 명령을 만들지 않고 “근거에는 명령이 없다”를 명확히 말한다.

## v0.1.6 비목표

- 새로운 Agent 서비스를 만들지 않는다.
- Qdrant schema를 대규모로 다시 갈아엎지 않는다.
- validation 생성물(`validation/real_loop_full.json`, batch log 등)은 Git에 넣지 않는다.
- gold answer를 서비스 호출 payload에 넣지 않는다.

## 설계 방향

### 1. Router 구조 변경

현재 문제:

- 짧은 한국어 운영 질문이 smalltalk로 떨어진다.
- “어떻게 만들어?”, “어떻게 확인해?” 같은 일반 표현이 인사/일반 대화로 오분류된다.

변경 방향:

```text
User query
  -> cheap OCP guard
       - OCP resource/object/command/operator/platform keyword
       - Korean operational verbs: 확인, 생성, 등록, 삭제, 설정, 적용, 수집, 승인, 업로드, 변경
       - command-like intent: 어떤 명령어, 어떻게 봐, 상태, 목록
  -> if OCP guard true:
       route = rag_candidate
  -> else:
       existing smalltalk/general router
```

RAG guard 예시:

- objects: Pod, PVC, PV, Route, CSR, OAuthClient, MachineSet, MachineConfigPool, ImageStream, Project, Namespace, Secret, Operator
- commands: `oc`, `kubectl`, `ccoctl`, `oc adm`, `oc get`, `oc create`, `oc logs`, `oc project`, `oc new-project`, `oc new-app`
- Korean aliases:
  - “새 프로젝트” -> `Project`, `Namespace`, `oc new-project`
  - “새 애플리케이션” -> `Application`, `Deployment`, `oc new-app`
  - “현재 선택된 프로젝트” -> `oc project`
  - “CSR 승인” -> `CertificateSigningRequest`, `oc adm certificate approve`
  - “지원되는 API 리소스” -> `api-resources`, `oc api-resources`

Acceptance criteria:

- 위 smalltalk 오분류 케이스 8건이 더 이상 `smalltalk`가 아니어야 한다.
- 최소 `rag` 또는 근거 부족 시 `clarification`이어야 한다.
- “안녕하세요 OCP 챗봇입니다” 답변은 운영 질문에서 나오면 실패로 본다.

### 2. Clarification Threshold 재정의

현재 문제:

- 검색 후보가 일부 존재해도 low confidence로 clarification 처리된다.
- clarification 메시지가 엉뚱한 문서 제목을 제안한다.

변경 방향:

- `clarification`은 다음 경우에만 허용한다.
  - OCP guard가 false이고 질문 자체가 모호함
  - 검색 top candidates가 모두 질문 signal과 충돌함
  - citation 가능한 chunk가 0건
- OCP guard가 true이고 command/resource intent가 명확하면:
  - low confidence라도 top chunk의 근거를 제한적으로 요약
  - 단, “근거가 약하다” warning을 내부 trace에 남김

Clarification 금지 예시:

- “클러스터 이벤트는 어떻게 확인해?”
- “클러스터 진단 데이터는 어떻게 수집해?”
- “Node Feature Discovery Operator 배포는 어떻게 확인해?”
- “제거 예정 API 사용 여부는 어떻게 확인해?”

Acceptance criteria:

- 기본 운영 질문이 `clarification`으로 빠지는 비율을 줄인다.
- clarification 답변에는 엉뚱한 문서 제목 대신 사용자의 질문에서 추출한 부족 정보만 물어본다.

### 3. Metadata/Signal 기반 Soft Scoring

현재 문제:

- 질문 signal을 추출해도 최종 chunk 선택에서 platform/domain/object mismatch가 남는다.
- AWS/GCP/Azure/RHOSP/vSphere 같은 platform signal이 약하다.
- etcd, Insights, registry, build/security 계열이 엉뚱한 chunk를 잡는다.

변경 방향:

soft scoring feature를 명시적으로 분리한다.

```text
score = base_hybrid_score
      + reranker_score
      + signal_match_boost
      - signal_conflict_penalty
      - command_drift_penalty
```

Boost 대상:

- `classification.domain` match
- `classification.subdomains` overlap
- `search_signals.objects` overlap
- `search_signals.operators` overlap
- `search_signals.components` overlap
- `search_signals.command_families` overlap
- `search_signals.intent_labels` overlap
- `platform` exact match
- `best_for_questions` semantic match

Penalty 대상:

- platform conflict
  - AWS 질문에 RHOSP chunk
  - Azure 질문에 RHOSP/vSphere chunk
  - GCP 질문에 Azure/RHOSP chunk
- object conflict
  - etcd 질문에 disk/lsblk only chunk
  - build input security 질문에 OAuth/OIDC only chunk
- command conflict
  - 질문/gold expected command family와 다른 command family가 top answer command로 등장

우선 가중치 조정 대상:

- `registry`
  - AWS/GCP/Azure/RHOSP image registry storage
  - Red Hat registry signature
  - image trigger
  - manifest list / multi-arch image stream
- `etcd`
  - defrag
  - backend quota
  - backup
  - latency
- `monitoring/support`
  - must-gather
  - Insights Operator
  - remote health reporting
- `node_ops`
  - NFD/GPU
  - MachineSet per platform
- `networking`
  - private DNS
  - private Ingress
  - jitter

### 4. Gold Answer 기반 Evaluation 개선

현재 문제:

- `similarity_pass_rate=0.0`으로 나와서 품질 지표로 쓰기 어렵다.
- 좋은 답변도 표현 차이 때문에 실패로 보일 수 있다.
- 나쁜 답변도 “답변 있음”만 보면 통과처럼 보인다.

변경 방향:

gold answer에서 아래 필드를 추출한 evaluation artifact를 만든다.

```json
{
  "case_id": "...",
  "question": "...",
  "gold_signals": {
    "expected_objects": ["Pod", "Project"],
    "expected_commands": ["oc logs", "oc project"],
    "expected_command_families": ["oc_logs", "oc_project"],
    "expected_intents": ["check_status", "configure_resource"],
    "expected_topics": ["pod logs", "current project"],
    "forbidden_topics": ["smalltalk", "unrelated oauth", "rhosp cinder"]
  },
  "actual_signals": {
    "response_kind": "rag",
    "answer_commands": ["oc logs pod/<pod_name>"],
    "citation_count": 2,
    "retrieved_domains": ["logging"]
  },
  "verdict": "pass | partial | fail",
  "failure_reason": "smalltalk_route | no_answer | wrong_domain | missing_command | command_drift | weak_citation"
}
```

판정 규칙:

- `smalltalk` + OCP guard true -> fail
- `no_answer` + expected command exists -> fail
- expected command family가 answer에 없고 retrieved chunk에도 없으면 fail
- expected object/topic은 맞지만 명령 일부 누락 -> partial
- citation이 없으면 fail 또는 partial
- gold 핵심 command와 answer command가 일치하고 설명이 같은 절차면 pass

Acceptance criteria:

- 100건 결과를 `pass/partial/fail`로 사람이 납득 가능한 수준으로 나눌 수 있어야 한다.
- 실패 유형별 count를 자동 산출한다.

### 5. Answer Generation Guard

현재 문제:

- retrieved chunk와 무관한 일반론 또는 엉뚱한 명령이 답변에 섞인다.
- 명령이 빠지거나 깨진다.

변경 방향:

- answer prompt에 “질문에서 요구한 answer_shape”를 넣는다.
- command 질문이면 다음 순서를 강제한다.
  1. top cited chunk에서 command 후보 추출
  2. expected command family와 맞는 command 우선
  3. command가 없으면 명령을 생성하지 않음
  4. 답변 첫 줄에 핵심 명령 또는 근거 부족을 명시
- `oc 프로세스`, `oc 클러스터의 설치 프로그램에서 생성한` 같은 깨진 command는 sanitize 단계에서 제거한다.

Acceptance criteria:

- command intent 질문에서 빈 코드블록/깨진 command가 나오지 않는다.
- “어떤 명령어” 질문에 관련 없는 command family가 top answer로 나오면 fail trace를 남긴다.

## 작업 순서

1. **Evaluation artifact 개선**
   - `validation_real_loop.py` 또는 별도 evaluator에 gold signal extraction 추가
   - pass/partial/fail 및 failure_reason 산출
   - 기존 `real_loop_full.json`을 재분석할 수 있는 offline mode 추가

2. **Router guard 수정**
   - OCP resource/command/operation guard 추가
   - smalltalk route보다 먼저 적용
   - 오분류 8건 회귀 테스트 추가

3. **Clarification policy 수정**
   - OCP guard true면 바로 clarification하지 않고 retrieval evidence를 먼저 사용
   - citation 0건/강한 conflict일 때만 clarification
   - clarification 문구 개선

4. **Signal scoring 가중치 조정**
   - platform match/conflict boost/penalty
   - domain/object/operator/component/command family overlap boost
   - wrong command drift penalty
   - domain별 targeted scoring module 추가 또는 기존 `scoring_adjustments_core_*` 확장

5. **Answer command guard**
   - extracted command validation 강화
   - empty/garbled command 제거
   - command intent answer format 개선

6. **Regression validation**
   - 100건 중 대표 실패 케이스를 fixture로 고정
   - 전체 live loop는 필요 시 10건 단위로 실행
   - validation output은 계속 Git ignore 유지

## 대표 회귀 케이스

라우터:

- 추가 OAuth 클라이언트는 어떻게 등록해?
- CSR 승인은 어떤 명령어로 진행해?
- 새 프로젝트는 어떻게 만들어?
- 새 애플리케이션은 어떻게 만들어?
- 현재 선택된 프로젝트는 어떻게 확인해?
- 현재 프로젝트 상태는 어떻게 확인해?
- 지원되는 API 리소스 목록은 어떻게 봐?

검색/가중치:

- AWS 사용자 프로비저닝 환경에서 레지스트리 스토리지는 어떻게 설정해?
- Google Cloud 사용자 프로비저닝 환경에서 레지스트리 스토리지는 어떻게 설정해?
- Azure에서 이미지 레지스트리 스토리지는 어떻게 설정해?
- etcd 수동 조각 모음은 어떤 명령어로 진행해?
- 빌드 입력 보안을 적용하려면 어떤 명령어를 써?
- 다중 아키텍처 이미지 스트림에서 매니페스트는 어떻게 가져와?
- 컨트롤 플레인 노드 간 네트워크 지터는 어떻게 측정해?

답변 생성:

- Google Cloud에서 컴퓨팅 머신 세트를 만들려면 어떻게 해?
- Prometheus 인증 지표를 보려면 먼저 무엇을 해야 해?
- Machine Config Operator 노드 업데이트 상태는 어떻게 확인해?
- Pod 로그는 어떻게 확인해?

## 완료 기준

- 기존 100건 validation을 offline evaluator로 재분석했을 때 실패 유형이 자동 분류된다.
- smalltalk 오분류 대표 케이스가 모두 RAG 경로로 들어간다.
- clarification 비율이 줄고, 기본 운영 질문은 근거 기반 답변을 생성한다.
- platform/domain mismatch 대표 케이스가 올바른 chunk를 top 후보로 올린다.
- command 질문에서 관련 없는 명령, 깨진 명령, 빈 코드블록이 감소한다.
- `validation/` 산출물은 Git에 포함되지 않는다.
