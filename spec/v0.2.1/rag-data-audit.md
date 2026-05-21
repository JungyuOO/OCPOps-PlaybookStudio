# v0.2.1 RAG Data Audit Criteria

## Purpose

Define the audit criteria that v0.2.2 must implement before any official corpus rebuild or retrieval pipeline replacement.

This document is planning only. It must not change production RAG behavior, Qdrant collections, database schema, or corpus artifacts.

## Target Input

Primary audit target:

```text
corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl
```

The current corpus is useful for citation and viewer routing, but not retrieval-ready enough for operational questions.

Known current strengths:

- stable `chunk_id`
- `book_slug`, `book_title`, `chapter`, `section`, `anchor`
- `source_url`, `viewer_path`, `section_id`, `section_path`
- source/trust fields such as `source_lane`, `source_type`, `version`, `locale`, `review_status`
- extracted signal arrays such as `cli_commands`, `error_strings`, `k8s_objects`, `operator_names`, `verification_hints`

Known current gaps:

- no durable `embedding_text`
- no durable `normalized_text`
- no structured `search_signals`
- no `best_for_questions`
- no `answer_shapes`
- weak `semantic_role`
- `k8s_objects` is regex-derived and contains aliases/plurals such as `PVC`, `PV`, `Pods`, `Nodes`, and `Deployments`
- source trust and retrieval trust are mixed into the same row
- official docs and manual synthesis may be mixed in one retrieval lane

## Audit Output

v0.2.2 should produce both machine-readable and human-readable reports:

```text
reports/v022_official_corpus_audit.json
reports/v022_official_corpus_audit.md
```

Do not commit generated reports by default. If a report becomes version evidence, promote it into:

```text
spec/v0.2.2/evidence/
```

Version naming rule:

- v0.2.2 implementation artifacts should use `v022_` or `v0.2.2/` naming.
- Older `v021_` report names must not be reused for v0.2.2 output, because v0.2.1 is planning-only and should not appear to have generated audit artifacts.
- If downstream planners still mention `v021_` generated reports, treat that as a planner cleanup task before implementing the v0.2.2 audit CLI.

## Required Metrics

### Corpus Shape

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `row_count` | non-zero, stable against manifest expectation | incomplete import or wrong file |
| `duplicate_chunk_id_count` | 0 | unsafe upsert/retrieval identity |
| `missing_chunk_id_count` | 0 | invalid row |
| `missing_text_count` | 0 | cannot embed/search |
| `missing_source_url_count` | 0 for citation-eligible rows | weak citation |
| `missing_viewer_path_count` | 0 for citation-eligible rows | broken viewer links |
| `missing_section_path_count` | low and explainable | weak context shaping |

### Retrieval Readiness

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `missing_embedding_text_count` | expected high before rebuild, must be measured | embeddings depend on importer heuristics |
| `missing_normalized_text_count` | expected high before rebuild, must be measured | BM25/keyword quality weak |
| `missing_semantic_role_count` | should be measured by `chunk_type` | answer shaping cannot distinguish concept/procedure/warning |
| `missing_best_for_questions_count` | expected high before enrichment | no question-expression bridge |
| `missing_search_signals_count` | expected high before enrichment | query/chunk matching remains keyword-heavy |
| `navigation_only_ratio` | should be bounded by book/section | navigation chunks can pollute top-k |

### Source Trust

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `source_type_distribution` | explicit official/manual/user lanes | source routing unclear |
| `manual_synthesis_ratio` | measured separately | synthesized content may be overtrusted |
| `review_status_distribution` | approved rows known | unreviewed content may be cited |
| `citation_eligible_false_count` | reported | no-answer/citation policy needs special handling |
| `trust_score_distribution` | reported | trust scoring is not useful if constant |

### Text Quality

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `dirty_code_marker_count` | 0 after cleanup prototype | command metadata noise |
| `mojibake_suspect_count` | 0 or explainable | encoding/source text corruption |
| `high_latin_ratio_count` | bounded by code-heavy sections | translation or mixed language issue |
| `table_fragment_ratio` | bounded | bad chunk boundaries |
| `repeated_heading_ratio` | bounded | chunks carry title boilerplate more than answer content |
| `token_count_mismatch_count` | 0 after recompute | chunk metadata stale |

Dirty marker examples:

```text
[CODE]
[/CODE]
oc
[/CODE]
```

Mojibake suspect examples should be pattern-based, not language-biased:

```text
� 
怨
硫
� repeated replacement characters
```

