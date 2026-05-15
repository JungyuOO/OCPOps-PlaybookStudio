# Corpus Audit

This document is the shared S/J contract for what lives under `corpus/`.

Related docs:

- `docs/corpus/METADATA_CORPUS_STRATEGY_2026-05-15.md`
- `docs/corpus/J_HANDOFF_METADATA_CORPUS_SUMMARY_2026-05-15.md`
- `docs/corpus/V014_TERM_BRIDGE.md`

## Operating Rule

`corpus/` is a seed/import/evidence area. After import, the product runtime truth
is PostgreSQL, Qdrant, and runtime storage. Do not treat a JSON/JSONL file under
`corpus/` as proof that the runtime product is healthy.

## v0.1.4 Boundary Contract

The current cleanup follows J's v0.1.4 schema split:

```text
corpus folder evidence
  -> parsing layer: source, version, parse job, parsed doc, blocks, assets
  -> corpus layer: documents, chunks, segments, commands, refs, questions
  -> projection: Qdrant payload and embedding jobs
  -> product runtime: Reader, Studio, Chat
```

Folder cleanup must not hide these boundaries. If a folder only contains legacy
seed files, say that. If a folder is a runtime sidecar, say that. If a package is
a clean source package, say how it maps into parsing/corpus.

New v0.1.4 checks added on 2026-05-15:

- Text must be explainable as `raw_text`, `markdown`, `normalized_text`, and
  `embedding_text`.
- UTF-8 handling is part of data quality, not a cosmetic cleanup.
- Qdrant is a deterministic projection; `embedding_text` or payload changes mean
  drop/rebuild planning, not silent reuse.

## Folder Decisions

| Path | Role | Runtime dependency | Decision | Evidence |
| --- | --- | --- | --- | --- |
| `corpus/sources/official/imported-gold/` | Legacy official retrieval seed | Import jobs, settings defaults, tests | Keep, document as legacy | Name says Gold but assets/topology/quality handoff are not closed |
| `corpus/sources/official/imported-gold/gold_candidate_books/` | Candidate rebuild manifest | Rebuild/evidence only | Keep, document as candidate evidence | Contains `full_rebuild_manifest.json`, not product Gold |
| `corpus/sources/official/imported-gold/gold_corpus_ko/` | Official retrieval chunks/BM25 seed | Official import and Qdrant refresh | Keep with deprecated meaning | Product Gold must be proven in DB/Qdrant/storage |
| `corpus/sources/official/imported-gold/gold_manualbook_ko/` | Generated manualbook/playbook artifacts | Viewer/source-book fallbacks | Keep with deprecated meaning | Still code-bound |
| `corpus/sources/official/imported-gold/silver_ko/` | Translation draft/cache evidence | Translation/rebuild tooling | Keep as build evidence | Not runtime truth |
| `corpus/sources/kmsc/parsed-preview/course_pbs/` | Current clean customer course package | Course import, KMSC import, tests | Keep, treat as reference package | Has chunks, assets, manifests, provenance, visual text |
| `corpus/manifests/official/` | Official source selection and rebuild control | Settings defaults and rebuild jobs | Keep | Active and candidate manifests must not be mixed silently |
| `corpus/manifests/course/` | Course/eval/handoff control | Course learning/eval jobs | Keep | Versioned QA and learning cases |
| `corpus/manifests/eval/` | Retrieval/answer evaluation cases | Evaluation commands | Keep | Shared quality evidence |
| `corpus/data/wiki_assets/` | Transitional wiki image assets | Viewer/relations support | Keep as sidecar | Not DB runtime truth |
| `corpus/data/wiki_relations/` | Transitional figure/entity/section relations | Wiki relation APIs | Keep as sidecar | Not DB runtime truth |
| `corpus/data/wiki_runtime_books/` | Transitional runtime manifest sidecar | Runtime freeze and viewer compatibility | Keep as legacy sidecar | Some recorded paths are stale |

## Current Inventory Baseline - 2026-05-15

Source: `worklog_S/todo/2026-05-15-inventory-baseline.md`.

| Item | Value |
| --- | ---: |
| Official source/runtime docs | 29 |
| Official catalog live | 29 |
| Official catalog candidates | 84 |
| Official catalog total | 113 |
| Gold Ready | 23 |
| Gold Repair | 11 |
| Official chunks | 27,907 |
| Study/KMSC chunks | 523 |
| User upload sources | 10 |
| User upload parsed docs | 14 |
| User upload chunks | 108 |
| User upload assets | 25 |
| Qdrant index entries | 28,538 |

## Naming Contract

- `Gold` in legacy folder names means historical retrieval seed, not product Gold.
- Product Gold means readable chunks, source/asset evidence, topology, quality
  snapshot, DB import, Qdrant index, and UI/reader verification all pass.
- `course_pbs` is the current clean customer package model despite the
  `parsed-preview` parent name.

## Reference Package Model

The clean reference package is:

```text
corpus/sources/kmsc/parsed-preview/course_pbs/
|-- README.md
|-- chunks.jsonl
|-- assets/
`-- manifests/
```

Future official/user-upload-derived packages should follow this packaging shape
before adding richer `quality/` and `handoff/` directories. The immediate cleanup
goal is not "move everything today"; it is to make every retained folder explain
whether it is a package, a manifest/control folder, or a transitional sidecar.

## Physical Cleanup Status - 2026-05-15

- Empty folders found: 0.
- Immediate delete candidates: none.
- Direct code/test references still exist for `course_pbs`, `imported-gold`,
  `gold_corpus_ko`, `gold_manualbook_ko`, `wiki_assets`, `wiki_relations`, and
  `wiki_runtime_books`.
- Physical rename/delete should wait until those references are routed through
  resolver aliases.

## Cleanup Rules

- Delete empty folders after confirming no runtime job creates them.
- Do not rename code-bound paths in the same step as documentation cleanup.
- Add resolver aliases first, update imports/tests second, then move paths only
  after `rg` shows no direct legacy literals outside compatibility shims.
- New source packages must include a README that states role, owner, import
  command, runtime dependency, and acceptance evidence.

## J Handoff Summary

- We hand off corpus health, metadata coverage, expected chunk IDs, known
  blockers, and golden questions.
- J should treat selected chunk IDs and citations as runtime evidence.
- If an answer fails and the correct chunk does not exist, it is a corpus gap.
- If the correct chunk exists but retrieval misses it, it is a retrieval/meta
  matching gap.
- If the correct chunk is selected but the answer is wrong, it is a chatbot
  answer-generation gap.
