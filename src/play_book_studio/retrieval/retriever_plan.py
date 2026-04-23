from __future__ import annotations

import re
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
    has_route_ingress_compare_intent,
    is_explainer_query,
    is_generic_intro_query,
    normalize_query,
    rewrite_query,
)
from .rewrite import rewrite_decision
from .text_utils import collapse_spaces

OFFICIAL_BLEND_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣#]+")
OFFICIAL_BLEND_STOPWORDS = {
    "고객",
    "고객사",
    "공식",
    "문서",
    "문서를",
    "설계서",
    "운영",
    "공식문서",
    "공식매뉴얼",
    "같이",
    "함께",
    "참고",
    "참고해서",
    "설명",
    "설명해줘",
    "알려줘",
    "찾아줘",
    "ocp",
    "openshift",
    "container",
    "platform",
}
OFFICIAL_BLEND_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "와",
    "과",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "도",
    "로",
)
OFFICIAL_BLEND_GENERIC_FOCUS_TOKENS = {
    "구성",
    "설정",
    "흐름",
    "절차",
    "방법",
    "단계",
}


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


def _normalize_query_for_context(query: str, context: SessionContext) -> str:
    raw_query = collapse_spaces(query)
    if (
        raw_query
        and bool(getattr(context, "selected_draft_ids", []))
        and is_generic_intro_query(raw_query)
    ):
        return raw_query
    return normalize_query(raw_query)


def _mentions_official_runtime_sources(query: str) -> bool:
    lowered = collapse_spaces(query).lower()
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


def _normalize_official_blend_token(token: str) -> str:
    cleaned = str(token or "").strip().lower()
    for suffix in OFFICIAL_BLEND_SUFFIXES:
        if cleaned.endswith(suffix) and len(cleaned) - len(suffix) >= 2:
            cleaned = cleaned[: -len(suffix)]
            break
    return cleaned


def _collect_official_blend_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in OFFICIAL_BLEND_TOKEN_RE.findall(collapse_spaces(query)):
        cleaned = _normalize_official_blend_token(token)
        if len(cleaned) < 2:
            continue
        if cleaned in OFFICIAL_BLEND_STOPWORDS:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        tokens.append(cleaned)
    return tokens


def _build_official_runtime_blend_subquery(query: str) -> str:
    tokens = _collect_official_blend_tokens(query)
    if not tokens:
        return ""
    parts = ["OpenShift", *tokens]
    if is_explainer_query(query) and not any(token in {"아키텍처", "architecture"} for token in tokens):
        parts.append("아키텍처")
    return collapse_spaces(" ".join(parts))


def _should_add_official_explainer_variants(query: str, context: SessionContext) -> bool:
    explainer_like = is_explainer_query(query) or is_generic_intro_query(query)
    if not bool(getattr(context, "selected_draft_ids", [])):
        return False
    if not _mentions_official_runtime_sources(query):
        return False
    if has_doc_locator_intent(query) and not explainer_like:
        return False
    if has_openshift_kubernetes_compare_intent(query):
        return False
    if has_route_ingress_compare_intent(query):
        return False
    return explainer_like


def _build_official_runtime_explainer_subqueries(query: str) -> list[str]:
    tokens = _collect_official_blend_tokens(query)
    if not tokens:
        return []
    focus_tokens = [
        token for token in tokens if token not in OFFICIAL_BLEND_GENERIC_FOCUS_TOKENS
    ]
    if not focus_tokens:
        focus_tokens = tokens[:1]
    focus_tokens = focus_tokens[:3]
    base = collapse_spaces(" ".join(["OpenShift", *focus_tokens]))
    variants: list[str] = []
    for suffix in ("아키텍처", "개요"):
        variant = collapse_spaces(f"{base} {suffix}")
        if variant and variant not in variants:
            variants.append(variant)
    return variants


def build_retrieval_plan(
    query: str,
    *,
    context: SessionContext,
    candidate_k: int,
) -> RetrievalPlan:
    normalize_started_at = time.perf_counter()
    normalized_query = _normalize_query_for_context(query, context)
    normalize_query_ms = round((time.perf_counter() - normalize_started_at) * 1000, 1)
    unsupported_product = detect_unsupported_product(normalized_query)
    decomposed_queries = decompose_retrieval_queries(query)
    follow_up_detected = has_follow_up_reference(query)
    selected_official_explainer_blend = _should_add_official_explainer_variants(query, context)
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
    if selected_official_explainer_blend:
        effective_candidate_k = max(effective_candidate_k, 50)

    rewritten_queries: list[str] = []

    def _append_rewritten_queries(subqueries: list[str], *, follow_up_context: SessionContext) -> None:
        for subquery in subqueries:
            rewritten_subquery = rewrite_query(
                _normalize_query_for_context(subquery, follow_up_context),
                follow_up_context,
            )
            if rewritten_subquery not in rewritten_queries:
                rewritten_queries.append(rewritten_subquery)

    _append_rewritten_queries(decomposed_queries, follow_up_context=context)
    if bool(getattr(context, "selected_draft_ids", [])) and _mentions_official_runtime_sources(query):
        official_context = SessionContext(
            mode=context.mode,
            ocp_version=context.ocp_version,
        )
        official_subqueries: list[str] = []
        official_subquery = _build_official_runtime_blend_subquery(query)
        if official_subquery:
            official_subqueries.append(official_subquery)
        if selected_official_explainer_blend:
            official_subqueries.extend(_build_official_runtime_explainer_subqueries(query))
        for official_subquery in official_subqueries:
            rewritten_official_query = rewrite_query(
                _normalize_query_for_context(official_subquery, official_context),
                official_context,
            )
            if rewritten_official_query not in rewritten_queries:
                rewritten_queries.append(rewritten_official_query)
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
