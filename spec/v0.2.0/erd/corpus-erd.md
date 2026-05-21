# Corpus ERD Draft

## Goal

Track candidate shapes for official/user corpus artifacts, LLM enrichment runs, retrieval indexes, and Qdrant sync state without mixing raw source data with retrieval-ready chunks.

This document is not a final schema. Official corpus storage must remain undecided until v0.2.2 analyzes the existing `chunks.jsonl`, enrichment sample quality, and rebuild options.

## Candidate Tables

These tables are candidates. They must not be turned into SQL migrations before the v0.2.2 corpus audit decision.

### corpus_sources

Source document or source collection identity.

Key fields:

- `id`
- `source_scope`
- `source_type`
- `source_uri`
- `version`
- `status`
- `metadata`

### corpus_artifacts

Generated artifact files such as raw chunks, cleaned chunks, enriched chunks, and text layers.

Key fields:

- `id`
- `source_id`
- `artifact_type`
- `artifact_path`
- `schema_version`
- `content_hash`
- `created_at`

### enrichment_runs

Batch run metadata for LLM enrichment.

Key fields:

- `id`
- `artifact_id`
- `prompt_version`
- `model`
- `status`
- `started_at`
- `completed_at`
- `error_message`

### enrichment_run_items

Per chunk enrichment status.

Key fields:

- `id`
- `run_id`
- `chunk_id`
- `status`
- `warnings`
- `output_payload`

### retrieval_vectors

Candidate table if pgvector becomes the default vector backend.

Key fields:

- `id`
- `chunk_id`
- `source_scope`
- `embedding_model`
- `embedding_dimensions`
- `embedding`
- `payload`
- `created_at`
- `updated_at`

This table must not be created until the Qdrant vs pgvector benchmark is complete.

## Notes

Existing `document_sources`, `parsed_documents`, and `document_chunks` must be audited before adding overlapping tables.

Possible outcomes after v0.2.2:

- keep existing tables and extend metadata
- split raw chunks and retrieval chunks
- introduce corpus artifact tables only
- rebuild official corpus from source documents
- separate `manual_synthesis` from official docs
