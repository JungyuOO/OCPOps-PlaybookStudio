# v0.1.4 Document Corpus Canonicalization and RAG Quality Reset

## Goal

v0.1.4는 새로운 기능 추가보다 문서 처리 파이프라인과 저장 구조를 먼저 정리한다.

첫 산출물은 `spec/v0.1.4/db-corpus-schema-audit.md`다. 해당 감사 문서의 결정 항목이 정리되기 전에는 schema migration을 작성하지 않는다.

현재 구조는 `document_sources`, `parsed_documents`, `document_blocks`, `document_assets`, `document_chunks`,
Qdrant payload, viewer JSON/HTML, course runtime chunk가 동시에 존재한다. 기능상 분리는 되어 있지만 운영자가
"어떤 데이터가 검색 원본이고 어떤 데이터가 렌더링 산출물인지" 즉시 판단하기 어렵다. 이 상태에서는 RAG 품질을 올리기 전에
문서 자체의 추출, 정규화, chunk metadata, 검색 payload 경계를 먼저 재정의해야 한다.

## Principles

- Postgres가 canonical corpus truth다. Qdrant는 파생 색인이고, viewer JSON/HTML은 렌더링 산출물이다.
- v0.1.4의 1순위는 parsing storage와 corpus storage를 분리하는 것이다.
- 문서 원본, 추출 결과, 정규화 텍스트, 이미지/OCR, chunk, viewer artifact를 한 단계씩 구분한다.
- JSONB는 무제한 잡동사니 저장소가 아니라 "확장 필드"로만 쓴다. 검색/필터/운영 판단에 필요한 값은 컬럼으로 승격한다.
- 평가 report, smoke output, app build artifact, tmp 산출물은 corpus import 대상이 아니다.
- Viewer가 JSON 기반이든 HTML 기반이든 DB의 canonical document/chunk 구조는 같아야 한다.

## Current Pain

- 테이블이 많고 JSONB payload가 많아 source of truth를 알기 어렵다.
- `document_chunks.metadata` 안에 `viewer_path`, `source_url`, `learning.next_refs`, `starter_question_candidates` 등이 들어가지만,
  어떤 필드가 필수인지 명확하지 않다.
- 공식문서, 업로드 문서, course 학습 카드, viewer artifact가 서로 다른 payload shape을 가진다.
- RAG 검색 필터에 중요한 도메인 facet이 구조화되어 있지 않다. 예: `install_category`, `platform`, `provider`, `ocp_version`.
- 문서 parsing과 viewer generation이 섞여 보이며, viewer 저장 형식(JSON/HTML)이 DB schema 판단에 영향을 주고 있다.

## Canonical Pipeline

1. Source Registration
   - 원본 문서 등록.
   - URL, local path, repository id, source scope, version, language, source kind 기록.

2. Extraction
   - 텍스트 추출.
   - OCR 수행.
   - 이미지/도표 추출.
   - 이미지 description 생성.
   - 결과는 block/asset 단위로 저장.

3. Normalization
   - 공백/제어문자/깨진 인코딩/불필요한 boilerplate 정리.
   - Markdown/table/code block 구조 보존.
   - 원문 텍스트와 normalized text를 분리 저장.

4. Structural Enrichment
   - title, chapter, section, heading, breadcrumb, anchor 생성.
   - document order, previous/next section, previous/next document 연결.
   - OCP domain facet 부여.

5. Chunking
   - retrieval chunk 생성.
   - chunk_type: `concept`, `procedure`, `command`, `troubleshooting`, `reference`, `navigation`.
   - chunk_role: `parent`, `leaf`, `summary`, `navigation`.
   - parent/child relation과 next/related refs 저장.

6. Index Projection
   - Postgres canonical chunk에서 Qdrant payload 생성.
   - Qdrant에는 검색에 필요한 projection만 넣는다.
   - Qdrant payload는 DB에서 재생성 가능해야 한다.

7. Viewer Artifact
   - JSON viewer든 HTML viewer든 artifact로 취급.
   - canonical DB는 viewer 형식과 무관해야 한다.
   - viewer_path는 chunk/document를 가리키는 링크일 뿐 truth가 아니다.

## Proposed Canonical Tables

Keep existing tables where possible, but define ownership clearly:

가능하면 기존 테이블은 유지하되, 각 테이블의 ownership을 명확히 정의한다.

Primary v0.1.4 decision: parser output tables and corpus tables should not be the same conceptual layer.

v0.1.4의 핵심 결정은 parser output table과 corpus table을 같은 개념 계층으로 보지 않는 것이다.

- Parsing layer:
  - `parse_jobs`
  - `parsed_documents`
  - `document_blocks`
  - `document_assets`
- Corpus layer:
  - future `corpus_documents`
  - future `corpus_chunks`
  - future relation tables for chunk assets and learning refs if needed
- Projection/runtime layer:
  - `qdrant_index_entries`
  - `embedding_jobs`
  - viewer JSON/HTML artifacts
  - course runtime tables

- `document_sources`
  - Canonical source identity.
  - Required: `source_uri`, `source_path`, `source_scope`, `source_type`, `source_collection`, `version`, `locale`.

