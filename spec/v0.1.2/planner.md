# v0.1.2 청크 품질 재구축과 초보자 답변 깊이 개선

## 진행 메모 (2026-05-13)

- [x] Phase C 보강: reranker를 로컬 mini cross-encoder에서 사내 BGE remote reranker로 전환
  - 기존 `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` 로컬 로딩 경로를 사용하지 않도록 `RemoteBgeReranker`로 교체
  - `RERANKER_BASE_URL` 기본값은 `EMBEDDING_BASE_URL`을 따르며, `EMBEDDING_BASE_URL`이 `/v1`로 끝나면 rerank endpoint는 TEI 구조에 맞춰 `http://tei.cywell.co.kr/rerank`로 계산
  - TEI 스타일 `texts` payload를 먼저 시도하고, 400/404/415/422 응답이면 OpenAI/Cohere 스타일 `documents` payload로 재시도
  - rerank 문서 입력에 book/chapter/section/path/heading/commands/k8s objects/error strings metadata를 포함해, Route timeout처럼 토큰만 겹치는 잘못된 책 선택을 규칙 매핑이 아니라 의미 점수로 줄이는 방향 적용
  - OCP ConfigMap과 production env 예시에 `RERANKER_BASE_URL`, `RERANKER_MODEL=dragonkue/bge-reranker-v2-m3-ko`, `RERANKER_TIMEOUT_SECONDS` 추가
  - 검증: compileall 통과, `tests/test_reranker.py tests/test_chat_grounding_quality.py tests/test_answer_eval_quality.py` 46개 통과
  - 실호출 확인: `http://tei.cywell.co.kr/v1/rerank`는 404, `http://tei.cywell.co.kr/rerank`는 endpoint가 존재하지만 현재 `texts` payload에 424 Failed Dependency를 반환. 즉 코드 endpoint 계산은 TEI 구조에 맞췄고, 서버 쪽 reranker 모델/backend 준비 여부는 별도 확인 필요
- [x] Phase D 배포 보강: 사내 TEI reranker 권한이 없을 때를 위해 OCP namespace 내부에 BGE reranker inference service를 추가
  - `bge-reranker-cache` PV/PVC, `bge-reranker` Deployment/Service 추가
  - `ghcr.io/huggingface/text-embeddings-inference:cpu-latest` + `dragonkue/bge-reranker-v2-m3-ko`로 시작하며 모델 캐시는 PVC `/data`에 유지
  - PlayBookStudio `RERANKER_BASE_URL`을 `http://bge-reranker:80`로 변경해 app이 namespace 내부 service를 호출하도록 구성
  - apply script가 `deployment/bge-reranker` rollout을 기다리도록 수정
  - README에 reranker 로그 확인 및 `/rerank` smoke 명령 추가
  - SNO 환경에 default StorageClass가 없어 기존 PBS PV 패턴과 동일한 hostPath PV(`/var/lib/playbookstudio-ocp/bge-reranker-cache`, node `52-54-00-47-49-49`)를 manifest에 추가
  - 검증: `kubectl kustomize deploy/openshift` 렌더링 통과, `bash -n deploy/openshift/apply-playbookstudio.sh` 통과
- [x] Phase D 로컬 검증 보강: OCP 내부 reranker를 port-forward/SSH tunnel로 로컬 품질 eval에 연결하는 helper 추가
  - `deploy/local-reranker-quality-eval.ps1` 추가
  - 기본 동작: `RERANKER_BASE_URL=http://127.0.0.1:8081` 설정, `/rerank` smoke, `pbs_chat_quality_v012_beginner_cases.jsonl` answer eval 실행
  - README에 Ubuntu 서버 `oc port-forward`, Windows SSH tunnel, v0.1.2 beginner/extended eval 실행 명령 추가
  - 검증: PowerShell scriptblock parse 통과

- [x] Phase C 보강: PDB/HPA/finalizer 계열 운영 질문을 intent profile과 intent-profile rerank rescue로 보강
  - 질문-답변 고정 매핑은 추가하지 않고, `PodDisruptionBudget`, `HorizontalPodAutoscaler`, namespace `finalizers`를 일반 intent profile의 target/evidence/primary command로 등록
  - reranker가 좋은 hybrid 후보를 잘라낸 경우에도 intent evidence 또는 선호 book slug가 있는 후보를 최종 후보로 구제하는 일반 rescue 경로를 추가
  - `ClusterOperator` 상태 답변은 `oc get clusteroperators`만 근거에 있어도 `oc describe clusteroperator <operator-name>` 후속 확인을 함께 안내하도록 보강
  - PVC 질문에 `events` 단어가 포함될 때 일반 이벤트 답변이 PVC 전용 답변을 가로채지 않도록 status answer 우선순위를 조정
  - 검증: compileall 통과, `tests/test_chat_grounding_quality.py tests/test_starter_questions.py tests/test_answer_eval_quality.py tests/test_query_understanding.py tests/test_answer_text_commands.py` 74개 통과
  - extended eval: `spec/v0.1.2/evidence/v012_answer_eval_extended_after.json` 갱신, pass_rate 0.5333 -> 0.5556, warning_free_rate 0.9778, citation_terms_rate 0.6667
  - 남은 병목: Route timeout은 HSTS route chunk가 timeout 질문을 오염시키고, PDB는 좋은 nodes chunk를 잡아도 일반 troubleshooting formatter가 PDB 전용 status answer를 타지 못함. DNS/NetworkPolicy/monitoring/namespace-list/previous-logs/SCC 등은 citation term과 book 선택 정밀도 보강 필요


## 진행 메모 (2026-05-12)

- [x] Phase C 보강: Node/Namespace/ImagePullBackOff 기본 운영 질의가 generic formatter나 low-confidence clarification으로 새지 않도록 citation 기반 status answer 경로를 추가
  - 질문-답변 고정 매핑이 아니라, 선택 citation의 실제 signal/cli_commands를 재사용하는 answer shaping 보강으로 처리
  - `Node 확인하려면 어떤 명령어부터 쓰면 돼?`는 `oc get nodes`/`oc describe node` 중심으로 응답
  - `네임스페이스 확인`은 현재 context 확인(`oc project`, `oc config view`)과 전체 목록 조회(`oc get namespaces`, `oc get projects`)를 분리
  - `ImagePullBackOff`는 Pod 이벤트, pull secret, registry 접근 순서로 확인하도록 citation 명령 기반 응답을 추가
  - 검증: compileall 통과, `tests/test_chat_grounding_quality.py tests/test_starter_questions.py tests/test_answer_eval_quality.py tests/test_query_understanding.py` 47개 통과, v012 beginner answer eval 6/6 통과(pass_rate 1.0, warning_free_rate 1.0)
  - 참고: full `studio_live_smoke` 재실행은 로컬 app 컨테이너가 Docker health는 healthy이나 `/api/health`와 starter API가 30초 이상 응답하지 않아 보류. 배포/라이브 smoke는 Phase D에서 별도 진행
- [x] Phase C 보강: must-gather, `oc adm inspect`, Pod CPU/memory 사용량, ClusterOperator 기본 운영 명령의 intent/profile과 status answer를 추가 보강
  - `must-gather`/`inspect`는 citation 명령이 없을 때도 code block 대신 inline fallback으로 안내하여 ungrounded code block을 만들지 않도록 처리
  - `특정 Pod의 리소스가 얼마나 잡아먹고 있는지` 같은 초보자 표현을 pod metrics intent로 연결하고 `oc adm top pod(s)` 문서 근거를 회수하도록 보강
  - balanced quote가 있는 selector 명령(`oc adm top pod --selector='<pod_name>'`)은 유지하고, OCR 설명에서 붙은 trailing quote만 제거하도록 sanitize 수정
  - 검증: compileall 통과, focused tests 통과, `tests/test_chat_grounding_quality.py tests/test_starter_questions.py tests/test_answer_eval_quality.py tests/test_query_understanding.py` 51개 통과, v012 beginner answer eval 6/6 통과(pass_rate 1.0)
  - 참고: `pbs_chat_quality_extended_cases.jsonl`은 45건 중 pass_rate 0.4667로 아직 낮음. 이번 보강으로 Pod metrics beginner 회귀는 회복됐으나 Route timeout, registry, DNS, NetworkPolicy, CVO/ODF/monitoring 등은 다음 보강 대상
- [x] 사전 작업 Step 2: `spec/v0.1.2/evidence/v012_chunk_quality_before.json`, `spec/v0.1.2/evidence/v012_chunk_quality_before.md`, `spec/v0.1.2/evidence/v012_studio_live_smoke_before.json` baseline 동결
- [x] Phase C Step 13 일부: `spec/v0.1.2/evidence/v012_retrieval_eval_after.json` 생성
  - retrieval eval: 18건, hit@1 0.8889, hit@3 0.9444, hit@5 0.9444, warning_free_rate 1.0
  - landing query: hit@1 0.5, hit@3 0.75, hit@5 1.0. 다음 보강 대상은 landing top1 정렬과 relation-aware miss 1건
- [ ] Phase C Step 13 일부: `spec/v0.1.2/evidence/v012_studio_live_smoke_after.json` 기준 미달
  - 80건 중 47건 pass, pass_rate 0.5875. starter endpoint 502는 `target_anchor` payload 계약 보강으로 해결
  - RBAC `oc auth can-i`와 `oc login` 계열은 intent 우선순위 보강으로 no-answer에서 citation 기반 답변으로 개선
  - 남은 큰 이슈는 ResourceQuota/LimitRange/ImagePullBackOff/finalizer 등 운영 객체 질문에서 command book lock 또는 answer shaping이 엉뚱한 CLI 템플릿을 선택하는 문제
  - 다음 작업은 특정 Q-A 고정이 아니라 intent profile evidence fallback, citation signal matching, answer template selection 순서를 더 일반화하는 방향으로 진행
