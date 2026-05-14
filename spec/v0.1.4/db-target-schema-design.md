# v0.1.4 Target DB Schema Design

## Purpose

This is the pre-migration target schema design. It does not implement SQL.

The goal is to define a production-style database contract before changing migrations:

- Parsing tables store extraction provenance.
- Corpus tables store searchable document truth.
- Projection tables track rebuildable downstream indexes.
- Runtime artifact tables support UI/course/viewer behavior without becoming corpus truth.
- Metadata JSONB remains allowed only for extension and provenance, not required retrieval/filter fields.

## 현재 DB 구조 요약

현재 schema는 다음 계층이 섞여 있다.

| Layer | Current Tables | Problem |
| --- | --- | --- |
| Scope/Auth | `tenants`, `workspaces`, `repositories` | 유지 가능. corpus taxonomy와 repository taxonomy가 섞이지 않도록 주의 필요. |
| Source/Parsing | `document_sources`, `document_versions`, `parse_jobs`, `parsed_documents`, `document_blocks`, `document_assets` | parser output과 corpus truth가 일부 섞여 있음. |
| Retrieval | `document_chunks` | 현재 RAG source이지만 parser output과 corpus layer가 한 테이블에 섞임. |
| Projection | `embedding_jobs`, `qdrant_index_entries` | `document_chunks` 기준으로 묶여 있어 향후 `corpus_chunks` 기준으로 전환 필요. |
| Runtime Logs | `question_logs`, `answer_logs`, `chat_sessions`, `chat_messages` | corpus와 분리 유지. |
| Course Runtime | `course_chunks`, `course_assets`, `course_manifests` | viewer/course artifact이지 document corpus truth가 아님. |

## Target Schema Overview

```text
tenants
workspaces
repositories

document_sources
document_versions

parse_jobs
parsed_documents
document_blocks
document_assets

corpus_documents
corpus_chunks
corpus_chunk_assets
corpus_chunk_refs
corpus_question_candidates

embedding_jobs
qdrant_index_entries

viewer_artifacts
course_chunks
course_assets
course_manifests

question_logs
answer_logs
chat_sessions
chat_messages
```

Initial v0.1.4 migration may choose either:

1. Add new `corpus_*` tables and keep `document_chunks` as compatibility source during transition.
2. Rename/conceptually migrate `document_chunks` into `corpus_chunks` with a compatibility view.

Recommendation: use new `corpus_documents` and `corpus_chunks` first, then compatibility views. This is safer than overloading `document_chunks` further.

## Naming Rules

- `document_*`: source identity, parser output, extraction provenance.
- `corpus_*`: normalized, searchable, learner-facing truth.
- `*_artifacts`: generated/rendered/rebuildable outputs.
- `*_jobs`: processing status.
- `*_entries`: projection/sync status.
- `metadata jsonb`: optional extension/provenance only.
- `payload jsonb`: runtime artifact payload only, not corpus truth.

## Scope Tables

### `tenants`

Keep current shape.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Tenant identity. |
| `slug` | text | yes | Stable tenant key. |
| `name` | text | yes | Display name. |
| `created_at` | timestamptz | yes | Audit. |

### `workspaces`

Keep current shape.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Workspace identity. |
| `tenant_id` | uuid | yes | Tenant scope. |
| `slug` | text | yes | Stable workspace key. |
| `name` | text | yes | Display name. |
| `created_at` | timestamptz | yes | Audit. |

### `repositories`

Keep, but treat as library/access grouping, not corpus taxonomy.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Repository identity. |
| `tenant_id` | uuid | no | Tenant scope. |
| `workspace_id` | uuid | no | Workspace scope. |
| `owner_user_id` | text | no | User owner. |
| `slug` | text | yes | Stable repository key. |
| `title` | text | yes | Display title. |
| `repository_kind` | text | yes | `personal`, `workspace`, `official`, `operations`, `course_runtime`. |
| `visibility` | text | yes | `private_user`, `workspace_shared`, `global_shared`. |
| `metadata` | jsonb | yes | UI/library extension only. |
| `created_at` | timestamptz | yes | Audit. |
| `updated_at` | timestamptz | yes | Audit. |

## Source Tables

