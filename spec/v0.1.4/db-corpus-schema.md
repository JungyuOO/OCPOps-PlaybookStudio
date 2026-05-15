# v0.1.4 Corpus Layer Schema

## Reality Check (실제 corpus 27,907개 chunk 전수 조사)

본 문서의 모든 enum과 컬럼은 다음 실제 데이터에서 도출된다. 추측 값은 마크업하거나 제외한다.

| 필드 | 실제 distinct 값과 분포 | 의미 |
| --- | --- | --- |
| `chunk_type` | `command` 12684, `procedure` 8518, `concept` 3863, `reference` 1496, `troubleshooting` 1343, `warning` 3 | 5종이 유의미. `warning`은 3개라 별도 enum값 안 둠. |
| `chunk_role` | DB ingestion이 `parent` 또는 `leaf`만 부여 | 2종만 enum. |
| `source_lane` | `official_ko` 22082, `applied_playbook` 5825 | 공식 한국어 라인과 응용 playbook 합성 라인 공존. |
| `source_type` | `official_doc` 22082, `manual_synthesis` 5825 | 데이터에 이 2종만 존재. |
| `review_status` | `approved` 24208, `needs_review` 3699 | mixed 값이 실제 존재 — 컬럼 필요. |
| `source_collection` | `core` 27907 | 단일 상수. 컬럼 가치 없음. |
| `verifiability` / `bundle_scope` / `classification` / `provider_egress_policy` / `approval_state` / `publication_state` / `redaction_state` | 전부 단일값 | 컬럼 아님 — `metadata`/`access_policy` jsonb. |
| `locale` / `product` / `version` | `ko` / `openshift` / `4.20` 단일 | 향후 확장 위해 컬럼 유지. |
| `cli_commands` non-empty | 55.2% | 컬럼 유지 (jsonb 배열). |
| `k8s_objects` non-empty | 44.4% | 컬럼 유지. |
| `verification_hints` non-empty | 45.5% | 컬럼 유지. |
| `operator_names` non-empty | 23.1% | 컬럼 유지. |
| `error_strings` non-empty | 4.8% | sparse지만 troubleshooting 한정 신호. 컬럼 유지. |
| `task_intent`, `lifecycle_phase`, `audience_level`, `privilege_scope` | 데이터에 **없음**, ingestion도 부여 안 함 | v0.1.4 컬럼에서 제거. 필요해지면 추후 enrichment phase에서 추가. |
| `source_kind` (코드 literal) | `html-single`, `source-first`, `project_artifact`, `seed`, `upload` 등 혼재 | enum을 코드 현실에 맞춰 정리. |
| `corpus_scope` (코드 literal) | `official_docs`, `study_docs` | 이 2종 + 향후 `user_upload` 정도. |
| `visibility` (코드 literal) | `global_shared`, `workspace_shared`, `private_user` | 3종. |

이 표가 본 schema 문서의 모든 enum 결정의 기준이다.

## 이 문서가 정의하는 것

Corpus layer는 사용자 질문에 답하기 위한 **유일한 검색·답변용 truth**다. JSON 공식문서든 PPT 운영문서든 PDF 업로드든, parsing layer를 거쳐 도달하는 순간부터는 같은 모양·같은 컬럼·같은 검색 인터페이스를 가진다.

본 문서는 다음 6개 corpus 테이블과 2개 projection 테이블을 정의한다.

| 테이블 | 한 줄 설명 |
| --- | --- |
| `corpus_documents` | 검색·인용 단위의 문서 1개. |
| `corpus_chunks` | retrieval과 인용의 기본 단위(보통 한 섹션 또는 한 절차). |
| `corpus_chunk_segments` | chunk를 구성하는 ordered typed segment(프로즈/명령/출력/표/이미지). 챗봇 카드의 직접 원본. |
| `corpus_chunk_commands` | chunk에 포함된 실행 명령을 구조화한 row. 환경 의존 여부 라벨링. |
| `corpus_chunk_refs` | next/prerequisite/related/env_clarification 등 학습 그래프. |
| `corpus_question_candidates` | 후속질문·시작질문 후보 풀. |
| `embedding_jobs` | embedding 작업 상태. |
| `qdrant_index_entries` | Qdrant projection 상태. |

추가로 답변 카드 렌더링 계약과 agent prompt 변경 가이드, PVC 시나리오 dry-run을 본 문서 끝에 둔다.

---

## `corpus_documents`

### 의미

`parsed_documents` 1개에서 derived되는 검색용 문서 1개. parser 산출물에서 깨끗한 텍스트·정규화된 메타데이터·OCP facet을 뽑아낸 결과.

사용자에게 "어떤 문서에서 나온 답이냐"를 인용할 때 쓰는 단위가 이것이다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 문서 식별자. |
| `document_source_id` | uuid | no | 원본 source. |
| `document_version_id` | uuid | yes | 원본 version. |
| `parsed_document_id` | uuid | no | 어떤 parser 결과에서 만들었는지. |
| `repository_id` | uuid | yes | 라이브러리 그룹. |
| `owner_user_id` | text | yes | 사용자 업로드면 소유자. 공식은 NULL. |
| `visibility` | text | no | `private_user`, `workspace_shared`, `global_shared`. |
| `corpus_scope` | text | no | 코드 literal에 맞춘 2종 + 계획 2종: `official_docs` (현재), `study_docs` (KMSC course 현재), `user_upload` (계획), `operations_docs` (PPT 운영문서 계획). |
| `document_slug` | text | no | 안정 식별 키 (예: `advanced_networking`, `pbs_intro_deck`). |
| `book_slug` | text | yes | 공식문서 book 식별자 (예: `nodes`, `storage`). 운영문서/업로드는 NULL 또는 deck slug. |
| `title` | text | no | 표시용 제목. |
| `summary` | text | yes | 문서 1줄 요약. AI 생성 가능. |
| `source_url` | text | yes | 인용용 원본 URL. |
| `viewer_artifact_path` | text | yes | 뷰어 산출물 경로 (뷰어가 있을 때만). |
| `locale` | text | yes | 언어. |
| `ocp_version` | text | yes | 적용 OCP/제품 버전. |
| `domain` | text | yes | 아래 enum. |
| `platform` | text | yes | 아래 enum. nullable — 비-환경 의존 문서는 NULL. |
| `doc_type` | text | no | 아래 enum. |
| `review_status` | text | no | `approved` / `needs_review`. 실제 corpus에 mixed 값 존재. |
| `source_lane` | text | no | `official_ko` / `applied_playbook` / `user_upload` (계획). corpus 합성 라인 구분. |
| `facets` | jsonb | no | 도메인별 facets (아래 shape). |
| `metadata` | jsonb | no | 확장 (아래 허용 키). |
| `created_at` | timestamptz | no | 감사. |
| `updated_at` | timestamptz | no | 감사. |

**제거된 컬럼 (Reality Check 기준):**
- `audience_level`, `task_intent`, `lifecycle_phase`, `privilege_scope` — 현재 데이터에 없고 ingestion이 부여하지도 않음. enrichment phase가 도입되는 시점에 추가.
- `summary`, `trust_score` — 의미 있는 값이 안 채워짐.

### enum: `domain`

실제 34권의 book_slug에서 도출된 enum. import 시 book_slug → domain 매핑 표(아래)로 결정적으로 채운다.

```text
install            설치 (installation_overview, installing_*, postinstallation_configuration, disconnected_environments, hosted_control_planes)
upgrade            업그레이드 (updating_clusters)
networking         네트워킹 (networking_overview, advanced_networking, ingress_and_load_balancing)
storage            스토리지 (storage)
operators          오퍼레이터 (operators)
security           보안·인증·권한 (security_and_compliance, authentication_and_authorization)
monitoring         모니터링·관측 (monitoring, observability_overview)
logging            로깅 (logging)
backup_restore     백업·복구 (backup_and_restore, etcd)
troubleshooting    지원·검증 (support, validation_and_troubleshooting)
nodes              노드·머신 (nodes, machine_configuration, machine_management)
registry           레지스트리·이미지 (registry, images)
ui_tooling         CLI·콘솔·API (cli_tools, web_console, api_overview)
architecture       아키텍처·개념 (architecture, overview, ai_workloads)
release_notes      release_notes
```

15종. 책 추가/축소 시 본 표 갱신.

### enum: `platform`

한국어 운영위키 34권에 실제로 존재하는 install 환경만 enum에 둔다. (`installing_on_azure` 같은 책이 한국어 corpus에 없기 때문에 aws/azure/gcp/vmware는 넣지 않는다.)

```text
bare_metal      installing_on_bare_metal 계열
any_platform    installing_on_any_platform (UPI/platform-agnostic)
agent_based     agent-based installer 계열
none            환경 무관 (대부분의 비-설치 책)
```

대부분의 chunk는 `platform=none` 또는 NULL이다. 한국어 corpus가 cloud provider 별 설치 책을 포함하면 그 시점에 enum을 확장한다. **provider 컬럼은 두지 않는다** — platform과 중복이라 코드에서 두 개 다 들고 다니면 라우팅 로직만 복잡해진다.

사내 PPT 운영문서가 실제로 Azure/AWS 등 cloud-specific 명령을 포함하면 그 값은 `facets.install.cloud_specific = "azure"` 같은 facet으로 기록한다. 컬럼 enum을 늘리지 않는다.

**book_slug → platform 매핑 (한국어 공식 corpus 34권 기준):**

| book_slug | platform |
| --- | --- |
| `installing_on_bare_metal` | `bare_metal` |
| `installing_on_any_platform` | `any_platform` |
| `installing_an_on-premise_cluster_with_the_agent-based_installer` | `agent_based` |
| `installation_overview`, `postinstallation_configuration`, `disconnected_environments`, `hosted_control_planes` | `none` (chunk 단위로 더 좁힐 수 있으면 좁힘) |
| 그 외 30권 (nodes, storage, operators, networking 등) | `none` 또는 NULL |

### enum: `doc_type`

Playbook Library는 UI 표면이지 doc_type이 아니다. Library에 진열되는 34권은 전부 `official_doc`이다.

```text
official_doc       Red Hat 공식 docs (22082 chunk, source_lane=official_ko)
manual_synthesis   applied_playbook 합성 corpus (5825 chunk, 현재 review_status=needs_review가 다수)
operations_doc     사내 PPT 운영문서 (계획 — 현재 데이터에 미존재)
user_upload        사용자 업로드 (계획 — 현재 데이터에 미존재)
```

