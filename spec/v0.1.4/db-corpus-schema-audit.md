# v0.1.4 DB Corpus Schema Audit

## Purpose

This audit is a planning artifact only. It does not define a migration yet.

v0.1.4 should first decide which tables and columns are canonical corpus data, derived artifacts, runtime status, or legacy compatibility. RAG quality work should not continue until the database contract makes it obvious where document truth lives and which JSON files or viewer outputs are only artifacts.

## 한국어 요약

이 문서는 migration 정의가 아니라 v0.1.4 schema 결정을 위한 계획 문서다.

v0.1.4에서는 먼저 어떤 테이블/컬럼이 canonical corpus인지, 어떤 것이 파생 artifact인지, 어떤 것이 runtime status인지, 어떤 것이 legacy compatibility인지 결정해야 한다. 문서 truth가 어디에 있고, JSON 파일이나 viewer output이 단순 artifact인지 명확해지기 전에는 RAG 품질 개선을 계속하지 않는다.

가장 중요한 결론은 parsing storage와 corpus storage를 분리하는 것이다. parser가 추출한 원본/중간 산출물과 RAG가 검색해야 하는 정제된 corpus truth를 같은 계층으로 취급하면, OCR/image description/viewer JSON/course runtime/search chunk가 계속 섞인다.

## Classification

- `canonical`: Source of truth for document parsing, retrieval, citation, or learning flow.
- `derived`: Rebuildable from canonical rows.
- `status`: Job, sync, runtime, or audit state.
- `artifact`: Viewer/render/cache/output material that should not drive canonical schema.
- `legacy`: Keep temporarily for compatibility, but do not build new behavior on top.
- `candidate`: Useful concept, but needs rename, merge, or stronger ownership before implementation.

## 분류 기준

- `canonical`: 문서 parsing, 검색, citation, 학습 흐름의 source of truth.
- `derived`: canonical row에서 다시 만들 수 있는 파생 데이터.
- `status`: job, sync, runtime, audit 상태.
- `artifact`: viewer/render/cache/output 산출물. canonical schema를 결정하면 안 됨.
- `legacy`: 호환성을 위해 임시 유지하지만 새 기능의 기반으로 삼지 않음.
- `candidate`: 개념은 유용하지만 구현 전에 이름 변경, 병합, ownership 정리가 필요한 항목.

## Table-Level Findings

| Table | Current Role | Classification | v0.1.4 Direction | Reason |
| --- | --- | --- | --- | --- |
| `tenants` | Multi-tenant ownership root | canonical | Keep | Needed for workspace and repository scoping. |
| `workspaces` | Tenant-local workspace root | canonical | Keep | Needed for user upload and session scope. |
| `repositories` | User/shared document library grouping | canonical | Keep, but clarify relation to corpus collection | Useful for ownership and library grouping, but should not duplicate corpus taxonomy. |
| `document_sources` | Original uploaded/official source identity | canonical | Keep and make more explicit | This should answer "where did this document come from?" |
| `document_versions` | Immutable source version record | canonical | Keep | Needed for repeatable parsing and re-indexing. |
| `parse_jobs` | Parser execution state | status | Keep, but do not mix with corpus truth | It explains processing state, not document meaning. |
| `parsed_documents` | Parsed document-level representation | canonical | Keep | This should hold document title, normalized body, outline, and document-level facets. |
| `document_blocks` | Extracted structural units | canonical | Keep | Needed for OCR/image/table/code provenance before chunking. |
| `document_assets` | Extracted images/assets and OCR/description outputs | canonical | Keep | Needed for image-based RAG and viewer references. |
| `document_chunks` | Retrieval and citation units | canonical | Keep as RAG center | Qdrant should be a projection from this table. |
| `embedding_jobs` | Embedding work state | status | Keep | Useful status table, not retrieval truth. |
| `qdrant_index_entries` | Qdrant sync bookkeeping | derived/status | Keep | Should only record projection sync state. |
| `question_logs` | Query audit trail | status | Keep separately from corpus | Useful for eval/quality, but not part of corpus. |
| `answer_logs` | Answer audit trail | status | Keep separately from corpus | Useful for traceability, but not part of corpus. |
| `chat_sessions` | Conversation session state | status | Keep | Product/session state, not corpus. |
| `chat_messages` | Conversation messages | status | Keep | Product/session state, not corpus. |
| `course_chunks` | Course runtime card/content payload | artifact/candidate | Separate from corpus; do not use as retrieval truth | This overlaps conceptually with document chunks but has different lifecycle. |
| `course_assets` | Course runtime asset storage | artifact | Keep as course artifact or derive from document assets where possible | Binary/runtime asset store should not define corpus schema. |
| `course_manifests` | Course runtime manifest | artifact | Keep as derived course artifact | Manifest should be generated from canonical course/corpus state. |

