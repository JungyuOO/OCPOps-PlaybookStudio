# Retrieval 파이프라인 재설계 — 설계 문서

- 날짜: 2026-05-18
- 브랜치: feat/v0.1.8/chatbot-latency-quality
- 범위: retrieval 계층 교체 (재임베딩 없음)

## 1. 문제 정의

공식 문서 `chunks.jsonl`은 Qdrant에 정상 적재되어 있다 (`oc login` 포함 청크 187개,
`poddisruptionbudget` 포함 청크 24개 확인). 그런데 자연어 질문 다수가 답을 못 찾는다:

- "ocp 로그인 어떻게 함" → "현재 Playbook Library에 해당 자료가 없습니다"
- "모든 프로젝트에서 pod 중단 예산 확인 어떻게해?" → 정답 청크를 못 가져옴

즉 적재 문제가 아니라 **질문 → 검색 → 답변** 파이프라인의 recall 문제다.

### 근본 원인 (조사로 확인)

파이프라인이 손으로 튜닝한 규칙 3중 스택이고, 각 계층이 독립적으로 정답 청크를 떨군다.

1. **Query 이해가 하드코딩 사전 의존** — `build_intent_profile`이 질문 → `target_object`
   → `primary_commands`를 손으로 적은 표에서 찾는다. 실측 결과:
   - "ocp 로그인 어떻게 함" → `intent=unknown`, `target_object=`(빈값), `primary_commands=()`
   - "oc login이 실패할 때 토큰이나 서버 URL 문제를..." → 정상 분류 (테스트에 하드코딩된 표현)
   - `unknown`으로 떨어지면 expansion이 lexicon 폴백으로 엉뚱한 확장을 한다
     ("모든 프로젝트에서 pod 중단 예산..." → `oc create namespace`, `CrashLoopBackOff`까지 붙어
     검색을 정답에서 멀어지게 오염시킴)

2. **스코어링이 per-query 매직 상수 수십 개** — `vsphere_storage_match_boost==2.2`,
   `v016_etcd_defrag_boost==2.1` 등. 미리 손튜닝한 질문만 랭킹이 맞고, 나머지는 generic
   vector score로 떨어진다.

3. **Grounding guard가 답을 차단** — `answerer.py`의 `has_sufficient_command_grounding`,
   `_requires_rbac/console/monitoring_grounding`이 citation을 키워드 기대와 비교해
   불일치 시 `_build_grounding_blocked_result` → "자료가 없습니다"를 낸다. 검색이 관련
   청크를 가져와도 키워드 체크가 실패하면 답이 막힌다.

데이터 품질 문제도 있다: corpus `cli_commands`에 마크업 누수(`oc\n[/CODE]`),
`k8s_objects` 오라벨링.

질문마다 실패 지점이 다르므로 alias 하나 추가로는 해결 불가 — 구조 문제다.

### 지연 문제 (별도 확인)

서버 실측: vector search 17~20초, reranker 15~20초 (총 30~40초).

- **vector 17~20초**: `vector.py`가 subquery당 임베딩 HTTP 호출 + Qdrant HTTP 호출 +
  매번 새 Postgres 커넥션 hydration + private-vector 호출을 직렬 반복. subquery는 최대 2개.
  Qdrant HNSW 자체는 28k 코퍼스에 ms 단위 — 느린 건 느린 임베딩 서버로의 반복 왕복.
- **reranker 15~20초**: 후보 5개를 단 1번의 HTTP 요청으로 채점. 리랭커 서버가 **CPU 전용**
  (GPU 불가, 변경 불가)이라 문서당 ~3~4초. batch size로 못 줄임.

`top-k`를 5로 줄여도 지연이 안 줄어든 이유: 비용이 *후보 개수*가 아니라 *느린 서버 왕복
횟수*와 *subquery fan-out*에 비례하기 때문.

## 2. 설계 원칙

- per-query 하드코딩 규칙 추가를 멈춘다. 그게 병이다.
- recall은 retrieval 계층(hybrid)에서 만들고, 규칙 계층에서 만들지 않는다.
- 리랭커는 "답을 찾는" 단계가 아니라 stage-1이 넘긴 후보의 *순서만* 바꾸는 단계다.
  따라서 핵심 지표는 **stage-1 hybrid의 recall@8** — 정답 청크가 상위 8 안에 드는가.
- 리랭커는 아키텍처 베팅이 아니라 설정 플래그(`RERANKER_ENABLED`)로 둔다. CPU 제약상
  현재는 비활성 후보지만, GPU가 생기면 1줄 토글로 복귀.
- A′(리랭커 OFF) vs B′(리랭커 ON, top_n≤8)는 직감이 아니라 eval 측정으로 결정한다.

## 3. 새 retrieval 경로 (아키텍처 & 데이터 흐름)

