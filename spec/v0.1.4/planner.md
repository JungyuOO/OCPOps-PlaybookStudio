# v0.1.4 Corpus Schema Redesign

## 한 줄 요약

JSON(공식문서)과 PPT-OCR(운영문서)을 같은 파이프라인으로 받고, RAG 답변이 "프로즈 카드 → 명령어 카드 → 출력 예시 카드" 순서로 깔끔히 분리되며, 다음 단계 가이드와 환경별 후속질문이 자동으로 따라붙는 DB 구조를 v0.1.4에서 확정한다.

본 폴더의 세부 설계 문서:

- `spec/v0.1.4/db-parsing-schema.md` — Parsing layer (원본 보존, JSON·PPT 공통)
- `spec/v0.1.4/db-corpus-schema.md` — Corpus layer (검색 truth, 세그먼트·명령어·refs·후속질문, 챗봇 통합)

이 두 문서가 SQL 마이그레이션 작성보다 먼저 합의되어야 한다.

## 왜 v0.1.4인가

현재 한 테이블(`document_chunks`)에 parser 산출물과 검색용 truth가 섞여 있고, chunk 본문이 `[CODE]...[/CODE]` 내부 마크업이 박힌 markdown 단일 문자열이라 다음 문제가 동시에 발생한다.

1. **챗봇 답변에서 코드와 프로즈가 깔끔히 분리되지 않는다.** LLM이 보는 근거가 하나의 blob이라, "명령 → 출력 예시 → 추가 리소스"가 한 카드로 뭉친다.
2. **환경 의존 명령이 무차별 노출된다.** "PVC 처음에 어디서 확인해?" 질문에 `oc create secret generic azure-secret ...`이 같이 나온다. Azure인지 vSphere인지 baremetal인지 모르는데도 명령이 함께 검색된다.
3. **다음 단계 안내가 약하다.** chunk 메타데이터에 `learning.next_refs`가 일부 있지만 first-class가 아니라 검색·랭킹·UI 어디서도 일관되게 못 쓴다.
4. **PPT 운영문서가 공식문서와 다른 형태로 흐른다.** course_chunks와 document_chunks가 따로 살고, 운영문서가 RAG corpus로 통합되지 않는다.

v0.1.4는 새 기능을 안 만든다. 위 4가지를 풀 수 있는 schema 경계를 정하고, 그 경계에 맞춰 ingestion·retrieval·answering이 작은 변경만으로 동작하도록 만든다.

## 원칙

1. **Parsing과 Corpus를 분리한다.**
   - Parsing: 원본이 무엇이었는지(JSON 노드, PPT 슬라이드 zone/attachment, OCR 결과)를 보존.
   - Corpus: 사용자 질문에 답하기 위한 normalized, retrievable, learner-facing truth.
   - 한 테이블이 둘 다 책임지지 않는다.

2. **JSON 원본과 PPT-OCR 원본은 같은 corpus 계약을 만든다.**
   - parser는 달라도 `corpus_chunks` 시점부터는 같은 컬럼·같은 segment 구조다.
   - 검색·랭킹·답변 코드는 출처가 JSON인지 PPT인지 알 필요가 없다.

3. **Chunk 본문은 단일 markdown blob이 아니라 ordered typed segments다.**
   - `corpus_chunk_segments` 테이블로 분리. segment_type ∈ {`prose`, `command`, `command_output`, `table`, `note`, `warning`, `image_ref`}.
   - 챗봇 카드 렌더러가 segment 시퀀스를 보고 텍스트 카드 / 코드 카드 / 출력 카드를 그대로 그린다.
   - LLM 프롬프트도 segments를 typed 리스트로 받는다(현재의 `[CODE]` 인라인 마크업 폐기).

4. **명령어는 텍스트가 아니라 first-class row다.**
   - `corpus_chunk_commands` 테이블. `command_template`, `placeholders`, `intent`, `subject`, `env_scope`, `requires_env_clarification` 컬럼.
   - 환경 의존 명령(예: `azure-secret`)은 `env_scope = {"platform": ["azure"]}` 로 라벨링.
   - 답변 시 사용자 세션의 platform이 없으면 그 명령은 숨기고, "어떤 설치환경이세요?" 후속질문을 제시한다.