## 테이블 단위 결론

| Table | 현재 역할 | 분류 | v0.1.4 방향 | 이유 |
| --- | --- | --- | --- | --- |
| `document_sources` | 원본 문서 identity | canonical | 유지하되 source URI/version/locale/collection을 명확히 함 | 문서가 어디서 왔는지 답해야 함. |
| `document_versions` | 원본 문서의 immutable version | canonical | 유지 | 재파싱/재색인 재현성에 필요. |
| `parse_jobs` | parser 실행 상태 | status | 유지하되 corpus truth와 분리 | 처리 상태이지 문서 의미가 아님. |
| `parsed_documents` | parser가 만든 문서 단위 출력 | parsing canonical | parsing layer로 유지 | parser output/provenance 보존용. |
| `document_blocks` | OCR/text/table/image/code 등 구조 단위 | parsing canonical | parsing layer로 유지 | chunking 이전의 추출 provenance 보존용. |
| `document_assets` | 이미지/도표/OCR/description 산출물 | parsing canonical | parsing layer로 유지 | image 기반 RAG와 viewer 참조에 필요. |
| `document_chunks` | 현재 retrieval/citation 단위 | candidate | `corpus_chunks`로 개념 전환하거나 compatibility view로 분리 결정 필요 | 현재 parsing과 corpus 의미가 섞여 있음. |
| `embedding_jobs` | embedding 상태 | status | projection/status 계층으로 유지 | corpus truth가 아님. |
| `qdrant_index_entries` | Qdrant sync 상태 | derived/status | projection/status 계층으로 유지 | Qdrant는 corpus에서 재생성 가능해야 함. |
| `course_chunks` | course runtime card/content | artifact/candidate | corpus truth로 쓰지 않음 | 학습 runtime artifact이지 원문 corpus가 아님. |
| `course_assets` | course runtime asset | artifact | runtime artifact로 유지 | binary/runtime 저장소가 corpus schema를 결정하면 안 됨. |
| `course_manifests` | course runtime manifest | artifact | 파생 manifest로 유지 | canonical corpus/course state에서 생성되어야 함. |

## Main Problem

The schema has useful pieces, but their boundaries are soft:

- `metadata jsonb` and `payload jsonb` carry critical meaning without a stable contract.
- Source taxonomy is split across `source_kind`, `source_scope`, `source_type`, `source_lane`, `source_collection`, and repository fields.
- Viewer paths and JSON/HTML artifacts are referenced from retrieval payloads, but the DB does not clearly say they are artifacts.
- Course runtime tables look similar to document chunk tables, but they are not the same kind of truth.
- Next-step learning references exist in metadata, but are not first-class enough for reliable guided learning.

## 현재 핵심 문제

schema에 필요한 조각들은 이미 있지만 경계가 약하다.

