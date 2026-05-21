# Vector Backend Decision Draft

## Context

The project currently stores source/chunk metadata in PostgreSQL and vector search state in Qdrant. As v0.2.x moves toward a database-centered OpenShift operations assistant, this split should be revisited.

Future features will all rely on PostgreSQL data relationships:

- enriched official/user corpus chunks
- LLM enrichment metadata
- runtime OCP snapshots
- operation watcher runs and notifications
- feedback/eval history
- chat/session history

Because PostgreSQL is already the system of record, pgvector may be a better default vector backend than Qdrant for the expected near-term scale.

## Decision Status

Not decided in v0.2.0.

v0.2.0 records the decision frame only. The final decision should be made after enriched corpus size, query load, and v0.2.4 retrieval benchmark results are available.

## Candidate Direction

Preferred direction to evaluate:

```text
Qdrant hard dependency
  -> vector backend abstraction
  -> pgvector as default candidate
  -> Qdrant as optional backend for larger deployments
```

## pgvector Benefits

- Single database to operate and back up.
- Vector rows can join directly with chunk/source/enrichment metadata.
- Runtime context, feedback, and retrieval traces can stay transactionally close.
- OpenShift deployment becomes simpler by removing Qdrant service/PVC from the default path.
- Schema migrations and retention policies can cover vector index state.
- Better fit for customer-specific workspace/tenant filtering.

## Qdrant Benefits

- Dedicated vector database.
- Better fit for very large vector collections.
- Independent scaling and collection management.
- Mature ANN/vector payload filtering model.
- Useful if official/user corpus grows beyond PostgreSQL comfort.

## Required Abstraction

Retrieval code should not assume one vector backend.

Candidate interface:

```text
VectorBackend
  - upsert_chunks(chunks)
  - search(query_vector, filters, limit)
  - delete_by_source(source_id)
  - refresh_payloads(chunks)
  - health()
```

Backend implementations:

```text
QdrantVectorBackend
PgVectorBackend
```

## pgvector Schema Candidate

Do not create this migration in v0.2.0. This is a candidate only.

```text
retrieval_vectors
  id uuid primary key
  chunk_id uuid not null
  source_scope text not null
  embedding_model text not null
  embedding_dimensions integer not null
  embedding vector(...)
  payload jsonb not null
  created_at timestamptz
  updated_at timestamptz

retrieval_index_runs
  id uuid primary key
  backend text not null
  collection_name text
  embedding_model text
  status text
  started_at timestamptz
  completed_at timestamptz
```

## Benchmark Criteria

Compare Qdrant and pgvector on:

- top-1/top-5/top-10 retrieval hit
- source scope correctness
- metadata filtering correctness
- latency p50/p95
- index build time
- deploy complexity
- backup/restore complexity
- operational failure modes

## Version Placement

- v0.2.0: decision frame and schema candidate
- v0.2.2: corpus size and enrichment sample estimates
- v0.2.4: Qdrant vs pgvector A/B benchmark
- later version: default backend decision and migration if benchmark supports it

## Non-goals

- Do not remove Qdrant in v0.2.0.
- Do not create pgvector tables in v0.2.0.
- Do not rewrite retrieval code before enriched corpus is available.
- Do not assume pgvector wins without benchmark evidence.
