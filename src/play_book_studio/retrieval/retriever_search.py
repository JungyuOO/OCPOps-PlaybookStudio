from __future__ import annotations

import time

from .intake_overlay import (
    filter_customer_pack_hits_by_selection,
    has_active_customer_pack_selection,
    load_selected_customer_pack_private_bm25_index,
    _runtime_eligible_selected_draft_ids,
    search_selected_customer_pack_private_vectors,
)
from .models import RetrievalHit
from .ranking import (
    rrf_merge_hit_lists as _rrf_merge_hit_lists,
    rrf_merge_named_hit_lists as _rrf_merge_named_hit_lists,
    summarize_hit_list as _summarize_hit_list,
)
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event


def _vector_subquery_runtime(
    *,
    query: str,
    runtime: dict[str, object],
) -> dict[str, object]:
    return {
        "query": query,
        "endpoint_used": str(runtime.get("endpoint_used", "")),
        "attempted_endpoints": [str(item) for item in (runtime.get("attempted_endpoints") or [])],
        "hit_count": int(runtime.get("hit_count", 0) or 0),
        "top_score": runtime.get("top_score"),
    }


def _aggregate_vector_runtime(subqueries: list[dict[str, object]]) -> dict[str, object]:
    endpoints_used = sorted(
        {
            str(item.get("endpoint_used", "")).strip()
            for item in subqueries
            if str(item.get("endpoint_used", "")).strip()
        }
    )
    return {
        "subquery_count": len(subqueries),
        "subqueries": subqueries,
        "endpoints_used": endpoints_used,
        "endpoint_used": endpoints_used[0] if len(endpoints_used) == 1 else "mixed" if endpoints_used else "",
        "empty_subqueries": sum(int(item.get("hit_count", 0) == 0) for item in subqueries),
    }


def search_bm25_candidates(
    retriever,
    *,
    context,
    rewritten_queries: list[str],
    effective_candidate_k: int,
    trace_callback,
    timings_ms: dict[str, float],
) -> dict[str, list[RetrievalHit]]:
    _emit_trace_event(
        trace_callback,
        step="bm25_search",
        label="키워드 검색 중",
        status="running",
    )
    bm25_started_at = time.perf_counter()
    bm25_hit_sets = [
        retriever.bm25_index.search(subquery, top_k=effective_candidate_k)
        for subquery in rewritten_queries
    ]
    core_hits = _rrf_merge_hit_lists(
        bm25_hit_sets,
        source_name="bm25",
        top_k=effective_candidate_k,
    )
    overlay_hits: list[RetrievalHit] = []
    private_index = load_selected_customer_pack_private_bm25_index(
        retriever.settings,
        context=context,
    )
    overlay_index = None
    if private_index is not None:
        overlay_index = private_index
    elif has_active_customer_pack_selection(context):
        overlay_index = retriever.customer_pack_overlay_index()
    eligible_selected = _runtime_eligible_selected_draft_ids(retriever.settings, context)
    if overlay_index is not None:
        overlay_hit_sets = [
            (
                overlay_index.search(subquery, top_k=effective_candidate_k)
                if private_index is not None
                else filter_customer_pack_hits_by_selection(
                    overlay_index.search(subquery, top_k=effective_candidate_k),
                    context=context,
                    allowed_draft_ids=eligible_selected,
                )
            )
            for subquery in rewritten_queries
        ]
        overlay_hits = _rrf_merge_hit_lists(
            overlay_hit_sets,
            source_name="overlay_bm25",
            top_k=effective_candidate_k,
        )
    bm25_hits = (
        _rrf_merge_named_hit_lists(
            {
                "bm25": core_hits,
                "overlay_bm25": overlay_hits,
            },
            source_name="bm25",
            top_k=effective_candidate_k,
            weights={"bm25": 1.0, "overlay_bm25": 1.35},
        )
        if overlay_hits
        else core_hits
    )
    timings_ms["bm25_search"] = _duration_ms(bm25_started_at)
    _emit_trace_event(
        trace_callback,
        step="bm25_search",
        label="키워드 검색 완료",
        status="done",
        detail=f"후보 {len(bm25_hits)}개",
        duration_ms=timings_ms["bm25_search"],
        meta={
            "candidate_k": effective_candidate_k,
            "count": len(bm25_hits),
            "overlay_count": len(overlay_hits),
            "private_overlay_ready": private_index is not None,
            "summary": _summarize_hit_list(bm25_hits),
        },
    )
    return {
        "core_hits": core_hits,
        "overlay_hits": overlay_hits,
        "hits": bm25_hits,
    }