- `metadata jsonb`와 `payload jsonb`가 중요한 의미를 담고 있지만 안정적인 계약이 없다.
- source taxonomy가 `source_kind`, `source_scope`, `source_type`, `source_lane`, `source_collection`, repository field로 흩어져 있다.
- viewer path와 JSON/HTML artifact가 retrieval payload에 들어가지만, DB가 이것이 artifact라고 명확히 표현하지 않는다.
- course runtime table은 document chunk table과 비슷해 보이지만 같은 truth가 아니다.
- 다음 단계 학습 reference가 metadata에 있긴 하지만 guided learning을 안정적으로 만들 만큼 first-class가 아니다.

## Priority 1: Split Parsing Storage From Corpus Storage

The first v0.1.4 schema decision is not which individual columns to add. It is to separate parsing-stage data from canonical corpus-stage data.

Parsing tables should preserve extraction provenance and parser output. Corpus tables should represent the cleaned, queryable, learner-facing document graph. Qdrant, viewer JSON/HTML, and course runtime artifacts should derive from corpus tables, not directly from parser output.

## 1순위: Parsing Storage와 Corpus Storage 분리

v0.1.4의 첫 schema 결정은 개별 컬럼을 무엇을 추가할지가 아니다. 먼저 parsing-stage data와 canonical corpus-stage data를 분리해야 한다.

Parsing table은 parser output과 extraction provenance를 보존해야 한다. Corpus table은 정제되고 검색 가능하며 학습자에게 보여줄 수 있는 document graph를 표현해야 한다. Qdrant, viewer JSON/HTML, course runtime artifact는 parser output에서 직접 파생되는 것이 아니라 corpus table에서 파생되어야 한다.

### Proposed Boundary

| Layer | Purpose | Example Tables | Not Responsible For |
| --- | --- | --- | --- |
| Parsing | Preserve raw extraction, OCR, image descriptions, blocks, parser warnings, and layout provenance | `parsed_documents`, `document_blocks`, `document_assets`, `parse_jobs` | Search ranking contract, guided learning graph, viewer runtime shape |
| Corpus | Store normalized document and chunk truth used by retrieval, citation, filtering, and guided learning | future `corpus_documents`, future `corpus_chunks`, future relation tables | Raw parser artifacts, OCR/layout debug details, job state |
| Projection | Track rebuildable downstream indexes | `qdrant_index_entries`, `embedding_jobs` | Canonical text or metadata ownership |
| Runtime Artifact | Store generated course/viewer/session outputs | `course_chunks`, `course_assets`, `course_manifests`, viewer JSON/HTML files | Canonical document truth |

### 제안 경계

| Layer | 목적 | 예시 테이블 | 책임지지 않는 것 |
| --- | --- | --- | --- |
| Parsing | raw extraction, OCR, image description, block, parser warning, layout provenance 보존 | `parsed_documents`, `document_blocks`, `document_assets`, `parse_jobs` | 검색 ranking 계약, guided learning graph, viewer runtime shape |
| Corpus | retrieval, citation, filtering, guided learning에 쓰이는 normalized document/chunk truth 저장 | future `corpus_documents`, future `corpus_chunks`, future relation tables | raw parser artifact, OCR/layout debug detail, job state |
| Projection | 재생성 가능한 downstream index 상태 추적 | `qdrant_index_entries`, `embedding_jobs` | canonical text/metadata ownership |
| Runtime Artifact | 생성된 course/viewer/session output 저장 | `course_chunks`, `course_assets`, `course_manifests`, viewer JSON/HTML files | canonical document truth |

### Why This Should Be First

- It removes ambiguity between "what the parser saw" and "what RAG should search".
- It prevents viewer/course JSON from becoming accidental corpus input.
- It gives OCR and image description a proper home without forcing every extraction detail into retrieval chunks.
- It makes re-parsing safe: parser output can change while corpus rows remain versioned and auditable.
- It creates a clean seam for quality work: normalize and enrich into corpus first, then project to Qdrant.

### 이것이 먼저여야 하는 이유

