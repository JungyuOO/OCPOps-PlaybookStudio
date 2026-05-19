from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .access_scope import filter_hits_by_session_scope
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


_DOMAIN_BOOK_HINTS: dict[str, tuple[str, ...]] = {
    "install": ("installation_overview", "installing_on_any_platform", "disconnected_environments"),
    "storage": ("storage", "support"),
    "networking": ("networking_overview", "advanced_networking", "ingress_and_load_balancing"),
    "security": ("authentication_and_authorization", "security_and_compliance"),
    "monitoring": ("monitoring", "observability_overview"),
    "troubleshooting": ("support", "validation_and_troubleshooting"),
    "operators": ("operators",),
    "logging": ("logging",),
    "registry": ("registry", "images"),
    "node_ops": ("nodes", "machine_management", "machine_configuration", "support"),
    "backup_restore": ("backup_and_restore", "etcd"),
    "etcd": ("etcd", "backup_and_restore"),
}


def _qdrant_query_filter(
    metadata_filter: dict[str, object] | None,
    *,
    domain_filter: str | None = None,
) -> dict[str, object] | None:
    if not metadata_filter:
        return None
    clean_filter = {
        key: value
        for key, value in metadata_filter.items()
        if not str(key).startswith("_")
    }
    if domain_filter:
        must = list(clean_filter.get("must") or [])
        must.append({"key": "classification.domain", "match": {"value": domain_filter}})
        clean_filter["must"] = must
    return clean_filter or None


def _combine_qdrant_filters(*filters: dict[str, object] | None) -> dict[str, object] | None:
    combined: dict[str, object] = {}
    must: list[object] = []
    for query_filter in filters:
        if not query_filter:
            continue
        for key, value in query_filter.items():
            if key == "must" and isinstance(value, list):
                must.extend(value)
            elif key not in combined:
                combined[key] = value
    if must:
        combined["must"] = must
    return combined or None


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


def _domain_filter_values(metadata_filter: dict[str, object] | None) -> tuple[str, ...]:
    if not metadata_filter:
        return ()
    values = metadata_filter.get("_domain_filter_values")
    if not isinstance(values, tuple | list):
        return ()
    return tuple(str(value).strip() for value in values if str(value or "").strip())


def _command_filter_values(metadata_filter: dict[str, object] | None) -> tuple[str, ...]:
    if not metadata_filter:
        return ()
    boosts = metadata_filter.get("_intent_signal_boosts")
    if not isinstance(boosts, dict):
        return ()
    values = boosts.get("commands")
    if not isinstance(values, tuple | list):
        return ()
    commands: list[str] = []
    seen: set[str] = set()
    for value in values:
        command = " ".join(str(value or "").split())
        key = command.casefold()
        if command and key not in seen:
            commands.append(command)
            seen.add(key)
    return tuple(commands[:3])


def _qdrant_command_filter(
    metadata_filter: dict[str, object] | None,
    *,
    command: str,
) -> dict[str, object] | None:
    clean_filter = _qdrant_query_filter(metadata_filter) or {}
    must = list(clean_filter.get("must") or [])
    must.append({"key": "search_signals.commands", "match": {"value": command}})
    clean_filter["must"] = must
    return clean_filter


def _intent_signal_boosts(metadata_filter: dict[str, object] | None) -> dict[str, tuple[str, ...]]:
    if not metadata_filter or not isinstance(metadata_filter.get("_intent_signal_boosts"), dict):
        boosts: dict[str, tuple[str, ...]] = {}
    else:
        boosts = {}
        for key, values in dict(metadata_filter["_intent_signal_boosts"]).items():
            if isinstance(values, tuple | list):
                cleaned = tuple(str(value).casefold() for value in values if str(value or "").strip())
                if cleaned:
                    boosts[str(key)] = cleaned
    domain_values = metadata_filter.get("_domain_boosts") if metadata_filter else ()
    if isinstance(domain_values, tuple | list):
        cleaned_domains = tuple(str(value).casefold() for value in domain_values if str(value or "").strip())
        if cleaned_domains:
            boosts["domains"] = cleaned_domains
    return boosts