### `document_sources`

Canonical source identity. This table answers: "what original source did this come from?"

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Source identity. |
| `tenant_id` | uuid | no | Tenant scope. |
| `workspace_id` | uuid | no | Workspace scope. |
| `repository_id` | uuid | no | Library grouping. |
| `owner_user_id` | text | no | Owner. |
| `visibility` | text | yes | Access boundary. |
| `source_kind` | text | yes | Physical source kind: `pdf`, `pptx`, `html`, `asciidoc`, `json_manifest`, `uploaded_file`, `official_repo`. |
| `source_uri` | text | yes | Original URI/path/repo ref independent of storage. |
| `source_path` | text | no | Local path when applicable. |
| `filename` | text | yes | Original/display file name. |
| `mime_type` | text | no | Parser dispatch. |
| `sha256` | text | yes | Source integrity/dedup. |
| `storage_key` | text | yes | Object/file storage pointer. |
| `byte_size` | bigint | yes | Source audit. |
| `source_collection` | text | yes | Corpus collection: `official_ocp`, `operations_docs`, `user_upload`, `course_seed`. |
| `source_version` | text | no | OCP/doc version, e.g. `4.20`. |
| `locale` | text | no | `ko`, `en`, etc. |
| `canonical_status` | text | yes | `active`, `superseded`, `deprecated`, `blocked`. |
| `access_policy` | jsonb | yes | Access policy extension. |
| `metadata` | jsonb | yes | Source-specific optional extension only. |
| `created_by` | text | no | Import actor. |
| `created_at` | timestamptz | yes | Audit. |

Allowed metadata examples:

```json
{
  "importer": "official-html",
  "source_commit": "abc123",
  "upstream_title": "Installing on Azure",
  "license": "redhat-docs"
}
```

Do not store required retrieval facets only in `document_sources.metadata`.

### `document_versions`

Immutable source version.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Version identity. |
| `document_source_id` | uuid | yes | Parent source. |
| `version_no` | integer | yes | Incrementing source version. |
| `source_sha256` | text | yes | Immutable source hash. |
| `storage_key` | text | yes | Versioned source storage. |
| `ingestion_run_id` | text | no | Import/rebuild run id. |
| `created_at` | timestamptz | yes | Audit. |

## Parsing Tables

Parsing tables preserve what the parser extracted. They are not the final RAG truth.

### `parse_jobs`

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Job identity. |
| `document_source_id` | uuid | yes | Source being parsed. |
| `document_version_id` | uuid | no | Source version. |
| `parser_name` | text | yes | Parser backend. |
| `parser_version` | text | yes | Parser version. |
| `status` | text | yes | `queued`, `running`, `completed`, `failed`, `skipped`. |
| `error_code` | text | no | Failure code. |
| `error_message` | text | no | Failure detail. |
| `started_at` | timestamptz | no | Job start. |
| `completed_at` | timestamptz | no | Job end. |
| `created_at` | timestamptz | yes | Audit. |

### `parsed_documents`

Parser-level document output. Keep markdown/outline here as parser artifacts, not viewer truth.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Parsed document identity. |
| `document_source_id` | uuid | yes | Source. |
| `document_version_id` | uuid | no | Source version. |
| `parse_job_id` | uuid | no | Parser job. |
| `parser_name` | text | yes | Parser backend. |
| `parser_version` | text | yes | Parser version. |
| `title` | text | no | Parser-detected title. |
| `raw_text` | text | no | Raw extracted text when available. |
| `raw_payload` | jsonb | no | Original structured source payload when the source itself is JSON. |
| `markdown` | text | no | Parser markdown artifact. |
| `normalized_text` | text | no | Parser-level cleaned text before corpus enrichment. |
| `outline` | jsonb | yes | Parser-detected outline. |
| `warnings` | jsonb | yes | Parser warnings. |
| `metadata` | jsonb | yes | Parser-specific extension. |
| `created_at` | timestamptz | yes | Audit. |

Allowed metadata examples:

```json
{
  "page_count": 32,
  "parser_backend": "pymupdf",
  "ocr_required": true,
  "source_manifest_key": "installing_on_azure"
}
```

### `document_blocks`