- "parser가 본 것"과 "RAG가 검색해야 하는 것"의 모호함을 제거한다.
- viewer/course JSON이 실수로 corpus input이 되는 것을 막는다.
- OCR과 image description을 retrieval chunk에 억지로 밀어 넣지 않고 적절한 위치에 둘 수 있다.
- 재파싱이 안전해진다. parser output은 바뀔 수 있지만 corpus row는 versioned/auditable하게 유지할 수 있다.
- 품질 개선의 경계가 명확해진다. 먼저 normalize/enrich해서 corpus에 넣고, 그 다음 Qdrant로 projection한다.

### Migration Shape To Consider Later

Do not implement this yet, but the likely direction is:

```text
document_sources       -> source identity and ownership
document_versions      -> immutable source versions
parse_jobs             -> parser job status
parsed_documents       -> parser-level document output
document_blocks        -> parser-level block/OCR/layout output
document_assets        -> parser-level extracted assets

corpus_documents       -> canonical searchable document truth
corpus_chunks          -> canonical searchable chunk truth
corpus_chunk_assets    -> chunk-to-asset links
corpus_chunk_refs      -> prerequisite/next/related/lab links
corpus_chunk_facets    -> optional normalized many-valued facets if JSON arrays become unmanageable

qdrant_index_entries   -> projection status from corpus_chunks
embedding_jobs         -> embedding status for corpus_chunks
```

Existing `document_chunks` may either be renamed conceptually into `corpus_chunks` or replaced by new `corpus_chunks` with a compatibility view. That decision should happen before migration SQL.

기존 `document_chunks`는 개념적으로 `corpus_chunks`로 전환할 수도 있고, 새 `corpus_chunks` 테이블을 만들고 compatibility view를 둘 수도 있다. 이 결정은 migration SQL 작성 전에 먼저 내려야 한다.

## Column Audit: `document_sources`

| Column | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `id` | canonical | Keep | Stable source identity. |
| `tenant_id` | canonical | Keep | Scope ownership. |
| `workspace_id` | canonical | Keep | Scope ownership. |
| `repository_id` | canonical | Keep | Library grouping. |
| `source_kind` | candidate | Rename/merge later | Overlaps with source type/scope; should mean physical source kind only, e.g. `upload`, `official_html`, `official_jsonl`. |
| `filename` | canonical | Keep | Human file identity for uploaded/local sources. |
| `mime_type` | canonical | Keep | Parser dispatch. |
| `sha256` | canonical | Keep | Source dedup/versioning. |
| `storage_key` | canonical | Keep | Object/file storage pointer. |
| `byte_size` | canonical | Keep | Source audit. |
| `access_policy` | canonical | Keep | Access control. |
| `owner_user_id` | canonical | Keep | User ownership. |
| `visibility` | canonical | Keep | Retrieval access boundary. |
| `source_scope` | candidate | Keep short-term, define enum | Useful, but currently too broad. |
| `metadata` | legacy/candidate | Keep as extension only | Should not contain required retrieval facets. |
| `created_by` | candidate | Merge later with `owner_user_id` or keep as audit | Ownership and audit are mixed. |
| `created_at` | status | Keep | Audit timestamp. |

### Missing Source Columns

These should be considered before migration:

| Proposed Column | Classification | Reason |
| --- | --- | --- |
| `source_uri` | canonical | Stable original URL/path/repo URI independent of storage key. |
| `source_collection` | canonical | Corpus collection, e.g. `official_ocp_ko`, `user_upload`, `kmsc_course`. |
| `source_version` | canonical | OCP/doc version, e.g. `4.20`. |
| `locale` | canonical | Language/locale facet. |
| `canonical_status` | status | `active`, `superseded`, `deprecated`, `blocked`. |

## Column Audit: `parsed_documents`