현재 corpus의 `source_type`이 실제로 가지는 2종(`official_doc`, `manual_synthesis`)을 그대로 채택하고, PPT/업로드 라인은 v0.1.4 schema에서 enum 값으로 미리 예약. `runbook`, `lab_guide`, `reference`, `troubleshooting_note`, `playbook`, `slide_deck`, `release_note`는 enum에 두지 않는다. `release_notes`는 별도 doc_type이 아니라 `book_slug=release_notes`로 식별한다.

### 무엇을 컬럼으로, 무엇을 facets로

**컬럼 — operating wiki 전체에 적용되는 broad facets:**
- `domain`, `book_slug`, `platform`, `ocp_version`, `locale`, `doc_type`, `source_lane`, `review_status`
- 모든 검색 라우팅·access·인용·필터에 직접 쓰인다.

**facets jsonb — 특정 책/도메인에서만 의미 있는 값:**
- `facets.install.scope` (`bare_metal`, `any_platform`, `agent_based`, `post_install`, `disconnected`, `hosted_control_plane`) — 한국어 corpus의 실제 install 책 구분
- `facets.install.cluster_topology` (`single_node`, `compact`, `multi_node`)
- `facets.install.network_mode` (`ovn_kubernetes`, `openshift_sdn`)
- `facets.install.environment` (`connected`, `disconnected`, `restricted_network`)
- `facets.install.cloud_specific` — 사내 PPT가 cloud-specific 명령을 포함할 때만 (`azure`, `aws`, `gcp`, `vsphere`). 공식 docs에서는 비움.
- `facets.nodes.node_role`, `facets.nodes.machine_config_pool`
- `facets.operators.operator_name`, `facets.operators.channel`
- `facets.storage.storage_class`, `facets.storage.csi_driver`
- `facets.security.identity_provider`, `facets.security.rbac_scope`
- `facets.networking.ingress`, `facets.networking.network_policy`
- `facets.backup_restore.backup_tool`, `facets.backup_restore.restore_scope`

`facets` jsonb는 위 키만 받는다. 새 facet group이 필요하면 본 문서에 추가한 뒤 import.

### `metadata` jsonb 허용 키

```json
{
  "source_manifest_id": "ocp_ko_4_20",
  "approval_note": "official translated source",
  "generation_notes": ["normalized from official source"],
  "chunking_strategy": "heading-aware-v1",
  "deck_template_family": "playbook_studio_v1",
  "upload_review_state": "auto_imported"
}
```

검색·인용·라우팅에 쓰이는 값을 이 metadata에 숨기지 않는다.

### 왜 `trust_score`가 없고 `review_status`가 있는가

`review_status`는 **있다.** 실제 corpus에 `approved`(24,208)와 `needs_review`(3,699)가 공존한다 — `applied_playbook` source_lane이 `needs_review` 상태로 들어와서 mixed가 진짜다. 컬럼으로 유지.

`trust_score`는 **없다.** 실제 27,907개 모두 `1.0` 상수라 정보량이 0이다. 사용자 업로드/AI 생성/공식문서를 함께 ranking하는 mixed-trust retrieval이 도입되는 시점에 추가한다.

`source_lane`(`official_ko`/`applied_playbook`/`user_upload`)이 corpus 라인 구분을, `review_status`(`approved`/`needs_review`)가 품질 게이트를, `visibility`가 access boundary를 각각 담당한다.

---

## `corpus_chunks`

### 의미

검색의 기본 단위. 한 문서가 보통 10~500개 chunk를 가진다. chunk 1개는 보통 한 섹션·한 절차·한 슬라이드에 해당한다.

**중요한 변경**: chunk의 본문은 더 이상 단일 markdown blob이 아니다. 본문은 `corpus_chunk_segments`에 ordered typed row로 저장되고, `corpus_chunks` 테이블은 검색 신호와 메타데이터만 가진다.

`embedding_text`만 chunk 테이블에 둔다 — segments에서 derived지만 embedding 생성 후 재계산 비용을 피하기 위해 캐시.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | chunk 식별자. |
| `corpus_document_id` | uuid | no | 부모 문서. |
| `parsed_document_id` | uuid | yes | parsing 추적용. |
| `source_block_ids` | jsonb | no | 어떤 `document_blocks.id` 들을 묶었는지 배열. |
| `chunk_key` | text | no | 문서 내 안정 키 (예: `verifying-connectivity-endpoint`). |
| `ordinal` | integer | no | 문서 순서. |
| `chunk_type` | text | no | 아래 enum. |
| `chunk_role` | text | no | 아래 enum. |
| `parent_chunk_id` | uuid | yes | 계층 chunk. |
| `navigation_only` | boolean | no | true면 retrieval에서 제외(목차 chunk 등). |
| `title` | text | no | chunk 제목. 보통 가장 가까운 섹션 제목. |
| `section_title` | text | yes | 섹션 제목(별도 보존). |
| `chapter_title` | text | yes | 챕터 제목. |
| `section_path` | jsonb | no | 섹션 경로 배열 (예: `["Installing", "Azure", "Create install config"]`). |
| `section_number` | text | yes | "1.2.3". |
| `source_anchor` | text | yes | 원본 anchor (`chunks.jsonl`의 `anchor` 필드). |
| `source_url` | text | yes | 인용 URL(문서에서 상속하지만 anchor가 다를 수 있어 별도). |
| `viewer_artifact_path` | text | yes | 뷰어 점프 경로. |
| `raw_text` | text | yes | 원본 텍스트 보존(재청킹·재임베딩의 입력). `[CODE]` 같은 parser 마크업 포함 가능. 임베딩·검색에 안 씀. |
| `markdown` | text | yes | 사용자 표시용 markdown. 코드 펜스/표/캡션 포함. 챗봇 카드 렌더링 input의 하나(주요 input은 segments). |
| `normalized_text` | text | no | BM25/keyword 검색용 cleaned text. 코드 펜스 ```` ``` ````·태그·중복 공백·NBSP·section label 제거됨. 한국어 NFC 정규화 적용. |
| `embedding_text` | text | no | 벡터 임베딩 전용. `[title]\\n[section_context]\\n[normalized_text의 의미 본문]` 형태. 펜스·언어 태그·viewer path 제거. |
| `token_count` | integer | no | `embedding_text` 토큰 수. |
| `book_slug` | text | yes | 검색 필터 (chunks.jsonl `book_slug` 직접 매핑). |
| `domain` | text | yes | 검색 필터 (문서에서 상속). |
| `platform` | text | yes | 환경 필터 (문서에서 상속). |
| `ocp_version` | text | yes | 버전 필터. |
| `doc_type` | text | no | 문서에서 상속. |
| `facets` | jsonb | no | 문서 facets에서 상속 + chunk 단위 보강. |
| `cli_commands` | jsonb | no | 명령어 배열 (예: `["oc get pvc <name>", "oc describe pvc <name>"]`). 현재 55.2%에 채워짐. RetrievalHit과 같은 이름. |
| `k8s_objects` | jsonb | no | 등장한 K8s/OCP 객체 이름 배열 (`Pod`, `Deployment`). 현재 44.4% 채워짐. |
| `operator_names` | jsonb | no | Operator 이름 배열. 현재 23.1% 채워짐. |
| `error_strings` | jsonb | no | 트러블슈팅 키워드 배열 (`TCPConnectError`). 현재 4.8%, troubleshooting chunk에서. |
| `verification_hints` | jsonb | no | "이렇게 보면 정상" 힌트 배열. 현재 45.5% 채워짐. |
| `beginner_narrative` | text | yes | 학습자용 풀어쓴 설명 (KMSC enrichment에서 부여). |
| `metadata` | jsonb | no | 확장. |
| `created_at` | timestamptz | no | 감사. |
| `updated_at` | timestamptz | no | 감사. |

### enum: `chunk_type`

실제 corpus 5종 + 향후 PPT/troubleshooting 라인용 1종.

```text
command         단일 명령 중심 (45%)
procedure       절차 (31%)
concept         개념 설명 (14%)
reference       참고/레퍼런스 (5%)
troubleshooting 트러블슈팅 (5%)
```

`warning` (실제 3개), `navigation`, `example`은 enum에 두지 않는다. 필요해지면 추가.

### enum: `chunk_role`

DB ingestion이 실제로 부여하는 2종만.

```text
parent  상위 chunk (섹션 헤딩, navigation 후보)
leaf    말단 retrieval chunk
```

`summary`, `navigation`은 enum 미사용.

### 라벨링 전략

`task_intent`, `lifecycle_phase`, `audience_level`, `privilege_scope`는 **v0.1.4 schema에 두지 않는다**. 현재 데이터에 없고 ingestion도 부여하지 않는다. enrichment phase(v0.1.5+)에서 휴리스틱·AI 라벨링이 도입되는 시점에 컬럼 또는 facets 키로 추가한다.

대신 현재 사용 가능한 라우팅 신호는:
- `chunk_type` (command/procedure/concept/reference/troubleshooting)
- `book_slug` + `domain` (책·도메인)
- `cli_commands` / `k8s_objects` / `operator_names` / `error_strings` / `verification_hints` (이미 채워져 있음)

이 정도로도 agent prompt의 `_intent_shape_hint`가 동작한다.

### Document vs Chunk Metadata Boundary (denormalize 규칙)

**규칙**

1. **`corpus_documents`가 문서 속성의 source of truth.**
2. 검색 라우팅·access·필터에 청크별로 필요한 문서 속성은 `corpus_chunks`에 **denormalize 컬럼**으로 복사 저장한다. Qdrant는 point(=청크) 단위로만 필터링하므로 청크 payload에 문서 속성이 들어가 있어야 검색이 동작한다.
3. import 시점 + 문서 속성 갱신 시 같은 문서의 모든 청크에 SQL UPDATE로 propagate. 임베딩 재생성은 불필요(필터 메타데이터만 바뀜) — Qdrant payload만 다시 set.

**필드 출처별 분류**

| 그룹 | corpus_documents에 저장 | corpus_chunks에 저장(denormalize) | Qdrant payload | 비고 |
| --- | --- | --- | --- | --- |
| 문서 고유 (Document-only) | ✓ | ✗ | ✗ | document_slug, title(문서 전체), summary, source_url(문서), viewer_artifact_path(문서), normalized_text(문서 전체) |
| Document → Chunk denormalize | ✓ source | ✓ copy | ✓ | book_slug, domain, doc_type, platform, ocp_version, locale, corpus_scope, visibility, source_lane, review_status, facets(문서 baseline) |
| 청크 고유 (Chunk-only) | ✗ | ✓ | ✓ | title(섹션 제목), section_path, section_anchor, ordinal, chunk_type, chunk_role, navigation_only, parent_chunk_id, cli_commands, k8s_objects, operator_names, error_strings, verification_hints, env_scope_present, env_scope_summary, facets(청크 override) |
| 본문 텍스트 | ✗(요약만) | ✓ | `text` + `text_fields` | 런타임 호환용 payload `text`는 embedding_text 문자열, `text_fields`는 normalized_text/embedding_text 스냅샷 |

**왜 denormalize인가**

- Qdrant는 join을 지원하지 않는다. point 자체에 모든 filter 값이 있어야 한다.
- 같은 문서 청크 수십~수천 개에 같은 값이 반복 저장된다 — 디스크는 싸고, 검색은 빠르다.
- 일관성: 문서 속성이 바뀌면 `UPDATE corpus_chunks SET ... WHERE corpus_document_id = ?` 한 번 + 그 청크들의 Qdrant payload set 한 번이면 끝. 임베딩 벡터는 안 건드림.

**import code 의무**

`corpus_chunks` row를 INSERT할 때 위 denormalize 컬럼은 반드시 `corpus_documents`에서 읽어와 채운다. NULL로 두면 안 됨. 문서 속성 변경 시 propagate 트리거가 없는 단순 INSERT만 있으면 stale 위험.

### Text 4계층 계약 (현재 단일 필드 문제 해결)

**현재 문제 (코드 검증 결과):**

`official_gold_import.py:632-633`에서 `markdown = embedding_text = chunk_text` 한 값을 두 컬럼에 그대로 둔다. `chunk_text`는 `_normalized_chunk_text(row)`의 출력인데, 이 함수는 `render_internal_markup_for_retrieval`을 통해 `[CODE language="shell"]oc get pvc[/CODE]`를 `` ```shell\noc get pvc\n``` ``로만 바꾼다. 즉 임베딩 모델이 `\`\`\`shell` 같은 펜스 토큰과 언어 태그를 그대로 학습한다.

