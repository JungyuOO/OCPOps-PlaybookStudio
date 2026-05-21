# v0.2.0 ERD Table Index

## Purpose

This index lists planned table domains for v0.2.x. It is not an approved migration list.

The official documentation storage/import schema is intentionally undecided here. Corpus/RAG tables are candidates only and must be finalized after v0.2.2 data analysis.

## Corpus / RAG

- `corpus_sources`
- `corpus_artifacts`
- `corpus_chunks`
- `corpus_text_layers`
- `enrichment_runs`
- `enrichment_run_items`
- `retrieval_indexes`
- `qdrant_sync_runs`
- `retrieval_vectors` (pgvector candidate only)
- `retrieval_index_runs` (backend-neutral candidate)

## Runtime Context

- `ocp_clusters`
- `ocp_user_workspaces`
- `ocp_namespace_bindings`
- `ocp_resource_snapshots`
- `ocp_pod_snapshots`
- `ocp_events`
- `ocp_log_segments`
- `ocp_alerts`
- `ocp_metric_summaries`
- `ocp_context_packs`

## Operation Watcher

- `operation_runs`
- `operation_steps`
- `operation_watch_targets`
- `operation_events`
- `operation_notifications`
- `operation_diagnoses`

## Feedback / Eval

- `answer_feedback`
- `retrieval_failure_cases`
- `benchmark_candidates`
- `eval_runs`
- `eval_run_items`

## Rule

Tables in this document are candidates. They become real only after detailed ERD review and flat migration approval.

Corpus/RAG tables also require the v0.2.2 corpus audit decision before migration approval.

Vector tables require a separate Qdrant vs pgvector decision before migration approval.