def search_vector_candidates(
    retriever,
    *,
    context,
    rewritten_queries: list[str],
    effective_candidate_k: int,
    trace_callback,
    timings_ms: dict[str, float],
) -> dict[str, object]:
    _private_probe_hits, private_probe_runtime = search_selected_customer_pack_private_vectors(
        retriever.settings,
        context=context,
        query=rewritten_queries[0] if rewritten_queries else "",
        top_k=effective_candidate_k,
    )
    if retriever.vector_retriever is None and str(private_probe_runtime.get("status") or "") != "ready":
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 실패",
            status="error",
            detail="vector retriever is not configured",
        )
        raise RuntimeError("vector retriever is not configured")
    try:
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 중",
            status="running",
        )
        vector_started_at = time.perf_counter()
        vector_hit_sets: list[list[RetrievalHit]] = []
        vector_subqueries: list[dict[str, object]] = []
        for subquery in rewritten_queries:
            official_hits: list[RetrievalHit] = []
            runtime = {
                "endpoint_used": "",
                "attempted_endpoints": [],
                "hit_count": 0,
                "top_score": None,
            }
            if retriever.vector_retriever is not None:
                if hasattr(retriever.vector_retriever, "search_with_trace"):
                    official_hits, runtime = retriever.vector_retriever.search_with_trace(
                        subquery,
                        top_k=effective_candidate_k,
                    )
                else:
                    official_hits = retriever.vector_retriever.search(subquery, top_k=effective_candidate_k)
                    runtime = {
                        "endpoint_used": "",
                        "attempted_endpoints": [],
                        "hit_count": len(official_hits),
                        "top_score": float(official_hits[0].raw_score) if official_hits else None,
                    }
            private_hits, private_runtime = search_selected_customer_pack_private_vectors(
                retriever.settings,
                context=context,
                query=subquery,
                top_k=effective_candidate_k,
            )
            merged_hits = (
                _rrf_merge_named_hit_lists(
                    {
                        "vector": official_hits,
                        "private_vector": private_hits,
                    },
                    source_name="vector",
                    top_k=effective_candidate_k,
                    weights={"vector": 1.0, "private_vector": 1.15},
                )
                if official_hits and private_hits
                else (private_hits or official_hits)
            )
            vector_hit_sets.append(merged_hits)
            runtime_payload = _vector_subquery_runtime(query=subquery, runtime=runtime)
            runtime_payload["private_vector_status"] = str(private_runtime.get("status", ""))
            runtime_payload["private_hit_count"] = int(private_runtime.get("hit_count", 0) or 0)
            vector_subqueries.append(runtime_payload)
        vector_hits = _rrf_merge_hit_lists(
            vector_hit_sets,
            source_name="vector",
            top_k=effective_candidate_k,
        )
        vector_runtime = _aggregate_vector_runtime(vector_subqueries)
        timings_ms["vector_search"] = _duration_ms(vector_started_at)
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 완료",
            status="done",
            detail=f"후보 {len(vector_hits)}개",
            duration_ms=timings_ms["vector_search"],
            meta={
                "candidate_k": effective_candidate_k,
                "count": len(vector_hits),
                "endpoint_used": vector_runtime["endpoint_used"],
                "endpoints_used": vector_runtime["endpoints_used"],
                "empty_subqueries": vector_runtime["empty_subqueries"],
                "summary": _summarize_hit_list(vector_hits),
            },
        )
        return {
            "hits": vector_hits,
            "runtime": vector_runtime,
        }
    except Exception as exc:  # noqa: BLE001
        _emit_trace_event(
            trace_callback,
            step="vector_search",
            label="의미 검색 실패",
            status="error",
            detail=str(exc),
        )
        raise RuntimeError(f"vector search failed: {exc}") from exc