def _boost_hits_by_intent_signals(
    hits: list[RetrievalHit],
    metadata_filter: dict[str, object] | None,
) -> list[RetrievalHit]:
    boosts = _intent_signal_boosts(metadata_filter)
    if not hits or not boosts:
        return hits

    def _contains_any(values: tuple[str, ...], candidates: tuple[str, ...]) -> bool:
        return any(candidate in value for value in values for candidate in candidates)

    scored_hits: list[tuple[float, int, RetrievalHit]] = []
    for index, hit in enumerate(hits):
        object_text = tuple(item.casefold() for item in (*hit.k8s_objects, hit.section, hit.heading_title, hit.text))
        command_text = tuple(item.casefold() for item in (*hit.cli_commands, hit.text))
        boost = 0.0
        if _contains_any(object_text, boosts.get("objects", ())):
            boost += 0.18
        if _contains_any(command_text, boosts.get("commands", ())):
            boost += 0.35
        if _contains_any(command_text, boosts.get("command_families", ())):
            boost += 0.12
        for domain in boosts.get("domains", ()):
            domain_books = _DOMAIN_BOOK_HINTS.get(domain, ())
            if hit.book_slug in domain_books:
                if domain == "node_ops":
                    if hit.book_slug == "nodes":
                        boost += 0.45
                    elif hit.book_slug == "support":
                        boost += 0.18
                    else:
                        boost += 0.06
                else:
                    boost += 0.18
        if boost:
            hit.component_scores["intent_signal_boost"] = round(boost, 4)
        scored_hits.append((float(hit.raw_score) + boost, index, hit))
    scored_hits.sort(key=lambda item: (-item[0], item[1]))
    return [hit for _score, _index, hit in scored_hits]


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
    for key in ("embedding_ms", "qdrant_ms", "hydrate_ms", "request_timeout_seconds"):
        if runtime.get(key) is not None:
            payload[key] = runtime[key]
    if isinstance(runtime.get("hydration"), dict):
        payload["hydration"] = dict(runtime["hydration"])
    if runtime.get("metadata_filter_applied"):
        payload["metadata_filter_applied"] = True
        if isinstance(runtime.get("metadata_filter"), dict):
            payload["metadata_filter"] = dict(runtime["metadata_filter"])
    if runtime.get("metadata_filter_fallback"):
        payload["metadata_filter_fallback"] = True
    if runtime.get("metadata_filter_pass"):
        payload["metadata_filter_pass"] = str(runtime["metadata_filter_pass"])
    if runtime.get("session_scope_filter_applied"):
        payload["session_scope_filter_applied"] = True
    if isinstance(runtime.get("filter_passes"), list):
        payload["filter_passes"] = list(runtime["filter_passes"])
    if isinstance(runtime.get("command_filter_passes"), list):
        payload["command_filter_passes"] = list(runtime["command_filter_passes"])
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
        "embedding_ms": round(sum(float(item.get("embedding_ms", 0.0) or 0.0) for item in subqueries), 1),
        "qdrant_ms": round(sum(float(item.get("qdrant_ms", 0.0) or 0.0) for item in subqueries), 1),
        "hydrate_ms": round(sum(float(item.get("hydrate_ms", 0.0) or 0.0) for item in subqueries), 1),
    }


