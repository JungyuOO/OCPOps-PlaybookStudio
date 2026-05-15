from __future__ import annotations

import copy
import json
import time
from functools import lru_cache
from pathlib import Path

from .intake_overlay import has_active_customer_pack_selection
from .models import RetrievalHit, RetrievalResult, SessionContext
from .retriever_plan import build_retrieval_plan
from .retriever_rerank import maybe_rerank_hits
from .retriever_search import search_bm25_candidates, search_vector_candidates
from .ranking import summarize_hit_list as _summarize_hit_list
from .query import (
    has_follow_up_reference,
    has_mco_concept_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_pod_lifecycle_concept_intent,
    has_route_ingress_compare_intent,
    is_generic_intro_query,
)
from .scoring import fuse_ranked_hits
from .trace import build_retrieval_trace, duration_ms as _duration_ms, emit_trace_event as _emit_trace_event

DERIVED_RUNTIME_SOURCE_TYPES = frozenset(
    {
        "topic_playbook",
        "operation_playbook",
        "troubleshooting_playbook",
        "policy_overlay_book",
        "synthesized_playbook",
    }
)


def _is_customer_pack_explicit_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(
        token in lowered
        for token in (
            "업로드 문서",
            "업로드한 문서",
            "고객 문서",
            "고객문서",
            "우리 문서",
            "our document",
            "customer pack",
            "customer-pack",
        )
    )


def _preserve_uploaded_customer_pack_candidate(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    overlay_hits: list[RetrievalHit],
    context: SessionContext | None,
) -> list[RetrievalHit]:
    if not overlay_hits:
        return hybrid_hits
    if not (
        _is_customer_pack_explicit_query(query)
        or has_active_customer_pack_selection(context)
    ):
        return hybrid_hits

    uploaded_sources: list[tuple[str, int, RetrievalHit]] = [
        ("hybrid", index, hit)
        for index, hit in enumerate(hybrid_hits)
        if str(hit.source_collection or "").strip() == "uploaded"
    ]
    existing_ids = {hit.chunk_id for hit in hybrid_hits}
    uploaded_sources.extend(
        ("overlay", index, hit)
        for index, hit in enumerate(overlay_hits)
        if hit.chunk_id not in existing_ids
    )
    if not uploaded_sources:
        return hybrid_hits

    uploaded_sources.sort(
        key=lambda item: (
            item[1] if item[0] == "hybrid" else 999 + item[1],
            -float(item[2].component_scores.get("overlay_bm25_score", item[2].raw_score)),
            item[2].book_slug,
            item[2].chunk_id,
        )
    )
    source_name, source_index, source_hit = uploaded_sources[0]
    if source_name == "hybrid":
        rescued = hybrid_hits[source_index]
    else:
        rescued = copy.deepcopy(source_hit)
        rescued.source = "hybrid_uploaded_seeded"
        rescued.component_scores = dict(rescued.component_scores)
        rescued.component_scores.setdefault("overlay_bm25_score", float(rescued.raw_score))
        rescued.component_scores.setdefault("overlay_bm25_rank", 1.0)
        rescued.fused_score = max(float(rescued.fused_score), float(rescued.raw_score))

    preserved = [rescued]
    preserved.extend(hit for hit in hybrid_hits if hit.chunk_id != rescued.chunk_id)
    return preserved[: max(len(hybrid_hits), 1)]


@lru_cache(maxsize=1)
def _active_runtime_slug_set(manifest_path: str) -> frozenset[str]:
    path = Path(manifest_path)
    if not path.exists():
        return frozenset()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return frozenset()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(
        str(item.get("slug") or "").strip()
        for item in entries
        if isinstance(item, dict) and str(item.get("slug") or "").strip()
    )


def _active_runtime_manifest_path(retriever) -> Path:
    return retriever.settings.root_dir / "data" / "wiki_runtime_books" / "active_manifest.json"


def _is_latest_only_hit(hit: RetrievalHit, *, active_slugs: frozenset[str]) -> bool:
    source_collection = str(hit.source_collection or "").strip()
    if source_collection == "uploaded":
        return True
    if str(hit.source_type or "").strip() in DERIVED_RUNTIME_SOURCE_TYPES:
        return True
    if not active_slugs:
        return True
    if str(hit.book_slug or "").strip() not in active_slugs:
        return True
    review_status = str(hit.review_status or "").strip()
    if review_status not in {"", "approved", "unreviewed"}:
        return False
    if source_collection != "core":
        return False
    return True