- [x] Phase A.1 Step 3: context citation excerpt/cli command/section label 내부 markup sanitize
- [x] Phase A.1 Step 4 일부: navigation-only hit 런타임 down-rank 추가(DB 컬럼 없음)
- [x] Phase A.1 Step 10 일부: starter FAQ lane에서 eval JSONL query 직접 노출 제거
- [x] Phase A.1 Step 15 일부: citation section label 노출 전 sanitize 적용
- [x] Phase A.2 Step 11: query_understanding intent 4개 + deterministic cross-lingual rewrite terms 추가
- [x] Phase A.2 Step 12: static concept synonym JSON + concept_expansion 연결(GraphDB 없음)
- [x] Phase A.2 Step 13 코드만: v012 beginner eval JSONL + schema/expansion test scaffold 추가
- [x] Phase B Step 14 일부: official gold chunks parent/leaf 보강 후 Postgres/Qdrant 재색인 완료
  - official gold: leaf 27,907개 + parent 5,815개 = 33,722개
  - official 신규 parent 5,815개 임베딩/색인, 기존 leaf 27,907개 payload refresh 완료
  - KMSC shared study_docs: 기존 523개 + source-scoped synthetic parent 100개 = 623개 import/index 완료
  - course runtime: chunks 523개, assets 775개, manifest 1개 정상 import
  - course Qdrant: `course_pbs_ko` 523개, `course_ops_learning_ko` 100개 upsert
  - DB corpus readiness: official_docs 33,722개, study_docs 1,225개, qdrant_index_parity true
  - `spec/v0.1.2/evidence/v012_chunk_quality_after.json` 생성: row_count 34,263, mojibake_suspect_count 0
  - GitHub 100MB 제한 때문에 보강된 official JSONL 자체는 커밋하지 않고, seed 시 `official-gold-import --enrich-runtime-metadata`로 컨테이너 안에서 재생성하도록 변경
- [x] Phase C Step 13 통과: v012 beginner answer eval 6/6 pass, `spec/v0.1.2/evidence/v012_answer_eval_after.json` 동결
  - answer format: `답변:`뿐 아니라 초보자용 `요약:`도 정상 포맷으로 인정하도록 eval 기준 보정
  - `Service`/`Endpoint`/`Route`, namespace 생성, Deployment YAML, Pod 리소스 확인 질문은 의도 기반 shaping으로 보강
  - Pod 리소스 명령은 공식 CLI 문서 기준 `oc adm top pod` 단수 명령으로 정정
  - 관찰 사항: Service 장애 케이스는 pass 상태지만 provenance noise가 1건 남음(`ingress_and_load_balancing` + 보조 citation). 다음 품질 패스에서 citation 압축/정밀도 개선 대상으로 유지

## 목표

v0.1.0이 RAG 파이프라인의 의도 분석/answer shape/스트리밍을 잡았고, v0.1.1이 추천 질문의 표면 톤을 초보자 어휘로 다듬었다면, v0.1.2는 **답변과 추천 질문이 빈약한 근본 원인인 "청크 데이터 품질"을 정면으로 다룬다.**

PlayBookStudio 사용자는 OCP를 처음 접하는 운영자/개발자이며, 다음과 같이 짧고 자연스러운 질문을 한다.

```text
OCP 설치는 어떻게 해?
Service쪽에서 계속 장애나는데 뭐가 원인일까?
특정 namespace를 만드는 명령어가 뭐야?
ocp에서 배포를 하고 싶으면 무슨 명령어로 해야되더라
보통 배포 yaml파일은 어케 작성하지
특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법
```

ChatGPT 웹 프로젝트에 동일 문서 PDF를 넣었을 때처럼, 짧은 질문에 대해서도 "정의 → 사용 맥락 → 명령어 → 확인 방법 → 다음 분기"가 풀어쓰여 나와야 한다. 현재 시스템에서 답변이 빈약한 이유는 프롬프트나 의도 분류가 아니라, **검색에 걸리는 청크 자체가 너무 작고 markup 오염이 심하며 narrative가 끊겨 있어서**다.

하드코딩된 질문-답변 매핑, 평가셋 query를 그대로 추천 질문에 노출하는 경로, 토픽별 고정 문말 어미 템플릿은 v0.1.2에서도 금지한다.

---

## 원칙

- 청크 metadata와 본문에서 의미를 추출해 자연어를 생성한다. 고정된 토픽-질문 매핑, 토픽-명사 매핑, 토픽-어미 매핑은 금지한다.
- 평가셋(`pbs_chat_quality_cases*.jsonl`, `answer_eval_cases*.jsonl`, `course_qa_cases*.jsonl`)의 `query` 필드를 사용자에게 보이는 추천 질문 표면에 직접 노출하지 않는다.
- 청크 사이즈를 키울 때는 retrieval 품질 회귀를 회피하기 위해 parent-child 구조로 양쪽을 유지한다. (small chunk로 정확히 매칭하고 parent chunk로 LLM에 전달)
- 청크 본문의 internal markup(`[CODE]`, `[/CODE]`, `[TABLE]`, `[/TABLE]`, AsciiDoc residue, OCR 캡션 잔류)은 retrieval-time text와 cli_commands 필드 양쪽에서 제거되도록 ingestion에서 차단한다.
- KMSC 운영 문서 OCR/캡션 nodes-만-나열된 청크는 자동 생성된 풀어쓰기 narrative 1문단을 prepend해서, LLM이 운영자 관점 산문을 만들 재료를 갖도록 한다.
- 한국어 사용자 질의가 영어 위주의 코드/주석 chunk와 연결되도록 cross-lingual term mapping을 query expansion 단계에 보강한다.
- 모든 코퍼스 변경은 reindex 명령으로 멱등 재생산 가능해야 하고, golden eval set 회귀가 없는 것을 검증한다.
- 문자 인코딩은 UTF-8 기준으로 유지한다. Windows 콘솔에서의 표시 깨짐은 데이터 손상이 아니라 콘솔 cp949 인코딩 문제임을 기억한다.

---

## 범위

### Core (P0 - v0.1.2 릴리스 기준)

- [ ] v0.1.2 브랜치 생성 및 planner 작성
- [ ] 청크 품질 baseline 재측정 및 회귀 기준 고정
- [ ] internal markup 누출(`[CODE]`/`[/CODE]` 등) 차단 (ingestion + serving)
- [ ] cli_commands 추출 버그 수정 (`oc\n[/CODE]` 류 제거)
- [ ] 네비게이션-only 청크 식별 및 retrieval down-rank
- [ ] 청크 사이즈 정책 재조정 (procedure/command/troubleshooting/concept)
- [ ] Parent-child 청크 구조 도입 (검색은 small, 전달은 parent)
- [ ] LLM context window 확대 (`max_chunks`, `max_chars_per_chunk`)
- [ ] 인접 청크 자동 동반 (같은 `section_id`, ordinal±1)
- [ ] KMSC course chunk에 beginner narrative 자동 prepend
- [ ] ops_learning_chunks를 KMSC 운영 청크에서 자동 derive하여 18 → 100+ 확장
- [ ] 추천 질문 생성에서 8-토픽 고정 템플릿 제거, 청크 단위 LLM pre-generated 질문 후보로 전환
- [ ] starter_questions FAQ lane의 eval JSONL 직접 query 노출 경로 차단
- [ ] section title이 그대로 추천 질문 surface에 들어가는 경로 normalize
- [ ] `oc auth can-i`, `oc adm top pods`, `oc set resources`, `oc create namespace`, `oc apply -f` 등 자주 쓰는 명령에 대한 retrieval 안정성 회복
- [ ] cross-lingual query expansion 보강 (`yaml`, `deployment`, `리소스 사용량` → 영어 keyword 동반)
- [ ] Service 장애 / Deployment YAML 작성 / Pod 리소스 확인 intent 추가
- [ ] 개념 동의어/인접 사전 JSON으로 query expansion 보강: Pod-Service-Endpoint-Route, Deployment-ReplicaSet-Pod, Secret/ConfigMap-Volume-envFrom 등 인접 개념 term 확장 (GraphDB 미사용, VectorDB + 사전 JSON만 사용)
- [ ] retrieval 실패 회귀 case를 v0.1.2 eval set에 추가하고 통과시키기
- [ ] studio_live_smoke pass rate 0.66 → 0.85 이상으로 회복
- [ ] backend focused tests 통과
- [ ] frontend production build 통과
- [ ] Playwright로 6개 대표 초보자 질문 시나리오 smoke 검증
- [ ] OCP 배포 환경 재배포 후 smoke 검증 (v0.1.1에서 이월된 항목 포함)

### Extras (P1 - 가능하면 포함)

- [ ] LLM 기반 청크 quality scorer (정보량/명확성/완결성) 도입
- [ ] 청크별 "초보자 친화 풀어쓰기" 자동 생성 (concept/overview 청크에 prepend)
- [ ] 동적 추천 질문에 사용자 세션 history를 반영한 난이도 가중치
- [ ] 답변 평가용 golden set을 6개 초보자 대표 질문 시나리오로 확장
- [ ] 응답 품질 회귀 테스트를 Playwright smoke와 연결
- [ ] retrieval trace를 chat_turns에 더 풍부하게 저장하여 품질 분석 강화
- [ ] 개념 동의어 사전을 활용한 인접성 기반 score 가중치 (reranker가 아니라 BM25/vector hit의 후처리 boost)

### 비범위 (v0.1.3 이후)

- 공식 문서 PDF/HTML의 전면 재OCR/재파싱
- 모든 KMSC 문서를 LLM으로 재요약하여 청크 본문 자체를 재생성
- Cross-encoder reranker의 finetune
- 외부 RAG SaaS와의 hybrid 비교 평가
- GraphDB(Neo4j 등) 도입, 완전한 ontology DSL 정의, KGQA 스타일 검색

