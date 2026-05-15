# retrieval 단계의 trace 이벤트와 결과 요약 조립을 담당한다.
# 검색 단계별 진행 로그와 최종 trace payload를 한 군데에서 관리한다.
from __future__ import annotations

import time
from typing import Any

from .models import RetrievalHit
from .ranking import summarize_hit_list


def duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


def emit_trace_event(
    trace_callback,
    *,
    step: str,
    label: str,
    status: str,
    detail: str = "",
    duration_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    if trace_callback is None:
        return
    event = {
        "type": "trace",
        "step": step,
        "label": label,
        "status": status,
    }
    if detail:
        event["detail"] = detail
    if duration_ms is not None:
        event["duration_ms"] = duration_ms
    if meta:
        event["meta"] = meta
    trace_callback(event)


def _top_book_slugs(hits: list[RetrievalHit], *, limit: int) -> list[str]:
    top_book_slugs: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        book_slug = str(hit.book_slug or "").strip()
        if not book_slug or book_slug in seen:
            continue
        seen.add(book_slug)
        top_book_slugs.append(book_slug)
        if len(top_book_slugs) >= limit:
            break
    return top_book_slugs


def _hit_support(hit: RetrievalHit | None) -> str:
    if hit is None:
        return "none"
    has_bm25 = any(key in hit.component_scores for key in ("bm25_score", "overlay_bm25_score"))
    has_vector = "vector_score" in hit.component_scores
    if has_bm25 and has_vector:
        return "both"
    if has_bm25:
        return "bm25"
    if has_vector:
        return "vector"
    return "unknown"


def _overlap_book_slugs(left: list[RetrievalHit], right: list[RetrievalHit], *, limit: int) -> list[str]:
    left_books = set(_top_book_slugs(left, limit=limit))
    right_books = set(_top_book_slugs(right, limit=limit))
    return sorted(left_books & right_books)


def build_retrieval_trace(
    *,
    warnings: list[str],
    bm25_hits: list[RetrievalHit],
    overlay_bm25_hits: list[RetrievalHit] | None = None,
    vector_hits: list[RetrievalHit],
    hybrid_hits: list[RetrievalHit],
    graph_trace: dict[str, Any],
    reranked_hits: list[RetrievalHit],
    reranker_trace: dict[str, Any],
    decomposed_queries: list[str],
    effective_candidate_k: int,
    fusion_output_k: int,
    timings_ms: dict[str, float],
    candidate_k: int,
    top_k: int,
    normalized_query: str = "",
    rewritten_query: str = "",
    rewrite_applied: bool = False,
    rewrite_reason: str = "",
    follow_up_detected: bool = False,
    use_bm25: bool = True,
    use_vector: bool = True,
    vector_runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bm25_summary = summarize_hit_list(bm25_hits)
    overlay_bm25_summary = summarize_hit_list(overlay_bm25_hits or [])
    vector_summary = summarize_hit_list(vector_hits)
    hybrid_summary = summarize_hit_list(hybrid_hits, score_key="fused_score")
    reranked_summary = summarize_hit_list(reranked_hits, score_key="fused_score")
    bm25_vector_overlap_books = _overlap_book_slugs(bm25_hits, vector_hits, limit=5)
    hybrid_top_hit = hybrid_hits[0] if hybrid_hits else None
    reranked_top_hit = reranked_hits[0] if reranked_hits else None
    rerank_reasons = [str(item) for item in (reranker_trace.get("rebalance_reasons") or []) if str(item).strip()]
    trace = {
        "warnings": warnings,
        "bm25": [hit.to_dict() for hit in bm25_hits[: min(candidate_k, 10)]],
        "vector": [hit.to_dict() for hit in vector_hits[: min(candidate_k, 10)]],
        "hybrid": [hit.to_dict() for hit in hybrid_hits[: min(fusion_output_k, 5)]],
        "graph": graph_trace,
        "reranked": [hit.to_dict() for hit in reranked_hits[: min(top_k, 5)]],
        "reranker": reranker_trace,
        "metrics": {
            "bm25": bm25_summary,
            "vector": vector_summary,
            "hybrid": hybrid_summary,
            "reranked": reranked_summary,
        },
        "plan": {
            "normalized_query": normalized_query,
            "rewritten_query": rewritten_query,
            "rewrite_applied": rewrite_applied,
            "rewrite_reason": rewrite_reason,
            "follow_up_detected": follow_up_detected,
            "decomposed_query_count": len(decomposed_queries),
        },
        "vector_runtime": vector_runtime or {},
        "ablation": {
            "bm25_requested": use_bm25,
            "vector_requested": use_vector,
            "bm25_top_book_slugs": _top_book_slugs(bm25_hits, limit=5),
            "vector_top_book_slugs": _top_book_slugs(vector_hits, limit=5),
            "hybrid_top_book_slugs": _top_book_slugs(hybrid_hits, limit=5),
            "reranked_top_book_slugs": _top_book_slugs(reranked_hits, limit=5),
            "bm25_vector_overlap_book_slugs": bm25_vector_overlap_books,
            "bm25_vector_overlap_count": len(bm25_vector_overlap_books),
            "hybrid_top_support": _hit_support(hybrid_top_hit),
            "top_support": _hit_support(hybrid_top_hit),
            "reranked_top_support": _hit_support(reranked_top_hit),
            "rerank_top1_changed": bool(reranker_trace.get("top1_changed", False)),
            "rerank_top1_from": str(reranker_trace.get("top1_before", "")),
            "rerank_top1_to": str(reranker_trace.get("top1_after", "")),
            "rerank_reasons": rerank_reasons,
        },
        "decomposed_queries": decomposed_queries,
        "effective_candidate_k": effective_candidate_k,
        "fusion_output_k": fusion_output_k,
        "timings_ms": timings_ms,
    }
    if overlay_bm25_hits:
        trace["overlay_bm25"] = [hit.to_dict() for hit in overlay_bm25_hits[: min(candidate_k, 10)]]
        trace["metrics"]["overlay_bm25"] = overlay_bm25_summary
    return trace
