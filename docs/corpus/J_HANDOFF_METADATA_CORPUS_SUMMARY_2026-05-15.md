# J Handoff - Metadata Corpus Summary

## Current State

S side already writes deterministic metadata spine fields to PostgreSQL chunks and
Qdrant payloads. This is not yet a promise that chatbot answers are good.
It means the corpus now has measurable retrieval features that J can inspect.

Runtime coverage measured on 2026-05-15:

| scope | documents | chunks | metadata spine | answerable questions |
| --- | ---: | ---: | ---: | ---: |
| official_docs | 29 | 27,907 | 100% | 100% |
| study_docs | 9 | 523 | 100% | 100% |
| user_upload | 10 | 108 | 100% | 100% |

Important caveat:

- Coverage is high, but generated metadata quality still needs review.
- Samples show Korean question wording issues and command extraction false positives.
- Owner-private `user_upload` does not appear in anonymous handoff report by default.

## Division of Work

S owns:

- source package / corpus package
- parsing quality
- reader markdown
- chunking
- metadata spine
- topology and asset evidence
- corpus handoff report
- golden questions with expected chunk IDs

J owns:

- query rewrite
- BM25/vector fusion
- reranker
- selected chunk IDs
- answer generation
- citation formatting
- chat pipeline trace
- Ops/live context integration

Shared:

- metadata matching
- retrieval evaluation
- citation precision
- failure classification

## Failure Classification

| Case | Classification | Owner |
| --- | --- | --- |
| Correct source/chunk does not exist | corpus_gap | S |
| Correct chunk exists but metadata is wrong or weak | metadata_gap | S, then shared |
| Correct chunk exists but is not retrieved top-k | retrieval_gap | J + S metadata |
| Correct chunk is selected but answer is wrong | answer_gap | J |
| Citation points to wrong source | citation_gap | Shared |
| Version/environment mismatch | context_gap | Shared |

## Contract J Should Return Per Answer

- `query`
- `rewritten_query`
- `selected_chunk_ids`
- `reranker_result`
- `citations`
- `response_kind`
- `pipeline_trace`

## Contract S Should Return Per Corpus Handoff

- `corpus_version`
- scope document/chunk counts
- metadata coverage
- topology/quality state
- golden questions
- expected chunk IDs
- known blockers

## Agreement Needed Today

1. Use shared golden questions instead of arguing from single chat examples.
2. If an answer fails, classify it as corpus/meta/retrieval/answer/citation/context.
3. Do not strip all special characters or spaces from source data. YAML, CLI flags,
   URLs, annotations, labels, paths, and error strings are core data.
4. Treat JSON/JSONL under `corpus/` as seed/import/evidence. Runtime truth is
   PostgreSQL, Qdrant, and storage.
