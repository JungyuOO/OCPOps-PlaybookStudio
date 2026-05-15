# Official Sources

This folder is for official OpenShift documentation inputs and generated official
corpus packages.

## Current State

- `imported-gold/` contains legacy imported official corpus artifacts.
- `imported-gold/gold_candidate_books/` contains a candidate rebuild manifest,
  not product Gold.
- Source-first manifest files live under `corpus/manifests/official/`.
- A future source-first package should be added here with an explicit name such
  as `source-first-gold/` once chunks, assets, relations, quality, and handoff are
  produced together.

Current inventory baseline:

- live official source/runtime docs: 29
- official catalog candidates: 84
- official catalog total: 113
- current official assets in DB baseline: 0

This means the official folder is not yet a complete v0.1.4 product corpus
package. It is a legacy official seed plus source-first manifest evidence.

## Rule

Do not treat `imported-gold/` as final product Gold unless the package includes
source provenance, assets, relations/topology, quality evidence, and a handoff
report.

For v0.1.4 dry-run, official data must prove how an official source maps into:

```text
document_sources
document_versions
parse_jobs
parsed_documents
document_blocks
document_assets
corpus_documents
corpus_chunks
corpus_chunk_segments
corpus_chunk_commands
corpus_chunk_refs
corpus_question_candidates
```

## Target Shape

Official packages should move toward the KMSC package model:

```text
official/<package-name>/
|-- README.md
|-- chunks.jsonl
|-- assets/
|-- manifests/
|-- quality/
`-- handoff/
```

Until imports/tests stop referencing `imported-gold`, keep the legacy path and
document its meaning instead of renaming it in place.
