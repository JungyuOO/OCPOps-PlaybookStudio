# Wiki Relations

This folder contains relation sidecars for wiki navigation.

## Typical Files

- `figure_assets.json`
- `figure_section_index.json`
- `figure_entity_index.json`
- `section_relation_index.json`
- `candidate_relations.json`

These are sidecar relation indexes. They should be regenerated from the same
source-first package that produces chunks and assets.

## v0.1.4 Caveat

Relations should eventually become `corpus_chunk_refs` or deterministic
topology/reader evidence. Sidecar JSON files are useful for migration, but they
are not the single source of truth for followups or next-step guidance.