| Column | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `id` | canonical | Keep | Parsed document identity. |
| `document_source_id` | canonical | Keep | Source linkage. |
| `document_version_id` | canonical | Keep | Version linkage. |
| `parse_job_id` | status | Keep | Parse provenance. |
| `parser_name` | status | Keep | Parse provenance. |
| `parser_version` | status | Keep | Parse reproducibility. |
| `title` | canonical | Keep | Document title. |
| `markdown` | candidate | Keep but define as parsed markdown | Should not be confused with chunk markdown or viewer HTML. |
| `outline` | canonical | Keep | Document structure. |
| `warnings` | status | Keep | Parse quality signal. |
| `metadata` | legacy/candidate | Keep as extension only | Required facets should be columns. |
| `created_at` | status | Keep | Audit timestamp. |

### Missing Parsed Document Columns

| Proposed Column | Classification | Reason |
| --- | --- | --- |
| `normalized_text` | canonical | Cleaned text used before chunking. |
| `document_slug` | canonical | Stable document route/key. |
| `source_url` | canonical | Citation source. |
| `viewer_artifact_path` | artifact | Pointer only; not truth. |
| `domain` | canonical | OCP domain facet. |
| `install_category` | canonical | Install subtype facet. |
| `platform` | canonical | VM, bare metal, cloud, local, etc. |
| `provider` | canonical | Azure, AWS, vSphere, OpenStack, none, etc. |
| `ocp_version` | canonical | Version filter. |
| `locale` | canonical | Language filter. |

## Column Audit: `document_blocks`

| Column | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `id` | canonical | Keep | Block identity. |
| `parsed_document_id` | canonical | Keep | Parent linkage. |
| `ordinal` | canonical | Keep | Original order. |
| `block_type` | canonical | Keep | Text/table/image/code/procedure/heading. |
| `heading_level` | canonical | Keep | Structure. |
| `page_number` | canonical | Keep | PDF/image provenance. |
| `text` | canonical | Keep | Raw extracted text. |
| `markdown` | candidate | Keep but define as block rendering text | Useful, but should not become viewer truth. |
| `section_path` | canonical | Keep | Structure path. |
| `section_number` | canonical | Keep | Official docs often need section numbering. |
| `heading_title` | canonical | Keep | Local heading context. |
| `source_anchor` | canonical | Keep | Citation/viewer anchor. |
| `toc_path` | candidate | Maybe merge with `section_path`/breadcrumb | Similar to section path; keep until viewer path rules are defined. |
| `bbox` | canonical | Keep | OCR/layout provenance. |
| `table_data` | canonical | Keep | Structured table extraction. |
| `metadata` | legacy/candidate | Keep as extension only | Parser-specific details. |

### Missing Block Columns

| Proposed Column | Classification | Reason |
| --- | --- | --- |
| `normalized_text` | canonical | Cleaned text for chunking while preserving raw `text`. |
| `ocr_text` | canonical | OCR result when block is image/scanned region. |
| `image_description` | canonical | Vision description associated with image/figure blocks. |
| `block_role` | canonical | `concept`, `procedure`, `warning`, `command`, `reference`, etc. |

## Column Audit: `document_assets`

| Column | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `id` | canonical | Keep | Asset identity. |
| `document_source_id` | canonical | Keep | Source linkage. |
| `parsed_document_id` | canonical | Keep | Parsed document linkage. |
| `block_id` | canonical | Keep | Block provenance. |
| `asset_type` | canonical | Keep | Image/table/diagram/etc. |
| `mime_type` | canonical | Keep | Render/parser handling. |
| `storage_key` | canonical | Keep | Asset storage pointer. |
| `sha256` | canonical | Keep | Dedup/integrity. |
| `width` | canonical | Keep | Image metadata. |
| `height` | canonical | Keep | Image metadata. |
| `page_number` | canonical | Keep | PDF provenance. |
| `bbox` | canonical | Keep | Layout provenance. |
| `caption_text` | canonical | Keep | Extracted caption. |
| `ocr_text` | canonical | Keep | Raw OCR result. |
| `qwen_description` | legacy/candidate | Rename later to model-neutral `image_description` | Current name hardcodes one provider/model family. |
| `qwen_model` | legacy/candidate | Rename later to `description_model` | Model-specific column name should not be canonical. |
| `metadata` | legacy/candidate | Keep as extension only | Tool-specific details. |
| `created_at` | status | Keep | Audit timestamp. |