Parser structural units before corpus chunking.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Block identity. |
| `parsed_document_id` | uuid | yes | Parsed document. |
| `ordinal` | integer | yes | Order in parsed document. |
| `block_type` | text | yes | `heading`, `paragraph`, `code`, `table`, `image`, `list`, `note`, `warning`. |
| `block_role` | text | no | `concept`, `procedure`, `command`, `reference`, `navigation`, `noise`. |
| `heading_level` | integer | no | Heading level. |
| `page_number` | integer | no | Page provenance. |
| `text` | text | no | Raw block text. |
| `normalized_text` | text | no | Cleaned block text. |
| `markdown` | text | no | Block rendering artifact. |
| `section_path` | jsonb | yes | Parser section path. |
| `section_number` | text | no | Section number. |
| `heading_title` | text | no | Heading context. |
| `source_anchor` | text | no | Source anchor. |
| `source_json_path` | text | no | JSON Pointer/JSONPath when the block came from structured JSON. |
| `source_location` | jsonb | yes | Structured provenance such as page, path, anchor, bbox, or upstream node id. |
| `bbox` | jsonb | yes | Layout box. |
| `table_data` | jsonb | yes | Structured table data. |
| `ocr_text` | text | no | OCR text if block is image/scanned. |
| `image_description` | text | no | Vision description if applicable. |
| `metadata` | jsonb | yes | Parser-specific extension. |

### `document_assets`

Extracted images, figures, tables, and source attachments.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Asset identity. |
| `document_source_id` | uuid | yes | Source. |
| `parsed_document_id` | uuid | no | Parsed document. |
| `block_id` | uuid | no | Source block. |
| `asset_type` | text | yes | `image`, `figure`, `table_image`, `attachment`. |
| `mime_type` | text | no | MIME type. |
| `storage_key` | text | yes | Asset storage. |
| `sha256` | text | yes | Asset hash. |
| `width` | integer | no | Image width. |
| `height` | integer | no | Image height. |
| `page_number` | integer | no | Page provenance. |
| `bbox` | jsonb | yes | Layout box. |
| `caption_text` | text | no | Extracted caption. |
| `ocr_text` | text | no | OCR text. |
| `normalized_ocr_text` | text | no | Cleaned OCR text. |
| `image_description` | text | no | Model-neutral image description. |
| `description_model` | text | no | Description model. |
| `description_status` | text | no | `missing`, `generated`, `failed`, `skipped`. |
| `metadata` | jsonb | yes | Tool-specific extension. |
| `created_at` | timestamptz | yes | Audit. |

Legacy mapping: `qwen_description` -> `image_description`, `qwen_model` -> `description_model`.

## Corpus Tables

Corpus tables are the source of truth for search, citation, guided learning, and Qdrant projection.

### `corpus_documents`

Canonical searchable document.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Corpus document identity. |
| `document_source_id` | uuid | yes | Original source. |
| `document_version_id` | uuid | no | Source version. |
| `parsed_document_id` | uuid | no | Parser output used. |
| `repository_id` | uuid | no | Library grouping. |
| `owner_user_id` | text | no | Access owner. |
| `visibility` | text | yes | Access boundary. |
| `corpus_scope` | text | yes | `official_docs`, `operations_docs`, `user_upload`, `course_runtime`. |
| `document_slug` | text | yes | Stable document key. |
| `title` | text | yes | Display title. |
| `summary` | text | no | Document summary. |
| `normalized_text` | text | no | Full normalized document text. |
| `source_url` | text | no | Citation source URL. |
| `viewer_artifact_path` | text | no | Viewer artifact pointer only. |
| `locale` | text | no | Language. |
| `ocp_version` | text | no | OCP/doc version. |
| `domain` | text | no | OCP domain. |
| `install_category` | text | no | Install subtype. |
| `platform` | text | no | Platform. |
| `provider` | text | no | Cloud/provider. |
| `review_status` | text | yes | `unreviewed`, `approved`, `rejected`, `generated`. |
| `trust_score` | numeric | yes | Corpus trust score. |
| `metadata` | jsonb | yes | Optional extension. |
| `created_at` | timestamptz | yes | Audit. |
| `updated_at` | timestamptz | yes | Audit. |

