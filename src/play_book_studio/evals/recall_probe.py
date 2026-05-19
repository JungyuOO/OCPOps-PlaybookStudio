"""Stage-1 hybrid recall measurement helpers.

The probe evaluates retrieval evidence before answer generation, so it can
catch misses that book-level hit metrics hide.
"""
from __future__ import annotations

from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.query_normalize import normalize_query
from play_book_studio.retrieval.ranking import rrf_merge_named_hit_lists


def hit_matches_case(hit: RetrievalHit, case: dict) -> bool:
    """Return True when a retrieval hit satisfies a case expectation."""
    expect_chunk_ids = {str(chunk_id) for chunk_id in case.get("expect_chunk_ids", []) if str(chunk_id)}
    if expect_chunk_ids and hit.chunk_id in expect_chunk_ids:
        return True

    expect_book = str(case.get("expect_book", "")).strip()
    section_needle = str(case.get("expect_section_contains", "")).strip()
    if expect_book:
        return hit.book_slug == expect_book and (not section_needle or section_needle in hit.section)

    command_needle = str(case.get("expect_command", "")).strip()
    if command_needle:
        if any(command_needle in command for command in hit.cli_commands):
            return True
        if command_needle in hit.text:
            return True

    if section_needle:
        return section_needle in hit.section

    return False


def rank_in_hits(hits: list[RetrievalHit], case: dict) -> int | None:
    """Return the 1-based rank of the first matching hit, or None."""
    for index, hit in enumerate(hits, start=1):
        if hit_matches_case(hit, case):
            return index
    return None


def probe_case(*, bm25_index, vector_retriever, case: dict, candidate_k: int = 40) -> dict:
    """Run one case through stage-1 retrieval and report per-stage ranks."""
    query = normalize_query(str(case.get("query", "")))

    bm25_hits = bm25_index.search(query, top_k=candidate_k) if bm25_index else []
    vector_hits = []
    vector_error = ""
    if vector_retriever is not None:
        try:
            vector_hits = vector_retriever.search(query, top_k=candidate_k)
        except Exception as exc:  # noqa: BLE001
            vector_error = str(exc)

    rrf_hits = rrf_merge_named_hit_lists(
        {"bm25": bm25_hits, "vector": vector_hits},
        source_name="hybrid",
        top_k=candidate_k,
    )

    bm25_rank = rank_in_hits(bm25_hits, case)
    vector_rank = rank_in_hits(vector_hits, case)
    rrf_rank = rank_in_hits(rrf_hits, case)

    return {
        "id": case.get("id"),
        "query": query,
        "bm25_rank": bm25_rank,
        "vector_rank": vector_rank,
        "rrf_rank": rrf_rank,
        "pass_at_8": rrf_rank is not None and rrf_rank <= 8,
        "pass_at_20": rrf_rank is not None and rrf_rank <= 20,
        "vector_error": vector_error,
    }


def summarize_probe_results(results: list[dict]) -> dict:
    """Summarize stage-1 probe rows into recall and rank metrics."""
    total = len(results)
    if total == 0:
        return {
            "case_count": 0,
            "recall_at_8": 0.0,
            "recall_at_20": 0.0,
            "mrr": 0.0,
            "fail_ids": [],
        }

    pass_at_8 = sum(1 for row in results if row.get("pass_at_8"))
    pass_at_20 = sum(1 for row in results if row.get("pass_at_20"))
    reciprocal_rank_sum = sum(1.0 / row["rrf_rank"] for row in results if row.get("rrf_rank"))
    return {
        "case_count": total,
        "recall_at_8": round(pass_at_8 / total, 4),
        "recall_at_20": round(pass_at_20 / total, 4),
        "mrr": round(reciprocal_rank_sum / total, 4),
        "fail_ids": [row.get("id") for row in results if not row.get("pass_at_8")],
    }