```
query
 → normalize_query   (단일 alias/lexicon 테이블, intent profile 없음, subquery fan-out 없음)
 → 임베딩 1회 호출
 → 병렬:  BM25 검색(top ~40)  ||  Qdrant 벡터 검색(top ~40)
 → RRF 병합 → top 8
 → RRF 병합 후 최종 top-8만 DB hydration
 → [RERANKER_ENABLED=true 일 때만] reranker가 그 8개 재정렬
 → context assembly → answer
```

### 현재 대비 차이

| 항목 | 현재 | 새 설계 |
|---|---|---|
| subquery | 최대 2개 (직렬, 각각 임베딩+Qdrant+DB+private) | 1개 |
| candidate_k | 5 (command면 10) | BM25/벡터 각 ~40 → 병합 top 8 |
| metadata pre-filter | signal_plan이 생성·적용 | 제거 (HNSW는 ms, 필터는 정답 청크 누락 위험만) |
| reranker | 항상 ON, top_n 5 | `RERANKER_ENABLED` 플래그, top_n ≤ 8 |
| per-query 스코어링 | v0xx 매직 상수 수십 개 | 제거, RRF 점수만 |
| 임베딩 호출 | subquery당 1회 (~2회) | 1회 |
| DB hydration | 벡터 검색 직후, 후보 전부 | RRF 병합 후 최종 top-8만 |

top-40 확대는 사실상 무비용임을 확인:
- BM25는 항상 전체 코퍼스를 채점하고 top_k는 슬라이싱일 뿐 — 차이 0
- Qdrant HNSW 비용은 `ef`가 좌우, top_k 아님 — 무시 수준
- hydration은 이미 배치(`WHERE c.id = ANY(%s)`) — 40개든 8개든 쿼리 1번

### 데이터 흐름 / 에러 처리

| 상황 | 동작 |
|---|---|
| 임베딩 서버 다운/타임아웃 | BM25-only 폴백, 답변 계속 생성, trace 기록 |
| Qdrant 실패 | BM25-only 폴백 |
| BM25 + 벡터 둘 다 실패 | 그때만 진짜 오류 |
| 리랭커 타임아웃/에러 | pre-rerank hybrid 순서로 폴백 (차단 안 함) |
| score floor 위 hit 0개 | 진짜 "자료 없음" 응답 |
| grounding guard 불일치 | 차단 아님 — 근거+주의문구로 soft-degrade |

## 4. 모듈 — 유지 / 신규 / 삭제

정확한 파일 단위 목록은 구현 계획 단계에서 확정. 큰 그림:

### 유지 (그대로 또는 소폭)
- `bm25.py` — 한국어 토큰화 점검
- `vector.py` — 단일 검색으로 단순화, hydration을 밖으로 이동
- `reranker.py` — 그대로, `RERANKER_ENABLED` 플래그 뒤로
- `ranking.py` — RRF 병합 함수만 남김
- `models.py`, `chunk_hydration.py`, `trace.py`
- `access_scope.py`, `corpus_scope.py`, `intake_overlay.py` — 세션/테넌트/customer-pack
  필터링은 정당한 권한 로직, 유지

### 신규 생성
- `query_normalize.py` — 정규화 단일 모듈. `query_terms*`, `query_understanding`,
  `intent_profile`, `rewrite`, `query_signal_pipeline`를 전부 대체. subquery fan-out 없음.
- `hybrid_search.py` — BM25+벡터 병렬 → RRF → top-8 → hydration. `retriever_search.py` 리워크.
- `aliases.toml` (또는 yaml) — 단일 alias 테이블 (코드 아닌 데이터):
  `pod 중단 예산 ↔ poddisruptionbudget`, `로그인 ↔ login` 등. 새 표현은 여기 한 줄만 추가.

### 삭제 (per-query 하드코딩 계층)
- `intent_profile.py`, `intent_detectors.py`, `intent_patterns.py`, `intents.py`
- `query_signal_pipeline.py`, `query_understanding.py`, `query_terms*.py`(7개), `rewrite.py`
- `scoring_adjustments*.py` 전체 (v0xx 매직 상수)
- `book_adjustment_*.py` 약 10개
- `concept_expansion.py`, `domain_lexicon.py`, `ambiguity.py`,
  `scoring_signals.py`, `scoring_postprocess.py`
- `retriever_rerank.py` — intent-profile rescue/rebalance 폐기, 순수 reranker 호출만
  `hybrid_search`로 흡수

### answerer.py 변경
- grounding guard들을 hard-block → soft-degrade (근거+주의문구로 답변)
- 진짜 "hit 0개" no-doc 경로만 유지

### 파급 — 테스트
`test_chat_grounding_quality.py`의 v0xx 매직 상수 단언, intent_profile 단언 등 상당수
테스트가 깨진다. 의도된 것 — 그 테스트들은 eval 케이스로 전환된다 (특정 boost 상수 검증
→ "정답이 top-8에 들어왔나" 검증).

## 5. eval 하니스 (recall 측정)

기존 `evals/` 디렉터리(`retrieval_eval.py`, `benchmark.py`, `answer_eval.py`) 위에 얹는다.