5. **다음 단계는 그래프가 아니라 시퀀스부터다.**
   - `corpus_chunk_refs` 테이블 하나로 `prerequisite`, `next`, `related`, `env_clarification`, `verify`, `lab`을 표현.
   - chunk 안의 jsonb `next_refs` 이중 저장은 폐기. 단일 truth.

6. **JSONB는 필요한 곳에만, 정의된 shape으로만 둔다.**
   - 모든 jsonb 컬럼은 본 v0.1.4 문서에 허용 키 목록을 명시. 그 외 키는 import 단계에서 reject.
   - 검색·랭킹·access·citation에 쓰이는 값은 모두 컬럼.

7. **불필요한 거버넌스 필드는 처음부터 안 넣는다.**
   - `trust_score` 같은 상수성 필드는 mixed-trust corpus가 도입되는 시점에 추가.
   - `review_status`는 정말 review pipeline이 값을 채울 때만 NOT NULL.

8. **기존 retrieval·answering 인터페이스를 깨지 않는다.**
   - `RetrievalHit` / `Citation` dataclass의 기존 필드(cli_commands, k8s_objects, verification_hints, navigation_only, followup_question_candidates 등)는 corpus 컬럼 또는 segments에서 derived view로 채워 호환 유지.
   - LLM 프롬프트 변경은 v0.1.4 후속 phase에서 점진 적용.

9. **원문·표시·검색·임베딩 텍스트를 4계층으로 분리한다.**
   - 현재는 `markdown == embedding_text` 같은 값으로 저장돼 ```` ``` ```` 펜스와 `[CODE language="..."]` 마크업이 임베딩 모델에 그대로 들어간다.
   - v0.1.4에서 `raw_text`(보존) / `markdown`(표시) / `normalized_text`(BM25) / `embedding_text`(벡터) 4개 컬럼으로 분리.
   - 임베딩 입력은 펜스·언어 태그·anchor URL·viewer path 완전 제거된 의미 본문만.
   - 자세히: `db-corpus-schema.md` "Text 4계층 계약" 섹션.

10. **모든 텍스트 I/O는 UTF-8을 명시한다.** (예방용 — 현재 corpus는 안 깨졌다)
    - `open(path)` 단독 사용 금지 → `encoding="utf-8"` 필수.
    - `json.dumps`에 `ensure_ascii=False`.
    - Windows 스크립트 stdout에 `sys.stdout.reconfigure(encoding="utf-8")`.
    - **PowerShell `Invoke-RestMethod`는 한국어 dump에 쓰지 마라** — ISO-8859-1 기본 디코딩으로 mojibake 만든다 (v0.1.4 작업 중 `qdrant_dump.json`에서 실측 확인). curl 또는 Python urllib 사용.
    - import 시 mojibake 패턴 자동 검증.
    - 자세히: `db-corpus-schema.md` "Encoding Contract" 섹션.

11. **v0.1.5 적용 시 Qdrant 컬렉션을 한 번 drop & rebuild한다.**
    - **이유는 인코딩이 아니다** (Qdrant payload는 정상 UTF-8 확인됨).
    - 진짜 이유: (a) `embedding_text`에 ```` ``` ````·`[CODE]` 펜스 잔여로 임베딩 품질 손상, (b) chunking 경계에서 `[CODE` vs `[/CODE` 941개 비대칭, (c) 4계층 텍스트 분리 schema 적용, (d) payload_version=1 새 계약.
    - 새 `embedding_text`로 모든 chunk 재임베딩.
    - 검증 SQL/스크립트 통과 후에만 서비스 전환.
    - 자세히: `db-corpus-schema.md` "Reindex Plan" 섹션.

