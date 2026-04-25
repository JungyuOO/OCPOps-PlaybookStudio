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
    has_doc_locator_intent,
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
CUSTOMER_PACK_BROAD_CONTEXT_TOKENS = (
    "자료",
    "문서",
    "운영",
    "설계",
    "ppt",
    "pptx",
    "ci/cd",
    "cicd",
    "운영북",
)


def _is_customer_pack_explicit_query(query: str) -> bool:
    lowered = (query or "").lower()
    exact_match = any(
        token in lowered
        for token in (
            "업로드 문서",
            "업로드한 문서",
            "업로드 자료",
            "업로드자료",
            "유저 업로드",
            "사용자 업로드",
            "고객 문서",
            "고객문서",
            "고객 자료",
            "고객자료",
            "고객 ppt",
            "고객ppt",
            "고객 운영북",
            "운영북",
            "ppt 자료",
            "ppt자료",
            "우리 문서",
            "our document",
            "customer pack",
            "customer-pack",
        )
    )
    broad_match = "고객" in lowered and any(
        token in lowered for token in CUSTOMER_PACK_BROAD_CONTEXT_TOKENS
    )
    return exact_match or broad_match


def _is_customer_pack_relation_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(
        token in lowered
        for token in (
            "흐름",
            "플로우",
            "flow",
            "순서",
            "어떻게 넘어",
            "어디로 넘어",
            "연결",
            "연계",
            "연동",
            "의존",
            "dependency",
            "차이",
            "difference",
            "비교",
            "승인",
            "gate",
            "owner",
            "ownership",
            "담당",
            "주체",
            "책임",
        )
    )


def _is_customer_pack_title_locator_query(query: str) -> bool:
    lowered = (query or "").lower()
    if not has_doc_locator_intent(lowered):
        return False
    return any(
        token in lowered
        for token in (
            "설계서",
            "제안서",
            "발표",
            "ppt",
            "pptx",
            "slide",
            "슬라이드",
        )
    ) or len([token for token in lowered.split() if token.strip()]) >= 3


