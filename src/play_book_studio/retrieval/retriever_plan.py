from __future__ import annotations

import time
from dataclasses import dataclass
import re
from typing import Any

from .access_scope import (
    SOURCE_GROUP_CUSTOMER_DOCS,
    SOURCE_GROUP_OFFICIAL_DOCS,
    active_document_scope_selected,
    enabled_source_scope_set,
)
from .models import SessionContext
from .query import (
    detect_unsupported_product,
    has_follow_up_reference,
    is_openshift_product_intro_query,
    normalize_query,
    rewrite_query,
)
from .query_signal_pipeline import QueryCorrection, build_query_signal_plan
from .rewrite import rewrite_decision

_OFFICIAL_ONLY_METADATA_KEYS = {
    "source.citation_eligible",
    "source.corpus_scope",
    "chunk.chunk_type",
}
_CUSTOMER_DOCUMENT_QUERY_RE = re.compile(
    r"(완료\s*보고서?|완료본|고객\s*(?:데이터|자료|문서)|PPTX?|"
    r"KMSC|COCP|RTER|RECR|아키텍[처쳐]\s*설계서|설계서\s*기준|"
    r"단위\s*테스트|통합\s*테스트|성능\s*테스트|테스트\s*(?:계획서|결과서))",
    re.IGNORECASE,
)


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
    query_signal_debug: dict[str, Any]


def _dedupe_queries(queries: tuple[str, ...], *, fallback: str) -> list[str]:
    deduped: list[str] = []
    for query in (*queries, fallback):
        cleaned = " ".join(str(query or "").split())
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped[:2]


def _signal_embedding_queries_for_retrieval(signal_plan: Any) -> tuple[str, ...]:
    embedding_queries = tuple(str(query or "") for query in signal_plan.embedding_queries)
    raw_query = " ".join(str(getattr(signal_plan, "raw_query", "") or "").split())
    if not embedding_queries or not raw_query:
        return embedding_queries
    first_query = " ".join(embedding_queries[0].split())
    if first_query == raw_query and len(embedding_queries) > 1:
        return embedding_queries[1:]
    return embedding_queries


def _uses_study_docs_scope(context: SessionContext) -> bool:
    if getattr(context, "enabled_source_scopes", None):
        return False
    return str(getattr(context, "preferred_source_scope", "") or "").strip() == "study_docs"


def _scope_compatible_metadata_filter(
    metadata_filter: dict[str, Any],
    context: SessionContext,
) -> dict[str, Any]:
    enabled_scopes = enabled_source_scope_set(context)
    if not enabled_scopes or enabled_scopes == {SOURCE_GROUP_OFFICIAL_DOCS}:
        return dict(metadata_filter)

    compatible_filter: dict[str, Any] = {}
    for key, value in metadata_filter.items():
        if key != "must":
            compatible_filter[key] = value
            continue
        if not isinstance(value, list):
            compatible_filter[key] = value
            continue
        must_conditions = [
            condition
            for condition in value
            if not (
                isinstance(condition, dict)
                and str(condition.get("key") or "").strip() in _OFFICIAL_ONLY_METADATA_KEYS
            )
        ]
        if must_conditions:
            compatible_filter[key] = must_conditions
    return compatible_filter


def _effective_candidate_k(candidate_k: int, signal_plan: Any) -> int:
    classification = signal_plan.classification if isinstance(signal_plan.classification, dict) else {}
    search_signals = signal_plan.search_signals if isinstance(signal_plan.search_signals, dict) else {}
    raw_query = str(getattr(signal_plan, "raw_query", "") or "")
    intent_labels = set(search_signals.get("intent_labels") or ())
    command_families = set(search_signals.get("command_families") or ())
    commands = set(search_signals.get("commands") or ())
    if _is_project_namespace_compare_query(raw_query):
        return max(candidate_k, 96)
    if (
        str(classification.get("domain") or "") == "etcd"
        and "backup" in intent_labels
        and "restore" not in intent_labels
        and (
            "cluster_backup" in command_families
            or any("cluster-backup.sh" in str(command) for command in commands)
        )
    ):
        return max(candidate_k, 64)
    return candidate_k


