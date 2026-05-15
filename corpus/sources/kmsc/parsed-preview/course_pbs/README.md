# KMSC Course PBS Package

This is the cleanest current customer corpus package.

Although the parent folder still says `parsed-preview`, this package is treated
as the current customer corpus reference package. The name is kept for path
compatibility with import jobs and tests.

## Contents

- `chunks.jsonl`: 523 customer/training chunks.
- `assets/`: extracted visual assets used by chunks.
- `manifests/course_v1.json`: course structure.
- `manifests/ops_learning_guides_v1.json`: guided learning paths.
- `manifests/ops_learning_chunks_v1.jsonl`: answer/evaluation-oriented learning
  chunks.

## Why It Matters

Chunks include image attachments, visual text, provenance, facets, and related
official document links. This folder is the model for how future official Wiki
Gold packages should be organized.

## v0.1.4 Use

Use this package as the customer/KMSC dry-run sample for the v0.1.4 path.

Minimum mapping to verify:

- source package -> `document_sources`
- chunk/package metadata -> `parsed_documents` and `document_blocks`
- image files -> `document_assets`
- text/procedure/command/image evidence -> `corpus_chunk_segments`
- learning routes and golden cases -> `corpus_chunk_refs` and
  `corpus_question_candidates`

Do not call this package final product Gold by itself. It is a clean source
package reference, and runtime truth still needs DB/Qdrant/storage checks.

## Runtime Contract

- Import scope: `study_docs`.
- Import shape: package directory with chunks, assets, and manifests together.
- Runtime truth after import: PostgreSQL, Qdrant, and storage, not this folder.
- Cleanup rule: do not rename or move this path until deploy jobs, tests, and
  `corpus_paths.py` aliases have moved first.
