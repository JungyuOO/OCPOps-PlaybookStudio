from __future__ import annotations

import time
from dataclasses import dataclass

from .models import SessionContext
from .query import (
    decompose_retrieval_queries,
    detect_unsupported_product,
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_doc_locator_intent,
    has_follow_up_reference,
    has_openshift_kubernetes_compare_intent,
    normalize_query,
    rewrite_query,
)
from .rewrite import rewrite_decision


@dataclass(slots=True)
class RetrievalPlan:
    normalized_query: str
    rewritten_query: str
    decomposed_queries: list[str]
    rewritten_queries: list[str]
    unsupported_product: str | None
    follow_up_detected: bool
    rewrite_applied: bool
    rewrite_reason: str
    effective_candidate_k: int
    normalize_query_ms: float
    rewrite_query_ms: float


def build_retrieval_plan(
    query: str,
    *,
    context: SessionContext,
    candidate_k: int,
) -> RetrievalPlan:
    normalize_started_at = time.perf_counter()
    normalized_query = normalize_query(query)
    normalize_query_ms = round((time.perf_counter() - normalize_started_at) * 1000, 1)
    unsupported_product = detect_unsupported_product(normalized_query)
    decomposed_queries = decompose_retrieval_queries(query)
    follow_up_detected = has_follow_up_reference(query)
    rewrite_started_at = time.perf_counter()
    rewrite_applied, rewrite_reason = rewrite_decision(normalized_query, context)
    rewritten_query = rewrite_query(normalized_query, context)
    rewrite_query_ms = round((time.perf_counter() - rewrite_started_at) * 1000, 1)

    effective_candidate_k = candidate_k
    if (
        len(decomposed_queries) > 1
        or has_openshift_kubernetes_compare_intent(normalized_query)
        or has_doc_locator_intent(normalized_query)
        or has_backup_restore_intent(normalized_query)
        or has_certificate_monitor_intent(normalized_query)
        or follow_up_detected
    ):
        effective_candidate_k = max(candidate_k, 40)

    rewritten_queries: list[str] = []

    def _append_rewritten_queries(subqueries: list[str], *, follow_up_context: SessionContext) -> None:
        for subquery in subqueries:
            rewritten_subquery = rewrite_query(normalize_query(subquery), follow_up_context)
            if rewritten_subquery not in rewritten_queries:
                rewritten_queries.append(rewritten_subquery)

    _append_rewritten_queries(decomposed_queries, follow_up_context=context)
    if follow_up_detected and rewritten_query != normalized_query:
        # follow-up는 rewrite 결과가 실제 retrieval intent를 완성하는 경우가 많다.
        # resolved query를 다시 분해해 secondary search variants로 함께 태운다.
        _append_rewritten_queries(
            decompose_retrieval_queries(rewritten_query),
            follow_up_context=SessionContext(),
        )

    return RetrievalPlan(
        normalized_query=normalized_query,
        rewritten_query=rewritten_query,
        decomposed_queries=decomposed_queries,
        rewritten_queries=rewritten_queries,
        unsupported_product=unsupported_product,
        follow_up_detected=follow_up_detected,
        rewrite_applied=rewrite_applied,
        rewrite_reason=rewrite_reason,
        effective_candidate_k=effective_candidate_k,
        normalize_query_ms=normalize_query_ms,
        rewrite_query_ms=rewrite_query_ms,
    )