12. **Intent Agent가 retrieval 앞단에서 질문 신호를 구조화한다.**
    - 사용자 질문을 바로 vector search에 넣지 않는다.
    - 먼저 Intent Agent가 `domain`, `book_slug_candidates`, `objects`, `error_states`, `intent_labels`, `answer_shapes`, `command_families`, `cluster_phase`, `execution_target` 후보를 추출한다.
    - 추출값은 controlled vocabulary에서만 선택한다. 자유 문자열 intent를 만들지 않는다.
    - confidence가 높은 broad 값만 metadata pre-filter에 쓰고, 나머지는 vector query 확장과 rank scoring에 쓴다.
    - 자세히: 본 문서 "Intent Agent + Metadata Retrieval Flow" 섹션.

## 범위 (Scope)

### In Scope

- 새 corpus 테이블 6개 정의: `corpus_documents`, `corpus_chunks`, `corpus_chunk_segments`, `corpus_chunk_commands`, `corpus_chunk_refs`, `corpus_question_candidates`.
- 기존 parsing 테이블 4개 컬럼 정리: `document_sources`, `parsed_documents`, `document_blocks`, `document_assets`.
- PPT 슬라이드 graph(`zones`, `attachments`, `ocr_text`, `relations`)를 `document_blocks` + `document_assets`로 매핑하는 규칙 정의.
- JSON 공식문서(`chunks.jsonl`, official manifest)를 `parsed_documents` + `document_blocks` → `corpus_chunks` + `corpus_chunk_segments`로 매핑하는 규칙 정의.
- chunk segment 모델과 챗봇 카드 렌더링 계약.
- 명령어 env_scope 라벨링 규칙 + agent prompt가 환경 후속질문을 만들어야 할 조건.
- `corpus_chunk_refs` 6가지 ref_type 정의 + 생성 전략 (휴리스틱·AI·수기).
- Qdrant projection이 `corpus_chunks` 기준으로 동작하기 위한 payload 계약.
- Intent Agent / Query Understanding 단계의 controlled vocabulary, 출력 shape, confidence 기반 pre-filter/rerank 분기 규칙.
- `source`, `classification`, `chunk`, `search_signals`, `text_fields` payload가 retrieval 단계별로 어떻게 쓰이는지에 대한 end-to-end 예시.

### Out of Scope

- SQL 마이그레이션 파일 작성 (v0.1.4 schema가 합의되면 v0.1.5에서).
- Reranker / retrieval scoring 알고리즘 변경.
- 실제 LLM Agent 런타임 구현 및 모델 프롬프트 배포. v0.1.4는 계약과 dry-run을 정의하고, v0.1.5에서 구현한다.
- 평가셋·smoke·report 처리 (별도 라인).
- Course runtime 테이블 재설계 (별도 운영). v0.1.4는 corpus가 course의 source가 될 수 있는지 확인만 한다.
- `document_chunks` 삭제 — 호환 view로 남긴다.

## 어떻게 SQL 없이 진행하나

새 컬럼·테이블을 SQL로 박기 전에, 모든 ingestion/retrieval/answering 코드가 새 구조를 가정한 인터페이스를 가질 수 있는지 두 설계문서로 검증한다. 검증 통과 후에야 v0.1.5에서 마이그레이션 SQL을 쓴다.

검증 절차:

1. `db-parsing-schema.md`와 `db-corpus-schema.md` 작성.
2. 각 테이블에 대해 (a) JSON 공식문서 한 챕터, (b) PPT 운영문서 한 슬라이드, (c) 사용자 업로드 PDF 한 페이지의 dry-run 매핑 작성.
3. 챗봇 답변 시나리오 3개에 대해 segments → card → prompt → LLM 출력 흐름 dry-run.
   - "OCP가 뭐야?" (개념)
   - "PV와 볼륨은 처음에 어디서 확인하면 돼?" (명령 + 환경 후속질문)
   - "MachineConfigPool이 degraded인데 어디부터 봐?" (단계별 가이드)