def _filter_latest_only_hits(retriever, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    active_slugs = _active_runtime_slug_set(str(_active_runtime_manifest_path(retriever)))
    return [hit for hit in hits if _is_latest_only_hit(hit, active_slugs=active_slugs)]


def _graph_worthy_intent(query: str) -> bool:
    return any(
        (
            has_follow_up_reference(query),
            has_mco_concept_intent(query),
            has_openshift_kubernetes_compare_intent(query),
            has_operator_concept_intent(query),
            has_pod_lifecycle_concept_intent(query),
            has_route_ingress_compare_intent(query),
            is_generic_intro_query(query),
        )
    )


def _has_graph_worthy_source(hits: list[RetrievalHit]) -> bool:
    for hit in hits[:4]:
        source_collection = str(hit.source_collection or "").strip()
        source_type = str(hit.source_type or "").strip()
        if source_collection not in {"", "core"}:
            return True
        if source_type in DERIVED_RUNTIME_SOURCE_TYPES:
            return True
    return False


def _has_cross_book_ambiguity(hits: list[RetrievalHit]) -> bool:
    if len(hits) < 2:
        return False
    top_hits = hits[:3]
    top_books = {str(hit.book_slug or "").strip() for hit in top_hits if str(hit.book_slug or "").strip()}
    if len(top_books) < 2:
        return False
    top_score = float(top_hits[0].fused_score or top_hits[0].raw_score or 0.0)
    if top_score <= 0:
        return True
    runner_up_score = max(float(hit.fused_score or hit.raw_score or 0.0) for hit in top_hits[1:])
    return runner_up_score >= (top_score * 0.92)


def _should_expand_graph(
    query: str,
    *,
    follow_up_detected: bool,
    decomposed_query_count: int,
    hits: list[RetrievalHit],
) -> tuple[bool, str]:
    if not hits:
        return False, "no_hits"
    if follow_up_detected:
        return True, "follow_up_reference"
    if decomposed_query_count > 1:
        return True, "decomposed_query"
    if _graph_worthy_intent(query):
        return True, "graph_worthy_intent"
    if _has_graph_worthy_source(hits):
        return True, "derived_or_non_core_hits"
    if _has_cross_book_ambiguity(hits):
        return True, "cross_book_ambiguity"
    return False, "not_needed"


def execute_retrieval_pipeline(
    retriever,
    query: str,
    *,
    context: SessionContext | None = None,
    top_k: int = 8,
    candidate_k: int = 20,
    use_bm25: bool = True,
    use_vector: bool = True,
    trace_callback=None,
) -> RetrievalResult:
    retrieve_started_at = time.perf_counter()
    context = context or SessionContext()
    timings_ms: dict[str, float] = {}
    plan = build_retrieval_plan(query, context=context, candidate_k=candidate_k)
    timings_ms["normalize_query"] = plan.normalize_query_ms
    _emit_trace_event(
        trace_callback,
        step="normalize_query",
        label="질문 정규화 완료",
        status="done",
        detail=plan.normalized_query[:180],
        duration_ms=timings_ms["normalize_query"],
    )
    warnings: list[str] = []
    unsupported_product = plan.unsupported_product
    timings_ms["rewrite_query"] = plan.rewrite_query_ms
    _emit_trace_event(
        trace_callback,
        step="rewrite_query",
        label="검색 질의 준비 완료",
        status="done",
        detail=plan.rewritten_query[:180],
        duration_ms=timings_ms["rewrite_query"],
        meta={
            "rewrite_applied": plan.rewrite_applied,
            "rewrite_reason": plan.rewrite_reason,
            "follow_up_detected": plan.follow_up_detected,
            "subquery_count": len(plan.rewritten_queries),
        },
    )
    if len(plan.decomposed_queries) > 1:
        _emit_trace_event(
            trace_callback,
            step="decompose_query",
            label="질문 분해 완료",
            status="done",
            detail=" | ".join(plan.decomposed_queries[:3]),
            meta={"subqueries": plan.decomposed_queries},
        )

    if unsupported_product is not None:
        warnings.append(f"query appears outside OCP corpus: {unsupported_product}")
        return RetrievalResult(
            query=query,
            normalized_query=plan.normalized_query,
            rewritten_query=plan.rewritten_query,
            top_k=top_k,
            candidate_k=candidate_k,
            context=context.to_dict(),
            hits=[],
            trace={
                "warnings": warnings,
                "bm25": [],
                "vector": [],
                "plan": {
                    "normalized_query": plan.normalized_query,
                    "rewritten_query": plan.rewritten_query,
                    "rewrite_applied": plan.rewrite_applied,
                    "rewrite_reason": plan.rewrite_reason,
                    "follow_up_detected": plan.follow_up_detected,
                    "decomposed_query_count": len(plan.decomposed_queries),
                },
                "vector_runtime": {},
                "ablation": {
                    "bm25_requested": use_bm25,
                    "vector_requested": use_vector,
                    "bm25_top_book_slugs": [],
                    "vector_top_book_slugs": [],
                    "hybrid_top_book_slugs": [],
                    "reranked_top_book_slugs": [],
                    "bm25_vector_overlap_book_slugs": [],
                    "bm25_vector_overlap_count": 0,
                    "hybrid_top_support": "none",
                    "top_support": "none",
                    "reranked_top_support": "none",
                    "rerank_top1_changed": False,
                    "rerank_top1_from": "",
                    "rerank_top1_to": "",
                    "rerank_reasons": [],
                },
                "timings_ms": {
                    **timings_ms,
                    "total": _duration_ms(retrieve_started_at),
                },
                "decomposed_queries": plan.decomposed_queries,
            },
        )

    effective_candidate_k = plan.effective_candidate_k

    bm25_hits: list[RetrievalHit] = []
    overlay_bm25_hits: list[RetrievalHit] = []
    if use_bm25:
        bm25_search = search_bm25_candidates(
            retriever,
            context=context,
            rewritten_queries=plan.rewritten_queries,
            effective_candidate_k=effective_candidate_k,
            trace_callback=trace_callback,
            timings_ms=timings_ms,
        )
        bm25_hits = bm25_search["hits"]
        overlay_bm25_hits = bm25_search["overlay_hits"]
        bm25_hits = _filter_latest_only_hits(retriever, bm25_hits)
        overlay_bm25_hits = _filter_latest_only_hits(retriever, overlay_bm25_hits)
    vector_hits: list[RetrievalHit] = []
    vector_runtime: dict[str, object] = {}
    if use_vector:
        vector_search = search_vector_candidates(
            retriever,
            context=context,
            rewritten_queries=plan.rewritten_queries,
            effective_candidate_k=effective_candidate_k,
            trace_callback=trace_callback,
            timings_ms=timings_ms,
        )
        vector_hits = vector_search["hits"]
        vector_runtime = vector_search["runtime"]
        vector_hits = _filter_latest_only_hits(retriever, vector_hits)

    _emit_trace_event(
        trace_callback,
        step="fusion",
        label="검색 결과 결합 중",
        status="running",
    )
    fusion_started_at = time.perf_counter()
    reranker_top_n = (
        max(top_k, retriever.reranker.top_n)
        if retriever.reranker is not None
        else top_k
    )
    fusion_output_k = max(top_k, min(effective_candidate_k, reranker_top_n))
    hybrid_hits = fuse_ranked_hits(
        plan.rewritten_query,
        {
            "bm25": bm25_hits,
            "vector": vector_hits,
        },
        context=context,
        top_k=fusion_output_k,
    )
    hybrid_hits = _preserve_uploaded_customer_pack_candidate(
        plan.rewritten_query,
        hybrid_hits=hybrid_hits,
        overlay_hits=overlay_bm25_hits,
        context=context,
    )
    hybrid_hits = _filter_latest_only_hits(retriever, hybrid_hits)
    timings_ms["fusion"] = _duration_ms(fusion_started_at)
    top_hit = hybrid_hits[0] if hybrid_hits else None
    top_detail = (
        f"{top_hit.book_slug} · {top_hit.section}"
        if top_hit is not None
        else "상위 근거 없음"
    )
    hybrid_top_support = "none"
    if top_hit is not None:
        has_bm25_support = any(
            key in top_hit.component_scores
            for key in ("bm25_score", "overlay_bm25_score")
        )
        has_vector_support = "vector_score" in top_hit.component_scores
        if has_bm25_support and has_vector_support:
            hybrid_top_support = "both"
        elif has_bm25_support:
            hybrid_top_support = "bm25"
        elif has_vector_support:
            hybrid_top_support = "vector"
        else:
            hybrid_top_support = "unknown"
    _emit_trace_event(
        trace_callback,
        step="fusion",
        label="검색 결과 결합 완료",
        status="done",
        detail=top_detail,
        duration_ms=timings_ms["fusion"],
        meta={
            "summary": _summarize_hit_list(hybrid_hits, score_key="fused_score"),
            "overlap_count": len(
                {
                    hit.book_slug
                    for hit in bm25_hits[:5]
                }
                & {
                    hit.book_slug
                    for hit in vector_hits[:5]
                }
            ),
            "top_support": hybrid_top_support,
        },
    )
    should_expand_graph, graph_reason = _should_expand_graph(
        plan.rewritten_query,
        follow_up_detected=plan.follow_up_detected,
        decomposed_query_count=len(plan.decomposed_queries),
        hits=hybrid_hits,
    )
    if should_expand_graph:
        graph_enriched_hits, graph_trace = retriever.graph_runtime.enrich_hits(
            query=plan.rewritten_query,
            hits=hybrid_hits,
            context=context,
            trace_callback=trace_callback,
        )
    else:
        graph_enriched_hits = list(hybrid_hits)
        graph_trace = retriever.graph_runtime.skipped_payload(reason=graph_reason)
        _emit_trace_event(
            trace_callback,
            step="graph_expand",
            label="관계/근거 그래프 생략",
            status="done",
            detail=graph_reason,
            meta={
                "adapter_mode": graph_trace.get("adapter_mode", "skipped"),
                "fallback_reason": graph_trace.get("fallback_reason", ""),
                "hit_count": 0,
            },
        )
    graph_enriched_hits = _preserve_uploaded_customer_pack_candidate(
        plan.rewritten_query,
        hybrid_hits=graph_enriched_hits,
        overlay_hits=overlay_bm25_hits,
        context=context,
    )
    graph_enriched_hits = _filter_latest_only_hits(retriever, graph_enriched_hits)
    hits, reranker_trace = maybe_rerank_hits(
        retriever,
        query=plan.rewritten_query,
        hybrid_hits=graph_enriched_hits,
        context=context,
        top_k=top_k,
        trace_callback=trace_callback,
        timings_ms=timings_ms,
    )
    hits = _filter_latest_only_hits(retriever, hits)
    trace = build_retrieval_trace(
        warnings=warnings,
        bm25_hits=bm25_hits,
        overlay_bm25_hits=overlay_bm25_hits,
        vector_hits=vector_hits,
        hybrid_hits=hybrid_hits,
        graph_trace=graph_trace,
        reranked_hits=hits,
        reranker_trace=reranker_trace,
        decomposed_queries=plan.decomposed_queries,
        effective_candidate_k=effective_candidate_k,
        fusion_output_k=fusion_output_k,
        timings_ms={
            **timings_ms,
            "total": _duration_ms(retrieve_started_at),
        },
        candidate_k=candidate_k,
        top_k=top_k,
        normalized_query=plan.normalized_query,
        rewritten_query=plan.rewritten_query,
        rewrite_applied=plan.rewrite_applied,
        rewrite_reason=plan.rewrite_reason,
        follow_up_detected=plan.follow_up_detected,
        use_bm25=use_bm25,
        use_vector=use_vector,
        vector_runtime=vector_runtime,
    )
    return RetrievalResult(
        query=query,
        normalized_query=plan.normalized_query,
        rewritten_query=plan.rewritten_query,
        top_k=top_k,
        candidate_k=candidate_k,
        context=context.to_dict(),
        hits=hits,
        trace=trace,
    )