## Column Audit: `document_chunks`

| Column | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `id` | canonical | Keep | Retrieval/citation identity. |
| `parsed_document_id` | canonical | Keep | Parent document. |
| `chunk_key` | canonical | Keep | Stable chunk key inside document. |
| `ordinal` | canonical | Keep | Retrieval ordering and navigation. |
| `chunk_type` | canonical | Keep, define enum | Should mean content kind: `concept`, `procedure`, `command`, `troubleshooting`, `reference`, `navigation`. |
| `chunk_role` | canonical | Keep | Parent/leaf/summary/navigation role. |
| `parent_chunk_id` | canonical | Keep | Hierarchical retrieval. |
| `child_chunk_ids` | candidate | Consider relation table later | JSON array is convenient but weak for consistency. |
| `navigation_only` | canonical | Keep | Prevent viewer/navigation chunks from polluting retrieval. |
| `markdown` | canonical | Keep | Human-readable chunk body. |
| `embedding_text` | canonical | Keep | Text sent to embedding model. |
| `token_count` | derived | Keep or recompute | Useful for chunk quality, but rebuildable. |
| `page_start` | canonical | Keep | Citation provenance. |
| `page_end` | canonical | Keep | Citation provenance. |
| `section_path` | canonical | Keep | Structural context. |
| `section_number` | canonical | Keep | Official docs and learning context. |
| `heading_title` | canonical | Keep | Local section title. |
| `source_anchor` | canonical | Keep | Citation/viewer anchor. |
| `toc_path` | candidate | Maybe merge into breadcrumb later | Overlaps with section path. |
| `asset_ids` | candidate | Consider relation table later | JSON array is weak for consistency but practical. |
| `beginner_narrative` | canonical | Keep | Learner-facing explanation. |
| `starter_question_candidates` | canonical | Keep | Starter question generation source. |
| `followup_question_candidates` | canonical | Keep | Guided learning source. |
| `question_candidates_version` | status | Keep | Candidate generation version. |
| `repository_id` | canonical | Keep | Access/library scoping. |
| `owner_user_id` | canonical | Keep | Access boundary. |
| `visibility` | canonical | Keep | Access boundary. |
| `source_scope` | candidate | Keep short-term, define enum | Scope is useful but currently overloaded. |
| `metadata` | legacy/candidate | Keep as extension only | Too much required retrieval data currently hides here. |
| `created_at` | status | Keep | Audit timestamp. |

### Missing Chunk Columns

These should be first-class because RAG and guided learning need to filter or reason on them:

| Proposed Column | Classification | Reason |
| --- | --- | --- |
| `title` | canonical | Chunk/document display title. |
| `section_title` | canonical | Better than deriving from JSON paths every time. |
| `chapter_title` | canonical | Multi-section docs need stable chapter context. |
| `breadcrumb` | canonical | Human navigation context. |
| `normalized_text` | canonical | Cleaned text before embedding. |
| `source_url` | canonical | Citation source. |
| `viewer_artifact_path` | artifact | Pointer only, not schema truth. |
| `book_slug` | canonical | Stable document/book grouping. |
| `domain` | canonical | OCP area: install, networking, auth, storage, operators, troubleshooting. |
| `install_category` | canonical | IPI, UPI, agent-based, assisted, SNO, disconnected, etc. |
| `platform` | canonical | baremetal, vm, cloud, local, managed. |
| `provider` | canonical | aws, azure, gcp, vsphere, openstack, none. |
| `ocp_version` | canonical | Version filtering. |
| `cluster_topology` | canonical | SNO, compact, HA, hosted-control-plane. |
| `network_mode` | canonical | connected, disconnected, proxy, restricted. |
| `environment` | canonical | lab, production, airgapped, public-cloud, private-cloud. |
| `cli_commands` | canonical | Command-aware retrieval. |
| `k8s_objects` | canonical | Object-aware retrieval. |
| `operator_names` | canonical | Operator-aware retrieval. |
| `error_strings` | canonical | Troubleshooting retrieval. |
| `verification_hints` | canonical | Answer quality and follow-up guidance. |
| `prerequisite_refs` | canonical | Guided learning graph. |
| `next_refs` | canonical | Guided learning graph. |
| `related_refs` | canonical | Guided learning graph. |
| `lab_refs` | canonical | Practice/lab linkage. |

