"""Stage-1 hybrid search: BM25 plus vector, then RRF."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .models import RetrievalHit
from .query_normalize import normalize_query
from .ranking import rrf_merge_named_hit_lists


@dataclass(slots=True)
class HybridSearchResult:
    hits: list[RetrievalHit]
    normalized_query: str
    bm25_count: int
    vector_count: int
    vector_failed: bool


def hydrate_final_hits(hits: list[RetrievalHit], *, database_url: str) -> list[RetrievalHit]:
    """Hydrate only the final merged candidates from canonical DB rows."""
    if not hits or not database_url.strip():
        return hits
    import psycopg

    from .chunk_hydration import hydrate_retrieval_hits

    with psycopg.connect(database_url) as connection:
        return hydrate_retrieval_hits(connection, hits)


def hybrid_search(
    query: str,
    *,
    bm25_index,
    vector_retriever,
    candidate_k: int = 40,
    top_k: int = 8,
    database_url: str = "",
) -> HybridSearchResult:
    normalized = normalize_query(query)
    vector_failed = False

    def run_bm25() -> list[RetrievalHit]:
        if bm25_index is None:
            return []
        return bm25_index.search(normalized, top_k=candidate_k)

    def run_vector() -> list[RetrievalHit]:
        nonlocal vector_failed
        if vector_retriever is None:
            return []
        try:
            return vector_retriever.search(normalized, top_k=candidate_k)
        except Exception:  # noqa: BLE001
            vector_failed = True
            return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        bm25_future = executor.submit(run_bm25)
        vector_future = executor.submit(run_vector)
        bm25_hits = bm25_future.result()
        vector_hits = vector_future.result()

    merged = rrf_merge_named_hit_lists(
        {"bm25": bm25_hits, "vector": vector_hits},
        source_name="hybrid",
        top_k=top_k,
    )
    merged = hydrate_final_hits(merged, database_url=database_url)
    return HybridSearchResult(
        hits=merged,
        normalized_query=normalized,
        bm25_count=len(bm25_hits),
        vector_count=len(vector_hits),
        vector_failed=vector_failed,
    )