Allowed metadata examples:

```json
{
  "source_manifest_id": "ocp_ko_4_20",
  "approval_note": "official translated source",
  "viewer_template": "official-doc"
}
```

### `corpus_chunks`

Canonical searchable chunk and Qdrant projection source.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Corpus chunk identity. |
| `corpus_document_id` | uuid | yes | Parent corpus document. |
| `parsed_document_id` | uuid | no | Source parser output. |
| `source_block_ids` | jsonb | no | Parser block provenance, transition-friendly. |
| `chunk_key` | text | yes | Stable chunk key within document. |
| `ordinal` | integer | yes | Document order. |
| `chunk_type` | text | yes | `concept`, `procedure`, `command`, `troubleshooting`, `reference`, `navigation`. |
| `chunk_role` | text | yes | `parent`, `leaf`, `summary`, `navigation`. |
| `parent_chunk_id` | uuid | no | Parent chunk. |
| `navigation_only` | boolean | yes | Exclude from normal retrieval when true. |
| `title` | text | yes | Chunk/document title. |
| `chapter_title` | text | no | Chapter title. |
| `section_title` | text | no | Section title. |
| `section_path` | jsonb | yes | Section path. |
| `section_number` | text | no | Section number. |
| `breadcrumb` | jsonb | yes | UI/navigation breadcrumb. |
| `source_anchor` | text | no | Source/viewer anchor. |
| `source_path` | text | no | Stable logical path inside the source document or manifest. |
| `source_json_path` | text | no | JSON Pointer/JSONPath for source JSON provenance. |
| `source_location` | jsonb | yes | Non-ranking provenance such as page, anchor, path, bbox, or upstream node id. |
| `markdown` | text | yes | Human-readable chunk body. |
| `normalized_text` | text | yes | Searchable cleaned chunk text. |
| `embedding_text` | text | yes | Text sent to embedding model. |
| `token_count` | integer | yes | Derived chunk size. |
| `source_url` | text | no | Citation source. |
| `viewer_artifact_path` | text | no | Viewer pointer only. |
| `book_slug` | text | no | Stable book/document grouping. |
| `domain` | text | no | OCP domain. |
| `install_category` | text | no | Install subtype. |
| `platform` | text | no | Platform facet. |
| `provider` | text | no | Provider facet. |
| `ocp_version` | text | no | Version facet. |
| `cluster_topology` | text | no | SNO/compact/HA/etc. |
| `network_mode` | text | no | connected/disconnected/proxy/etc. |
| `environment` | text | no | lab/prod/airgapped/etc. |
| `cli_commands` | jsonb | yes | Command list. |
| `k8s_objects` | jsonb | yes | Kubernetes/OpenShift object names. |
| `operator_names` | jsonb | yes | Operator names. |
| `error_strings` | jsonb | yes | Troubleshooting strings. |
| `verification_hints` | jsonb | yes | Answer/check hints. |
| `beginner_narrative` | text | no | Learner-facing explanation. |
| `review_status` | text | yes | `unreviewed`, `approved`, `rejected`, `generated`. |
| `trust_score` | numeric | yes | Chunk trust score. |
| `metadata` | jsonb | yes | Optional extension only. |
| `created_at` | timestamptz | yes | Audit. |
| `updated_at` | timestamptz | yes | Audit. |

Allowed metadata examples:

```json
{
  "generation_notes": ["normalized from official source"],
  "source_quality": "translated_ko",
  "chunking_strategy": "heading-aware-v1"
}
```

Do not store `domain`, `install_category`, `source_url`, `viewer_artifact_path`, `next_refs`, or candidate questions only in `metadata`.

### JSON Source Text and Embedding Boundary

When the original source is JSON, preserve its structure without letting that structure pollute embeddings.

The target flow is:

```text
source JSON
  -> parsed_documents.raw_payload / raw_text
  -> document_blocks with source_json_path and source_location
  -> corpus_chunks with semantic text plus promoted path/location columns
  -> embedding_text generated only from useful human-facing content
```

Rules:

- `raw_payload` keeps the original JSON object when the source is structured JSON.
- `raw_text` may keep a faithful text rendering of the source, including labels and ordering.
- `document_blocks.source_json_path` and `corpus_chunks.source_json_path` store a JSON Pointer or JSONPath to the upstream node.
- `source_path`, `source_anchor`, `source_location`, `breadcrumb`, and `section_path` are provenance/navigation fields. They may be used for filtering, citation, viewer jumps, and guided learning, but they should not be blindly embedded.
- `normalized_text` is cleaned readable text for keyword search and reranking.
- `embedding_text` must exclude JSON syntax, internal keys, UUIDs, file paths, viewer artifact paths, and structural labels unless the label is semantically meaningful to the user.
- `embedding_text` may include concise semantic context such as title, section title, procedure name, product/version, and install category because those improve retrieval intent matching.

Example:

```json
{
  "source_json_path": "$.books[0].chapters[2].steps[4]",
  "source_path": "installing/azure/create-install-config",
  "title": "Create the install-config.yaml file",
  "normalized_text": "Create install-config.yaml for Azure installation...",
  "embedding_text": "Azure OpenShift installation. Create the install-config.yaml file. Configure pull secret, base domain, region, and platform credentials."
}
```

Do not embed the literal JSON key path. Keep it as retrieval provenance and viewer navigation data.

### `corpus_chunk_assets`

Normalized chunk-to-asset relation. This can be delayed if JSON arrays are kept for v0.1.4 migration phase 1.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `corpus_chunk_id` | uuid | yes | Corpus chunk. |
| `document_asset_id` | uuid | yes | Parser asset. |
| `relation_type` | text | yes | `contains`, `supports`, `evidence`, `viewer`. |
| `ordinal` | integer | yes | Asset order for chunk. |
| `metadata` | jsonb | yes | Optional relation extension. |

### `corpus_chunk_refs`

Guided learning and related-document graph.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Ref identity. |
| `from_chunk_id` | uuid | yes | Source chunk. |
| `to_chunk_id` | uuid | no | Target chunk when known. |
| `to_document_id` | uuid | no | Target document when chunk not known. |
| `ref_type` | text | yes | `prerequisite`, `next`, `related`, `lab`, `same_task_different_platform`. |
| `title` | text | no | Display title. |
| `reason` | text | no | Why this ref exists. |
| `confidence` | numeric | no | Generation confidence. |
| `source` | text | yes | `manual`, `ai_generated`, `manifest_import`, `heuristic`. |
| `metadata` | jsonb | yes | Optional extension. |
| `created_at` | timestamptz | yes | Audit. |

### `corpus_question_candidates`

Studio 추천 질문 source. This replaces hand-written JSONL as the primary source.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Candidate identity. |
| `corpus_chunk_id` | uuid | yes | Source chunk. |
| `corpus_document_id` | uuid | yes | Source document. |
| `question` | text | yes | Candidate question. |
| `question_type` | text | yes | `starter`, `followup`, `troubleshooting`, `command_lookup`, `learning_next`. |
| `source_basis` | text | yes | `chunk_text`, `chunk_command`, `next_ref`, `image_description`, `operator_object`. |
| `generation_method` | text | yes | `heuristic`, `ai_generated`, `curated_fallback`. |
| `generation_model` | text | no | Model used. |
| `generation_version` | integer | yes | Generator version. |
| `quality_status` | text | yes | `candidate`, `approved`, `rejected`, `stale`. |
| `metadata` | jsonb | yes | Optional extension. |
| `created_at` | timestamptz | yes | Audit. |

Studio refresh behavior:

- sample from `quality_status='approved'`
- prefer official/operations corpus
- diversify by `corpus_document_id` and `question_type`
- use curated fallback only when pool is empty

## Projection Tables

### `embedding_jobs`

Target should point to `corpus_chunks`, not `document_chunks`.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Job identity. |
| `corpus_chunk_id` | uuid | yes | Chunk to embed. |
| `model` | text | yes | Embedding model. |
| `status` | text | yes | `queued`, `running`, `completed`, `failed`. |
| `error_message` | text | no | Failure detail. |
| `created_at` | timestamptz | yes | Audit. |
| `completed_at` | timestamptz | no | Completion timestamp. |

### `qdrant_index_entries`