또한 raw `chunks.jsonl.text`의 `[CODE`(12,436) vs `[/CODE`(13,377) **비대칭**은 chunking 경계에서 일부 chunk가 마크업 절반만 가진 채로 잘렸음을 의미한다. 그 chunk들의 embedding은 더 망가져 있다.

**v0.1.4 4계층 분리:**

| 컬럼 | 무엇이 들어가나 | 어디서 쓰이나 | 임베딩 입력? |
| --- | --- | --- | --- |
| `raw_text` | 원본 그대로 (parser 마크업 포함 가능, JSONL의 `text` 필드 그대로 보존) | 재청킹·재임베딩 input, 원본 재구성, audit | 안 씀 |
| `markdown` | 사용자 표시용. ```` ``` ```` 펜스/표/캡션 포함 | 챗봇 카드 fallback, viewer 렌더 | 안 씀 |
| `normalized_text` | BM25/keyword 검색용. cleaned readable text. **펜스 토큰·HTML 태그·NBSP·중복 공백·section label·anchor URL 제거**, NFC 정규화 | BM25, keyword filter, reranker input의 prose 파트 | 직접 안 씀 (embedding_text의 base) |
| `embedding_text` | 벡터 전용. `title \n section_context \n normalized_text(의미 본문만)` | 임베딩 모델 input, Qdrant payload `"text"` | **유일한 input** |

**Normalization pipeline (raw_text → normalized_text):**

```text
1. NFC 유니코드 정규화 (한국어 자모 결합 일관성)
2. NBSP(U+00A0) → 일반 공백
3. 제로폭 문자(U+200B, U+200C, U+200D, U+FEFF) 제거
4. `[CODE language="..."]...[/CODE]`, `[TABLE]...[/TABLE]` 마크업 제거 (펜스도 함께 제거 — markdown 컬럼 전용)
5. anchor/viewer URL hex (`%ED%95%9C%EA%B5%AD`) 제거
6. 연속 공백 1개로 압축, 줄 시작/끝 공백 trim
7. 3개 이상 연속 개행 2개로 압축
8. 문서/섹션 라벨 중복 제거 (예: 첫 줄에 "보안 및 컴플라이언스 > 1.2..." 같은 breadcrumb 라인)
```

**Embedding text composition (normalized_text → embedding_text):**

```text
[title]
[chapter_title > section_title]
[normalized_text의 의미 본문 (코드 출력 예시 제외, 명령 자체는 포함)]
[cli_commands 1줄 join, 명령만 (placeholder 포함 OK)]
```

- 코드 펜스, 언어 태그, anchor URL, viewer path, file path는 절대 포함 안 함.
- 명령은 의미 신호이므로 포함 (예: `oc get pvc <pvc-name>` 텍스트는 검색 의미를 만든다).
- 출력 예시 표는 제외 (`STATUS Bound...` 같은 출력은 의미 신호가 아니라 노이즈).

**Validation tests (import 시 자동 실행):**

- `embedding_text`에 ```` ``` ````, `[CODE`, `[/CODE`, `[TABLE`, `[/TABLE`, `<a href`, `%E` (퍼센트 인코딩) 패턴이 나타나면 fail.
- `embedding_text` 토큰 수가 `markdown` 토큰 수의 90%를 초과하면 fail (정규화가 안 일어났다는 신호).
- raw_text에 `[CODE` 개수와 `[/CODE` 개수가 다른 chunk는 `metadata.warnings`에 `unbalanced_markup` 기록.

### `cli_commands` 와 `corpus_chunk_commands` 의 관계

`corpus_chunks.cli_commands`는 chunk 단위의 **검색 신호** — 텍스트 배열로 BM25/keyword 매치 입력. RetrievalHit이 그대로 노출하는 필드라 호환성을 위해 이름을 그대로 둔다.

`corpus_chunk_commands`는 같은 명령을 **구조화한 row** — `command_template`, `placeholders`, `intent`, `subject`, `env_scope`로 분해된 형태. 답변 카드 렌더링·환경 후속질문 결정에 사용.

import 흐름:
1. block_type=`code` AND block_role=`command` 블록 발견.
2. 텍스트 추출 → 정규화 → `cli_commands` jsonb 배열에 push (검색 신호용).
3. 같은 텍스트를 파싱해서 `corpus_chunk_commands` row 생성 (구조화 신호용).

같은 정보가 두 곳에 있는 게 정상이다 — 용도가 다르다.

### `metadata` jsonb 허용 키

```json
{
  "chunking_strategy": "heading-aware-v1",
  "chunking_notes": ["merged with previous heading"],
  "generation_method": "imported_from_official_jsonl",
  "translation_status": "approved_ko",
  "parent_pack_id": "openshift_container_platform-4.20-core"
}
```

(`task_intent`/`lifecycle_phase` 같은 라벨 provenance는 enrichment phase가 도입되면 그때 metadata에 추가.)

---

## `corpus_chunk_segments`

### 의미

**v0.1.4 핵심 추가**. chunk 본문을 단일 markdown blob에서 ordered typed segments로 분해한다.

현재 chunk 본문에 `[CODE language="shell"]oc get pvc[/CODE]` 마크업이 박혀 있다. 이걸 그대로 LLM에 넣으면 답변 카드에서 코드/텍스트 경계가 흐려진다. segments로 분리하면:

- 챗봇 UI가 segment 시퀀스를 그대로 카드로 렌더한다.
- LLM 프롬프트가 segments를 typed 리스트로 받는다 — "이건 prose, 이건 command, 이건 expected output" 명시.
- agent가 명령만·출력만·프로즈만 필요할 때 segments에서 filter할 수 있다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | segment 식별자. |
| `corpus_chunk_id` | uuid | no | 부모 chunk. |
| `ordinal` | integer | no | chunk 내 segment 순서. |
| `segment_type` | text | no | 아래 enum. |
| `segment_role` | text | yes | 보조 역할(prerequisite, step, verification 등). |
| `content` | text | no | segment 본문. 명령이면 명령 자체. 출력이면 출력 텍스트. 프로즈면 문장. |
| `language` | text | yes | code/output일 때 언어(`shell`, `yaml`, `json`, `text`). |
| `caption` | text | yes | code/table/image에 대한 짧은 설명. |
| `source_block_id` | uuid | yes | 원천 `document_blocks.id`. |
| `asset_id` | uuid | yes | image segment의 자산 참조. |
| `metadata` | jsonb | no | 확장. |

### enum: `segment_type`

```text
prose               일반 텍스트
command             실행 명령(코드 블록 중 명령으로 식별된 것)
command_output      명령 실행 결과 예시
code                일반 코드(yaml, json, manifest)
table               표
note                인포 박스
warning             경고
image_ref           이미지 참조 (실제 이미지는 document_assets)
```

### `segment_role` enum (보조)

```text
prerequisite step verification example caveat reference
```

### `metadata` jsonb 허용 키

```json
{
  "command_id": "uuid-of-corpus_chunk_commands-row",
  "ocr_source_asset_id": "uuid",
  "table_columns": ["NAME", "STATUS", "VOLUME"],
  "highlight": false
}
```

### 챗봇 카드 렌더링 직접 매핑

| `segment_type` | UI 카드 | LLM 프롬프트 표시 |
| --- | --- | --- |
| `prose` | 텍스트 카드 | 그대로 |
| `command` | 코드 카드 (shell 강조) | `command_template`을 그대로, 위 `caption` 한 줄 설명 |
| `command_output` | 코드 카드 (output 스타일) | "Expected output:" 라벨로 prefix |
| `code` | 코드 카드 (`language` 표시) | code fence 포함 |
| `table` | 표 카드 | markdown table |
| `note` / `warning` | admonition 카드 | "Note:" / "Warning:" prefix |
| `image_ref` | 이미지 카드 + caption | "[Image: caption]" prose로 대체 |

### Block → Segment 변환 규칙

`document_blocks`에서 `corpus_chunk_segments`로 가는 규칙:

| block_type / block_role | → segment_type | segment_role |
| --- | --- | --- |
| `paragraph` / `concept` | `prose` | — |
| `paragraph` / `procedure` | `prose` | `step` |
| `paragraph` / `verification` | `prose` | `verification` |
| `paragraph` / `prerequisite` | `prose` | `prerequisite` |
| `code` / `command` | `command` | — |
| `code` / 기타 | `code` | — |
| `code_output` / * | `command_output` | — |
| `list_item` / `procedure` | `prose` | `step` |
| `table` / * | `table` | — |
| `note` / * | `note` | — |
| `warning` / * | `warning` | — |
| `image` / `figure` | `image_ref` | — |
| `slide_zone` (role=step) | `prose` | `step` |
| `slide_zone` (role=title) | (chunk title 후보, segment 생략) | — |
| `slide_attachment` | `image_ref` | — |

`[CODE]...[/CODE]` 인라인 마크업이 들어간 legacy text는 import 시 분해되어 `prose` + `command` + `prose` segments로 펼쳐진다. internal_markup.py의 render 함수는 v0.1.5에서 제거.

---

## `corpus_chunk_commands`

### 의미

chunk segments 중 `command` segment에서 추출된 구조화된 명령 row. 같은 명령이 chunk 안에 여러 번 나오면 ordinal로 구분.

**핵심 목적**: 환경 의존 명령(Azure secret 생성 같은)을 메타데이터로 라벨링해 답변 시 사용자 세션의 platform과 비교해서 노출 여부를 결정. 미스매치 시 환경 후속질문(`env_clarification`) 자동 생성.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 명령 row 식별자. |
| `corpus_chunk_id` | uuid | no | 부모 chunk. |
| `segment_id` | uuid | yes | 어느 segment에서 추출됐는지. |
| `ordinal` | integer | no | chunk 내 명령 순서. |
| `command_template` | text | no | 명령 원문. 예: `oc get pvc <pvc-name> -n <namespace>`. |
| `command_name` | text | no | 정규화된 동사 이름. 예: `oc get pvc`. |
| `tool` | text | no | `oc`, `kubectl`, `openshift-install`, `helm`, `podman`, `lsblk`, `journalctl`, `must-gather`. |
| `placeholders` | jsonb | no | 플레이스홀더 정의 (아래 shape). |
| `intent` | text | no | `verify`, `create`, `delete`, `configure`, `troubleshoot`, `observe`, `cleanup`, `install`. |
| `subject` | text | yes | 대상 리소스 (`pvc`, `pod`, `secret`, `route`, `clusterrolebinding`). |
| `env_scope` | jsonb | no | 환경 의존성 (아래 shape). |
| `requires_env_clarification` | boolean | no | env_scope가 있고 ambiguity가 있으면 true. |
| `expected_output_segment_id` | uuid | yes | 이 명령의 출력 예시 segment를 가리킴. |
| `verification_segment_id` | uuid | yes | 이 명령 결과 판정 segment를 가리킴. |
| `metadata` | jsonb | no | 확장. |

### `placeholders` jsonb shape

```json
[
  {"key": "pvc-name", "description": "PVC 이름", "example": "azurefile-pvc"},
  {"key": "namespace", "description": "네임스페이스", "example": "default"}
]
```

### `env_scope` jsonb shape

```json
{
  "platform": ["bare_metal"],
  "install_scope": ["agent_based"],
  "cloud_specific": ["azure"],
  "cluster_topology": null,
  "applies_when": "Azure File 스토리지를 사용하는 사내 운영문서에서만"
}
```

키 의미:
- `platform`: `corpus_documents.platform` enum과 같음 (`bare_metal`, `any_platform`, `agent_based`, `none`).
- `install_scope`: `facets.install.scope` 와 같음.
- `cloud_specific`: 한국어 공식문서에는 없지만 사내 PPT 운영문서가 cloud-specific 명령을 포함할 때 사용 (`azure`, `aws`, `gcp`, `vsphere`).
- `cluster_topology`: SNO/compact 등에서만 의미 있는 명령일 때.

null 또는 미존재 키는 "모든 환경에 해당"으로 해석. `env_scope`가 비어 있거나 모든 키가 null이면 환경 무관 명령 — 답변에 항상 노출.

### `intent` enum

현재 corpus에서 명령을 분류해본 결과 5종이면 충분하다(상위 verb 빈도 기반). 추가 분류는 enrichment phase에서.

```text
verify       oc get, oc describe, oc logs, oc adm top, oc get events
create       oc apply, oc create
configure    oc edit, oc patch, oc set
delete       oc delete
troubleshoot oc adm inspect, oc adm must-gather
```

`install`, `cleanup`, `observe`는 별도 enum값 안 둠. install은 `openshift-install` tool로 식별, 나머지는 verify/delete로 흡수.

### `tool` enum

실제 `cli_commands` 89%가 `oc`, 8%가 `oc adm`, 0.1%가 `kubectl`이다. 나머지는 추출 노이즈. enum은 현재 corpus가 실제로 가진 3종 + PPT 운영문서가 가져올 수 있는 4종.

**현재 데이터:**
```text
oc       oc xxx
oc-adm   oc adm xxx
kubectl  kubectl xxx (75개만, 사실상 미미)
```

**계획 (PPT 운영문서·향후 corpus):**
```text
openshift-install  설치용
podman             빌드/이미지
helm               차트 배포
must-gather        진단 번들
```

`tool=null`은 분류 실패 시 허용 (현재 `oc\n[/CODE]` 같은 추출 노이즈에서 발생).

### `metadata` jsonb 허용 키

```json
{
  "extraction_method": "ast_parse_v1",
  "extraction_confidence": 0.92,
  "raw_text_offset": 117,
  "normalization_notes": ["replaced <SECRET_NAME> with <secret-name>"]
}
```

### 환경 후속질문 결정 로직

답변 생성 시 사용되는 의사 코드:

```
selected_commands = [c for c in chunk.commands if matches_session_env(c, session)]
ambiguous_commands = [c for c in chunk.commands if c.requires_env_clarification and session.platform is None]

if ambiguous_commands and not selected_commands:
    suggest_followup(type="env_clarification", question="현재 설치환경이 어떻게 되십니까?", options=["Azure", "vSphere", "baremetal", "AWS", "GCP"])
elif ambiguous_commands and selected_commands:
    render selected_commands only
    suggest_followup(type="env_clarification", question="다른 환경(예: vSphere) 명령도 보시겠어요?")
else:
    render all commands
```

이 로직이 LLM이 아닌 코드에서 결정적으로 처리되므로 환경 누수 사고가 안 난다.

---

## `corpus_chunk_refs`

### 의미

학습 그래프. "이 chunk 다음에는 무엇을 보면 좋은가", "이걸 보기 전에 뭘 알아야 하는가", "관련 chunk는 무엇인가"를 row로 저장. **chunk 내부 jsonb `next_refs` 이중 저장은 폐기** — 본 테이블이 유일한 truth.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | ref 식별자. |
| `from_chunk_id` | uuid | no | 출발 chunk. |
| `to_chunk_id` | uuid | yes | 도착 chunk (있을 때). |
| `to_document_id` | uuid | yes | chunk 단위가 아니라 문서 단위 참조일 때. |
| `ref_type` | text | no | 아래 enum. |
| `title` | text | yes | 표시용 제목. |
| `reason` | text | yes | 왜 이 ref가 있는지 (학습용 문구). |
| `ordinal` | integer | no | 같은 from_chunk_id + ref_type 안에서 순서. |
| `confidence` | numeric | yes | 생성 신뢰도 (0.0~1.0). |
| `source` | text | no | `heuristic`, `ai_generated`, `manifest_import`, `manual`. |
| `metadata` | jsonb | no | 확장. |

### enum: `ref_type`

```text
prerequisite        선수 학습
next                다음 단계(같은 시나리오 내)
related             관련 주제
verify              이 절차의 결과 확인 chunk
lab                 실습/예제 chunk
env_clarification   환경 확인 후속질문이 필요할 때 가리킬 chunk (예: install 개요 chunk)
```

(한국어 corpus에 cloud별 install 책이 없으므로 `same_task_different_platform`은 두지 않는다. 사내 PPT 운영문서가 cloud-specific 변형을 가지면 그때 추가.)

### `metadata` jsonb 허용 키

```json
{
  "generated_by": "next_step_heuristic_v1",
  "generated_at": "2026-05-15T00:00:00Z",
  "based_on": ["section_path_continuity", "chunk_type_match"]
}
```

### 생성 전략

v0.1.4 import 시 휴리스틱:

1. **`next` (같은 문서 내)**: 같은 `corpus_document_id` 내에서 `ordinal+1` chunk가 `chunk_type=procedure`/`command` 흐름이면 `next` ref를 자동 생성.
2. **`prerequisite` (같은 문서 내)**: chunk_role=parent → leaf 관계가 있으면 leaf의 prerequisite으로 parent 자동.
3. **`related` (cross-document)**: 같은 `book_slug` + 비슷한 `section_title` 키워드 매치로 휴리스틱 생성. 신뢰도 낮음(0.4~0.6).
4. **`verify`**: 같은 chunk 내의 verification segment가 있으면 segment_id로, 외부 chunk면 휴리스틱.
5. **`env_clarification`**: chunk에 `requires_env_clarification=true` 명령이 있으면, 같은 book_slug의 환경 개요 chunk(보통 `installation_overview` 또는 `installing_on_*` 책의 시작 chunk)를 자동 link.

AI 생성과 수기 큐레이션은 후속 phase. 본 v0.1.4는 휴리스틱 ref 생성까지만 정의.

### Next-Step Guidance — 데이터 모델과 흐름

**핵심 결정**: 다음 단계 안내(`next_reference`, `next_step`, 후속 학습)는 청크 payload에 **두지 않는다**. `corpus_chunk_refs` 테이블 한 곳이 source of truth.

**왜 payload에 안 두나**

| 이유 | 설명 |
| --- | --- |
| 그래프 vs 벡터 | Qdrant payload는 필터/랭킹 신호 전용. 그래프 관계는 표현 안 맞음. |
| 재인덱싱 비용 | ref가 휴리스틱→AI생성→수기로 진화하면서 자주 바뀜. payload에 박으면 매번 Qdrant 재인덱싱. |
| 한 번 더 쿼리면 충분 | retrieval(Qdrant) 1회 + ref hydration(Postgres) 1회. SQL JOIN은 매우 싸다. |

**다음 단계 출처 2가지**

| 출처 | 내용 | 어디서 | 언제 |
| --- | --- | --- | --- |
| **Structural next** | 같은 문서 내 ordinal+1 청크 | Postgres (corpus_chunks) | 항상 — ref 그래프가 비어 있어도 동작 |
| **Semantic next** | 휴리스틱·AI·수기로 만든 ref 그래프 | Postgres (corpus_chunk_refs) | ref가 만들어진 청크에만 |

