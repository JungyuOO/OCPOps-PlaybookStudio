# Embedding / pgvector Audit

## pgvector Index

```json
{
  "backend": "pgvector",
  "model": "dragonkue/bge-m3-ko",
  "expected_vector_size": 1024,
  "indexable_count": 27184,
  "embedding_entry_count": 27184,
  "missing_count": 0,
  "stale_count": 0,
  "model_mismatch_count": 0,
  "dimension_bad_count": 0,
  "dimension_counts": {
    "1024": 27184
  },
  "source_counts": {
    "official_docs": {
      "indexable": 25881,
      "entries": 25881,
      "missing": 0,
      "stale": 0
    },
    "study_docs": {
      "indexable": 523,
      "entries": 523,
      "missing": 0,
      "stale": 0
    },
    "user_upload": {
      "indexable": 780,
      "entries": 780,
      "missing": 0,
      "stale": 0
    }
  },
  "missing_samples": [],
  "stale_samples": [],
  "model_mismatch_samples": [],
  "bad_dimension_samples": []
}
```

## DB Index Entries

```json
[
  {
    "source_scope": "official_docs",
    "indexable_chunks": 25881,
    "embedding_entries": 25881,
    "missing_indexable": 0,
    "vector_model_count": 1,
    "vector_model_min": "dragonkue/bge-m3-ko",
    "vector_model_max": "dragonkue/bge-m3-ko",
    "vector_dim_min": 1024,
    "vector_dim_max": 1024
  },
  {
    "source_scope": "study_docs",
    "indexable_chunks": 523,
    "embedding_entries": 523,
    "missing_indexable": 0,
    "vector_model_count": 1,
    "vector_model_min": "dragonkue/bge-m3-ko",
    "vector_model_max": "dragonkue/bge-m3-ko",
    "vector_dim_min": 1024,
    "vector_dim_max": 1024
  },
  {
    "source_scope": "user_upload",
    "indexable_chunks": 780,
    "embedding_entries": 780,
    "missing_indexable": 0,
    "vector_model_count": 1,
    "vector_model_min": "dragonkue/bge-m3-ko",
    "vector_model_max": "dragonkue/bge-m3-ko",
    "vector_dim_min": 1024,
    "vector_dim_max": 1024
  }
]
```