### eval셋 — 고정 파일
위치 예: `tests/eval/retrieval_eval_set.jsonl`. 실제 질문 30~50개. 케이스당 유연한 정답 매칭:

```json
{"id": "pdb-all-ns",
 "query": "모든 프로젝트에서 pod 중단 예산 확인 어떻게해?",
 "expect_book": "nodes",
 "expect_section_contains": "Pod 중단 예산",
 "expect_command": "oc get poddisruptionbudget --all-namespaces"}
```

chunk_id 정확 매칭(엄격) OR book+section 부분문자열 OR command 부분문자열 허용.

**eval셋 소스:**
- 이미 아는 실패 질문 ("ocp 로그인 어떻게 함", "모든 프로젝트에서 pod 중단 예산 확인" 등)
- corpus의 `starter_question_candidates` / `followup_question_candidates` — 애초에
  사용자가 물어볼 법한 질문으로 생성된 것
- 실제 OCP 운영자 말투로 새로 작성 (짧고 구어체)

v0xx 테스트 질문은 eval셋에 직접 넣지 않는다 (도메인 probe라 실제 사용자 말투와 동떨어짐).
대신 v0xx가 다룬 토픽(etcd defrag, PDB, route admission, insights 등)을 "토픽
체크리스트"로만 활용 — eval셋이 그 토픽들을 커버하는지 확인하되 문장은 자연스러운
사용자 말투로 다시 쓴다.

### recall 프로브 — 핵심 도구
각 질문을 stage-1 hybrid만 태운다 (answerer·LLM 없음, 빠름). 출력:
- 정답 청크의 순위 — BM25 / 벡터 / RRF 병합 리스트 각각에서
- 집계: recall@8, recall@20, recall@40, MRR
- 표 형태: 어느 질문이 통과/실패, 어느 단계에서 죽었나

```
case            BM25rank  VECrank  RRFrank  @8
pdb-all-ns          2        14       3      PASS
ocp-login          —         1        1      PASS
etcd-defrag        18        —        12     FAIL  ← BM25만 잡음, 벡터 누락
```

실패 질문이 "BM25는 찾았는데 벡터가 놓침"이면 alias 문제, "둘 다 놓침"이면
embedding_text 문제 — 원인이 표 한 장에 보인다. 질문 하나씩 채팅에 쳐볼 필요 없음.

### 답변 레벨 eval (선택, 느림)
전체 파이프라인 + LLM을 태워 "답변이 기대 command를 포함하나" 검증. `answer_eval.py` 재사용.

### 리랭커 = 오프라인 채점기
eval셋 정답 큐레이션 시 CPU 리랭커를 천천히 돌려 후보 중 진짜 정답을 가려내는 용도.

## 6. 구현 순서

각 단계가 독립 검증 가능하도록 순차 진행. 각 단계마다 recall 프로브로 회귀 확인.

1. **eval 하니스 먼저** — eval셋(30~50) + recall 프로브. 코드 미수정 상태로 현재
   파이프라인의 baseline recall@8 측정. 이 숫자가 모든 판단의 기준선.
2. **`query_normalize.py` + `aliases.toml`** — intent profile/signal pipeline/query_terms
   제거하고 단일 정규화로 교체. recall 프로브로 before/after 비교.
3. **`hybrid_search.py`** — BM25+벡터 병렬, RRF, top-8, hydration을 병합 후로 이동.
   metadata 필터 제거, subquery fan-out 제거.
4. **answerer guard soft-degrade** — hard-block 제거.
5. **삭제 정리** — scoring_adjustments/book_adjustment/retriever_rerank 등 dead 모듈
   제거, 깨진 테스트를 eval 케이스로 전환.
6. **A′/B′ 확정** — recall 프로브 최종 측정 → `RERANKER_ENABLED` 기본값 결정.

재임베딩(`embedding_text` 강화)은 이 스펙 범위 밖 — 별도 후속 단계. 운영상 Qdrant 벡터는
앱 이미지가 아닌 외부 Qdrant 서비스 상태이므로, 재임베딩은 이미지 재빌드가 아니라
indexer job 재실행 — 분리 처리.

## 7. 성공 기준 (measurable)

- recall@8: baseline 대비 명확히 상승 (목표치는 1단계에서 baseline 측정 후 확정)
- 알려진 실패 질문 PASS: "ocp 로그인 어떻게 함", "모든 프로젝트에서 pod 중단 예산 확인"
- 응답 지연: 리랭커 OFF 시 30~40초 → 한 자리 초반대 목표
- recall 프로브가 회귀 게이트로 동작 — 이후 변경이 recall@8을 떨어뜨리면 배포 전 감지

## 8. 범위 밖 (이번 스펙 비포함)

- `embedding_text` 강화 및 코퍼스 재임베딩 (별도 후속)
- corpus `cli_commands` 마크업 누수 / `k8s_objects` 오라벨링 정리 (별도 후속, 단
  recall 프로브가 영향 받는 케이스를 드러내면 우선순위 재검토)
- 리랭커 GPU 서빙 전환 (인프라 가용 시)
