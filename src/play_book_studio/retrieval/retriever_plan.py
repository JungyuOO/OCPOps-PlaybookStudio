from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import SessionContext
from .query import (
    detect_unsupported_product,
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_command_request,
    has_doc_locator_intent,
    has_follow_up_reference,
    has_openshift_kubernetes_compare_intent,
    normalize_query,
    rewrite_query,
)
from .query_signal_pipeline import QueryCorrection, build_query_signal_plan
from .rewrite import rewrite_decision


@dataclass(slots=True)
class RetrievalPlan:
    normalized_query: str
    rewritten_query: str
    decomposed_queries: list[str]
    rewritten_queries: list[str]
    retrieval_queries: list[str]
    metadata_filter: dict[str, Any]
    correction_notes: list[QueryCorrection]
    unsupported_product: str | None
    follow_up_detected: bool
    rewrite_applied: bool
    rewrite_reason: str
    effective_candidate_k: int
    normalize_query_ms: float
    rewrite_query_ms: float


def _dedupe_queries(queries: tuple[str, ...], *, fallback: str) -> list[str]:
    deduped: list[str] = []
    for query in (*queries, fallback):
        cleaned = " ".join(str(query or "").split())
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped[:2]


def _uses_study_docs_scope(context: SessionContext) -> bool:
    return str(getattr(context, "preferred_source_scope", "") or "").strip() == "study_docs"


def build_retrieval_plan(
    query: str,
    *,
    context: SessionContext,
    candidate_k: int,
    llm_client: Any | None = None,
) -> RetrievalPlan:
    normalize_started_at = time.perf_counter()
    normalized_query = normalize_query(query)
    normalize_query_ms = round((time.perf_counter() - normalize_started_at) * 1000, 1)
    unsupported_product = detect_unsupported_product(normalized_query)
    follow_up_detected = has_follow_up_reference(query)

    rewrite_started_at = time.perf_counter()
    rewrite_applied, rewrite_reason = rewrite_decision(normalized_query, context)
    rewritten_query = rewrite_query(normalized_query, context)
    signal_plan = build_query_signal_plan(rewritten_query, llm_client=llm_client)
    if _uses_study_docs_scope(context):
        retrieval_queries = _dedupe_queries((rewritten_query,), fallback=rewritten_query)
        metadata_filter: dict[str, Any] = {}
    else:
        retrieval_queries = _dedupe_queries(signal_plan.embedding_queries, fallback=rewritten_query)
        metadata_filter = signal_plan.metadata_filter
    rewrite_query_ms = round((time.perf_counter() - rewrite_started_at) * 1000, 1)

    effective_candidate_k = candidate_k
    if (
        len(retrieval_queries) > 1
        or has_openshift_kubernetes_compare_intent(normalized_query)
        or has_doc_locator_intent(normalized_query)
        or has_backup_restore_intent(normalized_query)
        or has_certificate_monitor_intent(normalized_query)
        or has_command_request(normalized_query)
        or (
            any(token in normalized_query for token in ("bootstrap", "부트스트랩"))
            and any(token in normalized_query for token in ("확인", "상태", "wait", "complete", "완료", "단계"))
        )
        or follow_up_detected
    ):
        effective_candidate_k = max(candidate_k, 10)

    return RetrievalPlan(
        normalized_query=normalized_query,
        rewritten_query=rewritten_query,
        decomposed_queries=list(retrieval_queries),
        rewritten_queries=list(retrieval_queries),
        retrieval_queries=list(retrieval_queries),
        metadata_filter=metadata_filter,
        correction_notes=list(signal_plan.correction_notes),
        unsupported_product=unsupported_product,
        follow_up_detected=follow_up_detected,
        rewrite_applied=rewrite_applied,
        rewrite_reason=rewrite_reason,
        effective_candidate_k=effective_candidate_k,
        normalize_query_ms=normalize_query_ms,
        rewrite_query_ms=rewrite_query_ms,
    )