structural next는 청크 payload의 `book_slug` + `ordinal`만으로 결정되므로 별도 메타데이터 불필요. semantic next는 `corpus_chunk_refs`에서 가져온다.

**Hydration 흐름**

```
사용자 질문
  ↓
Qdrant.search(top_k=10)  →  chunk_id 배열 + payload
  ↓
Postgres hydration 1: corpus_chunk_segments  (답변 카드 본문)
Postgres hydration 2: corpus_chunk_commands  (env 필터링)
Postgres hydration 3: corpus_chunk_refs      ← 여기서 next/prerequisite/related/verify
Postgres hydration 4: corpus_question_candidates  (후속질문 문구)
Postgres hydration 5: corpus_chunks(ordinal+1) (structural next fallback)
  ↓
agent prompt 합성 + 답변 카드 + 후속질문 카드
```

**Hydration SQL (다음 단계용)**

```sql
-- top hit chunk의 모든 ref를 한 번에
SELECT
  r.ref_type,                        -- next | prerequisite | related | verify | lab | env_clarification
  r.to_chunk_id,
  r.to_document_id,
  r.title         AS ref_title,
  r.reason        AS ref_reason,
  r.confidence,
  r.source        AS ref_source,     -- heuristic | ai_generated | manifest_import | manual
  r.ordinal       AS ref_ordinal,

  c2.title        AS target_chunk_title,
  c2.section_path AS target_section_path,
  c2.source_url   AS target_source_url,
  c2.viewer_artifact_path AS target_viewer_path,
  c2.book_slug    AS target_book_slug,
  c2.chunk_type   AS target_chunk_type,

  d2.title        AS target_doc_title,
  d2.source_url   AS target_doc_url
FROM corpus_chunk_refs r
LEFT JOIN corpus_chunks    c2 ON c2.id = r.to_chunk_id
LEFT JOIN corpus_documents d2 ON d2.id = r.to_document_id
WHERE r.from_chunk_id = :top_hit_chunk_id
ORDER BY
  CASE r.ref_type
    WHEN 'prerequisite' THEN 1
    WHEN 'next'         THEN 2
    WHEN 'verify'       THEN 3
    WHEN 'related'      THEN 4
    WHEN 'lab'          THEN 5
    WHEN 'env_clarification' THEN 6
  END,
  r.ordinal;
```

**Structural next fallback (ref 그래프 미완성일 때)**

```sql
-- 같은 문서 안에서 ordinal+1
SELECT id, chunk_key, title, ordinal, source_url, viewer_artifact_path
FROM corpus_chunks
WHERE corpus_document_id = :top_hit_corpus_document_id
  AND ordinal > :top_hit_ordinal
  AND navigation_only = false
  AND chunk_role = 'leaf'
ORDER BY ordinal
LIMIT 3;
```

`corpus_chunk_refs`에 row가 없어도 이 fallback이 항상 "문서 내 다음 절"을 제공한다.

**다음 문서(next document) 안내**

같은 책의 다음 큰 섹션 또는 cross-document recommendation도 같은 `corpus_chunk_refs`에서 처리:

- `ref_type='next'` + `to_document_id IS NOT NULL` (to_chunk_id는 NULL): 다음 **문서** 안내.
- `ref_type='next'` + `to_chunk_id IS NOT NULL`: 다음 **청크** 안내.

같은 SELECT 한 번에 둘 다 잡힌다 — `c2.*` 또는 `d2.*` 중 NULL 아닌 쪽을 UI 카드로 렌더.

**agent prompt에 들어가는 모습**

위 SQL 결과를 agent prompt의 `ordered_next_steps` 블록으로 직렬화:

```
ordered_next_steps:
  prerequisite [from corpus_chunk_refs.heuristic]:
    - StorageClass 확인 → /docs/.../storageclass#verify
  next [from corpus_chunk_refs.heuristic]:
    - PVC가 Bound 아닐 때 진단 → /docs/.../troubleshoot-pvc-pending
    - PVC와 PV 바인딩 관계 이해 → /docs/.../pvc-pv-binding
  verify [from corpus_chunk_refs.heuristic]:
    - oc get pvc 출력 STATUS 해석 → /docs/.../pvc-status-codes
  structural_fallback [from same document ordinal+1]:
    - 다음 절: PVC 삭제와 회수 정책
```

**UI 카드 출력**

답변 본문 카드 뒤에 자동으로 "다음 단계 안내" 카드 1개가 붙는다:

```
다음 단계 안내:
  ◦ (선수)  StorageClass 확인
  ◦ (다음)  PVC가 Bound 아닐 때 진단
  ◦ (다음)  PVC와 PV 바인딩 관계 이해
  ◦ (검증)  oc get pvc 출력 STATUS 해석
```

ref 그래프가 비어 있는 청크는 `structural_fallback`만 보여준다.

**왜 청크 payload에 `has_refs` 같은 boolean도 안 두나**

검토했지만 안 둠. 이유:

- 청크 한 개 retrieval당 Postgres ref SELECT가 어차피 1번 — boolean으로 미리 알아도 SELECT를 안 할 수 없음.
- ref가 갱신될 때마다 `has_refs` 값도 갱신해서 Qdrant payload set 필요 — 메타데이터 sync 부담만 늘어남.
- ref 그래프가 완성되면 거의 모든 청크가 has_refs=true가 되어 신호 가치 0.

`env_scope_present` 만 boolean으로 payload에 넣은 이유는 **session.platform 없을 때 SQL hit 없이 즉시 후속질문 트리거**를 결정하기 위해서 — ref와는 사용 패턴이 다르다.

**정리: next-step 메타데이터는 어디 있나**

| 무엇 | 어디 | 검색 메타데이터인가 |
| --- | --- | --- |
| 다음 청크 / 다음 문서 | `corpus_chunk_refs` (Postgres) | ✗ retrieval 후 hydration |
| 선수 학습 청크 | `corpus_chunk_refs` (Postgres) | ✗ |
| 검증 청크 | `corpus_chunk_refs` (Postgres) | ✗ |
| 관련 자료 | `corpus_chunk_refs` (Postgres) | ✗ |
| 후속 질문 문구 | `corpus_question_candidates` (Postgres) | ✗ |
| 환경 후속질문 트리거 | `env_scope_present` (Qdrant payload) | ✓ (예외) |
| 문서 내 자연 다음 절 | `ordinal` + `corpus_document_id` (Qdrant payload + Postgres) | △ payload 신호 + Postgres SELECT |

청크 검색 메타데이터에 next-step 필드가 안 보이는 건 의도된 설계다 — graph는 graph 테이블에, 벡터는 벡터 인덱스에.

---

## `corpus_question_candidates`

### 의미

Studio의 시작질문(starter)과 답변 카드 끝의 후속질문(followup)의 단일 source. 현재는 chunk의 jsonb `starter_question_candidates` 배열에 있는데, 별도 row로 빼서 품질 상태·생성 출처·중복 추적 가능하게 만든다.

### 컬럼

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 후보 식별자. |
| `corpus_chunk_id` | uuid | no | 원천 chunk. |
| `corpus_document_id` | uuid | no | 원천 문서(빠른 필터용 중복 저장). |
| `question` | text | no | 후보 질문. |
| `question_type` | text | no | `starter`, `followup`, `troubleshooting`, `command_lookup`, `learning_next`, `env_clarification`. |
| `source_basis` | text | no | `chunk_text`, `chunk_command`, `next_ref`, `image_description`, `operator_object`, `error_string`. |
| `generation_method` | text | no | `heuristic`, `ai_generated`, `curated_fallback`, `manifest_seed`. |
| `generation_model` | text | yes | AI 생성 시 모델명. |
| `generation_version` | integer | no | 생성기 버전. |
| `quality_status` | text | no | `candidate`, `approved`, `rejected`, `stale`. |
| `linked_ref_id` | uuid | yes | env_clarification 같은 경우 `corpus_chunk_refs` 참조. |
| `metadata` | jsonb | no | 확장. |
| `created_at` | timestamptz | no | 감사. |

### 운영 규칙

- Studio 시작질문: `question_type=starter` AND `quality_status=approved` 풀에서 무작위 샘플링.
- 답변 카드 후속질문: 사용된 citations의 chunk에서 `question_type IN (followup, learning_next)` AND `quality_status IN (approved, candidate)` 추출, 같은 chunk에서 최대 2개, 답변당 최대 3~4개.
- 환경 후속질문: `corpus_chunk_commands` 분석으로 동적으로 생성되거나, 이 테이블의 `question_type=env_clarification` 후보 사용.
- `quality_status=rejected`는 노출 절대 금지.

### `metadata` jsonb 허용 키

```json
{
  "generation_notes": ["derived from procedure step 1"],
  "human_review_at": null,
  "human_reviewer": null,
  "linked_segment_id": "uuid"
}
```

---

## Projection Tables

### `embedding_jobs`

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `id` | uuid | no | 잡 식별자. |
| `corpus_chunk_id` | uuid | no | 임베딩 대상. |
| `model` | text | no | 임베딩 모델 이름. |
| `model_version` | text | no | 모델 버전. |
| `status` | text | no | `queued`, `running`, `completed`, `failed`. |
| `embedding_text_hash` | text | yes | corpus_chunks.embedding_text 해시 (변경 감지). |
| `error_message` | text | yes | 실패 메시지. |
| `created_at` | timestamptz | no | 큐 시각. |
| `completed_at` | timestamptz | yes | 완료 시각. |

### `qdrant_index_entries`

| 컬럼 | 타입 | NULL | 의미 |
| --- | --- | --- | --- |
| `corpus_chunk_id` | uuid | no | 인덱싱된 chunk. |
| `collection` | text | no | Qdrant 컬렉션 이름. |
| `point_id` | text | no | Qdrant 포인트 id. |
| `vector_model` | text | no | 벡터 모델. |
| `payload_version` | integer | no | payload schema 버전. |
| `payload_hash` | text | no | payload 해시 (재인덱스 판단). |
| `indexed_at` | timestamptz | no | 마지막 인덱스 시각. |

### Qdrant payload 계약

corpus → Qdrant payload는 **deterministic projection**이다. corpus만 보고 다시 만들 수 있어야 한다.

