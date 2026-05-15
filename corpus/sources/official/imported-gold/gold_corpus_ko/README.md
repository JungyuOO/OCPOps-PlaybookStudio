# Official Korean Retrieval Corpus

This folder contains imported official Korean retrieval rows.

## Files

- `chunks.jsonl`: chunk-level retrieval rows.
- `bm25_corpus.jsonl`: sparse/BM25 retrieval rows.

## Role

Use this as an import seed or regression comparison for official document
retrieval.

## Caveat

This is not a complete Wiki Gold package. It currently lacks bundled image
assets, explicit source-first asset links, relation indexes, and package-level
handoff evidence.

## v0.1.4 Caveat

These rows are useful for comparison, but they still behave like legacy
retrieval rows:

- prose, code, tables, and outputs can still be mixed in one text field
- `chunks.jsonl` is not the same thing as `corpus_chunk_segments`
- BM25 rows are not the same thing as `normalized_text` contract proof
- Qdrant freshness must be proven from DB index entries and payload version, not
  this folder alone
