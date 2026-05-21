# v0.1.2 Chunk Quality Baseline

- Schema: corpus_quality_audit_v1
- Targets present: 3/3
- Total rows: 28448
- Mojibake suspects: 0
- Missing text rows: 0

| Target | Scope | Rows | Short | Long | Commands | Images | Assets | Query variants | Mojibake |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| official_gold_chunks | official_docs | 27907 | 65 | 0 | 15506 | 0 | 0 | 0 | 0 |
| kmsc_course_chunks | study_docs | 523 | 0 | 8 | 130 | 174 | 775 | 0 | 0 |
| kmsc_ops_learning_chunks | study_docs | 18 | 0 | 7 | 4 | 13 | 84 | 90 | 0 |

## Notes

- Baseline is frozen before Phase A.1 changes.
- Official docs and KMSC study docs are both present.
- KMSC course and ops learning chunks contain image asset references; those are required for runtime guide citations.