4. Intent Agent dry-run 3개에 대해 질문 → 신호 추출 → metadata pre-filter → vector query → rank scoring → answer source 선택 흐름을 검증.
   - "PVC가 Pending인데 뭐 확인해야 해?" (storage + troubleshooting)
   - "etcd 백업은 어느 노드에서 실행해?" (backup + execution target)
   - "UPI랑 agent-based 설치 차이 알려줘" (install + compare)
5. 통과하면 SQL 단계로 진입.

## Intent Agent + Metadata Retrieval Flow

v0.1.4의 Qdrant payload는 기존 `search.json` shape을 유지한다. `filter` / `rank` 같은 새 top-level 구획으로 물리적으로 나누지 않는다. 대신 각 필드가 retrieval 어느 단계에서 쓰이는지 계약을 명확히 한다. 런타임 호환을 위해 top-level `text`는 기존처럼 문자열로 유지하고, 4계층 텍스트 스냅샷은 `text_fields`에 둔다.

```json
{
  "source": {
    "corpus_scope": "official_docs | operations_docs | user_upload | study_docs",
    "doc_type": "official_doc | operations_doc | user_upload | manual_synthesis",
    "source_lane": "official_ko | applied_playbook | user_upload",
    "visibility": "private_user | workspace_shared | global_shared",
    "review_status": "approved | needs_review",
    "citation_eligible": true,
    "enabled_for_chat": true
  },
  "classification": {
    "domain": "install | storage | networking | security | monitoring | troubleshooting | upgrade | operators | logging | registry | ui_tooling | architecture | release_notes | node_ops | backup_restore | etcd",
    "subdomains": ["pvc", "storageclass", "etcd_backup"],
    "platform": "bare_metal | agent_based | any_platform | none",
    "ocp_version": "4.20",
    "locale": "ko | en",
    "book_slug": "문서 또는 덱 식별자"
  },
  "chunk": {
    "chunk_type": "concept | procedure | command | reference | troubleshooting | warning",
    "chunk_role": "parent | leaf",
    "navigation_only": false,
    "ordinal": 1,
    "title": "청크 제목",
    "section_path": ["상위 섹션", "하위 섹션"],
    "section_anchor": "anchor",
    "viewer_path": "/docs/...",
    "source_url": "https://..."
  },
  "search_signals": {
    "primary_topics": ["PVC", "StorageClass", "Persistent Volume"],
    "secondary_topics": ["volume binding", "storage provisioning"],
    "objects": ["Pod", "PVC", "PV", "StorageClass", "Secret", "Route"],
    "operators": ["OpenShift Data Foundation"],
    "components": ["kubelet", "scheduler", "CSI Driver"],
    "commands": ["oc get pvc", "oc describe pvc"],
    "command_families": ["oc_get", "oc_describe"],
    "error_states": ["Pending", "ImagePullBackOff", "NotReady"],
    "intent_labels": ["check_status", "configure_resource", "verify_result", "troubleshoot"],
    "answer_shapes": ["short_explanation", "step_by_step", "command", "checklist", "warning"],
    "cluster_phase": ["pre_install", "install", "post_install", "day2", "incident", "recovery", "upgrade"],
    "execution_target": ["cluster_admin_cli", "control_plane_node", "worker_node", "web_console"],
    "best_for_questions": ["PVC가 Pending일 때 확인 방법"],
    "verification_hints": ["STATUS가 Bound인지 확인"]
  },
  "text": "기존 RetrievalHit 호환용 embedding text 문자열",
  "text_fields": {
    "normalized_text": "BM25 검색용 정규화 텍스트",
    "embedding_text": "벡터 검색용 텍스트"
  }
}
```

### Intent Agent의 책임

Intent Agent는 답변을 생성하지 않는다. 사용자 질문을 검색 파이프라인 입력으로 변환한다.

출력 shape:

```json
{
  "raw_query": "PVC가 Pending인데 뭐 확인해야 해?",
  "normalized_query": "PVC Pending 상태 확인 방법",
  "classification": {
    "domain": "storage",
    "book_slug_candidates": ["storage"],
    "ocp_version": "4.20",
    "locale": "ko"
  },
  "search_signals": {
    "objects": ["PVC"],
    "error_states": ["Pending"],
    "intent_labels": ["troubleshoot", "check_status"],
    "answer_shapes": ["checklist", "command"],
    "command_families": ["oc_get", "oc_describe"],
    "cluster_phase": ["day2", "incident"],
    "execution_target": ["cluster_admin_cli"]
  },
  "confidence": {
    "domain": 0.91,
    "book_slug_candidates": 0.72,
    "objects": 0.95,
    "error_states": 0.93,
    "intent_labels": 0.88,
    "answer_shapes": 0.84,
    "command_families": 0.73
  }
}
```

confidence 사용 규칙:

| confidence | 사용 |
| --- | --- |
| `>= 0.85` | metadata pre-filter 후보 또는 strong rank signal |
| `0.60 ~ 0.85` | vector query expansion + rank scoring only |
| `< 0.60` | 로그/디버그용. hard filter 금지 |

`book_slug`는 사용자가 특정 문서를 열고 있거나 명시했을 때만 hard filter로 쓴다. 일반 질문에서는 `book_slug_candidates`를 rank signal로만 쓴다. 예: `etcd 백업/복구`는 `etcd`, `backup_and_restore`, `postinstallation_configuration`에 걸칠 수 있으므로 단일 `book_slug` hard filter를 피한다.

### Controlled Vocabulary

`intent_labels`는 자유 생성 금지. 아래 목록에서 다중 선택한다.

```json
[
  "explain_concept",
  "check_status",
  "verify_result",
  "troubleshoot",
  "configure_resource",
  "create_resource",
  "update_resource",
  "delete_resource",
  "backup",
  "restore",
  "install",
  "upgrade",
  "compare_options",
  "find_document",
  "command_lookup",
  "summarize",
  "list_prerequisites",
  "identify_execution_target",
  "explain_warning",
  "next_steps"
]
```

`answer_shapes`도 controlled vocabulary에서 다중 선택한다.

```json
[
  "short_explanation",
  "step_by_step",
  "command",
  "checklist",
  "yaml_example",
  "decision_guide",
  "warning",
  "troubleshooting_flow",
  "document_link"
]
```

예시 매핑:

| 사용자 질문 | intent_labels | answer_shapes |
| --- | --- | --- |
| `PVC가 Pending인데 뭐 확인해야 해?` | `troubleshoot`, `check_status` | `checklist`, `command`, `troubleshooting_flow` |
| `Machine Config Operator가 뭐야?` | `explain_concept` | `short_explanation` |
| `etcd 백업은 어느 노드에서 실행해?` | `backup`, `identify_execution_target`, `command_lookup` | `short_explanation`, `command` |
| `UPI랑 agent-based 설치 차이 알려줘` | `install`, `compare_options` | `decision_guide` |
| `RoleBinding YAML 예시 보여줘` | `create_resource`, `configure_resource` | `yaml_example` |

### 단계별 사용 규칙

1. **Query Understanding**
   - Intent Agent가 사용자 질문에서 `classification` 후보와 `search_signals` 후보를 추출한다.
   - rule/dictionary 기반 추출을 먼저 적용한다: OCP 객체(`PVC`, `Pod`, `Route`), 오류 상태(`Pending`, `ImagePullBackOff`), 명령 계열(`oc get`, `oc describe`)은 deterministic extractor가 우선한다.
   - LLM은 모호한 의도(`compare_options`, `next_steps`, `identify_execution_target`)와 답변 형태를 보강한다.

2. **Metadata Pre-filter**
   - vector search 전에 안정적인 값만 Qdrant filter로 건다.
   - 항상 필터: `source.enabled_for_chat`, `source.review_status`, `source.citation_eligible`, `classification.locale`, `classification.ocp_version`, `chunk.navigation_only=false`.
   - 확실할 때만 필터: `classification.domain`.
   - 매우 조심해서 필터: `classification.book_slug`, `chunk.chunk_type`.
   - 기본적으로 filter 금지: `search_signals.objects`, `error_states`, `intent_labels`, `answer_shapes`, `commands`, `best_for_questions`.