payload 키 (v1)는 기존 `search.json` 계약을 따른다. flat payload를 주 계약으로 쓰지 않고 `source`, `classification`, `chunk`, `search_signals`, `text_fields`로 역할을 나눈다. 이 구획은 저장 구조를 보기 쉽게 하기 위한 계약이며, retrieval 단계에서는 각 구획의 일부 필드만 pre-filter에 쓴다. 다만 기존 `RetrievalHit` 호환을 위해 top-level `text`는 문자열로 유지한다.

```json
{
  "id": "청크 UUID",
  "document_id": "문서 ID",
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
    "best_for_questions": [
      "PVC가 Pending일 때 확인 방법",
      "PVC 상태 확인 명령 알려줘"
    ],
    "verification_hints": ["STATUS가 Bound인지 확인"]
  },
  "text": "기존 RetrievalHit 호환용 embedding text 문자열",
  "text_fields": {
    "normalized_text": "BM25 검색용 정규화 텍스트",
    "embedding_text": "벡터 검색용 텍스트"
  }
}
```

`text`는 기존 vector retriever와 `RetrievalHit.text` 호환을 위한 문자열 alias다. `text_fields.embedding_text`는 Qdrant vector 생성 input과 payload 디버그용 스냅샷이다. 답변 생성용 본문 truth는 여전히 `corpus_chunks` + `corpus_chunk_segments` hydration 결과다. `text_fields.normalized_text`는 BM25/keyword fallback과 reranker input에 쓴다.

#### payload 필드 생성 출처

| payload 경로 | 생성 출처 | 사용 단계 |
| --- | --- | --- |
| `source.*` | `corpus_documents`에서 청크로 denormalize한 access/source 컬럼 | metadata pre-filter |
| `classification.domain`, `locale`, `ocp_version` | 문서 domain/version/locale denormalize + chunk override | metadata pre-filter |
| `classification.book_slug` | 문서 book 식별자 | 현재 문서 검색 hard filter 또는 rank signal |
| `classification.subdomains` | enrichment. 없으면 빈 배열 | rank signal. 매우 확실할 때만 filter |
| `chunk.navigation_only` | `corpus_chunks.navigation_only` | metadata pre-filter |
| `chunk.chunk_type` | `corpus_chunks.chunk_type` | rank signal. 명시 질의일 때만 filter |
| `chunk.title`, `section_path`, `viewer_path`, `source_url` | `corpus_chunks` citation/display 컬럼 | answer citation/display |
| `search_signals.objects` | `corpus_chunks.k8s_objects`에서 projection | rank signal |
| `search_signals.operators` | `corpus_chunks.operator_names`에서 projection | rank signal |
| `search_signals.commands` | `corpus_chunks.cli_commands` + `corpus_chunk_commands.command_template` | rank signal + 답변 명령 후보 |
| `search_signals.error_states` | `corpus_chunks.error_strings`에서 projection | rank signal |
| `search_signals.verification_hints` | `corpus_chunks.verification_hints` | rank signal + 답변 검증 기준 |
| `search_signals.intent_labels`, `answer_shapes`, `cluster_phase`, `execution_target`, `best_for_questions` | v0.1.5 enrichment / Intent Agent vocabulary와 같은 controlled vocabulary | rank signal. hard filter 금지 기본 |
| `text` | `corpus_chunks.embedding_text` | legacy `RetrievalHit.text` 호환 |
| `text_fields.normalized_text` | `corpus_chunks.normalized_text` | BM25/keyword fallback |
| `text_fields.embedding_text` | `corpus_chunks.embedding_text` | vector embedding input |

#### metadata pre-filter 규칙

항상 filter에 들어가는 값:

```json
{
  "must": [
    { "key": "source.enabled_for_chat", "match": { "value": true } },
    { "key": "source.review_status", "match": { "value": "approved" } },
    { "key": "source.citation_eligible", "match": { "value": true } },
    { "key": "classification.locale", "match": { "value": "ko" } },
    { "key": "classification.ocp_version", "match": { "value": "4.20" } },
    { "key": "chunk.navigation_only", "match": { "value": false } }
  ]
}
```

Intent Agent confidence가 높을 때만 filter에 추가하는 값:

```json
{
  "must": [
    { "key": "classification.domain", "match": { "value": "storage" } }
  ]
}
```

`classification.book_slug`는 사용자가 현재 문서를 열고 있거나 문서명을 명시했을 때만 hard filter다. 일반 질문에서는 `book_slug_candidates`를 rank scoring에만 쓴다.

기본적으로 hard filter에 쓰지 않는 값:

```text
search_signals.objects
search_signals.error_states
search_signals.intent_labels
search_signals.answer_shapes
search_signals.commands
search_signals.best_for_questions
```

이 값들은 추출 누락 가능성이 있어 정답 후보를 제거하지 않고 rank scoring에서 점수화한다.

#### Intent Agent controlled vocabulary

`search_signals.intent_labels`와 `search_signals.answer_shapes`는 자유 생성 금지. Intent Agent와 corpus enrichment는 같은 vocabulary를 사용한다.

```json
{
  "intent_labels": [
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
  ],
  "answer_shapes": [
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
}
```

#### end-to-end 사용 예: PVC Pending

사용자 질문:

```text
PVC가 Pending인데 뭐 확인해야 해?
```

Intent Agent 추출:

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
    "book_slug_candidates": 0.72,
    "objects": 0.95,
    "error_states": 0.93,
    "intent_labels": 0.88,
    "answer_shapes": 0.84
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

Vector query:

```text
PVC Pending 상태 확인 OpenShift PersistentVolumeClaim StorageClass volume binding oc get pvc oc describe pvc troubleshooting
```

Rank scoring:

```python
score = hit.score
payload = hit.payload

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

`payload_version=1` 고정. payload schema가 바뀌면 +1 하고 재인덱스.

---

## Chatbot Output Card Contract

### 답변 응답 shape (확장)

기존 `AnswerResult`는 `answer: str` 단일 필드를 가진다. v0.1.4에서 다음을 추가:

```python
@dataclass
class AnswerCard:
    card_type: str        # "prose" | "command" | "command_output" | "code" | "table" | "note" | "warning" | "image"
    content: str
    language: str | None  # code/command 카드일 때
    caption: str | None
    citation_indices: list[int]
    command_id: str | None  # command 카드일 때 corpus_chunk_commands.id

@dataclass
class FollowupSuggestion:
    question: str
    question_type: str    # "next" | "related" | "env_clarification" | "verify"
    candidate_id: str | None
    env_options: list[str] | None  # env_clarification일 때

@dataclass
class AnswerResult:
    ...existing fields...
    cards: list[AnswerCard]                    # 새로 추가
    followups: list[FollowupSuggestion]        # 새로 추가
```

기존 `answer: str`은 cards를 markdown으로 직렬화한 호환용 값으로 유지. 새 UI는 `cards` 배열을 사용.

### 카드 생성 흐름

1. retrieval로 top-k `RetrievalHit` 확보.
2. 각 hit의 `corpus_chunks.id`로 `corpus_chunk_segments` 조회 (ordinal 순).
3. LLM 프롬프트에는 segments를 typed 리스트로 직렬화해 전달 (아래 프롬프트 섹션).
4. LLM이 인용한 chunk들의 segments를 추리고, 환경 의존 명령은 session.platform과 비교해 필터링.
5. segments → AnswerCard 매핑은 위 segment_type 표 그대로.
6. followups는 (a) `corpus_chunk_refs`에서 `ref_type=next/related`, (b) `corpus_chunk_commands.requires_env_clarification`이 사용된 chunk에 있으면 env_clarification 카드 추가, (c) `corpus_question_candidates`에서 사용 chunk의 followup 후보 합쳐 dedup.

### 사용자의 PV 시나리오에서 카드 출력

질문: "PV와 볼륨은 처음에 어디서 확인하면 돼?"

세션: `session.platform = null` (사용자가 환경 미지정).

retrieval → chunk A (PVC 상태 확인 일반 절차), chunk B (Azure file PVC 설정).

chunk A의 segments:
1. `prose`: "PV/PVC를 처음 확인할 때는 클러스터에 등록된 PVC 상태부터 봅니다."
2. `command`: `oc get pvc <pvc-name> -n <namespace>` (env_scope 없음 → 노출)
3. `prose`: "STATUS가 Bound가 아니면 다음 명령으로 자세한 원인을 봅니다."
4. `command`: `oc describe pvc <pvc-name> -n <namespace>` (env_scope 없음 → 노출)
5. `command_output`: 표 출력 예시

chunk B의 segments (사내 PPT 운영문서에서 추출됐다고 가정. 한국어 공식 docs에는 Azure 책이 없으므로 공식 corpus에서는 이런 명령이 나오지 않는다):
1. `prose`: "Azure File을 사용하는 경우 storage account 인증을 위한 secret을 만듭니다."
2. `command`: `oc create secret generic azure-secret -n <namespace> --type=Opaque --from-literal=azurestorageaccountname=... ` (env_scope=`{cloud_specific: ["azure"]}` → 세션에 cloud 환경 정보가 없으므로 **숨김**)
3. `prose`: "..."

→ 출력 cards:
```
[prose] PV/PVC를 처음 확인할 때는 클러스터에 등록된 PVC 상태부터 봅니다.
[command] oc get pvc <pvc-name> -n <namespace>
[prose] STATUS가 Bound가 아니면 다음 명령으로 자세한 원인을 봅니다.
[command] oc describe pvc <pvc-name> -n <namespace>
[command_output] NAME STATUS VOLUME ...
                 pvc-name Bound pv-azurefile ...
```

→ 출력 followups:
```
- Bound가 아닌 PVC는 어떻게 진단하나요?         (next ref from chunk A)
- StorageClass는 어떻게 확인하나요?              (related ref from chunk A)
- 현재 설치환경이 어떻게 되십니까?               (env_clarification — chunk B에 환경 의존 명령이 있어서)
  옵션: bare-metal / any-platform (UPI) / agent-based / 기타(클라우드)