## Column Audit: Runtime and Projection Tables

| Table/Column Family | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `embedding_jobs.*` | status | Keep | Tracks work state only. |
| `qdrant_index_entries.*` | derived/status | Keep | Qdrant should be rebuildable from chunks. |
| `question_logs.*` | status | Keep out of corpus | Quality/debug state only. |
| `answer_logs.*` | status | Keep out of corpus | Quality/debug state only. |
| `chat_sessions.*` | status | Keep out of corpus | Product state. |
| `chat_messages.*` | status | Keep out of corpus | Product state. |

## Column Audit: Course Runtime Tables

| Table | Classification | Direction | Reason |
| --- | --- | --- | --- |
| `course_chunks` | artifact/candidate | Do not merge into `document_chunks` yet | Course cards can be generated from corpus plus curriculum state, but they are not raw document chunks. |
| `course_chunks.payload` | artifact/legacy | Audit before extending | Required course fields should eventually be explicit or derived. |
| `course_chunks.search_text` | derived | Keep short-term | Rebuildable from course payload. |
| `course_assets` | artifact | Keep as runtime artifact store | Binary payload should not determine corpus schema. |
| `course_assets.payload` | artifact/legacy | Audit before extending | Should not hide required asset semantics. |
| `course_manifests` | artifact | Keep as generated manifest | Should be rebuildable from canonical course/corpus state. |
| `course_manifests.payload` | artifact/legacy | Audit before extending | Manifest JSON is an output contract, not document truth. |

## Redundant or Confusing Concepts

| Concept | Current Places | Direction |
| --- | --- | --- |
| Source taxonomy | `source_kind`, `source_scope`, `source_type`, `source_lane`, `source_collection`, `repository_kind` | Define a small taxonomy and stop adding synonyms. |
| Viewer path | chunk metadata, source metadata, viewer JSON/HTML | Rename DB pointer to `viewer_artifact_path` and treat it as artifact reference. |
| Text forms | `text`, `markdown`, `embedding_text`, `search_text`, `normalized_text` proposal | Define lifecycle: raw text -> normalized text -> chunk markdown -> embedding text -> derived search text. |
| Learning refs | metadata `learning.next_refs`, course payload refs, proposed chunk refs | Promote document/chunk refs to first-class columns or relation table. |
| Asset descriptions | `qwen_description`, `qwen_model`, metadata descriptions | Rename model-neutral fields before adding another vision provider. |
| Course chunks vs document chunks | `course_chunks`, `document_chunks` | Keep separate; connect via refs, not by treating course JSON as document corpus. |

## Recommended v0.1.4 Schema Shape

Do not delete existing columns in the first migration. Instead:

1. Define enum-like allowed values in docs/tests first.
2. Add missing first-class columns only for fields used by retrieval/filtering/guided learning.
3. Backfill from `metadata` and `payload`.
4. Update importers and Qdrant projection to prefer columns.
5. Add audits that fail when required fields are only in JSONB.
6. Only then mark redundant fields as `legacy`.

## Proposed Minimal Canonical Corpus Contract

### `document_sources`

Required conceptual fields:

```text
id
tenant_id
workspace_id
repository_id
source_kind
source_uri
storage_key
sha256
source_collection
source_version
locale
visibility
owner_user_id
canonical_status
metadata
```

### `parsed_documents`

Required conceptual fields:

```text
id
document_source_id
document_version_id
parse_job_id
title
document_slug
markdown
normalized_text
outline
domain
install_category
platform
provider
ocp_version
locale
metadata
```

### `document_blocks`

Required conceptual fields:

```text
id
parsed_document_id
ordinal
block_type
block_role
text
normalized_text
markdown
ocr_text
image_description
section_path
section_number
heading_title
source_anchor
page_number
bbox
table_data
metadata
```

### `document_assets`

Required conceptual fields:

```text
id
document_source_id
parsed_document_id
block_id
asset_type
storage_key
sha256
mime_type
width
height
page_number
bbox
caption_text
ocr_text
normalized_ocr_text
image_description
description_model
metadata
```

### `document_chunks`

Required conceptual fields:

```text
id
parsed_document_id
chunk_key
ordinal
chunk_type
chunk_role
parent_chunk_id
navigation_only
title
chapter_title
section_title
section_path
section_number
source_anchor
markdown
normalized_text
embedding_text
source_url
viewer_artifact_path
book_slug
domain
install_category
platform
provider
ocp_version
cluster_topology
network_mode
environment
asset_ids
cli_commands
k8s_objects
operator_names
error_strings
verification_hints
starter_question_candidates
followup_question_candidates
prerequisite_refs
next_refs
related_refs
lab_refs
metadata
```

## Deletion Candidates

Do not delete these immediately, but stop expanding them until audited:

| Candidate | Why |
| --- | --- |
| Broad `metadata` fields as required data | They hide corpus meaning. |
| Broad `payload` fields in course tables | They hide runtime contract. |
| `qwen_description` / `qwen_model` names | Model-specific names should not be canonical. |
| `source_lane` if introduced elsewhere | Likely synonym of collection/scope. |
| `toc_path` if breadcrumb is adopted | Could become redundant. |
| JSON array links like `child_chunk_ids`, `asset_ids` | Consider relation tables if consistency matters. |

## 삭제/정리 후보

바로 삭제하지는 않는다. 다만 감사가 끝나기 전까지는 아래 항목을 더 확장하지 않는다.

| 후보 | 이유 |
| --- | --- |
| 필수 데이터처럼 쓰이는 넓은 `metadata` field | corpus 의미가 숨는다. |
| course table의 넓은 `payload` field | runtime 계약이 숨는다. |
| `qwen_description` / `qwen_model` 이름 | 특정 모델명에 묶인 컬럼명은 canonical이 되기 어렵다. |
| 다른 곳에 추가된 `source_lane` | collection/scope와 중복될 가능성이 높다. |
| breadcrumb를 도입할 경우 `toc_path` | 중복될 수 있다. |
| `child_chunk_ids`, `asset_ids` 같은 JSON array link | consistency가 중요해지면 relation table 검토가 필요하다. |

## Decision Needed Before Migration

Before writing SQL, decide these names:

1. Keep `viewer_path` or rename to `viewer_artifact_path`.
2. Keep `source_scope` or split into `access_scope` and `corpus_scope`.
3. Keep JSON arrays for refs/assets or introduce relation tables.
4. Decide whether course runtime tables remain artifacts or become a separate canonical curriculum schema.
5. Decide the enum values for `domain`, `install_category`, `platform`, `provider`, `chunk_type`, and `block_type`.

## Migration 전 결정 필요

SQL을 작성하기 전에 아래 결정을 먼저 내려야 한다.

1. `viewer_path`를 유지할지, `viewer_artifact_path`로 이름을 바꿀지 결정한다.
2. `source_scope`를 유지할지, `access_scope`와 `corpus_scope`로 나눌지 결정한다.
3. refs/assets를 JSON array로 유지할지, relation table을 만들지 결정한다.
4. course runtime table을 artifact로 유지할지, 별도의 canonical curriculum schema로 승격할지 결정한다.
5. `domain`, `install_category`, `platform`, `provider`, `chunk_type`, `block_type`의 enum 값을 결정한다.