3. **Vector Query**
   - `raw_query`만 쓰지 않고 Intent Agent 출력으로 확장한다.
   - 예: `PVC Pending 상태 확인 OpenShift PersistentVolumeClaim StorageClass volume binding oc get pvc oc describe pvc troubleshooting`.

4. **Vector Search**
   - Qdrant는 pre-filter로 줄어든 후보 안에서만 vector search를 수행한다.
   - `text_fields.embedding_text`가 embedding 대상이며, `text_fields.normalized_text`는 BM25/keyword fallback에 쓴다.

5. **Rank Scoring**
   - vector score에 payload score를 더한다.
   - `search_signals.objects`, `error_states`, `intent_labels`, `answer_shapes`, `command_families`, `commands`, `verification_hints`, `chunk.chunk_type`, `classification.book_slug` 후보 일치를 점수화한다.

6. **Context Selection**
   - 상위 청크를 선택하고 `corpus_chunk_refs`의 `prerequisite`, `next`, `verify`, `related` 청크를 필요한 만큼 확장한다.
   - `chunk.parent_chunk_id`가 있으면 parent context를 소량 붙인다.

7. **Answer Generation**
   - LLM은 선택된 청크의 `text`/hydrated segments, `search_signals.commands`, `verification_hints`, `chunk.section_path`, `viewer_path`, `source_url`을 근거로 답한다.
   - 답변에는 명령, 정상 확인 기준, 출처가 포함되어야 한다.

### Dry-run: PVC Pending

사용자 질문:

```text
PVC가 Pending인데 뭐 확인해야 해?
```

Intent Agent 출력:

```json
{
  "classification": {
    "domain": "storage",
    "book_slug_candidates": ["storage"],
    "ocp_version": "4.20",
    "locale": "ko"
  },
  "search_signals": {
    "objects": ["PVC"],
    "error_states": ["Pending"],
    "intent_labels": ["troubleshoot", "check_status"],
    "answer_shapes": ["checklist", "command"],
    "command_families": ["oc_get", "oc_describe"]
  },
  "confidence": {
    "domain": 0.91,
    "objects": 0.95,
    "error_states": 0.93,
    "intent_labels": 0.88,
    "answer_shapes": 0.84,
    "book_slug_candidates": 0.72
  }
}
```

Qdrant pre-filter:

```json
{
  "must": [
    { "key": "source.enabled_for_chat", "match": { "value": true } },
    { "key": "source.review_status", "match": { "value": "approved" } },
    { "key": "source.citation_eligible", "match": { "value": true } },
    { "key": "classification.locale", "match": { "value": "ko" } },
    { "key": "classification.ocp_version", "match": { "value": "4.20" } },
    { "key": "classification.domain", "match": { "value": "storage" } },
    { "key": "chunk.navigation_only", "match": { "value": false } }
  ]
}
```

`objects=PVC`, `error_states=Pending`, `answer_shapes=command`는 추출 누락 위험이 있어 pre-filter가 아니라 rank scoring에 쓴다.

Vector query:

```text
PVC Pending 상태 확인 OpenShift PersistentVolumeClaim StorageClass volume binding oc get pvc oc describe pvc troubleshooting
```

Rank scoring 예:

```python
score = hit.score
if "PVC" in payload["search_signals"]["objects"]:
    score += 0.20
if "Pending" in payload["search_signals"]["error_states"]:
    score += 0.25
if "troubleshoot" in payload["search_signals"]["intent_labels"]:
    score += 0.15
if "check_status" in payload["search_signals"]["intent_labels"]:
    score += 0.10
if "command" in payload["search_signals"]["answer_shapes"]:
    score += 0.10
if "checklist" in payload["search_signals"]["answer_shapes"]:
    score += 0.08
if "oc_get" in payload["search_signals"]["command_families"]:
    score += 0.08
if "oc_describe" in payload["search_signals"]["command_families"]:
    score += 0.08
if payload["chunk"]["chunk_type"] in ["troubleshooting", "command", "procedure"]:
    score += 0.10
```