```

사용자가 답하면 그 값이 세션에 저장되고 다음 턴부터 해당 환경 명령이 포함됨. "기타(클라우드)"를 고르면 cloud_specific(azure/aws/gcp/vsphere) 옵션을 한 번 더 묻는다 — 한국어 공식 docs에는 cloud별 install 책이 없으므로 cloud-specific 명령은 사내 PPT 운영문서에서만 나오기 때문.

---

## Agent Prompt Changes

### 현재 프롬프트의 한계

현재 `answering/prompt.py`는 citations를 prompt_context에 markdown 텍스트로 직렬화한다. citation에는 `cli_commands`, `verification_hints`가 들어 있지만 본문 텍스트 안에 `[CODE]` 마크업이 박혀 있어 LLM이 prose/command 경계를 혼동한다.

system 메시지에 `[CODE], [/CODE], [TABLE], [/TABLE] 같은 내부 태그는 그대로 노출하지 말고 markdown 코드 블록이나 자연어로 바꿔라` 라는 우회 지시가 있는데, segment 분리 후에는 이 지시 자체가 불필요해진다.

### 새 프롬프트 계약 (v0.1.4)

context_bundle.prompt_context에 chunk를 다음 shape으로 직렬화:

```text
[Source 1] (book=advanced_networking, section=끝점 연결 확인, doc_type=official_doc)
prose: PV/PVC를 처음 확인할 때는 클러스터에 등록된 PVC 상태부터 봅니다.
command [oc, intent=verify, subject=pvc]: oc get pvc <pvc-name> -n <namespace>
prose: STATUS가 Bound가 아니면 자세한 원인을 봅니다.
command [oc, intent=verify, subject=pvc]: oc describe pvc <pvc-name> -n <namespace>
command_output: NAME STATUS VOLUME CAPACITY ACCESS MODES STORAGECLASS AGE
                pvc-name Bound pv-azurefile 5Gi ReadWriteMany my-sc 7m2s

[Source 2] (doc_type=operations_doc, section=Azure file PVC 셋업, env_cloud=azure)
prose: Azure file은 secret이 필요합니다.
command [oc, intent=create, subject=secret, env_scope={cloud_specific: [azure]}]: oc create secret generic azure-secret ...

ordered_cli_commands_for_user_session:
  1. oc get pvc <pvc-name> -n <namespace>   (verify)
  2. oc describe pvc <pvc-name> -n <namespace>   (verify)

env_filtered_out:
  - oc create secret generic azure-secret ... (reason: session.platform unknown)

verification_hints:
  - STATUS=Bound 이면 정상
```

system 프롬프트 변경:
- `[CODE]` 마크업 관련 우회 지시 제거.
- "근거에 segment_type=command로 표시된 항목만 코드 블록으로 보여라. prose는 자연어로 답하라." 추가.
- "env_filtered_out에 있는 명령은 답변에 포함하지 마라. 그 명령이 환경별이라는 사실은 followup에서 처리된다." 추가.
- "ordered_cli_commands_for_user_session의 순서를 유지하라"는 기존 지시 유지.

### LLM 응답 → cards 변환

LLM은 markdown으로 답하지만, 답변 후처리에서 prose 문단과 fenced code block을 다시 segments shape으로 파싱해 `AnswerCard` 배열을 만든다. 단, prose-code 경계가 LLM 출력에서 흐려졌으면 (드물지만) fallback으로 citations의 segments를 그대로 사용한다.

### Retrieval Hit / Citation 호환

기존 dataclass 필드(`cli_commands`, `k8s_objects`, `verification_hints`, `error_strings`, `operator_names`, `block_kinds`, `navigation_only`, `parent_chunk_id`, `child_chunk_ids`, `starter_question_candidates`, `followup_question_candidates`)는 모두 v0.1.4 corpus_chunks 컬럼 또는 derived view에서 채울 수 있다:

| dataclass 필드 | corpus v0.1.4 source |
| --- | --- |
| `cli_commands` | `corpus_chunks.cli_commands` (이름 그대로). 답변 카드용 구조화 명령은 `corpus_chunk_commands`에 별도. |
| `k8s_objects` | `corpus_chunks.k8s_objects` |
| `verification_hints` | `corpus_chunks.verification_hints` |
| `error_strings` | `corpus_chunks.error_strings` |
| `operator_names` | `corpus_chunks.operator_names` |
| `block_kinds` | `corpus_chunk_segments` 의 distinct `segment_type` 배열 |
| `navigation_only` | `corpus_chunks.navigation_only` |
| `parent_chunk_id` | `corpus_chunks.parent_chunk_id` |
| `child_chunk_ids` | `corpus_chunks` 에서 `parent_chunk_id=self.id` 인 행 id 배열 |
| `starter_question_candidates` | `corpus_question_candidates` (question_type=starter, approved) |
| `followup_question_candidates` | `corpus_question_candidates` (question_type=followup/learning_next, approved/candidate) |
| `beginner_narrative` | `corpus_chunks.beginner_narrative` |
| `source_url` / `viewer_path` | `corpus_chunks.source_url` / `viewer_artifact_path` |
| `learning.next_refs` (legacy jsonb) | `corpus_chunk_refs` where ref_type=next |

기존 retrieval/answering 코드는 dataclass 시그니처를 그대로 두고, hydration 쿼리만 corpus_* 테이블로 바꾸면 호환 유지.

---

## 운영 시나리오 Dry-Run

### 시나리오 A — "OCP가 뭐야?" (개념)

retrieval → chunk(`book_slug=architecture`, `domain=architecture`, `chunk_type=concept`, `beginner_narrative` 채워짐), segments=[prose×3].

cards:
```
[prose] OpenShift Container Platform은 Red Hat이 제공하는 엔터프라이즈 Kubernetes 플랫폼입니다.
[prose] 핵심 구성은 control plane, worker nodes, OpenShift API server, Operator 기반 관리 컴포넌트입니다.
[prose] 실무에서는 Operator를 통해 클러스터·앱·설치를 자동화합니다.
```

followups: `corpus_chunk_refs` (related=Operator 개요, learning_next=설치 방식 비교).

### 시나리오 B — "PV와 볼륨은 처음에 어디서 확인하면 돼?" (위 카드 시나리오)

위 "Chatbot Output Card Contract"의 PV 시나리오 그대로.

### 시나리오 C — "MachineConfigPool이 degraded인데 어디부터 봐?" (단계별 가이드)

retrieval → chunk(`book_slug=machine_management`, `domain=nodes`, `chunk_type=troubleshooting`, `k8s_objects=["MachineConfigPool", "Node"]`, `cli_commands=["oc get mcp", "oc describe mcp"]`, `error_strings=["Degraded"]`).

segments:
1. `prose`: "먼저 어떤 MCP가 degraded인지 확인합니다."
2. `command`: `oc get mcp`
3. `command_output`: 표 예시
4. `prose`: "각 MCP의 상세 상태와 실패 노드를 확인합니다."
5. `command`: `oc describe mcp <name>`
6. `prose`: "노드별 MachineConfig 적용 상태를 봅니다."
7. `command`: `oc get nodes -o jsonpath=...`

`corpus_chunk_refs` next: chunk "MachineConfig 적용 실패 진단" → "노드 reboot 확인" → "MCO 로그 분석".

cards: 위 segments + 단계 번호 자동.
followups: next refs 3개 + related "MCO 개념" + verify "MCP=Updated 인지 어떻게 확인하나요?".

---

## Encoding Contract

### 진단

raw `chunks.jsonl`의 한글은 **UTF-8로 정상**이다 (`보안 및 컴플라이언스`, `Compliance Operator를 사용하여` 모두 정상 디코딩 확인). 사용자가 본 "한글 깨짐"은 다음 중 하나에서 발생한다:

1. **Windows 콘솔 / VS Code가 cp949·cp1252로 파일을 열었음.** `code .\security_and_compliance.jsonl`이 IDE 인코딩 기본값을 따른다. UTF-8 BOM이 없으면 cp949로 해석돼 `ì¤ìí í¹ì±` 같은 mojibake가 보인다 — 파일은 멀쩡, 디코딩만 틀림.
2. **Python `open(path)` (encoding 미지정).** Windows에서 기본은 cp949. JSONL을 cp949로 읽으면 처음 마주치는 비-ASCII 바이트에서 UnicodeDecodeError 또는 깨진 디코딩.
3. **Python `json.dumps(...)` (`ensure_ascii=True` 기본).** 한글을 `\uXXXX` escape로 직렬화. 데이터는 안 깨지지만 파일 크기 증가와 가독성 저하.
4. **Python `print(text)` (Windows stdout cp949).** stdout 자체가 UnicodeEncodeError. 출력만 깨짐.

방금 본 schema 검증 작업에서도 첫 Python 호출이 `UnicodeEncodeError: 'cp949' codec can't encode character '\xec'`로 죽었다 — 이 경고가 실재함.

### 규칙 (v0.1.4 import·export 코드 전체에 적용)

```python
# 파일 read
open(path, "r", encoding="utf-8")

# 파일 write
open(path, "w", encoding="utf-8", newline="\n")

# JSON write
json.dumps(obj, ensure_ascii=False)

# Windows 스크립트 stdout
import sys; sys.stdout.reconfigure(encoding="utf-8")

# Subprocess 한국어 출력
subprocess.run(..., encoding="utf-8", errors="replace")

# Postgres 연결
connection = psycopg.connect(..., client_encoding="UTF8")

# Qdrant 클라이언트
# QdrantClient(...)는 내부적으로 UTF-8 JSON으로 처리하므로 추가 설정 불필요 —
# 단, payload에 넣는 텍스트가 이미 UTF-8 정상이라는 전제. 깨진 채 들어가면 그대로 저장됨.
```

### Import 시 자동 검증

각 chunk import 시:

1. `raw_text`를 `text.encode("utf-8").decode("utf-8")` 라운드트립 후 동일성 확인.
2. NFC 정규화 (`unicodedata.normalize("NFC", text)`).
3. mojibake 패턴 감지:
   - `ì[À-ÿ]` (라틴-1로 잘못 디코딩된 한글 시작 바이트 패턴)
   - `â[€-„]` (라틴-1로 잘못 디코딩된 UTF-8 3바이트 패턴)
   - `Ã[€-ÿ]` (이중 인코딩 패턴)
   가 chunk text에 나타나면 import fail.
4. 한글 비율이 0%인데 `locale=ko`면 warning (번역 누락 가능성).

### PowerShell `Invoke-RestMethod` 한국어 mojibake 함정 (실측)

v0.1.4 작업 중 `qdrant_dump.json`(PowerShell `Invoke-RestMethod` + `Out-File -Encoding utf8`로 만들어진 dump)에서 한국어가 깨져 있는 사례를 발견했다. 직접 검증한 결과는 다음과 같다.

**원본 chunks.jsonl (UTF-8):**
```
chapter: "6장. File Integrity Operator"
section: "6.7.2. 중요한 특성"
text:    "하면 AIDE 데몬 세트의 Pod에서 실행 중인 데몬에서 추가 정보를 출력합니다."
```

