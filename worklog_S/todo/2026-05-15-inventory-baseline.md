# 2026-05-15 Inventory Baseline

Purpose: v0.1.4 dry-run과 corpus 정리 전에 현재 데이터 숫자를 고정한다.

## Why This Comes First

지금 먼저 해야 할 일은 구현이 아니라 인벤토리 baseline이다.

이유:

- `29개`, `34권`, `113개`가 서로 다른 단위를 세고 있다.
- parsing/corpus/Qdrant/runtime output이 섞이면 dry-run mapping도 틀어진다.
- v0.1.4 schema로 가려면 현재 데이터가 어느 계층에 있는지 먼저 알아야 한다.

## Runtime/API Baseline

Checked from `/api/data-control-room`, `/api/repositories/official-catalog`, `/api/repositories/topology?scope=official`.

| Metric | Current value | Meaning |
| --- | ---: | --- |
| Official source/runtime docs | 29 | 현재 공식 문서 live/imported 기준 |
| Official catalog total | 113 | live 29 + candidate 84 |
| Official catalog live | 29 | DB/live에 있는 공식 문서 |
| Official catalog candidates | 84 | 아직 materialized 되지 않은 후보 |
| Gold Ready | 23 | 운영 위키 Gold ready output |
| Gold Recovery / repair needed | 11 | Gold로 가기 위한 repair queue |
| Official corpus chunks | 27,907 | 공식 문서 chunk 수 |
| Customer/study chunks | 523 | KMSC/customer study docs chunk 수 |
| Total repository chunks | 28,538 | API summary 기준 전체 indexed chunk |
| Qdrant index entries | 28,538 | DB `qdrant_index_entries` count |
| Qdrant parity | true | API summary 기준 DB/Qdrant parity |
| Official topology docs | 29 | official topology endpoint 기준 |
| Official topology ready | 29 | topology ready count |
| Official topology nodes | 35,218 | topology node count |
| Official topology edges | 99,964 | topology edge count |
| Official topology assets | 0 | official asset evidence 없음 |

## PostgreSQL Baseline

Source: `document_sources`, `parsed_documents`, `document_chunks`, `qdrant_index_entries`, `document_assets`, `document_quality_snapshots`.

| source_scope | sources | parsed_docs | chunks | indexed_chunks | assets |
| --- | ---: | ---: | ---: | ---: | ---: |
| official_docs | 29 | 29 | 27,907 | 27,907 | 0 |
| study_docs | 9 | 9 | 523 | 523 | 0 |
| user_upload | 10 | 14 | 108 | 108 | 25 |

Quality snapshots:

| source_scope | state | count |
| --- | --- | ---: |
| user_upload | gold_ready | 6 |
| user_upload | needs_repair | 6 |

Important observation:

- `user_upload`는 `sources=10`, `parsed_docs=14`, `quality_snapshots=12`다.
- 즉 user upload는 이미 `source 1개 = parsed 1개 = quality 1개`가 아니다.
- v0.1.4 dry-run에서 version/parse job/current parsed 기준을 반드시 확인해야 한다.

## Filesystem Baseline

Current top-level corpus shape:

```text
corpus/
  data/
    wiki_assets/
    wiki_relations/
    wiki_runtime_books/
  manifests/
    concepts/
    course/
    demo/
    eval/
    official/
  sources/
    official/
      imported-gold/
    kmsc/
      parsed-preview/
        course_pbs/
```

KMSC clean reference:

```text
corpus/sources/kmsc/parsed-preview/course_pbs/
  assets/
  manifests/
  chunks.jsonl
  README.md
```

Manifest evidence:

- `corpus/data/wiki_runtime_books/active_manifest.json`
  - `runtime_count`: 29
  - source repo: `https://github.com/openshift/openshift-docs`
  - source branch: `enterprise-4.20`
- `corpus/data/wiki_runtime_books/full_rebuild_manifest.json`
  - `runtime_count`: 29
  - `source_strategy`: `source-first-strict-no-auto-fallback`

## Current Schema vs v0.1.4 Gap Already Visible

Current `document_sources` lacks several v0.1.4 proposed fields:

- `source_uri`
- `source_path`
- `source_collection`
- `source_version`
- `locale`
- `canonical_status`

Current `parsed_documents` still stores:

- `markdown`

v0.1.4 wants parsing to preserve:

- `raw_text`
- `raw_payload`
- parser output/outline/warnings

Current `document_chunks` still mixes several concerns:

- `markdown`
- `embedding_text`
- `metadata`
- `starter_question_candidates`
- `followup_question_candidates`
- hierarchy/navigation fields

v0.1.4 wants to split these into:

- `corpus_chunks`
- `corpus_chunk_segments`
- `corpus_chunk_commands`
- `corpus_chunk_refs`
- `corpus_question_candidates`

Current `qdrant_index_entries` lacks proposed v0.1.4 field:

- `payload_version`

## First Follow-Up

Next task after this baseline:

1. Keep this as today's numeric truth.
2. Update corpus folder docs only if they conflict with this baseline.
3. Build the v0.1.4 dry-run sample table for:
   - official JSON/OCP doc
   - KMSC/customer package doc
   - user upload PDF