답변에 쓰는 payload:

```json
{
  "chunk": {
    "title": "PVC 상태 확인",
    "section_path": ["Storage", "Persistent storage", "PVC 확인"],
    "viewer_path": "/docs/ocp/4.20/ko/storage/index.html#verifying-pvc-status",
    "source_url": "https://docs.redhat.com/..."
  },
  "search_signals": {
    "commands": ["oc get pvc", "oc describe pvc"],
    "verification_hints": ["STATUS가 Bound인지 확인"]
  }
}
```

생성 답변 shape:

```text
PVC가 Pending이면 먼저 PVC 상태와 이벤트를 확인합니다.

1. PVC 상태 확인
   oc get pvc

2. 상세 이벤트 확인
   oc describe pvc <pvc-name>

3. StorageClass와 PV 바인딩 상태를 확인합니다.

정상 기준:
- STATUS가 Bound인지 확인합니다.

출처:
Storage > Persistent storage > PVC 확인
```

## 챗봇 답변에 v0.1.4 schema가 어떻게 보이는지

`db-corpus-schema.md`의 "Chatbot Output Card Contract" 섹션에 자세히. 짧은 요약:

```
[프로즈 카드]   PV/PVC를 처음 확인할 때는 클러스터에 등록된 PVC 상태부터 봅니다.
[명령 카드]    oc get pvc <pvc-name> -n <namespace>
[프로즈 카드]   STATUS가 Bound가 아니면 다음 명령으로 자세한 원인을 봅니다.
[명령 카드]    oc describe pvc <pvc-name> -n <namespace>
[출력 카드]    NAME   STATUS   VOLUME            ...
              pvc-name Bound  pv-azurefile      ...
[후속질문]     - Bound가 아닌 PVC를 어떻게 진단하나요?
              - StorageClass를 어떻게 확인하나요?
              [환경 확인] 현재 설치환경이 어떻게 되십니까? (Azure / vSphere / baremetal)
```

각 카드는 `corpus_chunk_segments`의 하나의 row를 그대로 렌더링한 결과다. 환경 후속질문은 명령 카드 중 하나라도 `env_scope`가 있고 세션에 환경 정보가 없을 때 자동 추가된다. 일반 후속질문은 `corpus_chunk_refs` (ref_type=`next`, `related`)에서 가져온다.

## DoD (Definition of Done)

- v0.1.4 schema 문서 2개(`db-parsing-schema.md`, `db-corpus-schema.md`)가 완성되어 SQL 마이그레이션 작성 직전 상태가 된다.
- 각 테이블이 무엇을 의미하는지·각 컬럼에 어떤 값이 들어가는지·각 jsonb의 허용 키가 무엇인지 본 문서에서 모두 확인 가능하다.
- JSON 공식문서와 PPT-OCR 운영문서가 같은 `corpus_chunks` shape으로 도달하는 경로가 두 문서에 dry-run 예시로 들어 있다.
- 챗봇 답변 시나리오 3개(개념·명령+환경후속·단계별가이드)가 새 schema에서 어떻게 카드와 후속질문으로 렌더링되는지 예시가 들어 있다.
- Intent Agent controlled vocabulary, confidence 기준, metadata pre-filter/rank scoring 분기, PVC dry-run 예시가 문서에 포함되어 구현자가 추가 의사결정 없이 v0.1.5 작업으로 넘길 수 있다.
- 기존 `RetrievalHit` / `Citation` 인터페이스를 깨지 않고 호환 view 또는 derived 컬럼으로 채울 수 있다는 매핑이 명시된다.
- 다음 phase(v0.1.5)에서 SQL 마이그레이션을 쓸 때 추가 의사결정이 필요 없다.
