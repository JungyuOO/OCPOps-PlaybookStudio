# Corpus Manifests

This folder contains manifests that describe what should be imported, evaluated,
or handed off.

Manifests are control files, not runtime truth. They decide or explain what
should be imported, evaluated, or handed off, but the current product state must
be checked through PostgreSQL, Qdrant, storage, and API summaries.

## Subfolders

- `official/`: OpenShift official document source selection and rebuild
  manifests.
- `course/`: KMSC/course evaluation and learning manifests.
- `eval/`: answer, retrieval, RAGAS, and smoke test cases.
- `demo/`: demo and scenario manifests.
- `concepts/`: concept synonym and taxonomy manifests.

Manifests should explain intent. Large row data belongs in source packages as
JSONL.

## v0.1.4 Rule

Manifests should use the same language as the schema specs:

- source selection feeds `document_sources` and `document_versions`
- parsing evidence maps to `parsed_documents`, `document_blocks`, `document_assets`
- answer/search evaluation maps to `corpus_chunks`, `corpus_chunk_segments`,
  `corpus_chunk_commands`, `corpus_chunk_refs`, and `corpus_question_candidates`
- Qdrant manifests must state payload version and rebuild requirement when the
  projection shape changes