---

## 단계 그룹화 (Phase 분리)

v0.1.2는 RAG 데이터 계층 재구축 릴리즈이며, 청크 스키마와 검색 인덱스가 함께 바뀐다. 그러나 모든 작업의 위험도가 같지는 않다. **재색인이 필요한 작업과 그렇지 않은 작업, 그리고 사용자 가시 클린업과 retrieval 보강을 분리하여 5개 PR을 가진 4개 phase로 묶고**, A.1 → A.2 → B → C → D 순서로 진행한다.

PR 분리의 핵심 원칙은 **"코드 머지 시점"과 "eval 통과 검증 시점"을 분리**한다는 것이다. retrieval 보강 코드(intent 추가, concept synonym, cross-lingual rewrite, v012 eval JSONL 파일 자체)는 Phase A.2에서 일찍 머지되어 Phase B 재색인 전후 회귀 비교의 기준선이 되고, "v012 6개 통과" 선언은 Phase B 재색인 이후 Phase C에서만 한다.

| Phase | PR | 내용 | 재색인 | 사용자 가시성 | 평가 기준 |
|---|---|---|---|---|---|
| **A.1** | PR #1 | markup/command sanitize + FAQ lane eval JSONL 노출 차단 + nav-only chunk 런타임 휴리스틱 down-rank (DB 컬럼 추가 없음) | X | 즉시: `oc [/CODE]` 잔류 제거, 평가셋 question 노출 차단, nav-only 단독 인용 감소 | studio_live_smoke 회귀 없음 |
| **A.2** | PR #2 | query_understanding intent 4개 추가 + concept synonym JSON 사전 + cross-lingual rewrite + v012 beginner eval JSONL 파일 추가 (통과 검증은 미실시) | X | retrieval term 확장, eval set만 정의 | retrieval eval 회귀 없음, v012 통과 여부는 측정만 하고 gate 아님 |
| **B** | PR #3 | chunk size 정책 + parent-child emit + navigation_only DB 컬럼 영구화 + LLM context 확대 + KMSC beginner_narrative + ops_learning auto-derive + chunk question candidates 사전 생성 + starter_questions/follow-up 재설계 → **한 번에 재색인 1회** | O (1회) | 답변 깊이/길이 증가, 추천 질문 다양화/회전, 운영 답변 narrative 확장 | studio_live_smoke pass rate ≥ 0.85, 청크 품질 baseline 회귀 비교 |
| **C** | PR #4 또는 리포트 | v012 beginner 6개 통과 + 회귀 비교 리포트 + 필요 시 query/synonym tune | X | retrieval 정확도, 짧은 자연어 질문 대응 확정 | v012 6개 모두 통과 |
| **D** | 운영 | Playwright smoke + OCP rollout + live smoke + v0.1.1 잔여 (terminal paste/wrap) | X | 최종 사용자 검증 | live smoke 통과 |

Step 1-16과의 매핑:

```text
사전 작업 (모든 Phase 시작 전)
  Step 1   v0.1.2 브랜치 + planner 확정
  Step 2   v012_chunk_quality_before 등 baseline 리포트 동결

Phase A.1  (PR #1, 재색인 없음, 사용자 가시 클린업)
  Step 3   internal markup / cli_commands sanitize
  Step 4 일부   navigation_only를 retrieval 후처리에서 런타임 휴리스틱으로 down-rank
                (이 단계에서는 DB 컬럼 추가하지 않고 chunking.py 메모리 플래그 또는
                 score_postprocess.py 패턴 매칭만으로 처리)
  Step 10 일부  starter_questions FAQ lane의 평가셋 JSONL 직접 query 노출 분기 제거
                (chunk pool 기반 sampling으로 전환하기 전 단계로, 기존
                 _compose_beginner_question fallback에 임시 의존)
  Step 15 일부  session_flow의 section title 노출 정리(_clean_subject_title 통과 후만 사용)

Phase A.2  (PR #2, 재색인 없음, retrieval add-on 코드 머지)
  Step 11      query_understanding intent 4개 추가 (deployment_yaml_authoring,
                pod_resource_inspection, service_failure_diagnosis, namespace_create)
                + retrieval term 보강 + cross-lingual rewrite (deterministic 규칙)
  Step 12      concept synonym JSON 사전(ocp_concept_synonyms_v1.json) 신규 추가 +
                retrieval/concept_expansion.py 신규 + query.py에 expand 결과 merge
  Step 13 코드만   pbs_chat_quality_v012_beginner_cases.jsonl 파일과
                tests/test_answer_quality_v012_beginner.py 스켈레톤 추가
                (통과 단정은 하지 않고, 현재 fail/pass 분포만 기록)

Phase B  (PR #3, 단일 PR로 묶음, 끝에 재색인 1회)
  Step 4 마저  navigation_only를 DB 컬럼으로 영구화하고 인덱스 추가
                (A.1의 런타임 휴리스틱과 동일 규칙 공유, 결과 차이 0 확인)
  Step 5       chunk size 정책 재조정 + parent-child emit
  Step 6       max_chunks/max_chars_per_chunk 확대
  Step 7       KMSC beginner_narrative pre-generation
  Step 8       ops_learning_chunks auto-derive (18 → 100+)
  Step 9       chunk.starter_question_candidates / followup_question_candidates 사전 생성
  Step 10 마저 starter_questions/session_flow를 chunk 후보 pool 기반으로 재설계
                (A.1에서 임시 의존한 _compose_beginner_question fallback을 격하)
  Step 14      전체 재청킹/재색인 (공식 + KMSC, Qdrant + Postgres)

Phase C  (PR #4 또는 리포트, 재색인 없음, eval 통과 검증)
  Step 13 통과 v012 beginner 6개 eval case 통과 단정 활성화
  회귀 비교    spec/v0.1.2/evidence/v012_studio_live_smoke_after.json,
                v012_retrieval_eval_after.json, v012_answer_eval_after.json 생성
  필요 시 tune   concept synonym 누락, intent 매치 누락, chunk question candidate
                품질 문제 발견 시 작은 follow-up PR로 보강

Phase D  (배포 단계)
  Step 15      UI/Playwright smoke
  Step 16      OCP rollout + live smoke (v0.1.1 이월 항목 포함)
```

원칙:

- **PR 분리의 핵심은 회귀 측정 단위 분리.** A.1 머지 후 measure → A.2 머지 후 measure → B 머지 후 measure 흐름을 만들어 각 변경의 효과를 독립적으로 본다.
- Phase B는 **중간 partial deploy 금지**. parent-child emit과 question candidates 생성, starter_questions 재설계 중 일부만 배포되면 검색기와 답변/추천 질문이 일관성을 잃는다. 코드 + 재색인 + DB 마이그레이션을 한 PR에 묶고, dev 환경에서 재색인까지 끝낸 뒤에 머지한다.
- A.1에서 nav-only down-rank는 휴리스틱(체크: line ≤ 2, body token < 60, chunk_type=reference, "이 문서에서는 X를 다룹니다" 패턴)으로만 처리한다. Phase B에서 DB 컬럼으로 승격될 때 휴리스틱 동작 결과와 차이가 발생하지 않도록 동일 규칙을 공유하고, 차이 0를 테스트로 확인한다.
- A.2의 cross-lingual rewrite와 synonym expansion은 retrieval add-on이며, 원본 한국어 query는 항상 BM25 입력으로 유지한다. A.2 머지 직후에는 v012 6개 통과를 강제하지 않는다(작은 청크 상태로는 narrative 깊이가 부족해 일부 케이스가 자연스럽게 fail로 측정될 수 있다).
- Phase C는 신규 기능 PR이라기보다 **"Phase B 결과를 v012 6개 기준으로 통과 단정하고 회귀 리포트를 동결하는 단계"** 다. 통과 실패 시 작은 follow-up PR로만 보강하고, 큰 청크 정책 재변경은 v0.1.3으로 이월한다.
- 각 Phase 시작 전에 이전 Phase의 회귀 평가(retrieval eval, answer eval, studio_live_smoke)를 통과해야 한다. 실패 시 다음 Phase로 넘어가지 않는다.
- v0.1.2 최종 릴리즈는 Phase D 완료 시점이며, Phase A.1·A.2·B·C 각각이 단독으로는 v0.1.2 릴리즈로 간주되지 않는다.

---

## 배경: v0.1.0/v0.1.1 분석 결과 요약

v0.1.0/v0.1.1에서 다듬어진 영역은 다음과 같다.

- `answering/prompt.py`: install_overview, secret_config_troubleshooting, troubleshooting, command_lookup, RBAC, drain, scale, Pod Pending, CrashLoopBackOff, Pod lifecycle, Operator, MCO 등 12+ intent별 answer shape hint가 잘 정리되어 있다.
- `retrieval/query_understanding.py`: OCP↔OpenShift, install, command, troubleshooting, secret_config, namespace 6개 intent 정규화가 들어 있다.
- `http/starter_questions.py`: STARTER_CATEGORY_RULES 8개 카테고리를 청크/manifest에서 매칭해 초보자 자연어 질문으로 변환한다.

그러나 v0.1.1까지의 작업으로도 다음 문제는 남는다.

### 1. 청크가 너무 작고 markup이 오염되어 있다

공식 코퍼스(27,907 청크) 실측:

| 항목 | 값 |
|---|---|
| token_count p50/p90/p95/max | 181 / 219 / 229 / 363 |
| char count p50/p90/max | 436 / 659 / 1305 |
| 헤더 prefix(book_title + section_path) 비중 | ≈ 50 token |
| 실제 body 크기 | 48~130 token (한글 ~120~330자) |
| procedure/command/troubleshooting 본문 token 상한 | `chunk_profile_for_section`에서 128 token |
| concept/overview 본문 token 하한 | 192 token (실제 p90도 207) |