The audit should report examples, not silently discard rows.

### Command Signal Quality

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `dirty_cli_command_count` | 0 after validator | command boost is unsafe |
| `unsupported_command_count` | reported | LLM or extractor hallucination risk |
| `command_without_text_evidence_count` | 0 for accepted commands | command not grounded in chunk |
| `multi_command_single_string_count` | reported | answer formatter may choose wrong command |
| `read_write_command_ratio` | reported | operational safety policy needed |

Command classification:

```text
read_only
write
delete
admin
debug
unknown
```

Write/delete/admin commands are allowed only if grounded and tagged with safety warnings.

### Kubernetes Object Signal Quality

The current `k8s_objects` field is not reliable enough to use as-is for metadata filters or scoring. It is generated by rule-based matching and may contain aliases, abbreviations, or plural display words rather than canonical Kubernetes/OpenShift kinds.

Observed examples from the current official corpus:

| Current value | Issue | Canonical target |
| --- | --- | --- |
| `PVC` | abbreviation | `PersistentVolumeClaim` with alias `PVC` |
| `PV` | abbreviation | `PersistentVolume` with alias `PV` |
| `Pods` | plural | `Pod` with alias `Pods` |
| `Nodes` | plural | `Node` with alias `Nodes` |
| `Deployments` | plural | `Deployment` with alias `Deployments` |

v0.2.2 audit must report:

| Metric | Pass Target | Failure Meaning |
| --- | ---: | --- |
| `k8s_object_unique_count` | reported | object vocabulary drift |
| `k8s_object_alias_count` | reported | aliases are mixed with canonical names |
| `k8s_object_plural_count` | 0 after normalization | plural display terms are used as object keys |
| `k8s_object_unknown_count` | 0 for accepted objects | extractor captured a non-resource word |
| `k8s_object_not_grounded_row_count` | 0 | at least one metadata object in a row is not present or supported by source text |
| `k8s_object_not_grounded_occurrence_count` | 0 | individual object labels are not present or supported by source text |
| `k8s_object_conflict_count` | 0 | query/chunk object names cannot be compared reliably |

Object validation should produce two fields:

```json
{
  "objects": ["PersistentVolumeClaim"],
  "object_aliases": ["PVC"]
}
```

Rules:

- `objects` must contain canonical singular resource names.
- `object_aliases` may contain `PVC`, `PV`, `Pods`, `Nodes`, `Deployments`, and similar source/user-facing terms.
- aliases must not be used as the primary filter key.
- an object must be grounded by source text, deterministic command evidence, or a known alias map.
- unknown object strings should become `quality_warnings`, not accepted metadata.

Initial canonicalization map:

| Alias | Canonical |
| --- | --- |
| `Pod`, `Pods` | `Pod` |
| `Deployment`, `Deployments` | `Deployment` |
| `Node`, `Nodes` | `Node` |
| `PVC`, `PersistentVolumeClaim` | `PersistentVolumeClaim` |
| `PV`, `PersistentVolume` | `PersistentVolume` |
| `Project` | `Project` |
| `Namespace` | `Namespace` |
| `Service` | `Service` |
| `Route` | `Route` |
| `Ingress` | `Ingress` |
| `ConfigMap` | `ConfigMap` |
| `Secret` | `Secret` |
| `MachineConfig` | `MachineConfig` |
| `MachineConfigPool` | `MachineConfigPool` |
| `ClusterVersion` | `ClusterVersion` |
| `StatefulSet` | `StatefulSet` |
| `DaemonSet` | `DaemonSet` |
| `ReplicaSet` | `ReplicaSet` |
| `Job` | `Job` |
| `CronJob` | `CronJob` |
| `DeploymentConfig` | `DeploymentConfig` |

## Row-Level Audit Record

Each problematic row should be emitted with enough context for repair:

```json
{
  "chunk_id": "uuid",
  "book_slug": "advanced_networking",
  "section_id": "advanced_networking:verifying-connectivity-endpoint",
  "viewer_path": "/docs/...",
  "issues": [
    {
      "code": "missing_embedding_text",
      "severity": "warning",
      "field": "embedding_text",
      "evidence": ""
    }
  ]
}
```

Severity:

```text
info
warning
error
blocker
```

Blockers prevent enrichment/import. Warnings may continue with quality marks.

## Rebuild Decision Inputs

The audit report must include a recommendation input block:

