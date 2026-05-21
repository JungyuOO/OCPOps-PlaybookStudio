# v0.0.6 - OCP 명령어 학습 RAG 검증

## 목표

v0.0.6의 1순위 목표는 사용자가 Studio Chat에서 OpenShift 질문을 던지고, 문서 근거가 붙은 명령어 안내를 받은 뒤, 실제 Terminal Session에서 그 명령어를 입력하면서 OCP를 단계적으로 학습할 수 있는지 검증하는 것이다.

핵심 방향:

- 사용자 질문 기반으로 답변해야 한다.
- 공식 문서/청크/citation에 근거한 답변이어야 한다.
- 초보자가 바로 터미널에 입력해볼 수 있는 명령어와 판단 기준을 제공해야 한다.
- 질문별 고정 답변 테이블이나 하드코딩된 예상 질문 → 답변 매핑은 절대 사용하지 않는다.

검증 기준:

- 명령어 질문에서 엉뚱한 문서나 무관한 절차가 선택되지 않아야 한다.
- 답변에 나온 주요 명령어는 citation 또는 citation의 `cli_commands`로 추적 가능해야 한다.
- 단일 명령 lookup뿐 아니라 `drain → uncordon`, `oc debug → chroot /host → backup` 같은 다단계 흐름도 검증한다.
- 실패 케이스는 검색 후보 생성, rerank, citation 선택, 답변 조립, 청크 품질 중 어디 문제인지 분리해서 기록한다.

---

## 범위

### Core (P0 - v0.0.6 릴리스 기준)

- [x] OCP 명령어 학습 전용 eval manifest 추가
- [x] namespace/project, pod, node, RBAC, route/service, PVC, MCO, certificate, etcd, bootstrap 설치 흐름을 포함한 20개 live smoke 케이스 정의
- [x] live smoke가 답변 필수 term과 citation 필수 term을 검증하도록 확장
- [x] starter question 없이 특정 eval manifest만 실행할 수 있는 옵션 추가
- [x] 단순 키워드 매칭이 아니라 질문의 의도/대상/작업/필요 명령 후보를 구조화하는 `intent_profile` 추가
- [x] `intent_profile`을 query expansion과 retrieval scoring에 연결
- [x] 관련 회귀 테스트 추가
- [x] v0.0.6 live smoke 결과와 남은 실패 유형 기록

### P1 - 이어서 개선

- [ ] 실패 case별 retrieval trace를 읽어 candidate generation, reranker, citation eligibility, answer stripping 중 어디 문제인지 분류
- [ ] generic `oc get` CLI reference chunk가 정확한 명령 chunk를 이기는 문제 개선
- [ ] `oc get service`/`oc get services`, `oc get clusteroperator`/`oc get clusteroperators` 같은 명령 변형을 citation grounding에서 더 자연스럽게 처리
- [ ] node drain 학습 질문에서 `oc adm drain`과 `oc adm uncordon`을 같은 작업 흐름으로 안정적으로 묶기
- [ ] etcd backup 학습 질문에서 `oc debug`, `chroot /host`, `cluster-backup.sh` 순서를 citation 기반으로 유지
- [ ] project/namespace `Terminating` 케이스가 low-confidence clarification으로 빠지는 원인 제거

### 비범위 (v0.0.7 이후)

- LLM 기반 별도 intent classification agent 도입
- corpus 전체 reimport/rechunking
- 사용자별 학습 상태 기반 adaptive curriculum
- 실제 OCP 클러스터 명령 실행 결과까지 자동 채점하는 e2e 학습 평가
- 고정된 예상 질문 → 고정 답변 데이터셋을 runtime 응답에 직접 사용하는 방식

---

## 현재 구조 확인

현재 PBS Chat/RAG 경계는 다음 흐름으로 동작한다.

- Eval runner: `src/play_book_studio/evals/studio_live_smoke.py`
  - Studio Chat API에 질문을 보내고 event stream/result/citation을 검증한다.
  - 기존에는 응답 성공 여부 중심이었고, v0.0.6에서 answer/citation term 검증을 추가했다.
- Query expansion: `src/play_book_studio/retrieval/query_terms*.py`
  - 사용자 질문에서 검색에 보탤 term을 만든다.
  - 한국어 질문에서 영어 OCP 명령어 term이 누락되면 엉뚱한 문서가 선택될 수 있다.
- Retrieval scoring: `src/play_book_studio/retrieval/scoring*.py`
  - BM25/vector/reranker 후보를 합치고 hit 점수를 조정한다.
  - 기존에는 "명령어 질문이면 CLI 명령이 있는 chunk 선호" 수준이라, 정확한 명령과 무관한 generic CLI chunk가 올라올 수 있었다.