v007 audit (`spec/v0.0.7/evidence/v007_official_chunk_quality_baseline.md`) 기준 다음과 같은 이슈가 이미 카운트되어 있다.

```text
raw_code_markup            14,508 (52%)
high_latin_ratio_ko_chunk   8,406 (30%)
command_dense_chunk         7,927
code_plus_navigation          358
oversized_chunk               313
mixed_procedure_navigation    150
```

KMSC course (`spec/v0.0.7/evidence/v007_user_study_chunk_quality_baseline.md`):

```text
token p50/p90/max = 25 / 62 / 125
undersized_chunk = 160  (전체 523개 중 31%)
```

→ KMSC 청크는 슬라이드 1장당 1청크인데, 본문이 OCR/캡션 entity 나열뿐이어서 산문 narrative가 거의 없다.

### 2. internal markup이 cli_commands / suggested queries / answer로 누출된다

`ingestion/chunking.py` 가 `render_internal_markup_for_retrieval`로 `[CODE]`/`[TABLE]`을 markdown으로 변환하지만, 본문 일부에 `oc\n[/CODE]` 같은 깨진 토막이 남아 cli_commands 필드에 들어간다.

`answering/context.py:118 _citation_cli_commands`는 hit.cli_commands(오염됨)와 `_commands_from_excerpt(excerpt)`를 merge한다. 그래서 추천 질문에 다음과 같은 문장이 그대로 노출된다.

```text
`oc [/CODE]` 명령은 언제 쓰면 돼?
`oc [/CODE]` 결과에서 무엇을 확인해야 해?
`oc debug node/${NODE} -- chroot /host /bin/bash -c 'rm -f /var/lib/ovn-ic/etc...` 명령은 언제 쓰면 돼?
```

(`spec/v0.1.2/evidence/studio_live_smoke_report.json`에서 실측. `case_id: starter:faq:0`, `ops-answer-001`)

### 3. 네비게이션-only 청크가 retrieval을 오염시킨다

`chunk_type=reference`이면서 token_count<150, 라인 4줄 이하인 청크가 421개. 이들은 본문이 "BookTitle\nSection Path\n\n이 문서에서는 X를 다룹니다." 1문장뿐이다. retrieval에서 BM25 정확 매치가 일어나면 LLM에 빈 헤더만 전달된다.

studio_live_smoke `starter:faq:1`("What should I check first in 고급 네트워킹?") → citation은 `advanced_networking` "OpenShift Container Platform의 전문화된 고급 네트워킹 주제" 챕터 intro만 잡힘 → 답변이 "구체적인 점검 대상이 무엇인지 확인이 필요합니다." 로 빠진다.

### 4. 한국어 질의가 영어 코드 위주 chunk와 연결되지 않는다

`oc auth can-i` 관련 청크는 5개 존재하지만, 본문이 영어 주석(`# Check to see if I can create pods in any namespace`)과 영어 명령으로 채워져 있다. 한국어 질의 "특정 사용자가 namespace에서 pods를 delete할 수 있는지 확인하는 명령은?"이 들어오면 BM25는 keyword 매치 부족으로 빠지고, vector도 cross-lingual을 충분히 못 한다.

studio_live_smoke `pbs-ext-rbac-can-i-001` → citation 0개, "현재 Playbook Library에 해당 자료가 없습니다." 응답.

### 5. 추천 질문이 사실상 8개 토픽 × 고정 어미 템플릿이다

`http/starter_questions.py`의 generation chain:

```text
STARTER_CATEGORY_RULES                    8개 고정 카테고리
_starter_topic_terms                      13개 키워드 if-elif 버킷
_beginner_subject_from_context            토픽별 하드코딩 한국어 명사
_compose_beginner_question                토픽 + lane 조합 → 하드코딩 어미
```

청크가 100개든 500개든 추천 질문 표면은 ≈ 40가지 변주에 갇힌다.

FAQ lane은 한 발 더 나아가 `PBS_CHAT_QUALITY_CASES_PATH`/`ANSWER_EVAL_CASES_PATH`에서 평가셋 `query`를 그대로 사용자 화면에 노출한다 (`starter_questions.py:160-189`). 이는 v0.1.0/v0.1.1의 "하드코딩 금지" 원칙에 위배된다.

### 6. follow-up 추천 질문도 section title을 그대로 surface로 쓴다

`http/session_flow.py:520-529`:

```text
"{section} 기준으로 다음 확인 단계는 뭐야?"
"{section} 절차에서 흔한 실패 지점은 뭐야?"
"{section} 내용을 초보자용 3단계로 다시 정리해줘"
```

`{section}`이 "OpenShift Container Platform의 전문화된 고급 네트워킹 주제"처럼 길고 운영자 용어가 그대로 들어가면 초보자 어조가 깨진다.

### 7. ops_learning_chunks가 18개에 그친다

KMSC course chunk는 523개인데 ops_learning은 18개 manifest 청크에서 회전한다. operations lane이 항상 비슷한 운영 질문만 보이는 1차 원인.

### 8. studio_live_smoke 실측 실패 분포 (80 케이스, pass=53)

```text
command_query_missing_grounded_command   6  명령 질문인데 명령 미인용
low_confidence_for_seeded_question       6  추천 질문이 low-conf로 막힘
unexpected_clarification                 6  clarification으로 회피
missing_citation_term:* (다양)           20+ 정확한 keyword 청크 미인용
missing_required_term:* (다양)           10+ 답변 본문에 핵심 term 미포함
answer_code_not_visible_in_citations     1
```

→ 모두 청크 quality와 retrieval 정확도의 문제로 환원된다.

---

## 아키텍처 방향

### 1. Ingestion 단계: 청크 본문과 metadata를 정제한다

```text
canonical section
    ↓ chunk_sections (chunking.py)
    ↓
1. internal markup 잔류 청소 (현재 render만 하고 잔류 토막 미정리)
    [/CODE], [/TABLE], 닫는 태그 단독 라인, 빈 [CODE language=""] 빈 본문 토막 제거
2. cli_commands 필드 sanitize
    canonical/command_split.py 통과시키고, [/CODE]/[/TABLE] suffix 제거
    빈 oc/kubectl 단독 명령은 cli_commands에서 제외
3. navigation_only flag 추가
    body 라인 수 ≤ 2, 본문이 "이 문서에서는 X를 다룹니다" 패턴이면 chunk.metadata.navigation_only=true
    retrieval-time에서 down-rank 또는 제외
4. high_latin_ratio_ko_chunk에 visible_terms_ko 보강
    영어 keyword에 대응하는 한국어 동의어를 chunk.search_text에 부가하여 BM25 매치 회복
5. KMSC OCR/캡션 청크에 beginner_narrative 1문단 자동 prepend
    chunk.text의 OCR/캡션 dump 앞에 LLM 또는 deterministic generator로 만든 운영자 관점 산문 추가
6. ops_learning_chunks 자동 derive
    523개 course chunk 중 procedure/troubleshooting/design_summary에서 100~200개 ops_learning을 자동 생성
```

### 2. Chunking 정책 재조정

`config/corpus_policy.py`:

```text
현재:
  procedure/command/troubleshooting   chunk_size 상한 128 token, overlap 16
  concept/overview                    chunk_size 하한 192 token

v0.1.2 (제안):
  procedure/command/troubleshooting   chunk_size 상한 256 token, overlap 32
  concept/overview                    chunk_size 320~512 token, overlap 32
  reference                           chunk_size 240 token 유지
  reference-heavy (apis 등)            240 token 유지
  navigation_only                     chunk_size 무시 (제거 대상 후보)
```

단, 사이즈만 키우면 BM25 retrieval 정확도가 떨어질 수 있으므로 다음 parent-child 구조와 함께 적용한다.

### 3. Parent-child chunking

```text
section
  ├── small_chunk_1   (검색용, 96~128 token)
  ├── small_chunk_2
  ├── small_chunk_3
  └── parent_chunk    (전달용, 384~768 token, small_chunks의 합)
```

- BM25/vector retrieval은 small_chunk와 parent_chunk 모두 색인
- assemble_context는 small_chunk hit을 받으면 같은 parent_chunk_id의 본문을 LLM에 전달
- 단일 small_chunk가 너무 좁은 경우 인접 small_chunk(ordinal±1)도 함께 전달
- 코드 변경 위치: `ingestion/chunking.py` (parent emit), `answering/context.py:_select_hits` (parent 우선 dedup)

### 4. Serving 단계: LLM context를 넓힌다

`answering/context.py:assemble_context`:

```text
현재 max_chunks=6, max_chars_per_chunk=900
v0.1.2: max_chunks=8, max_chars_per_chunk=2000 (or parent_chunk면 자동 1800)
```

`MAX_PROMPT_CLI_COMMANDS=4`는 유지하되 internal markup 잔류는 차단한다.

### 5. Beginner narrative pre-generation

KMSC OCR/캡션 청크에 대해 다음을 사전 1회 실행해 청크 본문 앞에 prepend한다.

```text
input: chunk.text (OCR + caption + 도식 entity 나열)
       + chunk.title
       + chunk.learning_goal (있을 때)
       + chunk.source_terms
       + chunk.image_evidence
output:
  beginner_narrative: 4~6문장 운영자 관점 산문
    - 이 슬라이드/문서가 다루는 영역
    - 핵심 구성 요소 2~3개와 책임
    - 운영자가 화면에서 무엇을 봐야 하는지
    - 다음에 이어지는 운영 흐름
```

생성기는 LLM 호출이고, 출력은 chunk.text에 prepend되어 BM25/vector 양쪽에 재색인된다. 하드코딩이 아니라 청크 본문에서 파생되며, 출력은 운영자가 사용자에게 설명하는 톤으로 고정한다.

