from __future__ import annotations

import time

from .access_scope import filter_hits_by_session_scope
from .intake_overlay import (
    filter_customer_pack_hits_by_selection,
    has_active_customer_pack_selection,
    load_selected_customer_pack_private_bm25_index,
    _runtime_eligible_selected_draft_ids,
    search_selected_customer_pack_private_vectors,
)
from .models import RetrievalHit
from .query_signal_pipeline import build_query_signal_plan
from .ranking import (
    rrf_merge_hit_lists as _rrf_merge_hit_lists,
    rrf_merge_named_hit_lists as _rrf_merge_named_hit_lists,
    summarize_hit_list as _summarize_hit_list,
)
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event


def _session_scope_row_filter(context):
    active_document_id = str(getattr(context, "active_document_id", "") or "").strip()
    active_repository_id = str(getattr(context, "active_repository_id", "") or "").strip()
    if not active_document_id and not active_repository_id:
        return None

    def predicate(row: dict[str, object]) -> bool:
        if active_document_id:
            document_source_id = str(row.get("document_source_id") or row.get("source_id") or "").strip()
            if document_source_id != active_document_id:
                return False
        if active_repository_id:
            repository_id = str(row.get("repository_id") or "").strip()
            if repository_id != active_repository_id:
                return False
        return True

    return predicate


def _session_scope_qdrant_filter(context) -> dict[str, object] | None:
    active_document_id = str(getattr(context, "active_document_id", "") or "").strip()
    active_repository_id = str(getattr(context, "active_repository_id", "") or "").strip()
    must: list[dict[str, object]] = []
    if active_document_id:
        must.append({"key": "document_source_id", "match": {"value": active_document_id}})
    if active_repository_id:
        must.append({"key": "repository_id", "match": {"value": active_repository_id}})
    if not must:
        return None
    return {"must": must}


def _vector_subquery_runtime(
    *,
    query: str,
    runtime: dict[str, object],
) -> dict[str, object]:
    payload = {
        "query": query,
        "endpoint_used": str(runtime.get("endpoint_used", "")),
        "attempted_endpoints": [str(item) for item in (runtime.get("attempted_endpoints") or [])],
        "hit_count": int(runtime.get("hit_count", 0) or 0),
        "top_score": runtime.get("top_score"),
    }
    if isinstance(runtime.get("hydration"), dict):
        payload["hydration"] = dict(runtime["hydration"])
    if runtime.get("metadata_filter_applied"):
        payload["metadata_filter_applied"] = True
        if isinstance(runtime.get("metadata_filter"), dict):
            payload["metadata_filter"] = dict(runtime["metadata_filter"])
    if runtime.get("metadata_filter_fallback"):
        payload["metadata_filter_fallback"] = True
    if runtime.get("vector_query") and str(runtime.get("vector_query")) != query:
        payload["vector_query"] = str(runtime["vector_query"])
    if runtime.get("normalized_query"):
        payload["normalized_query"] = str(runtime["normalized_query"])
    if runtime.get("embedding_query_index") is not None:
        payload["embedding_query_index"] = int(runtime.get("embedding_query_index") or 0)
    if runtime.get("correction_notes"):
        payload["correction_notes"] = list(runtime.get("correction_notes") or [])
    return payload


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
    scope_row_filter = _session_scope_row_filter(context)
    bm25_hit_sets = [
        retriever.bm25_index.search(subquery, top_k=effective_candidate_k, row_filter=scope_row_filter)
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
    bm25_hits = filter_hits_by_session_scope(bm25_hits, context=context)
    overlay_hits = filter_hits_by_session_scope(overlay_hits, context=context)
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
            "session_scope_filter_applied": scope_row_filter is not None,
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
        seen_embedding_queries: set[str] = set()
        query_signal_llm_client = getattr(retriever, "query_signal_llm_client", None)
        scope_qdrant_filter = _session_scope_qdrant_filter(context)
        for subquery in rewritten_queries:
            query_plan = build_query_signal_plan(subquery, llm_client=query_signal_llm_client)
            metadata_filter = scope_qdrant_filter or query_plan.metadata_filter or None
            for embedding_query_index, vector_query in enumerate(query_plan.embedding_queries, start=1):
                if vector_query in seen_embedding_queries:
                    continue
                seen_embedding_queries.add(vector_query)
                official_hits: list[RetrievalHit] = []
                runtime = {
                    "endpoint_used": "",
                    "attempted_endpoints": [],
                    "hit_count": 0,
                    "top_score": None,
                    "vector_query": vector_query,
                    "normalized_query": query_plan.normalized_query,
                    "embedding_query_index": embedding_query_index,
                    "correction_notes": [item.to_dict() for item in query_plan.correction_notes],
                }
                if retriever.vector_retriever is not None:
                    if hasattr(retriever.vector_retriever, "search_with_trace"):
                        try:
                            official_hits, runtime = retriever.vector_retriever.search_with_trace(
                                vector_query,
                                top_k=effective_candidate_k,
                                query_filter=metadata_filter,
                            )
                        except TypeError:
                            official_hits, runtime = retriever.vector_retriever.search_with_trace(
                                vector_query,
                                top_k=effective_candidate_k,
                            )
                        runtime["vector_query"] = vector_query
                        runtime["normalized_query"] = query_plan.normalized_query
                        runtime["embedding_query_index"] = embedding_query_index
                        runtime["correction_notes"] = [item.to_dict() for item in query_plan.correction_notes]
                        if not official_hits and metadata_filter and scope_qdrant_filter is None:
                            official_hits, fallback_runtime = retriever.vector_retriever.search_with_trace(
                                vector_query,
                                top_k=effective_candidate_k,
                            )
                            runtime = {
                                **fallback_runtime,
                                "metadata_filter_applied": True,
                                "metadata_filter": metadata_filter,
                                "metadata_filter_fallback": True,
                                "vector_query": vector_query,
                                "normalized_query": query_plan.normalized_query,
                                "embedding_query_index": embedding_query_index,
                                "correction_notes": [item.to_dict() for item in query_plan.correction_notes],
                            }
                    else:
                        official_hits = retriever.vector_retriever.search(
                            vector_query,
                            top_k=effective_candidate_k,
                        )
                        runtime = {
                            "endpoint_used": "",
                            "attempted_endpoints": [],
                            "hit_count": len(official_hits),
                            "top_score": float(official_hits[0].raw_score) if official_hits else None,
                            "vector_query": vector_query,
                            "normalized_query": query_plan.normalized_query,
                            "embedding_query_index": embedding_query_index,
                            "correction_notes": [item.to_dict() for item in query_plan.correction_notes],
                        }
                official_hits = filter_hits_by_session_scope(official_hits, context=context)
                private_hits, private_runtime = search_selected_customer_pack_private_vectors(
                    retriever.settings,
                    context=context,
                    query=vector_query,
                    top_k=effective_candidate_k,
                )
                private_hits = filter_hits_by_session_scope(private_hits, context=context)
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
                runtime_payload = _vector_subquery_runtime(query=vector_query, runtime=runtime)
                runtime_payload["source_query"] = subquery
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