def _mentions_official_runtime_sources(query: str) -> bool:
    lowered = (query or "").lower()
    return any(
        token in lowered
        for token in (
            "공식문서",
            "공식 문서",
            "공식매뉴얼",
            "공식 매뉴얼",
            "ocp 공식",
            "openshift 공식",
            "official doc",
            "official docs",
            "official manual",
            "official manuals",
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
        or _is_customer_pack_title_locator_query(query)
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

    relation_query = _is_customer_pack_relation_query(query)
    title_locator_query = _is_customer_pack_title_locator_query(query)
    uploaded_sources.sort(
        key=lambda item: (
            0
            if (
                relation_query
                and (
                    str(item[2].chunk_type or "").strip() == "relation"
                    or "flow" in tuple(str(entry).strip() for entry in item[2].graph_relations)
                    or "gate" in tuple(str(entry).strip() for entry in item[2].graph_relations)
                )
            )
            else 1,
            -float(item[2].component_scores.get("overlay_bm25_score", item[2].raw_score)),
            item[1] if (relation_query or not title_locator_query) and item[0] == "hybrid" else 999 + item[1],
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
    has_distinct_hybrid_support = any(hit.chunk_id != rescued.chunk_id for hit in hybrid_hits)
    return preserved[: max(len(hybrid_hits), 2 if has_distinct_hybrid_support else 1)]


def _preserve_customer_pack_core_blend(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    core_hits: list[RetrievalHit],
    context: SessionContext | None,
) -> list[RetrievalHit]:
    context = context or SessionContext()
    explicit_blend_request = (
        _is_customer_pack_explicit_query(query)
        or has_active_customer_pack_selection(context)
    ) and _mentions_official_runtime_sources(query)
    if context.restrict_uploaded_sources and not explicit_blend_request:
        return hybrid_hits
    if _is_customer_pack_title_locator_query(query) and not _mentions_official_runtime_sources(query):
        return hybrid_hits
    if not (_is_customer_pack_explicit_query(query) or has_active_customer_pack_selection(context)):
        return hybrid_hits
    if not (_mentions_official_runtime_sources(query) or has_active_customer_pack_selection(context)):
        return hybrid_hits

    uploaded_candidate = next(
        (hit for hit in hybrid_hits if str(hit.source_collection or "").strip() == "uploaded"),
        None,
    )
    core_candidate = next(
        (hit for hit in hybrid_hits if str(hit.source_collection or "").strip() == "core"),
        None,
    )
    if core_candidate is None:
        core_candidate = next(
            (hit for hit in core_hits if str(hit.source_collection or "").strip() == "core"),
            None,
        )
    if uploaded_candidate is None or core_candidate is None:
        return hybrid_hits

    seeded: list[RetrievalHit] = []
    if hybrid_hits:
        seeded.append(hybrid_hits[0])
    if all(hit.chunk_id != uploaded_candidate.chunk_id for hit in seeded):
        seeded.append(uploaded_candidate)
    if all(hit.chunk_id != core_candidate.chunk_id for hit in seeded):
        seeded.append(copy.deepcopy(core_candidate))
    seeded.extend(
        hit
        for hit in hybrid_hits
        if all(existing.chunk_id != hit.chunk_id for existing in seeded)
    )
    target_size = max(len(hybrid_hits), 2)
    return seeded[:target_size]


def _preserve_official_title_locator_candidate(
    *,
    hybrid_hits: list[RetrievalHit],
    official_title_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if not official_title_hits:
        return hybrid_hits
    source_hit = official_title_hits[0]
    if not str(source_hit.book_slug or "").strip():
        return hybrid_hits

    target_chunk_id = str(source_hit.chunk_id or "").strip()
    target_book_slug = str(source_hit.book_slug or "").strip()
    if hybrid_hits and hybrid_hits[0].book_slug == target_book_slug:
        return hybrid_hits

    reordered = list(hybrid_hits)
    existing_index = next(
        (
            index
            for index, hit in enumerate(reordered)
            if str(hit.chunk_id or "").strip() == target_chunk_id
        ),
        None,
    )
    if existing_index is not None:
        official_hit = reordered.pop(existing_index)
    else:
        official_hit = copy.deepcopy(source_hit)
        official_hit.source = "hybrid_official_title_seeded"

    official_hit.component_scores = dict(official_hit.component_scores)
    official_hit.component_scores.setdefault("official_title_seed", 1.0)
    official_hit.component_scores.setdefault(
        "pre_official_title_seed_score",
        float(official_hit.fused_score or official_hit.raw_score or 0.0),
    )
    official_hit.fused_score = max(
        float(official_hit.fused_score or 0.0),
        float(source_hit.raw_score or 0.0),
    )
    official_hit.raw_score = max(float(official_hit.raw_score or 0.0), official_hit.fused_score)
    reordered.insert(0, official_hit)
    return reordered[: max(len(hybrid_hits), 1)]


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
    if review_status not in {"", "approved", "unreviewed", "needs_review"}:
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
    relation_query = _is_customer_pack_relation_query(plan.rewritten_query or plan.normalized_query or query)
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
    if (relation_query or _is_customer_pack_title_locator_query(plan.rewritten_query or plan.normalized_query or query)) and (
        _is_customer_pack_explicit_query(query)
        or has_active_customer_pack_selection(context)
        or _is_customer_pack_title_locator_query(query)
    ):
        effective_candidate_k = max(effective_candidate_k, candidate_k, 30)

    bm25_hits: list[RetrievalHit] = []
    overlay_bm25_hits: list[RetrievalHit] = []
    official_title_locator_hits: list[RetrievalHit] = []
    core_reference_hits: list[RetrievalHit] = []
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
        official_title_locator_hits = bm25_search.get("official_title_locator_hits", [])
        core_reference_hits = bm25_search["core_hits"]
        bm25_hits = _filter_latest_only_hits(retriever, bm25_hits)
        overlay_bm25_hits = _filter_latest_only_hits(retriever, overlay_bm25_hits)
        official_title_locator_hits = _filter_latest_only_hits(
            retriever,
            official_title_locator_hits,
        )
        core_reference_hits = _filter_latest_only_hits(retriever, core_reference_hits)
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
        core_reference_hits.extend(
            hit for hit in vector_hits if str(hit.source_collection or "").strip() == "core"
        )

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
    hybrid_hits = _preserve_customer_pack_core_blend(
        plan.rewritten_query,
        hybrid_hits=hybrid_hits,
        core_hits=core_reference_hits,
        context=context,
    )
    hybrid_hits = _preserve_official_title_locator_candidate(
        hybrid_hits=hybrid_hits,
        official_title_hits=official_title_locator_hits,
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
    graph_enriched_hits = _preserve_customer_pack_core_blend(
        plan.rewritten_query,
        hybrid_hits=graph_enriched_hits,
        core_hits=core_reference_hits,
        context=context,
    )
    graph_enriched_hits = _preserve_official_title_locator_candidate(
        hybrid_hits=graph_enriched_hits,
        official_title_hits=official_title_locator_hits,
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
    hits = _preserve_official_title_locator_candidate(
        hybrid_hits=hits,
        official_title_hits=official_title_locator_hits,
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