- Answer grounding: `src/play_book_studio/answering/answer_text_commands.py`
  - citation에 있는 명령어를 바탕으로 command guide 답변을 만든다.
  - citation이 정확하지 않으면 답변도 정확한 명령을 유지하지 못한다.

따라서 v0.0.6은 새 챗봇 엔진을 만드는 작업이 아니라, 기존 RAG 흐름에서 "명령어 학습 질문"을 검증하고 검색/grounding의 약점을 드러내는 품질 게이트를 만드는 작업이다.

---

## 구현 계획

### Step 1. 명령어 학습 eval manifest 추가

목표:

- 사용자가 실제로 물어볼 법한 OCP 명령어 질문을 폭넓게 만든다.
- 각 케이스는 runtime 고정 답변이 아니라 검증용 기대 term만 가진다.
- 답변 필수 term과 citation 필수 term을 분리한다.

포함 영역:

```text
namespace/project
pod events/logs/CrashLoopBackOff
clusteroperators
node usage/drain/debug
etcd backup
bootstrap wait
oc login
RBAC can-i / role assignment
route/service
PVC Pending
MachineConfigPool
certificate monitor
project Terminating
```

추가 파일:

- `corpus/manifests/eval/ocp_command_learning_v006_cases.jsonl`

### Step 2. live smoke 검증 확장

목표:

- 기존 smoke가 "응답이 왔는지"만 보는 수준을 넘어서, 명령어 학습 질문에 필요한 grounded term을 검사한다.
- 특정 manifest만 실행할 수 있게 해서 v0.0.6 품질 게이트를 독립적으로 돌릴 수 있게 한다.

추가/변경:

- `--case-file`
- `--skip-starters`
- `must_include_terms`
- `must_not_include_terms`
- `expected_citation_terms`
- `forbidden_citation_terms`
- `query_type`

검증 예:

```powershell
python -m play_book_studio.evals.studio_live_smoke `
  --base-url http://127.0.0.1:8080 `
  --case-file corpus/manifests/eval/ocp_command_learning_v006_cases.jsonl `
  --skip-starters `
  --manifest-limit 0 `
  --followups-per-case 0 `
  --limit 0 `
  --report-path spec/v0.0.6/evidence/ocp_command_learning_v006_live_smoke.json
```

### Step 3. Intent Profile 추가

사용자 의견:

```text
의도 파악을 애초에 키워드로 하는 게 맞나?
아예 따로 의도 분류 agent가 있는 게 낫지 않나?
```

판단:

- 별도 LLM intent classification agent는 장기적으로 검토할 수 있다.
- 하지만 v0.0.6에서는 새 agent를 넣으면 latency, fallback, 테스트 안정성, 운영 복잡도가 커진다.
- 우선 deterministic `intent_profile`을 별도 모듈로 분리해 "키워드 if문을 흩뿌리는 방식"보다 나은 중간 구조를 만든다.
- 이 profile은 답변을 고정 생성하지 않고 retrieval/query/ranking 신호로만 사용한다.

추가 파일:

- `src/play_book_studio/retrieval/intent_profile.py`

profile 필드:

```text
intent
target_object
task
needs_command
primary_commands
evidence_terms
query_terms
confidence
reasons
```

### Step 4. Query Expansion / Ranking 연결

목표:

- "명령어 질문"이면 아무 CLI chunk나 올리는 것이 아니라, 질문의 대상 명령과 실제 hit의 `text`, `cli_commands`, `verification_hints`가 맞는지 반영한다.
- 다만 corpus에 없는 명령을 억지로 답변에 넣지는 않는다.

변경 파일:

- `src/play_book_studio/retrieval/query_terms.py`
- `src/play_book_studio/retrieval/query_terms_operations_project_node_deployment.py`
- `src/play_book_studio/retrieval/book_adjustment_node_ops.py`
- `src/play_book_studio/retrieval/scoring_signals.py`
- `src/play_book_studio/retrieval/scoring_adjustments.py`

주의:

- `intent_profile.primary_commands`는 검색/랭킹 후보 신호이지, runtime 답변 본문에 무조건 삽입하는 값이 아니다.
- 답변은 여전히 citation 기반이어야 한다.
- profile이 강해질수록 generic CLI reference를 과도하게 누를 위험이 있으므로 smoke 결과로 조정한다.

### Step 5. Regression Test 추가

검증 파일:

- `tests/test_chat_grounding_quality.py`
- `tests/test_answer_text_commands.py`

검증 내용:

- namespace 현재 context 질문과 namespace 목록 질문을 구분한다.
- clusteroperator 한국어 질문이 `oc get clusteroperators` 쪽으로 확장된다.
- node debug/MCP 질문에서 `chroot /host`, `oc get mcp` term이 살아난다.
- RBAC can-i, PVC, previous logs, route/service, etcd backup profile이 생성된다.
- live smoke validator가 missing answer/citation term을 실패로 잡는다.

---

## 완료 기준 (DoD)

1. v0.0.6 명령어 학습 eval manifest가 존재한다.
2. live smoke가 case-file 기반으로 20개 명령어 학습 질문을 독립 실행할 수 있다.
3. 답변 필수 term과 citation 필수 term을 모두 검증할 수 있다.
4. runtime 답변은 고정 Q&A 테이블 없이 retrieval/citation 기반으로 생성된다.
5. `intent_profile`은 답변 생성기가 아니라 retrieval/ranking 보조 신호로만 사용된다.
6. focused regression test가 통과한다.
7. live smoke 결과와 남은 실패 유형이 planner와 report에 기록된다.
8. 남은 실패가 "다음 작업에서 무엇을 봐야 하는지" 수준으로 분류되어 있다.

---

## 위험과 주의사항

- 명령어 term을 너무 강하게 boost하면 정확 문서가 아니라 CLI reference generic chunk만 선택될 수 있다.
- 반대로 mismatch penalty를 강하게 주면 유효한 command chunk도 밀릴 수 있다. 실제로 1.75 boost/0.78 penalty 실험은 live smoke pass rate를 낮춰 되돌렸다.
- `oc get service`와 `oc get services`처럼 명령 변형이 많은데, citation 검증이 너무 문자열 exact match에 가까우면 실제로는 맞는 답변도 실패할 수 있다.
- `--previous`, `chroot /host`처럼 문서 본문에는 있지만 `cli_commands` metadata에 빠진 경우가 있다. 이 경우 answer grounding과 chunk metadata를 함께 봐야 한다.
- `citation_eligible=false`인 curated chunk에 정확 명령이 있을 수 있다. 이때는 retrieval 후보에는 보이지만 최종 citation으로 쓰이지 못한다.
- live smoke pass rate가 낮다고 해서 답변을 하드코딩하면 안 된다. 실패 원인은 retrieval trace와 chunk evidence로 분리해야 한다.
- 앞으로 문서와 코드 파일은 UTF-8 기준으로 읽고 쓴다. PowerShell에서 파일을 다룰 때는 가능한 `-Encoding UTF8`을 명시한다.

---

## 작업 메모

- 2026-05-11: v0.0.6 브랜치 `feat/v0.0.6/ocp-command-learning-eval`에서 작업을 시작했다.
- 2026-05-11: `corpus/manifests/eval/ocp_command_learning_v006_cases.jsonl`에 20개 명령어 학습 케이스를 추가했다.
- 2026-05-11: `studio_live_smoke`에 custom case-file, starter skip, required/forbidden answer term, expected/forbidden citation term 검증을 추가했다.
- 2026-05-11: 초기 live smoke는 `20`개 기준 약 `9/20` 통과 수준이었다. 주요 실패는 namespace 목록, pod events, previous logs, clusteroperators, node drain, etcd backup, bootstrap wait, RBAC can-i, route/service, project terminating이었다.
- 2026-05-11: 사용자 피드백에 따라 단순 키워드 분기 대신 `intent_profile` 모듈을 추가했다. 이 모듈은 답변을 고정하지 않고 질문에서 검색 의도와 근거 term을 구조화한다.
- 2026-05-11: `intent_profile`을 query expansion과 retrieval scoring에 연결했다. 목표 명령과 hit의 실제 `text`/`cli_commands`/`verification_hints`가 맞으면 boost하고, 무관한 command chunk는 약하게 penalty를 준다.
- 2026-05-11: 회귀 테스트 `pytest tests/test_chat_grounding_quality.py tests/test_answer_text_commands.py -q` 결과 `40 passed`.
- 2026-05-11: app 컨테이너 rebuild 후 `/api/health` 200 OK를 확인했다.
- 2026-05-11: v0.0.6 live smoke 최종 기록은 `10/20`, `pass_rate=0.50`이다. report는 `spec/v0.0.6/evidence/ocp_command_learning_v006_live_smoke.json`에 남겼다.
- 2026-05-11: 남은 실패는 고정 답변으로 해결하지 않고, 다음 작업에서 retrieval trace 기반으로 candidate generation/reranker/citation/answer stripping 중 어디 문제인지 분류해야 한다.
- 2026-05-11: 커밋 `979650d Ground OCP command learning on retrieval evidence`로 v0.0.6 진행분을 저장하고 원격 브랜치 `origin/feat/v0.0.6/ocp-command-learning-eval`에 push했다.