Target should point to `corpus_chunks`.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `corpus_chunk_id` | uuid | yes | Indexed corpus chunk. |
| `collection` | text | yes | Qdrant collection. |
| `point_id` | text | yes | Qdrant point id. |
| `vector_model` | text | yes | Vector model. |
| `payload_version` | integer | yes | Payload schema version. |
| `payload_hash` | text | yes | Projection hash. |
| `indexed_at` | timestamptz | yes | Last index timestamp. |

## Viewer Artifact Table

### `viewer_artifacts`

Optional, but recommended if JSON/HTML viewer output is generated and stored.

| Column | Type | Required | Purpose |
| --- | --- | --- | --- |
| `id` | uuid | yes | Artifact identity. |
| `corpus_document_id` | uuid | no | Related document. |
| `corpus_chunk_id` | uuid | no | Related chunk. |
| `artifact_type` | text | yes | `html`, `json`, `markdown`, `image_index`. |
| `artifact_path` | text | yes | Storage/path. |
| `content_type` | text | yes | MIME type. |
| `checksum` | text | yes | Artifact checksum. |
| `renderer_name` | text | yes | Renderer. |
| `renderer_version` | text | yes | Renderer version. |
| `metadata` | jsonb | yes | Optional render extension. |
| `created_at` | timestamptz | yes | Audit. |

Rule: viewer artifacts are outputs. They must point back to corpus rows.

## Runtime Artifact Tables

Keep `course_chunks`, `course_assets`, and `course_manifests` during transition. Do not treat them as document corpus.

Target direction:

- `course_chunks.payload`: runtime output only
- `course_assets.payload`: runtime output only
- `course_manifests.payload`: runtime output only
- long-term: generate these from corpus/curriculum rows where possible

## Metadata Rules

### JSONB 허용 원칙

JSONB는 완전히 제거하지 않는다. 하지만 아래 목적에만 허용한다.

- parser/tool-specific provenance
- optional UI extension
- temporary migration bridge
- third-party payload preservation
- low-value fields not used for filtering/ranking/routing

### JSONB 금지 대상

아래 값은 JSONB에만 있으면 안 된다.

- `source_url`
- `viewer_artifact_path`
- `domain`
- `install_category`
- `platform`
- `provider`
- `ocp_version`
- `chunk_type`
- `chunk_role`
- `next/prerequisite/related/lab refs`
- `starter/followup question candidates`
- access fields: `visibility`, `owner_user_id`, `tenant_id`, `workspace_id`

## Enum Draft

### `domain`

```text
install
upgrade
networking
storage
operators
security
authentication
authorization
monitoring
logging
backup_restore
troubleshooting
application_deployment
architecture
```

### `install_category`

```text
ipi
upi
agent_based
assisted
single_node
disconnected
connected
post_install
not_applicable
```

### `platform`

```text
aws
azure
gcp
vsphere
baremetal
openstack
vm
local
none
```

### `chunk_type`

```text
concept
procedure
command
troubleshooting
reference
navigation
example
warning
```

## Migration Compatibility Plan

1. Add `corpus_documents`, `corpus_chunks`, and optional `viewer_artifacts`.
2. Backfill from `document_sources`, `parsed_documents`, and `document_chunks`.
3. Build compatibility view or dual-read adapter so existing RAG can still read old payload shape.
4. Update Qdrant projection to read from `corpus_chunks`.
5. Generate `corpus_question_candidates` from corpus chunks.
6. Keep `ops_learning_chunks_v1.jsonl` as fallback until equivalent starter question and ops learning coverage is proven.
7. Add deletion manifest for data files.
8. Remove or archive redundant JSON/runtime seeds only after compatibility tests pass.

## First SQL Migration Scope

Do not try to solve every relation in the first migration.

Recommended first migration:

- add `corpus_documents`
- add `corpus_chunks`
- add `corpus_question_candidates`
- add `viewer_artifacts` if viewer storage remains file-based
- add compatibility indexes
- do not delete `document_chunks`
- do not delete course runtime tables
- do not delete JSONL data files

Deferred:

- `corpus_chunk_assets`
- `corpus_chunk_refs`
- `corpus_chunk_facets`
- deletion of `qwen_*` legacy columns
- deletion of runtime seed JSONL
