# Go / No-Go

- Passed: `13` / `13`
- Decision: `go`

| gate | status | detail |
|---|---|---|
| `official_docs_present` | `pass` | official_docs chunks=27907 |
| `study_docs_present` | `pass` | study_docs chunks=523 |
| `clean_embedding_text` | `pass` | DB embedding_text raw [CODE]/[TABLE] count must be 0 |
| `kmsc_parent_size` | `pass` | study_docs parent token max=None |
| `pgvector_embedding_count` | `pass` | indexable=27184 embedding_entries=27184 missing=0 |
| `pgvector_stale_embeddings` | `pass` | stale=0 |
| `pgvector_embedding_model` | `pass` | expected model=dragonkue/bge-m3-ko mismatches=0 |
| `pgvector_vector_size` | `pass` | expected=1024 dimensions={'1024': 27184} |
| `answer_viewer_check` | `pass` | status=pass checks=8 |
| `retrieval_retrieval_sanity_v004_readable_cases.jsonl_hit5` | `pass` | hit@1=0.5 hit@3=1.0 hit@5=1.0 |
| `retrieval_retrieval_benchmark_cases.jsonl_hit5` | `pass` | hit@1=0.7667 hit@3=0.9 hit@5=1.0 |
| `retrieval_retrieval_foundation_p0_cases.jsonl_hit5` | `pass` | hit@1=0.65 hit@3=0.9 hit@5=1.0 |
| `retrieval_retrieval_foundation_p0_cases.jsonl_scope_hit1` | `pass` | scope_cases=30 hit@1=1.0 hit@3=1.0 hit@5=1.0 |