def _merge_vector_filter_pass_runtimes(
    runtimes: list[dict[str, object]],
    *,
    vector_query: str,
    filter_pass: str,
) -> dict[str, object]:
    if not runtimes:
        return {
            "endpoint_used": "",
            "attempted_endpoints": [],
            "hit_count": 0,
            "top_score": None,
            "vector_query": vector_query,
            "metadata_filter_pass": filter_pass,
        }
    attempted: list[str] = []
    errors: list[object] = []
    for runtime in runtimes:
        attempted.extend(str(item) for item in (runtime.get("attempted_endpoints") or []))
        if runtime.get("errors"):
            errors.extend(list(runtime.get("errors") or []))
    top_scores = [
        float(runtime["top_score"])
        for runtime in runtimes
        if runtime.get("top_score") is not None
    ]
    return {
        "endpoint_used": str(runtimes[0].get("endpoint_used", "")),
        "attempted_endpoints": list(dict.fromkeys(attempted)),
        "errors": errors,
        "hit_count": sum(int(runtime.get("hit_count", 0) or 0) for runtime in runtimes),
        "top_score": max(top_scores) if top_scores else None,
        "embedding_ms": round(sum(float(runtime.get("embedding_ms", 0.0) or 0.0) for runtime in runtimes), 1),
        "qdrant_ms": round(sum(float(runtime.get("qdrant_ms", 0.0) or 0.0) for runtime in runtimes), 1),
        "hydrate_ms": round(sum(float(runtime.get("hydrate_ms", 0.0) or 0.0) for runtime in runtimes), 1),
        "request_timeout_seconds": runtimes[0].get("request_timeout_seconds"),
        "metadata_filter_applied": True,
        "metadata_filter_pass": filter_pass,
        "vector_query": vector_query,
        "filter_passes": [
            {
                "pass": runtime.get("metadata_filter_pass"),
                "hit_count": runtime.get("hit_count"),
                "top_score": runtime.get("top_score"),
                "embedding_ms": runtime.get("embedding_ms"),
                "qdrant_ms": runtime.get("qdrant_ms"),
                "hydrate_ms": runtime.get("hydrate_ms"),
                "metadata_filter": runtime.get("metadata_filter"),
            }
            for runtime in runtimes
        ],
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
    metadata_filter: dict[str, object] | None = None,
    correction_notes: list[object] | None = None,
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
        embedding_query_items: list[tuple[int, str]] = []
        session_qdrant_filter = _session_scope_qdrant_filter(context)
        session_scope_filter_applied = session_qdrant_filter is not None
        base_qdrant_filter = _combine_qdrant_filters(
            _qdrant_query_filter(metadata_filter),
            session_qdrant_filter,
        )
        domain_filters = (
            _domain_filter_values(metadata_filter)
            if bool(getattr(retriever.settings, "vector_domain_filter_enabled", False))
            else ()
        )
        serialized_corrections = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for item in (correction_notes or [])
            if hasattr(item, "to_dict") or isinstance(item, dict)
        ]
        for embedding_query_index, vector_query in enumerate(rewritten_queries, start=1):
            if vector_query in seen_embedding_queries:
                continue
            seen_embedding_queries.add(vector_query)
            embedding_query_items.append((embedding_query_index, vector_query))

        def _search_one_vector_query(item: tuple[int, str]) -> tuple[int, list[RetrievalHit], dict[str, object]]:
            embedding_query_index, vector_query = item
            official_hits: list[RetrievalHit] = []
            runtime = {
                "endpoint_used": "",
                "attempted_endpoints": [],
                "hit_count": 0,
                "top_score": None,
                "vector_query": vector_query,
                "normalized_query": vector_query,
                "embedding_query_index": embedding_query_index,
                "correction_notes": serialized_corrections,
            }
            if retriever.vector_retriever is not None:
                if hasattr(retriever.vector_retriever, "search_with_trace"):
                    filter_pass = "base"
                    applied_filter = base_qdrant_filter
                    try:
                        domain_hit_sets: list[list[RetrievalHit]] = []
                        domain_runtimes: list[dict[str, object]] = []
                        for domain_value in domain_filters:
                            domain_filter = _combine_qdrant_filters(
                                _qdrant_query_filter(metadata_filter, domain_filter=domain_value),
                                session_qdrant_filter,
                            )
                            domain_hits, domain_runtime = retriever.vector_retriever.search_with_trace(
                                vector_query,
                                top_k=effective_candidate_k,
                                query_filter=domain_filter,
                            )
                            domain_runtime["metadata_filter_pass"] = f"domain:{domain_value}"
                            domain_hit_sets.append(domain_hits)
                            domain_runtimes.append(domain_runtime)
                        if domain_hit_sets:
                            official_hits = _rrf_merge_hit_lists(
                                domain_hit_sets,
                                source_name="vector",
                                top_k=effective_candidate_k,
                            )
                            runtime = _merge_vector_filter_pass_runtimes(
                                domain_runtimes,
                                vector_query=vector_query,
                                filter_pass="domain",
                            )
                            filter_pass = "domain"
                            applied_filter = None
                        else:
                            official_hits, runtime = retriever.vector_retriever.search_with_trace(
                                vector_query,
                                top_k=effective_candidate_k,
                                query_filter=base_qdrant_filter,
                            )
                    except TypeError:
                        official_hits, runtime = retriever.vector_retriever.search_with_trace(
                            vector_query,
                            top_k=effective_candidate_k,
                        )
                        filter_pass = "unfiltered_legacy"
                        applied_filter = None
                    runtime["vector_query"] = vector_query
                    runtime["normalized_query"] = vector_query
                    runtime["embedding_query_index"] = embedding_query_index
                    runtime["correction_notes"] = serialized_corrections
                    runtime["metadata_filter_pass"] = filter_pass
                    if session_scope_filter_applied:
                        runtime["session_scope_filter_applied"] = True
                    if applied_filter:
                        runtime["metadata_filter"] = applied_filter
                    if not official_hits and domain_filters:
                        official_hits, fallback_runtime = retriever.vector_retriever.search_with_trace(
                            vector_query,
                            top_k=effective_candidate_k,
                            query_filter=base_qdrant_filter,
                        )
                        runtime = {
                            **fallback_runtime,
                            "metadata_filter_applied": True,
                            "metadata_filter": base_qdrant_filter or {},
                            "metadata_filter_fallback": True,
                            "metadata_filter_pass": "base_after_domain_empty",
                            "vector_query": vector_query,
                            "normalized_query": vector_query,
                            "embedding_query_index": embedding_query_index,
                            "correction_notes": serialized_corrections,
                        }
                    if not official_hits and base_qdrant_filter and not session_scope_filter_applied:
                        official_hits, fallback_runtime = retriever.vector_retriever.search_with_trace(
                            vector_query,
                            top_k=effective_candidate_k,
                        )
                        runtime = {
                            **fallback_runtime,
                            "metadata_filter_applied": True,
                            "metadata_filter": base_qdrant_filter,
                            "metadata_filter_fallback": True,
                            "metadata_filter_pass": "unfiltered_after_base_empty",
                            "vector_query": vector_query,
                            "normalized_query": vector_query,
                            "embedding_query_index": embedding_query_index,
                            "correction_notes": serialized_corrections,
                        }
                    command_filter_hits: list[list[RetrievalHit]] = []
                    command_filter_runtimes: list[dict[str, object]] = []
                    for command_value in _command_filter_values(metadata_filter):
                        command_filter = _combine_qdrant_filters(
                            _qdrant_command_filter(metadata_filter, command=command_value),
                            session_qdrant_filter,
                        )
                        command_hits, command_runtime = retriever.vector_retriever.search_with_trace(
                            vector_query,
                            top_k=effective_candidate_k,
                            query_filter=command_filter,
                        )
                        if not command_hits:
                            continue
                        for command_hit in command_hits:
                            command_hit.component_scores = dict(command_hit.component_scores)
                            command_hit.component_scores["command_filter_match"] = 1.0
                        command_filter_hits.append(command_hits)
                        command_runtime["metadata_filter_pass"] = f"command:{command_value}"
                        command_runtime["metadata_filter"] = command_filter
                        command_filter_runtimes.append(command_runtime)
                    if command_filter_hits:
                        command_named_hits = {
                            "base": official_hits,
                            **{
                                f"command:{index}": hits
                                for index, hits in enumerate(command_filter_hits, start=1)
                            },
                        }
                        official_hits = _rrf_merge_named_hit_lists(
                            command_named_hits,
                            source_name="vector",
                            top_k=effective_candidate_k,
                            weights={
                                "base": 1.0,
                                **{
                                    f"command:{index}": 1.25
                                    for index in range(1, len(command_filter_hits) + 1)
                                },
                            },
                        )
                        runtime["command_filter_passes"] = [
                            {
                                "pass": item.get("metadata_filter_pass"),
                                "hit_count": item.get("hit_count"),
                                "top_score": item.get("top_score"),
                            }
                            for item in command_filter_runtimes
                        ]
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
                        "normalized_query": vector_query,
                        "embedding_query_index": embedding_query_index,
                        "correction_notes": serialized_corrections,
                    }
            official_hits = filter_hits_by_session_scope(official_hits, context=context)
            official_hits = _boost_hits_by_intent_signals(official_hits, metadata_filter)
            private_hits, private_runtime = search_selected_customer_pack_private_vectors(
                retriever.settings,
                context=context,
                query=vector_query,
                top_k=effective_candidate_k,
            )
            private_hits = filter_hits_by_session_scope(private_hits, context=context)
            private_hits = _boost_hits_by_intent_signals(private_hits, metadata_filter)
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
            runtime_payload = _vector_subquery_runtime(query=vector_query, runtime=runtime)
            runtime_payload["source_query"] = vector_query
            runtime_payload["private_vector_status"] = str(private_runtime.get("status", ""))
            runtime_payload["private_hit_count"] = int(private_runtime.get("hit_count", 0) or 0)
            return embedding_query_index, merged_hits, runtime_payload

        max_parallel_requests = max(
            1,
            int(getattr(retriever.settings, "vector_max_parallel_requests", 4) or 1),
        )
        vector_workers = min(max_parallel_requests, max(1, len(embedding_query_items)))
        if vector_workers > 1 and len(embedding_query_items) > 1:
            with ThreadPoolExecutor(max_workers=vector_workers) as executor:
                vector_results = list(executor.map(_search_one_vector_query, embedding_query_items))
        else:
            vector_results = [_search_one_vector_query(item) for item in embedding_query_items]
        vector_results.sort(key=lambda item: item[0])
        for _embedding_query_index, merged_hits, runtime_payload in vector_results:
            vector_hit_sets.append(merged_hits)
            vector_subqueries.append(runtime_payload)
        vector_hits = _rrf_merge_hit_lists(
            vector_hit_sets,
            source_name="vector",
            top_k=effective_candidate_k,
        )
        vector_runtime = _aggregate_vector_runtime(vector_subqueries)
        vector_runtime["parallel_workers"] = vector_workers
        vector_runtime["parallel_enabled"] = vector_workers > 1 and len(embedding_query_items) > 1
        vector_runtime["domain_filter_enabled"] = bool(domain_filters)
        vector_runtime["session_scope_filter_applied"] = session_scope_filter_applied
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
                "session_scope_filter_applied": session_scope_filter_applied,
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