**Qdrant payload (HTTP raw bytes, Python urllib로 직접 확인):**
```
chapter raw bytes: 36 ec 9e a5 2e 20 46 69 6c 65 ...
                    └─┬─┘ └─────┬─────┘
                     "6"    "장" (UTF-8)
chapter decoded:   "6장. File Integrity Operator"   ← 정상
section decoded:   "6.7.2. 중요한 특성"            ← 정상
text decoded:      "하면 AIDE 데몬 세트의 Pod..."   ← 정상
```

**PowerShell dump (`qdrant_dump.json`):**
```
chapter: "6ì\x9e¥. File Integrity Operator"   ← 깨짐
section: "6.7.2. ì¤ìí í¹ì±"                  ← 깨짐
text:    "íë©´ AIDE ë°ëª¬ ì¸í¸ì Podìì..."    ← 깨짐
```

**원인:** PowerShell 5.1 `Invoke-RestMethod`는 HTTP 응답의 `Content-Type: application/json` charset을 무시하고 **ISO-8859-1**로 디코딩한다. 한국어 1글자(UTF-8 3바이트, 예: `장` = `EC 9E A5`)가 3개의 Latin-1 문자(`U+00EC`, `U+009E`, `U+00A5`)로 잘못 해석된 채 PowerShell 메모리에 들어가고, `Out-File -Encoding utf8`이 그 깨진 문자열을 UTF-8로 다시 인코딩한다 → 파일은 valid UTF-8이지만 내용은 mojibake.

**Qdrant 자체는 정상이다.** 재인덱싱이 필요한 다른 이유(`[CODE]` 펜스 등)는 있지만, 인코딩 때문에 재인덱싱할 필요는 없다.

### 복구가 가능한 mojibake인지 확인하는 1줄 테스트

Python에서:

```python
fixed = broken.encode("latin-1").decode("utf-8")
```

이게 정상 한국어를 만들면 그 데이터는 안 깨졌다 — diagnostic tool이 깨진 것.

### Qdrant payload를 안전하게 dump하는 방법

PowerShell `Invoke-RestMethod`를 **쓰지 마라**. 대신:

**옵션 1: curl + 출력 redirect (Git Bash / cmd):**
```bash
curl -s -X POST "http://127.0.0.1:6335/collections/openshift_docs/points/scroll" \
     -H "Content-Type: application/json" \
     -d '{"limit": 3, "with_payload": true}' \
     -o qdrant_dump.json
```

**옵션 2: Python (Windows에서도 인코딩 안전):**
```python
import json, urllib.request, sys
sys.stdout.reconfigure(encoding="utf-8")
body = json.dumps({"limit": 3, "with_payload": True}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:6335/collections/openshift_docs/points/scroll",
    data=body, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req) as r:
    doc = json.loads(r.read().decode("utf-8"))
with open("qdrant_dump.json", "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
```

**옵션 3: PowerShell을 꼭 써야 한다면 — `Invoke-WebRequest`로 raw 바이트 받기:**
```powershell
$r = Invoke-WebRequest -Uri "http://127.0.0.1:6335/collections/openshift_docs/points/scroll" `
                       -Method POST -ContentType "application/json" `
                       -Body '{"limit":3,"with_payload":true}'
[System.IO.File]::WriteAllBytes("qdrant_dump.json", $r.Content)
```
`.Content`가 byte[]이므로 PowerShell이 내부적으로 디코딩하지 않는다.

이 진단은 v0.1.4 작업 중 실제 검증으로 확정된 결론이다. Schema 재구성 또는 재인덱싱 결정 시 PowerShell dump의 mojibake를 "Qdrant 데이터 깨짐"으로 오해하지 말 것.

## Reindex Plan (v0.1.5 phase에서 실행)

### 왜 재인덱싱하는가 (정정된 이유)

Qdrant 재인덱싱이 필요한 진짜 이유 정리:

| 이유 | 필요한가 | 근거 |
| --- | --- | --- |
| Qdrant payload의 한국어가 깨졌다 | **아니오** | 위 "PowerShell mojibake 함정" 진단으로 Qdrant payload는 정상 UTF-8 확인. PowerShell dump 도구가 깨뜨린 것. |
| `embedding_text`에 ```` ``` ```` 코드 펜스/`[CODE]` 마크업 잔여 | **예** | `official_gold_import.py:632-633`이 `markdown = embedding_text` 같은 값을 저장. 임베딩 모델이 펜스 토큰을 학습한 상태. |
| chunking 경계에서 `[CODE` vs `[/CODE` 941개 비대칭 | **예** | 일부 chunk가 마크업 절반만 가짐. 그 chunk의 embedding은 추가 손상. |
| 4계층 텍스트 분리 적용 (`raw_text` 보존, `normalized_text` 신설, `embedding_text` 재정의) | **예** | v0.1.4 schema의 핵심 변경. |
| corpus_chunks의 새 컬럼·facets 반영 | **예** | payload 계약 자체가 바뀜 (payload_version=1). |

따라서 v0.1.5에서 **재인덱싱은 하되, 인코딩이 이유가 아니라 텍스트 정규화·페이로드 계약 변경이 이유다.** Schema 결정의 우선순위가 흐려지지 않도록 분리.

### 순서

1. **기존 Qdrant 컬렉션 백업·삭제.**
   ```powershell
   # snapshot
   Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:6335/collections/openshift_docs/snapshots"
   # delete
   Invoke-RestMethod -Method DELETE -Uri "http://127.0.0.1:6335/collections/openshift_docs"
   ```

2. **`corpus_chunks` 재생성 (raw_text 보존, normalized_text·embedding_text 새 정규화로 생성).**
   - `_normalized_chunk_text`를 4계층 분리 함수로 교체.
   - `[CODE]` 마크업 완전 제거, ```` ``` ```` 펜스도 normalized_text/embedding_text에서 제거.
   - NFC 정규화 + mojibake validation.

3. **`corpus_chunk_segments` 생성.** 마크업 분해 결과를 typed segments로 분리(코드/프로즈/출력). 답변 카드의 직접 input.

4. **`corpus_chunk_commands` 추출.** `command` segments에서 명령 템플릿·placeholder·env_scope 분류.

5. **`corpus_chunk_refs` 휴리스틱 생성.** prerequisite/next/related.

6. **재임베딩.** `corpus_chunks.embedding_text`로 모든 chunk 재임베딩. payload_version=1.

7. **Qdrant 컬렉션 재생성 + upsert.** payload는 본 문서 Qdrant payload 계약 그대로.

8. **검증 SQL/스크립트:**
   - `SELECT COUNT(*) FROM corpus_chunks WHERE embedding_text ~ '\\[/?CODE'` → 0이어야 함.
   - `SELECT COUNT(*) FROM corpus_chunks WHERE embedding_text ~ '```'` → 0이어야 함.
   - `SELECT COUNT(*) FROM corpus_chunks WHERE octet_length(embedding_text) = 0` → 0이어야 함.
   - 임의 chunk 50개 샘플: `embedding_text`에 한글 또는 영문 단어만 있고 마크업/URL 없음 확인.
   - Qdrant에서 동일 chunk_id의 payload `text` 필드가 `corpus_chunks.embedding_text`와 일치 확인.

### 임베딩 정합성 검증

재임베딩 후 다음 sanity check를 통과해야 한다:

1. **벡터 dim**: 모든 점이 동일한 벡터 차원 (예: 1024 또는 모델 기본값).
2. **NaN/Inf 없음**: 일부 점에서 NaN이 나오면 입력 텍스트가 빈 문자열이거나 토크나이저 실패. 해당 chunk를 `quality_status=rejected` 처리.
3. **한국어 sanity query**: "PVC 상태 확인", "MachineConfigPool degraded", "RBAC 권한 부여" 3개 쿼리로 retrieval. Top-1 chunk의 `book_slug`와 `chunk_type`이 직관과 맞는지 수동 확인.
4. **마크업 누락 확인**: 답변 결과 hits의 `text` payload에 ```` ``` ````, `[CODE`, `%E` 같은 패턴이 0%이어야 함.
5. **인코딩 round-trip**: 임의 hits 100개의 `text`를 `text.encode("utf-8").decode("utf-8")` 후 비교, 모두 동일해야 함.

검증 실패 시 단계 2부터 다시 — corpus가 잘못된 채로 Qdrant에 들어가면 retrieval 품질이 직접 깨진다.

## v0.1.4 합의 후 v0.1.5에서 할 일

1. SQL 마이그레이션 작성 (`db/migrations/0009_corpus_layer.sql` 가정):
   - 새 6개 corpus 테이블 + 2개 projection 갱신.
   - 기존 `document_chunks` 유지, `document_chunks` 호환 view 추가.
2. Ingestion 변경:
   - JSON 공식문서 importer가 `corpus_documents` + `corpus_chunks` + `corpus_chunk_segments`를 채움.
   - PPT importer(`course/pipeline/canonical.py`)가 slide_graph → corpus 매핑.
   - `corpus_chunk_commands` 추출기(AST 또는 regex 기반).
   - `corpus_chunk_refs` 휴리스틱 생성기.
3. Retrieval/Answering 변경:
   - hydration이 `corpus_chunks`를 읽고 segments join.
   - prompt builder가 typed segments 직렬화.
   - card 생성 후처리 추가.
   - env_clarification 후속질문 생성기.
4. Qdrant 재인덱싱:
   - 기존 컬렉션 snapshot → drop.
   - 새 `embedding_text`(펜스·마크업 제거된 cleaned text)로 모든 chunk 재임베딩.
   - payload_version=1 deterministic projection으로 재생성.
   - 본 문서의 "Reindex Plan" 검증 SQL/스크립트 통과.
5. 인코딩 정합화:
   - 모든 file I/O에 `encoding="utf-8"` 명시.
   - 모든 `json.dumps`에 `ensure_ascii=False`.
   - Windows 스크립트 stdout `sys.stdout.reconfigure(encoding="utf-8")`.
   - import 시점에 mojibake validation 자동 실행.
6. 정리:
   - `internal_markup.py`의 `[CODE]` 렌더 코드 제거(또는 호환용 deprecation).
   - chunk metadata jsonb의 next_refs/learning 키 사용 중단.
   - DB `document_chunks.markdown = embedding_text` 같은 값 저장 패턴 폐기 — 4계층 분리 적용.

본 문서가 이 모든 변경의 single source of truth다.
