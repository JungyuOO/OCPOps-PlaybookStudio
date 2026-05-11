# Chunk Quality Audit

- Schema: `pbs_chunk_quality_audit_v1`
- Source: `official-gold-corpus-ko`
- Chunks: `27907`
- Token count p50/p90/p95/max: `181` / `219` / `229` / `363`
- Char count p50/p90/max: `436` / `659` / `1305`
- Command chunks: `15397` (`0.5517`)
- Decision: `audit_before_rechunking`

## Issue Counts

- `code_plus_navigation`: `358`
- `command_dense_chunk`: `7927`
- `high_latin_ratio_ko_chunk`: `8406`
- `mixed_procedure_navigation`: `150`
- `oversized_chunk`: `313`
- `raw_code_markup`: `14508`
- `undersized_chunk`: `1`

## Decision

Use retrieval/eval failures to target metadata or child chunk changes; do not reimport the corpus until raw markup, oversized, or mixed-procedure evidence crosses the threshold.
