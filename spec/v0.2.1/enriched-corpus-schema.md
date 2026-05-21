# v0.2.1 Enriched Corpus Schema Draft

## Purpose

Define the schema shape that v0.2.2 should prototype and v0.2.3 may apply to the full official corpus.

The core design rule is separation:

```text
raw/citation chunk != retrieval-ready chunk
```

The raw chunk preserves source text and citation identity. The retrieval chunk contains cleaned text and search metadata optimized for RAG.

## Schema Units

### raw_chunk

Raw chunk preserves current source identity.

Required fields:

```json
{
  "chunk_id": "uuid",
  "source_id": "openshift_container_platform:4.20:ko:advanced_networking",
  "book_slug": "advanced_networking",
  "book_title": "...",
  "chapter": "...",
  "section": "...",
  "section_id": "...",
  "section_path": ["..."],
  "anchor": "...",
  "anchor_id": "...",
  "source_url": "https://docs.redhat.com/...",
  "viewer_path": "/docs/...",
  "text": "...",
  "token_count": 128,
  "chunk_type": "concept",
  "source_type": "official_doc",
  "source_lane": "official_ko",
  "review_status": "approved",
  "citation_eligible": true
}
```

Rules:

- Preserve `chunk_id` when enriching existing chunks.
- Preserve `source_url` and `viewer_path` exactly.
- Preserve raw `text` even if dirty.
- Do not place LLM-generated wording into raw fields.

### retrieval_chunk

Retrieval chunk is derived from raw chunk plus deterministic cleanup and optional LLM enrichment.

Required fields:

```json
{
  "chunk_id": "uuid",
  "raw_chunk_id": "uuid",
  "schema_version": "retrieval_chunk.v1",
  "source": {},
  "chunk": {},
  "text_fields": {},
  "search_signals": {},
  "quality": {},
  "provenance": {}
}
```

## Source Block

```json
{
  "source": {
    "source_id": "openshift_container_platform:4.20:ko:advanced_networking",
    "source_type": "official_doc",
    "source_lane": "official_ko",
    "source_collection": "core",
    "product": "openshift",
    "version": "4.20",
    "locale": "ko",
    "trust_level": "official",
    "citation_eligible": true,
    "source_url": "https://docs.redhat.com/...",
    "viewer_path": "/docs/..."
  }
}
```

Rules:

- `source_type` must distinguish `official_doc`, `manual_synthesis`, `study_doc`, and future `runtime_context`.
- `trust_level` should not be inferred only from `source_type`; review status and citation eligibility also matter.
- Manual synthesis must be routable separately from official docs.

## Chunk Block

```json
{
  "chunk": {
    "book_slug": "advanced_networking",
    "section_id": "advanced_networking:verifying-connectivity-endpoint",
    "section_path": ["..."],
    "anchor_id": "verifying-connectivity-endpoint",
    "chunk_type": "concept",
    "semantic_role": "concept",
    "chunk_role": "leaf",
    "parent_chunk_id": null,
    "child_chunk_ids": []
  }
}
```

Allowed `semantic_role` values:

```text
concept
procedure
command_reference
troubleshooting
warning
requirement
verification
architecture
navigation
reference
unknown
```

Navigation-only chunks should be searchable only when the query is about document location or overview.

## Text Fields

```json
{
  "text_fields": {
    "raw_text": "...",
    "clean_text": "...",
    "normalized_text": "...",
    "embedding_text": "...",
    "summary": "...",
    "title_path_text": "advanced_networking > ..."
  }
}
```

Rules:

- `raw_text` is copied from source.
- `clean_text` is deterministic cleanup output.
- `normalized_text` is for lexical/BM25 search.
- `embedding_text` is optimized for semantic retrieval and may include concise question-like phrases.
- `summary` must not introduce facts absent from raw/clean text.

`embedding_text` should include:

- object/operator names found in the source
- important command names grounded in text
- symptom/error wording grounded in text
- procedure purpose
- alternative Korean/English operational expressions when supported by source terms

`embedding_text` should not include:

- unsupported commands
- broad product marketing copy
- unrelated keyword stuffing
- hidden boost strings
- user/customer/private data

## Search Signals

```json
{
  "search_signals": {
    "primary_topics": [],
    "secondary_topics": [],
    "objects": [],
    "object_aliases": [],
    "operators": [],
    "commands": [],
    "command_families": [],
    "error_states": [],
    "intent_labels": [],
    "answer_shapes": [],
    "best_for_questions": []
  }
}
```

Allowed `answer_shapes`:

```text
definition
step_by_step
command_lookup
diagnosis
comparison
warning
verification_checklist
configuration_example
no_answer
```

Rules:

- `objects` must use canonical singular Kubernetes/OpenShift resource names.
- `object_aliases` may preserve source/user terms such as `PVC`, `PV`, `Pods`, `Nodes`, or `Deployments`.
- aliases must not be used as primary metadata filter keys.
- `commands` must be grounded in raw/clean text.
- `best_for_questions` should be realistic user questions, not artificial keyword lists.
- `intent_labels` should describe what the chunk can answer, not what it merely mentions.

## Quality Block

```json
{
  "quality": {
    "quality_warnings": [],
    "dirty_marker_count": 0,
    "mojibake_suspect": false,
    "navigation_only": false,
    "command_grounding_status": "grounded",
    "object_grounding_status": "grounded",
    "source_url_valid": true,
    "viewer_path_valid": true,
    "enrichment_status": "validated"
  }
}
```

Allowed `enrichment_status`:

```text
not_enriched
llm_generated
validated
rejected
manual_review
```

## Provenance Block

```json
{
  "provenance": {
    "raw_artifact": "gold_corpus_ko/chunks.jsonl",
    "cleanup_version": "deterministic-cleanup.v1",
    "enrichment_model": "unset",
    "enrichment_prompt_version": "unset",
    "validator_version": "enriched-validator.v1",
    "created_at": "ISO-8601",
    "updated_at": "ISO-8601"
  }
}
```

## Artifact Shape

Prototype output for v0.2.2:

```text
artifacts/v0.2.2/enriched_sample/retrieval_chunks.sample.jsonl
artifacts/v0.2.2/enriched_sample/audit_report.json
artifacts/v0.2.2/enriched_sample/validation_report.json
```

Do not commit generated artifacts unless promoted to `spec/v0.2.2/evidence/`.

## Migration Boundary

This schema is not a database migration.

v0.2.1 must not create:

- new corpus tables
- pgvector tables
- Qdrant collections
- DB indexes

Database mapping is decided after v0.2.2 audit/prototype and v0.2.4 vector backend benchmark.