def _is_project_namespace_compare_query(query: str) -> bool:
    lowered = (query or "").lower()
    has_project = "project" in lowered or "프로젝트" in query
    has_namespace = "namespace" in lowered or "네임스페이스" in query
    compare_or_explain = any(token in query for token in ("차이", "설명", "초보자")) or any(
        token in lowered for token in ("compare", "difference")
    )
    return has_project and has_namespace and compare_or_explain


def _uses_deterministic_signal_plan(query: str) -> bool:
    lowered = (query or "").lower()
    web_console_locator = (
        ("web console" in lowered or "웹 콘솔" in query or "콘솔" in query)
        and (
            any(token in lowered for token in ("project", "projects", "workload", "workloads"))
            or any(token in query for token in ("프로젝트", "워크로드", "애플리케이션", "앱"))
        )
        and (
            any(token in query for token in ("어디", "확인", "봐야", "보려면"))
            or any(token in lowered for token in ("where", "view", "check", "show"))
        )
    )
    image_pull_grounding = (
        any(token in lowered for token in ("imagepullbackoff", "errimagepull"))
        and (
            any(token in lowered for token in ("pull secret", "registry"))
            or any(token in query for token in ("풀 시크릿", "레지스트리", "시크릿"))
        )
    )
    return _is_project_namespace_compare_query(query) or web_console_locator or image_pull_grounding


def _has_customer_document_query_signal(query: str) -> bool:
    return bool(_CUSTOMER_DOCUMENT_QUERY_RE.search(query or ""))


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
    if (
        str(getattr(context, "active_document_id", "") or "").strip()
        or str(getattr(context, "active_repository_id", "") or "").strip()
    ):
        unsupported_product = None
    follow_up_detected = has_follow_up_reference(query)

    rewrite_started_at = time.perf_counter()
    rewrite_applied, rewrite_reason = rewrite_decision(normalized_query, context)
    rewritten_query = rewrite_query(normalized_query, context)
    deterministic_signal_plan = _uses_deterministic_signal_plan(query)
    signal_plan = build_query_signal_plan(
        query,
        llm_client=None if deterministic_signal_plan else llm_client,
    )
    product_intro_query = is_openshift_product_intro_query(query)
    enabled_scopes = enabled_source_scope_set(context)
    customer_document_query = _has_customer_document_query_signal(query)
    has_repository_scope = bool(str(getattr(context, "active_repository_id", "") or "").strip())
    has_document_scope = active_document_scope_selected(context) or has_repository_scope
    if _uses_study_docs_scope(context):
        retrieval_queries = _dedupe_queries((rewritten_query, query), fallback=rewritten_query)
        metadata_filter: dict[str, Any] = {}
    elif has_document_scope:
        retrieval_queries = _dedupe_queries(
            (rewritten_query, *_signal_embedding_queries_for_retrieval(signal_plan)),
            fallback=rewritten_query,
        )
        metadata_filter = {}
    elif product_intro_query and not customer_document_query:
        retrieval_queries = _dedupe_queries((rewritten_query,), fallback=rewritten_query)
        metadata_filter = signal_plan.metadata_filter
    else:
        base_queries = (rewritten_query, *_signal_embedding_queries_for_retrieval(signal_plan))
        if SOURCE_GROUP_CUSTOMER_DOCS in enabled_scopes and customer_document_query:
            base_queries = (rewritten_query, query, *_signal_embedding_queries_for_retrieval(signal_plan))
        retrieval_queries = _dedupe_queries(
            base_queries,
            fallback=rewritten_query,
        )
        metadata_filter = _scope_compatible_metadata_filter(signal_plan.metadata_filter, context)
    rewrite_query_ms = round((time.perf_counter() - rewrite_started_at) * 1000, 1)

    effective_candidate_k = _effective_candidate_k(candidate_k, signal_plan)

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
        query_signal_debug=dict(signal_plan.debug or {}),
    )