- `document_versions`
  - Immutable source version.
  - Required: source hash, storage key, ingestion run id.

- `parsed_documents`
  - Extraction run output for a document version.
  - Required: parser backend, extraction status, document title, parser metadata.

- `document_blocks`
  - Extracted structural units.
  - Required: block type, raw text, normalized text, page, section anchor, asset link.

- `document_assets`
  - Images/tables/figures.
  - Required: asset type, storage path, OCR text, generated description, model provenance.

- `document_chunks`
  - Retrieval unit and Qdrant source.
  - Required columns should include:
    - `chunk_type`
    - `chunk_role`
    - `title`
    - `section_title`
    - `section_path`
    - `source_anchor`
    - `viewer_path`
    - `source_url`
    - `install_category`
    - `platform`
    - `provider`
    - `ocp_version`
    - `next_chunk_id`
    - `next_document_source_id`
    - `metadata` for non-filter extension only

- `qdrant_index_entries`
  - Projection status only.
  - Should answer: this chunk id is indexed in this collection with this payload version.

## Metadata Contract

Every retrievable chunk should have:

```json
{
  "title": "Installing a cluster on Azure",
  "section_title": "Creating the installation configuration file",
  "section_path": ["Installing", "Azure", "Installer-provisioned infrastructure"],
  "viewer_path": "/docs/ocp/4.20/ko/installing_on_azure/index.html#create-install-config",
  "source_url": "https://docs.redhat.com/...",
  "chunk_type": "procedure",
  "domain": "install",
  "install_category": "ipi",
  "platform": "azure",
  "provider": "azure",
  "ocp_version": "4.20",
  "next_refs": [
    {
      "kind": "section",
      "title": "Deploying the cluster",
      "viewer_path": "...",
      "chunk_id": "..."
    }
  ],
  "related_refs": [
    {
      "kind": "document",
      "title": "Installing on AWS",
      "viewer_path": "...",
      "relation": "same_task_different_platform"
    }
  ],
  "starter_question_candidates": [],
  "followup_question_candidates": []
}
```

Fields used for filtering/ranking should be columns or generated columns, not only nested JSON.

## OCP Facets

Install-related OCP docs need explicit facets:

- `domain`: install, upgrade, networking, storage, operators, security, troubleshooting
- `install_category`: ipi, upi, disconnected, assisted, single_node, agent_based
- `platform`: aws, azure, gcp, vsphere, baremetal, openstack, none
- `provider`: aws, azure, gcp, vmware, redhat, user
- `cluster_topology`: single_node, compact, multi_node
- `network_mode`: ovn_kubernetes, openshift_sdn, none
- `environment`: connected, disconnected, restricted_network

These values should be available to retriever, reranker prompt, starter question generator, and viewer navigation.

## Audit Tasks

- Audit the existing DB table/column contract first.
  - Output: `spec/v0.1.4/db-corpus-schema-audit.md`.
  - Classify each table/column as canonical, derived, status, artifact, legacy, or candidate.
  - Decide which JSONB/payload fields must become explicit columns before writing migration SQL.
- List every JSON/JSONL artifact currently used as corpus source, viewer artifact, eval report, temporary output, or course runtime artifact.
- Mark each path as:
  - `canonical_source`
  - `parsed_artifact`
  - `viewer_artifact`
  - `index_projection`
  - `eval_report`
  - `temporary`
  - `deprecated`
- Verify no `reports/`, `tmp/`, smoke JSON, or eval output is imported into `document_sources`.
- Dump current `document_chunks.metadata` key frequency.
- Dump current Qdrant payload key frequency.
- Compare Postgres chunk metadata vs Qdrant payload projection.

## Implementation Phases

### Phase A: Corpus Audit

- Add audit command that prints:
  - source counts by `source_scope`, `source_type`, `source_collection`
  - metadata key frequency
  - chunks missing `viewer_path`, `source_url`, `title`, `section_path`
  - chunks with empty `next_refs` / `related_refs`
  - suspected non-corpus sources: reports, smoke, tmp, artifacts, dist

### Phase B: Metadata Contract

- Define required metadata contract for retrievable chunks.
- Add validation tests for official docs and uploaded docs.
- Introduce missing columns or generated columns for high-value facets.

### Phase C: Parser Pipeline Cleanup

- Separate extraction, normalization, enrichment, chunking, viewer generation.
- Preserve raw text and normalized text.
- Add image OCR/description provenance.

### Phase D: Qdrant Projection Reset

- Make Qdrant payload a deterministic projection from Postgres.
- Add payload version.
- Rebuild Qdrant collection after DB contract passes.

### Phase E: Viewer Independence

- Treat JSON/HTML viewer outputs as artifacts.
- Ensure viewer_path resolves from DB canonical chunk/document metadata.
- Viewer storage format must not change DB schema.

## DoD

- A developer can answer "what is indexed in Qdrant?" with one SQL query.
- Every Qdrant payload can be traced back to `document_chunks.id`.
- Every retrievable chunk has title, section, source URL, viewer path, chunk type, and OCP facets when applicable.
- Next-step / related-document refs are populated or explicitly empty with reason.
- No eval/smoke/report artifacts are imported as corpus.
- Viewer JSON/HTML can be regenerated from DB canonical state.