### 6. ops_learning_chunks 자동 확장

`ingestion/kmsc_course_import.py`(또는 신규 derive 스크립트)에서 다음 룰로 자동 derive.

```text
trigger: chunk.kind in {design_summary, procedure, troubleshooting} AND chunk.image_attachments 또는 source_terms 충분
output: ops_learning_chunk_v1 1개
  - guide_id          상위 stage_id에서 파생
  - step_id           슬라이드 시퀀스 또는 chapter ordinal
  - audience          beginner_operator
  - learning_goal     LLM 또는 deterministic compose
  - operational_sequence  OCR/캡션에서 절차/항목 lines 추출
  - what_to_look_for       source_terms + image instructional_role
  - query_variants    5개, LLM이 청크 본문에서 합성
```

목표: 18 → 100~200개. starter_questions operations lane은 이 후보 풀에서 sampling하면 회전성과 다양성이 즉시 살아난다.

### 7. 추천 질문 재설계 (질문 풀 분리)

기존 `starter_questions.py` 흐름을 다음으로 바꾼다.

```text
모든 retrieval-eligible chunk에 대해 사전 1회:
  chunk.starter_question_candidates  list[str]   (LLM pre-generated, 1~3개)
    "이 청크를 본 초보자가 짧고 자연스럽게 가장 먼저 물을 자연어 질문"
    OCP/KMSC 운영 어휘 어디까지 노출할지는 prompt로 통제

  chunk.followup_question_candidates list[str]   (cli_commands/section/learning_goal에서 파생)
    "이 청크의 결과를 본 사용자가 이어서 물을 후속 질문"

starter_questions API:
  lane=faq          official 청크 sampling, score 가중치
  lane=learning     learning_path 또는 manifest section 청크 sampling
  lane=operations   ops_learning_chunks(자동 확장된 100~200개) sampling
  seed로 회전
  토픽-어미 고정 템플릿 제거, 후보 자체를 그대로 표면화
```

`STARTER_CATEGORY_RULES`, `_starter_topic_terms`, `_beginner_subject_from_context`, `_compose_beginner_question`은 fallback 전용으로 격하하고, 기본 경로는 chunk.starter_question_candidates 사용으로 변경한다.

`session_flow.py`의 follow-up 템플릿도 chunk.followup_question_candidates를 우선 사용한다. cli_commands 기반 fallback은 section/cli sanitize 통과 후에만 적용한다.

### 8. starter_questions FAQ lane: 평가셋 query 노출 차단

`starter_questions.py:160-189`의 `PBS_CHAT_QUALITY_CASES_PATH`/`ANSWER_EVAL_CASES_PATH` 직접 query 노출 분기를 제거한다. DB 부재 fallback도 chunk.starter_question_candidates 풀에서 sampling하도록 통일한다.

평가셋 JSONL은 v0.1.2에서도 retrieval/answer eval 입력으로만 쓰이며, 사용자 화면에는 노출되지 않는다.

### 9. Query Understanding 확장

`retrieval/query_understanding.py`에 다음 intent를 추가한다.

```text
deployment_yaml_authoring
  매치: 배포|deployment|yaml|매니페스트|manifest + 작성|생성|만들|create
  retrieval_terms: Deployment, kind: Deployment, oc create -f, oc apply -f,
                   spec.template, replicas, selector, apiVersion: apps/v1

pod_resource_inspection
  매치: pod + 리소스|cpu|메모리|memory|사용량|점유|usage
  retrieval_terms: oc adm top pods, oc top pod, metrics-server, requests, limits

service_failure_diagnosis
  매치: service + 장애|문제|안 됨|연결 안 됨|접속 안|fail
  retrieval_terms: Service, Endpoint, EndpointSlice, selector, oc get endpoints,
                   oc describe svc, port/targetPort, Route, headless service

namespace_create
  매치: namespace|네임스페이스|project + 만들|생성|create
  retrieval_terms: oc new-project, oc create namespace, kind: Namespace
```

기존 intent도 retrieval_terms를 보강한다. (예: command_lookup이면 OCP CLI 4.20 명령군과 일반 oc verb를 모두 노출)

### 10. 개념 동의어/인접 사전 기반 query expansion 보강

GraphDB(Neo4j 등)나 별도 그래프 인프라는 도입하지 않는다. 검색의 메인 경로는 v0.1.0/v0.1.1과 동일하게 BM25(Postgres) + Vector(Qdrant) hybrid이며, v0.1.2에서는 정적 JSON 사전 한 개로 query expansion만 보강한다.

`retrieval/graph_runtime.py`는 기존에 sidecar JSON에서 book 간 관계 metadata를 lookup해 retrieval hit에 부가하는 보조 레이어로만 동작하고 있으며 (graph_backend 기본값 `local`, Neo4j는 옵션, 현재 `.env`에 graph 관련 설정 0개), v0.1.2 작업 범위에서는 이 모듈을 확장하지 않고 그대로 둔다.

대신 다음 신규 JSON 사전을 도입한다.

```text
corpus/manifests/concepts/ocp_concept_synonyms_v1.json
```

이 사전에는 다음 25개 정도의 핵심 OCP 개념만 정의한다.

```text
Pod, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, CronJob
Service, Endpoint, EndpointSlice, Route, Ingress
Namespace, Project
Secret, ConfigMap, ServiceAccount, Role, RoleBinding, ClusterRole, ClusterRoleBinding
PV, PVC, StorageClass, VolumeMount
Node, MachineSet, MachineConfig, MachineConfigPool, ClusterOperator
oc, kubectl, openshift-install
```

각 항목은 다음 필드만 가지며, "노드" 같은 그래프 용어는 쓰지 않는다.

```text
concept_id        (e.g. ocp:resource:Service)
display_name_ko   "Service / 서비스"
synonyms          ["svc", "서비스", "Service"]   # 정규식 매칭용
adjacent_terms    ["Endpoint", "EndpointSlice", "Route", "Pod selector",
                   "oc describe svc", "oc get endpoints"]   # query에 추가할 검색어
```

query에 synonym 매치가 일어나면 adjacent_terms를 retrieval terms에 단순 append한다. 예: "Service쪽 장애" → Service + Endpoint + Route + Pod selector + oc describe svc.

구현은 순수 JSON 로딩 + 정규식 매칭 + list extend로 끝낸다. graph 자료구조, 인접 행렬, 트래버설 알고리즘 같은 것은 도입하지 않는다. v0.1.3 이후에도 GraphDB 도입은 비범위로 유지하며, 사전 규모가 커지면 같은 JSON에 항목을 추가하는 방식으로 확장한다.

### 11. Eval 회귀 case 추가

`corpus/manifests/eval/pbs_chat_quality_cases.jsonl` 또는 신규 `pbs_chat_quality_v012_beginner_cases.jsonl`에 다음 6개를 추가하고 통과시킨다.

```text
v012-beginner-001  "OCP 설치는 어떻게 해?"
  expected_book_slugs: [installation_overview, installing_on_any_platform]
  must_include_terms: [Assisted Installer, IPI, UPI, 또는 설치 방식]
  must_show_structure: [정의, 방식 비교, 추천, 준비물, 흐름, 확인 명령]

v012-beginner-002  "Service쪽에서 계속 장애나는데 뭐가 원인일까?"
  expected_book_slugs: [networking_overview, ingress_and_load_balancing, support]
  must_include_terms: [Endpoint, selector, oc describe, oc get endpoints]

v012-beginner-003  "특정 namespace를 만드는 명령어가 뭐야?"
  expected_book_slugs: [authentication_and_authorization, tutorials, cli_tools]
  must_include_terms: [oc new-project, 또는 oc create namespace]

v012-beginner-004  "ocp에서 배포를 하고 싶으면 무슨 명령어로 해야되더라"
  expected_book_slugs: [building_applications, cli_tools]
  must_include_terms: [oc new-app, 또는 oc apply -f, 또는 oc create -f]

v012-beginner-005  "보통 배포 yaml파일은 어케 작성하지"
  expected_book_slugs: [building_applications, applications]
  must_include_terms: [Deployment, apiVersion, spec, replicas]
  must_show_yaml_block: true

v012-beginner-006  "특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법"
  expected_book_slugs: [support, monitoring]
  must_include_terms: [oc adm top pod, 또는 oc top pod]
```

이 6개가 통과하면 사용자가 ChatGPT에 PDF 넣고 받는 답변 품질에 근접한다고 보고, baseline으로 동결한다.

---

## 구현 계획

### Step 1. v0.1.2 작업 기준 확정

- `feat/v0.1.2/chunk-quality-rebuild` 브랜치 생성
- `spec/v0.1.2/planner.md` 작성 (이 문서)
- UTF-8 기준 유지
- 작업 메모를 planner에 누적

### Step 2. 청크 품질 재측정 baseline 동결

```text
output:
  spec/v0.1.2/evidence/v012_chunk_quality_before.json
  spec/v0.1.2/evidence/v012_chunk_quality_before.md
  spec/v0.1.2/evidence/v012_studio_live_smoke_before.json

측정 항목:
  공식/KMSC 청크 수, token 분포, raw_code_markup, high_latin_ratio,
  navigation_only, oversized, mixed_procedure_navigation
  studio_live_smoke pass rate
  retrieval miss rate (eval set 기준)
```

`src/play_book_studio/ingestion/corpus_quality_audit.py`를 확장해 navigation_only 카운터, ko_visible_term_count, parent_chunk_id 충족율을 측정한다.

### Step 3. internal markup 잔류 차단

수정 파일:

