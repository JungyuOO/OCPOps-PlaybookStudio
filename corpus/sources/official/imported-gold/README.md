# Imported Official Legacy Retrieval Seeds

This is a legacy imported official corpus area.

The folder name includes `gold` because these files were previously used as
approved official retrieval seeds. It does not automatically mean product-level
Wiki Gold.

Do not use this folder name as evidence that the current official corpus has
passed product Gold. For product Gold, the runtime DB/Qdrant/storage state must
also prove readable chunks, source/asset evidence, topology, quality snapshots,
and import/index verification.

## Contents

- `gold_corpus_ko/`: official Korean retrieval chunks and BM25 rows.
- `gold_manualbook_ko/`: generated playbook/manualbook documents.
- `silver_ko/`: translation drafts, normalized docs, and translation cache.
- `gold_candidate_books/`: candidate rebuild manifest artifacts.

## Current Caveat

The current official package is text-heavy. Assets, source-first provenance,
relations/topology, and quality handoff are not closed in one package yet.

## v0.1.4 Interpretation

Treat this folder as legacy retrieval seed/evidence.

It is useful for:

- comparing old chunk/text artifacts
- checking historical official book coverage
- rebuilding compatibility imports while code still references this path

It is not enough for:

- v0.1.4 segment/command/ref proof
- official image/asset coverage
- `raw_text` / `markdown` / `normalized_text` / `embedding_text` 4-layer proof
- Qdrant payload freshness after schema changes
- product Gold certification

Before this folder can be replaced, direct code/test references must move to
resolver aliases and the new official package must pass dry-run mapping.