```json
{
  "recommendation_inputs": {
    "can_enrich_existing_chunks": true,
    "needs_source_recollection": false,
    "needs_manual_synthesis_split": true,
    "needs_partial_rebuild_books": ["..."],
    "blocking_reasons": []
  }
}
```

This block does not make the final decision. It feeds the v0.2.2 decision report and v0.2.3 rebuild plan.

## Rebuild Decision Matrix

v0.2.2 should decide between four paths.

```text
A. Keep existing chunks.jsonl + full enrichment
B. Recollect official source + new chunking + enrichment
C. Split official docs and manual_synthesis corpora
D. Partial rebuild for selected book_slug values
```

### A. Keep Existing chunks.jsonl + Full Enrichment

Choose this when:

- `source_url` and `viewer_path` validity is high.
- duplicate chunk IDs are zero.
- raw text is mostly usable after deterministic cleanup.
- chunk boundaries are acceptable for most books.
- dirty command ratio is repairable by validator.
- manual synthesis mixing is low or routable by existing fields.

Do not choose this when:

- mojibake/source corruption affects core books.
- navigation-only chunks dominate important query paths.
- citation anchors are unreliable.
- command metadata cannot be grounded.

### B. Recollect Official Source + New Chunking + Enrichment

Choose this when:

- source text corruption is broad.
- chunk boundaries consistently mix unrelated sections.
- headings/navigation dominate retrieval candidates.
- official/manual synthesis separation cannot be repaired from current rows.
- source manifests can recreate citation links.

Risks:

- citation compatibility may break.
- rebuild cost is higher.
- viewer path mapping must be revalidated.

### C. Split Official Docs and Manual Synthesis Corpora

Choose this when:

- `manual_synthesis` is useful but should not carry official-doc trust.
- retrieval often ranks synthesized content above official docs.
- answer policy needs distinct citation wording.

This path can combine with A or B.

### D. Partial Rebuild by book_slug

Choose this when:

- only selected books have high corruption or bad chunk boundaries.
- global rebuild cost is too high.
- existing citation paths are acceptable for most books.

The decision report must list:

```text
book_slug
reason
blocking metrics
expected rebuild benefit
citation risk
```

## Evaluation Criteria Redefinition

v0.2.x evaluation should stop treating RAG quality as one pass/fail score.

Evaluation axes:

| Axis | What It Measures | Example Failure |
| --- | --- | --- |
| retrieval hit@1/hit@5/hit@10 | whether the right chunk is retrieved | correct document appears only after top-10 |
| citation correctness | whether cited source supports answer | answer cites unrelated overview |
| source scope correctness | official/user/runtime source routing | user-scoped question answered from official only |
| answer usefulness | whether answer resolves the task | correct citation but vague answer |
| command correctness | command is grounded and appropriate | `oc delete` appears without source support |
| no-answer appropriateness | refusal when evidence is missing | hallucinated answer for absent data |
| clarification overuse | asks clarification when enough evidence exists | unnecessary follow-up prompt |
| dirty metadata exposure | leaked `[CODE]`, mojibake, broken command markers | raw markup in final answer |
| latency impact | extra enrichment/retrieval cost | unacceptable response time |

Minimum v0.2.2 report fields:

```json
{
  "case_id": "string",
  "query": "string",
  "expected_source_scope": "official",
  "retrieval_hit_at_1": true,
  "retrieval_hit_at_5": true,
  "citation_correct": true,
  "answer_useful": true,
  "command_correct": true,
  "dirty_metadata_exposed": false,
  "latency_ms": 0,
  "failure_reasons": []
}
```

Do not hide retrieval failures behind answer-quality success. Retrieval, citation, and answer shaping should be reported separately.

## Non-Goals

- no Qdrant update
- no DB migration
- no corpus rewrite
- no LLM call in v0.2.1
- no production route behavior change

## v0.2.2 Implementation Handoff

Recommended implementation order:

1. Build a read-only corpus audit CLI that emits the metrics in this document.
2. Add deterministic cleanup output for a small sample without changing the source corpus.
3. Add enriched schema validation against `enriched-corpus-schema.md`.
4. Run LLM enrichment only on a stratified sample after cleanup and validation scaffolding exist.
5. Compare raw vs enriched sample retrieval with separate retrieval, citation, command, object, and answer usefulness metrics.
6. Produce a rebuild decision report using the A/B/C/D matrix in this document.

v0.2.2 must not skip the audit CLI and jump directly to LLM enrichment. The point of v0.2.2 is to measure whether current `chunks.jsonl` can be enriched safely or whether official source recollection is required.