```text
src/play_book_studio/ingestion/internal_markup.py
  - render_internal_markup_for_retrieval 출력에 남은 [/CODE]/[CODE 단독 토막 제거
  - empty body code block 자체 제거
  - language 미지정 빈 body 제거
src/play_book_studio/answering/context.py:_trim_command_candidate
  - " [/CODE]" 외에 "\n[/CODE]", "[/CODE]" suffix 모두 제거
  - 명령 길이 1글자(예: "oc")이고 인자 없으면 cli_commands에서 제외
src/play_book_studio/answering/context.py:_commands_from_excerpt
  - 정규식이 lookahead로 [/CODE] 직전까지만 캡처하도록 수정
  - 캡처 후 trailing `]`/`[/`로 끝나면 reject
src/play_book_studio/canonical/command_split.py
  - oc/kubectl/openshift-install 단독 토큰은 명령으로 인정하지 않음
src/play_book_studio/ingestion/metadata_extraction.py
  - cli_commands 저장 전 [/CODE] 류 sanitize
```

테스트: `tests/test_internal_markup_sanitize.py` 신규 추가.

### Step 4. 네비게이션 청크 식별 및 down-rank

수정 파일:

```text
src/play_book_studio/ingestion/chunking.py
  - chunk.metadata.navigation_only = true 플래그 부착
  - 룰: body 라인 ≤ 2 AND body token < 60 AND chunk_type == reference
  - "이 문서에서는 X를 다룹니다" 패턴이면 navigation_only

src/play_book_studio/db/migrations/00XX_chunk_navigation_flag.sql
  - chunk 테이블에 navigation_only boolean 컬럼 추가
  - 인덱스: WHERE navigation_only = false

src/play_book_studio/retrieval/scoring_postprocess.py
  - navigation_only=true 청크는 -0.3 score penalty
  - cited 청크 list에서 navigation_only는 다른 대안이 있으면 제외
```

테스트: `tests/test_navigation_only_chunk_filter.py`.

### Step 5. 청크 사이즈 정책 재조정 및 parent-child emit

수정 파일:

```text
src/play_book_studio/config/corpus_policy.py
  - procedure/command/troubleshooting 상한 128 → 256
  - concept/overview 하한 192 → 320, 권장 512
  - overlap 16 → 32

src/play_book_studio/ingestion/chunking.py
  - chunk_sections이 small_chunks와 parent_chunk를 모두 emit
  - ChunkRecord에 parent_chunk_id, child_chunk_ids 필드 채움
  - parent_chunk.text = "\n\n".join(child.text without prefix repeat)
  - parent_chunk.chunk_role = "parent"
  - child.chunk_role = "leaf"

src/play_book_studio/ingestion/qdrant_store.py
  - parent와 leaf 모두 색인
  - leaf만 vector 검색, parent도 별도 lane

src/play_book_studio/retrieval/scoring.py
  - leaf hit이 들어오면 retrieval result에 parent_chunk_id 함께 표기

src/play_book_studio/answering/context.py:_select_hits
  - leaf hit을 받으면 parent_chunk로 confirm 후 parent 본문을 LLM에 전달
  - 단일 leaf인 경우 인접 leaf(ordinal±1)도 묶어서 전달
```

테스트: `tests/test_parent_child_chunk.py`, `tests/test_parent_chunk_promotion.py`.

DB 마이그레이션: `db/migrations/00XX_parent_child_chunks.sql`.

### Step 6. LLM context 확대

수정 파일:

```text
src/play_book_studio/answering/context.py:assemble_context
  - max_chunks 6 → 8
  - max_chars_per_chunk 900 → 2000
  - parent chunk가 전달되면 chunk별 1800 char cap

src/play_book_studio/answering/answerer.py
  - assemble_context 호출 인자 갱신
  - 토큰 예산 추정 헬퍼에 새 상한 반영
```

테스트: `tests/test_context_size_budget.py`.

### Step 7. KMSC beginner narrative pre-generation

신규 파일:

```text
src/play_book_studio/ingestion/kmsc_beginner_narrative.py
  - input: ops_learning chunk 또는 kmsc course chunk
  - output: 4~6문장 한국어 운영자 narrative
  - LLM 호출 후 deterministic post-process로 외부 용어/누락 fallback 처리
  - 생성된 narrative는 chunk.text에 prepend되어 재색인된다

scripts/regenerate_kmsc_narratives.py
  - 멱등 재실행 가능한 CLI
  - --force, --dry-run, --slug, --stage 옵션
```

ops_learning_chunks_v1.jsonl을 재생성하고, KMSC 청크 metadata에 `beginner_narrative_version`을 기록한다.

테스트: `tests/test_kmsc_beginner_narrative.py`.

### Step 8. ops_learning_chunks 자동 확장 (18 → 100+)

수정 파일:

```text
src/play_book_studio/ingestion/kmsc_course_import.py
  - chunk.kind in {design_summary, procedure, troubleshooting}이면 ops_learning derive
  - 같은 stage_id 내에서 ordinal 순으로 next_step_ids 자동 연결
  - query_variants는 LLM이 chunk 본문에서 합성

src/play_book_studio/course/learning_path_seed.py
  - 확장된 ops_learning을 learning_path/learning_step에 seed
  - 기존 18개 manifest seed는 reserved/curated 후보로 유지하되 별도 stage 분리
```

테스트: `tests/test_ops_learning_auto_derive.py`, `tests/test_course_ops_learning.py` 보강.

### Step 9. 청크별 starter/followup 질문 후보 사전 생성

신규 파일:

```text
src/play_book_studio/ingestion/chunk_question_candidates.py
  - input: chunk + metadata
  - output:
      starter_question_candidates: list[str]   (1~3)
      followup_question_candidates: list[str]  (2~4)
  - prompt 원칙:
      OCP 운영자 용어는 사용자가 그 자체로 이해할 수 있는 것만 노출
      Day-2 같은 내부 단계명은 풀어쓰기
      청크의 cli_commands가 있으면 "왜 쓰는지/언제 쓰는지/결과는 어떻게 보는지" 후속

scripts/regenerate_chunk_question_candidates.py
  - 멱등 재실행 가능한 CLI

DB migration:
  db/migrations/00XX_chunk_question_candidates.sql
    chunk_starter_candidates(text[])
    chunk_followup_candidates(text[])
    chunk_question_candidates_version int
```

테스트: `tests/test_chunk_question_candidates.py`.

### Step 10. starter_questions 재설계 (8-토픽 고정 템플릿 제거)

수정 파일:

```text
src/play_book_studio/http/starter_questions.py
  - 기본 경로: chunk.starter_question_candidates pool에서 lane별 sampling
  - lane=faq           public/official 청크 중 high-quality 후보
  - lane=learning      learning_path 또는 stage_id 기준
  - lane=operations    ops_learning_chunks(auto-derived) 후보
  - STARTER_CATEGORY_RULES와 _compose_beginner_question은 fallback only
  - eval JSONL 직접 query 노출 분기 제거

src/play_book_studio/http/session_flow.py
  - follow-up도 chunk.followup_question_candidates 우선
  - cli_commands template fallback은 sanitize 통과 후
  - section title fallback은 _clean_subject_title을 통과한 결과만
```

테스트: `tests/test_starter_questions.py`, `tests/test_starter_questions_readable.py`, `tests/test_followup_suggestions.py` 보강.

### Step 11. Query Understanding & Cross-lingual 확장

수정 파일:

```text
src/play_book_studio/retrieval/query_understanding.py
  - intent 추가: deployment_yaml_authoring, pod_resource_inspection,
                service_failure_diagnosis, namespace_create
  - 각 intent의 retrieval_terms 보강
  - 짧고 모호한 자연어 질문에 대한 신호 가중치 보강

src/play_book_studio/retrieval/query_terms_*.py
  - oc adm top pods, oc auth can-i, oc apply -f, oc new-app 등 자주 빠지는
    명령어를 expansion query에 보강

src/play_book_studio/retrieval/rewrite.py
  - 한국어 "리소스 사용량" → "resource usage", "cpu memory utilization"
  - 한국어 "배포 매니페스트" → "Deployment manifest yaml"
  - cross-lingual rewrite는 deterministic 규칙으로 시작
```

테스트: `tests/test_query_understanding.py` 보강 (intent 4개 추가), `tests/test_query_rewrite_cross_lingual.py`.

### Step 12. 개념 동의어 사전 도입 및 query expansion 연결

GraphDB/Neo4j는 도입하지 않는다. 순수 정적 JSON 사전 1개로 처리한다.

수정 파일:

```text
corpus/manifests/concepts/ocp_concept_synonyms_v1.json   (신규)
  - 25개 항목 (Pod, Deployment, Service, Route, Namespace, Secret, ConfigMap,
    PVC, Node, MachineConfigPool, ClusterOperator 등)
  - 각 항목 필드: concept_id, display_name_ko, synonyms, adjacent_terms
  - 기존 graph_runtime sidecar와 별도 파일이며, graph_runtime은 손대지 않음

src/play_book_studio/retrieval/concept_expansion.py   (신규)
  - load_concept_synonyms() 한 번 로드 후 lru_cache
  - expand_query_terms(query: str) -> list[str]
    1) query에 synonym regex 매치
    2) 매치된 concept의 adjacent_terms를 list로 append
    3) 중복 제거 후 반환
  - graph 자료구조 없음, 단순 dict + 정규식

src/play_book_studio/retrieval/query.py
  - understand_query 결과에 concept_expansion.expand_query_terms 결과를 retrieval_terms에 merge
  - 기존 query_terms_* 정규식 사전과 동일한 자리에 추가
```

테스트: `tests/test_concept_synonym_expansion.py` (사전 로딩, regex 매치, adjacent_terms append, 중복 제거, 빈 query/없는 concept fallback).

### Step 13. v012 eval 회귀 case 추가 및 통과

```text
corpus/manifests/eval/pbs_chat_quality_v012_beginner_cases.jsonl   (신규)
  - 위 v012-beginner-001~006 정의
tests/test_answer_quality_v012_beginner.py   (신규)
  - 6개 케이스를 retrieval + answer 양쪽에서 검증
```

전 케이스 통과 + studio_live_smoke pass rate ≥ 0.85가 v0.1.2 완료 조건.

### Step 14. 재색인 및 데이터 회귀 확인

```text
1. internal markup sanitize 반영하여 공식 코퍼스 re-chunk
2. parent-child 구조로 emit
3. navigation_only 플래그 부착
4. KMSC narrative pre-generation 실행
5. ops_learning derive 실행
6. starter/followup question candidates 생성
7. Qdrant/Postgres에 재색인
8. retrieval eval, answer eval, studio_live_smoke 회귀
```

회귀 비교:

```text
spec/v0.1.2/evidence/v012_chunk_quality_after.md (not archived; JSON evidence is spec/v0.1.2/evidence/v012_chunk_quality_after.json)
spec/v0.1.2/evidence/v012_studio_live_smoke_after.json
spec/v0.1.2/evidence/v012_retrieval_eval_after.json
spec/v0.1.2/evidence/v012_answer_eval_after.json
```

### Step 15. UI 검증

```text
Playwright smoke:
  6개 beginner 질문 시나리오 + 추천 질문 클릭 + follow-up 클릭
  light/dark mode contrast
  스트리밍 자연스러움
  citation [1] 클릭 시 이미지 viewer 안정성
  Terminal paste/wrap (v0.1.1 잔여 항목 포함)
```

### Step 16. OCP 재배포 및 live smoke

```text
1. dev merge 후 GHCR publish
2. oc rollout restart deployment/app deployment/web -n pbs-ocpops
3. oc rollout status 확인
4. live smoke:
   - 6개 v012 beginner 케이스
   - 운영 lane 추천 질문 회전 확인
   - 명령어 copy 후 터미널 paste (v0.1.1 잔여)
   - wrap된 명령 backspace (v0.1.1 잔여)
```

---

## API 확인 목록

| API | 목적 | v0.1.2 상태 |
|---|---|---|
| `/api/chat` | 일반 chat RAG | context size, parent chunk 적용 |
| `/api/chat/stream` | streaming chat RAG | 유지 |
| `/api/studio/starter-questions` | 추천 질문 | chunk.starter_question_candidates 기반 재구성 |
| `/api/chat-history/sessions` | 사용자 세션 | 유지 |
| `/api/chat-history/messages` | 사용자 메시지 | 유지 |
| `/api/repositories/documents` | 문서 scope | 유지 |
| `/api/v1/course/chat` | KMSC 운영 chat | beginner_narrative 보강 효과 검증 |
| `/api/v1/course/assets` | KMSC 이미지 | 유지 |
| `/api/v1/course/manifest` | course runtime | ops_learning 확장 반영 |
| `/api/chat-quality/query-insights` | 분석 전용 | navigation_only/markup leak 카운트 추가 |
| 신규 `/api/admin/chunks/regenerate-narratives` | 운영 도구 | 멱등 재생성 트리거 |
| 신규 `/api/admin/chunks/regenerate-question-candidates` | 운영 도구 | 멱등 재생성 트리거 |

---

## 테스트 계획

### Python (focused)

```powershell
pytest tests/test_internal_markup_sanitize.py
pytest tests/test_navigation_only_chunk_filter.py
pytest tests/test_parent_child_chunk.py
pytest tests/test_parent_chunk_promotion.py
pytest tests/test_context_size_budget.py
pytest tests/test_kmsc_beginner_narrative.py
pytest tests/test_ops_learning_auto_derive.py
pytest tests/test_chunk_question_candidates.py
pytest tests/test_starter_questions.py
pytest tests/test_starter_questions_readable.py
pytest tests/test_followup_suggestions.py
pytest tests/test_query_understanding.py
pytest tests/test_query_rewrite_cross_lingual.py
pytest tests/test_graph_concept_expansion.py
pytest tests/test_answer_quality_v012_beginner.py
pytest tests/test_low_confidence_guard.py
pytest tests/test_chat_grounding_quality.py
pytest tests/test_answer_eval_quality.py
pytest tests/test_corpus_quality_audit.py
pytest tests/test_course_api.py
pytest tests/test_course_ops_learning.py
```

### Frontend

```powershell
npm --prefix apps/web run build
```

### Browser / Playwright

```text
Studio Chat:
- OCP 설치는 어떻게 해?
- Service쪽에서 계속 장애나는데 뭐가 원인일까?
- 특정 namespace를 만드는 명령어가 뭐야?
- ocp에서 배포를 하고 싶으면 무슨 명령어로 해야되더라
- 보통 배포 yaml파일은 어케 작성하지
- 특정 Pod의 리소스가 얼마나 잡아먹고 있는지 확인하는 법
- 추천 질문 회전 (seed별)
- 추천 질문 클릭 → 답변 streaming 표시
- follow-up 추천 질문 자연스러움 ([/CODE] 잔류 0)
- code copy 후 Terminal paste
- 라이트 모드 contrast
```

### Live smoke (재배포 후)

```bash
oc rollout restart deployment/app deployment/web -n pbs-ocpops
oc rollout status deployment/app -n pbs-ocpops
oc rollout status deployment/web -n pbs-ocpops
```

---

## 완료 기준 (DoD)

1. studio_live_smoke pass rate가 0.66 → 0.85 이상으로 회복된다.
2. studio_live_smoke 결과에서 `[/CODE]`, `[CODE`, AsciiDoc 잔류 토큰이 추천 질문/답변/cli_commands에서 0건이다.
3. navigation_only 청크가 citation에 단독으로 나오는 비율이 5% 미만이다.
4. parent-child 청크 구조가 모든 official/KMSC 청크에 적용되어 있으며, leaf hit 시 parent context 전달이 동작한다.
5. KMSC course chunk에 beginner_narrative가 prepend되어 있고, 운영 답변에서 산문 narrative 비율이 늘었다.
6. ops_learning_chunks가 100개 이상이며, operations lane 추천 질문이 seed별로 회전한다.
7. 모든 retrieval-eligible 청크에 starter_question_candidates 또는 followup_question_candidates가 비어있지 않다.
8. starter_questions FAQ lane이 더 이상 평가셋 query를 직접 노출하지 않는다.
9. v012-beginner-001~006이 모두 통과한다.
10. `pbs-ext-rbac-can-i-001` 류 cross-lingual 미스가 통과한다.
11. 라이트 모드 / 다크 모드에서 추천 질문 contrast가 유지된다.
12. 채팅 명령어 copy 후 Terminal Ctrl+V가 동작한다 (v0.1.1 잔여).
13. wrap된 명령에서 Backspace가 이전 줄까지 자연스럽게 지운다 (v0.1.1 잔여).
14. backend focused tests가 통과한다.
15. frontend production build가 통과한다.
16. OCP 배포 환경 smoke가 통과한다.

---

## 위험 요소와 대응

| 위험 | 설명 | 대응 |
|---|---|---|
| 재색인 시간 | 27,907 + 523 청크 재색인 비용 | 멱등 CLI로 dry-run 먼저 검증, 야간 배치 |
| LLM 호출 비용 | beginner_narrative + question_candidates 사전 생성 | 청크별 1회 cache, version 필드로 회귀 비교 |
| parent chunk가 LLM context를 과점 | 너무 길어서 다른 근거가 잘림 | per-chunk 1800 char cap, max_chunks 8 유지 |
| 청크 사이즈 확대로 BM25 정확도 감소 | leaf chunk가 너무 커지면 keyword 매치 좁아짐 | parent-child 구조의 leaf는 96~128 유지 |
| ops_learning 자동 derive 결과 품질 | curated 18개 대비 noise 가능성 | curated와 auto-derived를 별도 stage로 운영, lane별 가중치 |
| eval 회귀 | 기존 통과 케이스가 깨질 가능성 | 모든 변경 후 retrieval + answer eval + studio_live_smoke 회귀 비교 |
| 개념 동의어 사전 누락 | 핵심 25개 외 누락 개념 | v0.1.3에서 운영 로그 기반 추가, v0.1.2는 핵심 25개만 |
| 한국어 사용자 질의에 대한 cross-lingual rewrite 과적합 | rewrite가 영어 term을 과도하게 끌어와 한국어 청크를 밀어냄 | rewrite 결과를 add-on으로 추가하되 원본 한국어 query를 우선 BM25에 유지 |
| starter_question_candidates 사전 생성이 오래 걸림 | 27,907개 + KMSC 523 + 자동 ops_learning 200 | 백그라운드 배치, 우선 lane(operations, learning)부터 채움 |

---

## 작업 메모

- 2026-05-11: v0.1.2 planner 작성 시작. v0.1.0/v0.1.1 분석 결과와 spec/v0.0.7/evidence/v007_official_chunk_quality_baseline.md, spec/v0.1.2/evidence/studio_live_smoke_report.json 실측을 근거로 청크 품질 재구축이 다음 단계의 핵심임을 결정.
- 2026-05-11: 사용자 시나리오 6개("OCP 설치는 어떻게 해?", "Service쪽 장애", "namespace 만드는 명령", "배포 명령어", "배포 yaml 작성", "Pod 리소스 확인")를 v012 beginner eval case로 동결.
- 2026-05-11: `oc\n[/CODE]` 류 markup leak이 studio_live_smoke 80 case 중 다수 실패의 공통 패턴임을 확인.
- 2026-05-11: KMSC course chunk가 1슬라이드=1청크 구조라서 본문이 OCR/캡션 entity 나열뿐임을 확인. beginner_narrative pre-generation으로 운영자 산문을 prepend하기로 결정.
- 2026-05-11: ops_learning_chunks가 18개에 그쳐 operations lane 회전이 단조롭다. KMSC 523개 청크에서 자동 derive하여 100개 이상으로 확장하기로 결정.
- 2026-05-11: starter_questions FAQ lane이 여전히 평가셋 JSONL의 query 필드를 직접 노출하는 fallback 경로가 남아 있어, v0.1.2에서 완전 차단하기로 결정.
- 2026-05-11: 8-토픽 STARTER_CATEGORY_RULES + 13-키워드 _starter_topic_terms + 토픽별 고정 한국어 명사/어미는 사실상 ~40가지 변주만 가능한 템플릿 시스템임을 확인. chunk.starter_question_candidates 사전 생성으로 전환하기로 결정.
- 2026-05-11: 16 step을 4개 phase로 묶기로 결정. Phase A(코드만, 별도 PR) → Phase B(재색인 1회 묶음 PR) → Phase C(검색 보강 PR) → Phase D(배포). Phase B 중간 partial deploy는 금지하며, Phase A는 markup leak 가시성 때문에 별도 PR로 먼저 머지한다.
- 2026-05-12: Phase A를 A.1과 A.2 두 PR로 추가 분리. A.1은 사용자 가시 클린업(markup/cli sanitize, FAQ JSONL 노출 차단, nav-only 휴리스틱, section title 노출 정리)이고 A.2는 retrieval add-on 코드 머지(query_understanding intent 4개, concept synonym JSON, cross-lingual rewrite, v012 eval JSONL 파일과 테스트 스켈레톤 추가). "코드 머지 시점"과 "eval 통과 검증 시점"을 분리해 Phase B 재색인 전후 회귀 비교의 기준선을 만든다. v012 6개 통과 단정은 Phase C에서만 한다.
- 2026-05-11: 사용자 결정에 따라 GraphDB/Neo4j 등 별도 그래프 인프라는 도입하지 않는다. VectorDB(Qdrant) + BM25(Postgres) hybrid를 유지하고, 개념 인접 검색은 `corpus/manifests/concepts/ocp_concept_synonyms_v1.json` 정적 JSON 사전 + 정규식 매칭 + retrieval_terms list extend 수준으로만 처리한다. 기존 `retrieval/graph_runtime.py`(로컬 sidecar JSON 메타데이터 부가 레이어)는 v0.1.2에서 손대지 않는다.

- 2026-05-12: Phase B 일부 구현. `document_chunks`에 `navigation_only`, parent-child, starter/followup candidate, beginner narrative 컬럼을 추가하는 `0008_chunk_runtime_enrichment` migration을 작성했고, official/KMSC import와 Qdrant payload, `RetrievalHit`, vector hydration, context cap(8 chunks/2000 chars, parent 1800 chars)을 연결했다. `starter_questions`는 DB chunk candidate pool을 우선 사용하고, 없을 때만 기존 manifest/ops learning fallback을 사용한다. 검증: `tests/test_chunk_runtime_enrichment.py`, `tests/test_corpus_policy.py`, `tests/test_db_migrations.py`, `tests/test_qdrant_indexer.py`, `tests/test_answer_context_metadata.py`, `tests/test_chunk_hydration.py`, `tests/test_starter_questions.py`, `tests/test_starter_questions_readable.py` 통과. 남음: Step 7/8의 KMSC beginner narrative 및 ops_learning_chunks 100+ 자동 확장, Step 14 전체 재청킹/재색인.
- 2026-05-12: Phase B Step 7/8 구현. `ingestion/kmsc_beginner_narrative.py`를 추가해 KMSC chunk title/body/image metadata 기반 beginner narrative와 ops learning chunk를 deterministic하게 파생한다. `load_ops_learning_chunks()`는 curated 18개를 유지하면서 course chunk에서 자동 후보를 보강해 최소 100개를 반환한다. 실제 corpus 확인 결과 100개(자동 생성 82개) 로딩. 검증: `tests/test_kmsc_beginner_narrative.py`, `tests/test_course_ops_learning.py`, `tests/test_course_api.py` 통과. 남음: Step 14 전체 재청킹/재색인 및 Phase C live smoke 비교.
- 2026-05-12: Phase A.1/Step 10 일부 추가 보강. ResourceQuota/LimitRange 계열에서 KMSC 원문 명령이 `oc patch ... # oc get ...`처럼 한 줄에 섞여 들어와 답변이 수정 명령 중심으로 흐르는 문제를 수정했다. citation command를 `#` 기준으로 분해하고, ResourceQuota/LimitRange 질문에서는 read-only 확인 명령(`oc get resourcequotas ...`)을 우선 선택한다. citation 확정 이후 status 전용 답변을 다시 승격하고, 충분한 코드 블록이 있는 구체 답변을 beginner generic command formatter가 덮어쓰지 않도록 조정했다.
- 2026-05-12: 검증 결과. `pytest -q tests/test_chat_grounding_quality.py tests/test_starter_questions.py tests/test_answer_eval_quality.py tests/test_query_understanding.py`는 41개 통과. v012 beginner answer eval은 6/6 통과, pass_rate 1.0, warning_free_rate 1.0이며 provenance noise는 `v012-beginner-002` 1건 남음. 로컬 API smoke에서 `ResourceQuota 때문에 Pod 생성이 막힌 건지 확인하려면 어디를 봐?`는 warning 없이 `oc get resourcequotas -n chak-test` 중심 답변으로 반환됐다.
- 2026-05-12: full `studio_live_smoke` 재실행. `spec/v0.1.2/evidence/v012_studio_live_smoke_after.json` 갱신 결과 80건 중 49건 통과(pass_rate 0.6125)로 이전 47건 대비 개선됐지만 DoD(0.85)에는 미달. ResourceQuota/LimitRange missing required term은 해소됐고, 남은 큰 실패군은 Node/namespace 같은 기본 명령, MCO/CVO/DNS/NetworkPolicy/SCC/ImagePullBackOff/registry/ODF/monitoring intent가 잘못된 문서 또는 generic command formatter로 빠지는 케이스다. 다음 보강은 특정 질문 하나가 아니라 intent profile + context evidence recovery + answer shaping의 공통 경로에서 처리해야 한다.
- 2026-05-12: 운영 intent profile 보강. Node status, MCO, CVO, DNS, NetworkPolicy, allowed registry, internal image registry, SCC를 별도 profile로 분리하고 context recovery가 `query_terms`까지 evidence 후보로 쓰도록 확장했다. `oc debug node` 질문은 node status보다 host-debug가 먼저 매칭되도록 우선순위를 조정했다.
- 2026-05-12: CLI command sanitize 보강. OCR/문장형 citation에 `oc get node ... 명령어 실행 결과`, `oc edit ... oc new-project ... oc get networkpolicy ...`처럼 여러 명령과 설명이 한 줄에 섞인 경우 `#`, 반복 `oc`, 한국어 설명 marker를 기준으로 후보 명령을 분리한다. 검증: `tests/test_chat_grounding_quality.py::test_embedded_cli_text_is_split_before_answering`, `test_beginner_command_lookup_sanitizes_embedded_cli_text` 추가 및 통과. 전체 focused suite는 43개 통과.
- 2026-05-12: 최신 상태. v012 beginner answer eval은 재실행 후에도 6/6 통과, pass_rate 1.0 유지. 단, 실제 API focused check에서 MCO와 ResourceQuota는 개선 확인됐지만 Node/namespace/NetworkPolicy/ImagePullBackOff는 아직 완전하지 않다. 특히 Node/NetworkPolicy는 citation command sanitize가 일부 적용됐지만 final answer 경로에서 여전히 generic formatter가 개입하므로 다음 작업은 status-answer 우선순위와 citation command parity를 더 좁혀야 한다.
## 진행 메모 (2026-05-13)

- [x] Phase C 보강: DNS, Route timeout, NetworkPolicy/egress, Cluster Version Operator, 업데이트 사전 점검, ODF, Prometheus/Alertmanager 계열 운영 intent profile과 검색어 확장을 추가했다.
  - 질문-답변 고정 매핑이 아니라 `IntentProfile.query_terms`, evidence term, citation 기반 status answer dispatch를 보강했다.
  - generic command formatter가 잘못된 근거를 코드블록으로 끌고 오지 않도록 DNS/Route timeout/NetworkPolicy/egress/registry/CVO/update precheck/ODF/monitoring의 command grounding 조건을 추가했다.
  - `ClusterOperator + node update precheck`, `events namespace 기준`, `finalizer/Terminating`처럼 더 구체적인 운영 intent가 Node/Namespace generic 답변보다 먼저 선택되도록 dispatch 순서를 조정했다.
  - `pod-metrics` intent에서 nodes CLI 근거를 우선할 수 있도록 intent-profile 기반 book priority rerank를 확장했다.
  - 검증: compileall 통과, `tests/test_chat_grounding_quality.py tests/test_answer_eval_quality.py` 41개 통과, `tests/test_chat_grounding_quality.py tests/test_starter_questions.py tests/test_answer_eval_quality.py tests/test_query_understanding.py` 53개 통과.
  - v012 beginner eval: 6/6 통과, pass_rate 1.0, 결과 `spec/v0.1.2/evidence/v012_answer_eval_after.json` 갱신.
  - extended eval: pass_rate 0.4667 → 0.5111 → 0.5333으로 개선, 결과 `spec/v0.1.2/evidence/v012_answer_eval_extended_after.json` 갱신.
  - 남은 주요 실패군: Route timeout citation이 HSTS route chunk로 빠짐, DNS가 generic Operator 문서로 인용됨, NetworkPolicy가 Day-2 overview로 빠짐, `oc adm inspect` citation 미확보, finalizer/PDB/HPA/SCC/namespace/previous logs 등은 citation term synonym 또는 검색 후보 품질 보강 필요.
