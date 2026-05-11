# Chunk Quality Audit

- Schema: `pbs_chunk_quality_audit_v1`
- Source: `user-study-course-pbs`
- Chunks: `523`
- Token count p50/p90/p95/max: `25` / `62` / `72` / `125`
- Char count p50/p90/max: `171` / `423` / `623`
- Command chunks: `125` (`0.239`)
- Decision: `keep_chunking_stable`

## Issue Counts

- `command_dense_chunk`: `13`
- `undersized_chunk`: `160`

## Decision

Use retrieval/eval failures to target metadata or child chunk changes; do not reimport the corpus until raw markup, oversized, or mixed-procedure evidence crosses the threshold.
