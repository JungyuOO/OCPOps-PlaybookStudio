from __future__ import annotations

import copy
import time
from typing import Any

from play_book_studio.app.wiki_user_overlay import build_wiki_overlay_signal_payload

from .followups import has_follow_up_reference
from .intake_overlay import has_active_customer_pack_selection
from .models import RetrievalHit, SessionContext
from .query import (
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_command_request,
    has_cluster_node_usage_intent,
    has_machine_config_reboot_intent,
    has_mco_concept_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_pod_lifecycle_concept_intent,
    has_route_ingress_compare_intent,
    is_explainer_query,
    is_generic_intro_query,
)
from .ranking import summarize_hit_list as _summarize_hit_list
from .trace import duration_ms as _duration_ms, emit_trace_event as _emit_trace_event


DERIVED_RUNTIME_SOURCE_TYPES = frozenset(
    {
        "topic_playbook",
        "operation_playbook",
        "troubleshooting_playbook",
        "policy_overlay_book",
        "synthesized_playbook",
    }
)


def _has_registry_storage_ops_intent(query: str) -> bool:
    lowered_query = query.lower()
    has_registry_signal = (
        "image registry" in lowered_query
        or "imageregistry" in lowered_query
        or "registry" in lowered_query
        or "레지스트리" in query
    )
    has_image_signal = "image" in lowered_query or "이미지" in query
    has_storage_signal = (
        "storage" in lowered_query
        or "mirror" in lowered_query
        or "미러" in query
        or "스토리지" in query
        or "저장소" in query
    )
    has_configuration_signal = (
        "config" in lowered_query
        or "configure" in lowered_query
        or "구성" in query
        or "설정" in query
        or "준비" in query
    )
    has_install_scope_signal = (
        "install" in lowered_query
        or "설치" in query
        or "platform" in lowered_query
        or "플랫폼" in query
        or "manual" in lowered_query
        or "수동" in query
        or "bare metal" in lowered_query
        or "베어 메탈" in query
    )
    return (
        has_registry_signal
        and has_image_signal
        and (has_storage_signal or has_configuration_signal)
        and not has_install_scope_signal
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


def _prime_hits_for_rebalance(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    primed_hits: list[RetrievalHit] = []
    for source_hit in hits:
        hit = copy.deepcopy(source_hit)
        hit.component_scores = dict(hit.component_scores)
        hit.component_scores.setdefault("pre_rerank_fused_score", float(hit.fused_score))
        hit.component_scores.setdefault("reranker_score", float(hit.fused_score))
        primed_hits.append(hit)
    return primed_hits


def _has_non_core_or_derived_hits(hits: list[RetrievalHit]) -> bool:
    for hit in hits[:5]:
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


def _is_heuristic_first_query(query: str) -> bool:
    return any(
        (
            has_backup_restore_intent(query),
            _has_registry_storage_ops_intent(query),
        )
    )


def _is_explanation_query(query: str) -> bool:
    return any(
        (
            is_explainer_query(query),
            is_generic_intro_query(query),
            has_openshift_kubernetes_compare_intent(query),
            has_route_ingress_compare_intent(query),
            has_operator_concept_intent(query),
            has_mco_concept_intent(query),
            has_pod_lifecycle_concept_intent(query),
        )
    )


def _has_confident_hybrid_top_hit(hits: list[RetrievalHit]) -> bool:
    if not hits:
        return False
    top_hit = hits[0]
    top_score = float(top_hit.fused_score or top_hit.raw_score or 0.0)
    if top_score <= 0:
        return False
    component_scores = getattr(top_hit, "component_scores", {}) or {}
    has_dual_support = any(key in component_scores for key in ("bm25_score", "overlay_bm25_score")) and (
        "vector_score" in component_scores
    )
    if len(hits) == 1:
        return has_dual_support or top_score >= 0.9
    runner_up_score = max(float(hit.fused_score or hit.raw_score or 0.0) for hit in hits[1:3])
    if not has_dual_support:
        return False
    return runner_up_score < (top_score * 0.88)


def _rerank_candidate_budget(
    query: str,
    *,
    top_k: int,
    reranker_top_n: int,
) -> int | None:
    if reranker_top_n <= 0 or not _is_explanation_query(query):
        return None
    cap = 6 if any(
        (
            has_openshift_kubernetes_compare_intent(query),
            has_route_ingress_compare_intent(query),
        )
    ) else 5
    budget = min(reranker_top_n, max(top_k, cap))
    if budget >= reranker_top_n:
        return None
    return budget


def _needs_semantic_model_rerank(query: str) -> bool:
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


def _should_apply_reranker_model(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
) -> tuple[bool, str]:
    if not hybrid_hits:
        return False, "no_hits"
    if _has_non_core_or_derived_hits(hybrid_hits):
        return True, "derived_or_non_core_hits"
    if has_follow_up_reference(query):
        return True, "follow_up_reference"
    if _is_heuristic_first_query(query):
        return False, "heuristic_first_intent"
    if _is_explanation_query(query) and not _has_cross_book_ambiguity(hybrid_hits):
        if _has_confident_hybrid_top_hit(hybrid_hits):
            return False, "confident_explanation_hybrid_top_hit"
    if _needs_semantic_model_rerank(query):
        return True, "semantic_intent"
    if len(hybrid_hits) <= 2:
        top_books = {
            str(hit.book_slug or "").strip()
            for hit in hybrid_hits[:2]
            if str(hit.book_slug or "").strip()
        }
        if len(top_books) <= 1:
            return False, "small_candidate_set"
    if _has_cross_book_ambiguity(hybrid_hits):
        return True, "cross_book_ambiguity"
    return True, "default_model_rerank"


def _call_reranker(
    reranker,
    *,
    query: str,
    hybrid_hits: list[RetrievalHit],
    top_k: int,
    top_n_override: int | None,
) -> list[RetrievalHit]:
    rerank_kwargs: dict[str, Any] = {"top_k": top_k}
    if top_n_override is not None:
        rerank_kwargs["top_n_override"] = top_n_override
    try:
        return reranker.rerank(query, hybrid_hits, **rerank_kwargs)
    except TypeError:
        if "top_n_override" not in rerank_kwargs:
            raise
        rerank_kwargs.pop("top_n_override", None)
        return reranker.rerank(query, hybrid_hits, **rerank_kwargs)


def _preferred_derived_family(query: str) -> str | None:
    normalized = query or ""
    lowered = normalized.lower()
    has_policy_signal = any(
        token in lowered
        for token in (
            "policy",
            "unsupported",
            "not supported",
            "support matrix",
            "prerequisite",
            "requirements",
            "requirement",
            "restriction",
            "restrictions",
            "compliance",
            "guardrail",
        )
    ) or any(
        token in normalized
        for token in (
            "정책",
            "요구사항",
            "요구 사항",
            "사전 조건",
            "사전조건",
            "제한",
            "지원 제한",
            "미지원",
            "지원되지",
            "컴플라이언스",
            "가드레일",
        )
    )
    has_troubleshooting_signal = any(
        token in lowered
        for token in (
            "troubleshoot",
            "troubleshooting",
            "debug",
            "error",
            "errors",
            "failure",
            "failed",
            "issue",
            "issues",
            "terminating",
            "crashloopbackoff",
            "notready",
            "degraded",
            "recovery",
        )
    ) or any(
        token in normalized
        for token in (
            "문제",
            "장애",
            "오류",
            "에러",
            "실패",
            "복구",
            "디버그",
            "안 돼",
            "안돼",
            "안 지워",
            "안 없어",
            "멈춤",
        )
    )
    has_operation_signal = (
        has_command_request(normalized)
        or has_backup_restore_intent(normalized)
        or has_cluster_node_usage_intent(normalized)
        or has_machine_config_reboot_intent(normalized)
        or any(
            token in normalized
            for token in (
                "절차",
                "운영",
                "실행",
                "검증",
                "점검",
                "방법",
                "어떻게",
                "명령",
            )
        )
    )
    has_topic_signal = is_generic_intro_query(normalized) or any(
        token in normalized
        for token in (
            "핵심",
            "요약",
            "정리",
            "개요",
        )
    )

    if has_policy_signal:
        return "policy_overlay_book"
    if has_troubleshooting_signal:
        return "troubleshooting_playbook"
    if has_operation_signal:
        return "operation_playbook"
    if has_topic_signal:
        return "topic_playbook"
    return None


def _rebalance_derived_family_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if _is_customer_pack_explicit_query(query):
        return reranked_hits

    preferred_family = _preferred_derived_family(query)
    if preferred_family is None:
        return reranked_hits
    if not hybrid_hits or not reranked_hits:
        return reranked_hits
    if str(reranked_hits[0].source_type or "").strip() == preferred_family:
        return reranked_hits

    family_priority = {
        "operation_playbook": {
            "operation_playbook": 0,
            "topic_playbook": 1,
            "synthesized_playbook": 2,
        },
        "troubleshooting_playbook": {
            "troubleshooting_playbook": 0,
            "operation_playbook": 1,
            "topic_playbook": 2,
            "synthesized_playbook": 3,
        },
        "policy_overlay_book": {
            "policy_overlay_book": 0,
            "synthesized_playbook": 1,
            "topic_playbook": 2,
        },
        "topic_playbook": {
            "topic_playbook": 0,
            "synthesized_playbook": 1,
            "operation_playbook": 2,
        },
    }.get(preferred_family, {preferred_family: 0})

    if not any(
        str(hit.source_type or "").strip() == preferred_family
        for hit in hybrid_hits[: min(len(hybrid_hits), 8)]
    ):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    existing_ids = {hit.chunk_id for hit in reordered}
    candidate_sources: list[tuple[str, int, RetrievalHit]] = [
        ("reranked", index, hit)
        for index, hit in enumerate(reordered)
        if str(hit.source_type or "").strip() in family_priority
    ]
    candidate_sources.extend(
        ("hybrid", -1, hit)
        for hit in hybrid_hits
        if str(hit.source_type or "").strip() in family_priority and hit.chunk_id not in existing_ids
    )
    if not candidate_sources:
        return reranked_hits

    def _candidate_sort_key(item: tuple[str, int, RetrievalHit]) -> tuple[int, int, float, float, str, str]:
        hit = item[2]
        source_type = str(hit.source_type or "").strip()
        return (
            family_priority.get(source_type, 9),
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", hit.fused_score),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            str(hit.book_slug or ""),
            str(hit.chunk_id or ""),
        )

    candidate_sources.sort(key=_candidate_sort_key)
    source_name, source_index, source_hit = candidate_sources[0]
    if str(source_hit.source_type or "").strip() != preferred_family:
        return reranked_hits

    if source_name == "reranked":
        preferred_hit = reordered.pop(source_index)
    else:
        preferred_hit = copy.deepcopy(source_hit)
        preferred_hit.source = "hybrid_derived_family_rescued"
        preferred_hit.component_scores.setdefault(
            "pre_rerank_fused_score",
            float(preferred_hit.fused_score),
        )
        preferred_hit.component_scores.setdefault(
            "reranker_score",
            float(preferred_hit.component_scores["pre_rerank_fused_score"]),
        )
    reordered.insert(0, preferred_hit)
    return reordered


def _rebalance_uploaded_customer_pack_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
    context: SessionContext | None,
) -> list[RetrievalHit]:
    if not (
        _is_customer_pack_explicit_query(query)
        or has_active_customer_pack_selection(context)
    ):
        return reranked_hits
    if not any(str(hit.source_collection or "").strip() == "uploaded" for hit in hybrid_hits):
        return reranked_hits
    if reranked_hits and str(reranked_hits[0].source_collection or "").strip() == "uploaded":
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    existing_ids = {hit.chunk_id for hit in reordered}
    uploaded_sources: list[tuple[str, int, RetrievalHit]] = [
        ("reranked", index, hit)
        for index, hit in enumerate(reordered)
        if str(hit.source_collection or "").strip() == "uploaded"
    ]
    uploaded_sources.extend(
        ("hybrid", -1, hit)
        for hit in hybrid_hits
        if str(hit.source_collection or "").strip() == "uploaded" and hit.chunk_id not in existing_ids
    )
    if not uploaded_sources:
        return reranked_hits

    def _uploaded_sort_key(item: tuple[str, int, RetrievalHit]) -> tuple[int, float, float, str, str]:
        hit = item[2]
        return (
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", hit.fused_score),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )

    uploaded_sources.sort(key=_uploaded_sort_key)
    source_name, source_index, source_hit = uploaded_sources[0]
    if source_name == "reranked":
        uploaded_hit = reordered.pop(source_index)
    else:
        uploaded_hit = copy.deepcopy(source_hit)
        uploaded_hit.source = "hybrid_uploaded_rescued"
        uploaded_hit.component_scores.setdefault(
            "pre_rerank_fused_score",
            float(uploaded_hit.fused_score),
        )
        uploaded_hit.component_scores.setdefault(
            "reranker_score",
            float(uploaded_hit.component_scores["pre_rerank_fused_score"]),
        )
    reordered.insert(0, uploaded_hit)
    return reordered


def _rebalance_registry_storage_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if not _has_registry_storage_ops_intent(query):
        return reranked_hits

    preferred_books = {"registry", "images"}
    install_books = {"installation_overview", "installing_on_any_platform"}
    if not hybrid_hits or not any(hit.book_slug in preferred_books for hit in hybrid_hits):
        return reranked_hits
    if not reranked_hits or reranked_hits[0].book_slug not in install_books:
        return reranked_hits
    if not any(hit.book_slug in preferred_books for hit in reranked_hits):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            0 if hit.book_slug in preferred_books else 1,
            1 if hit.book_slug in install_books else 0,
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _rebalance_registry_follow_up_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    lowered_query = query.lower()
    if not has_follow_up_reference(query):
        return reranked_hits
    if not (
        ("image registry" in lowered_query or "registry" in lowered_query or "레지스트리" in query)
        and ("image" in lowered_query or "이미지" in query or "저장소" in query)
    ):
        return reranked_hits
    if not hybrid_hits or hybrid_hits[0].book_slug not in {"registry", "images"}:
        return reranked_hits
    if not reranked_hits or reranked_hits[0].book_slug in {"registry", "images"}:
        return reranked_hits

    preferred_books = {"registry", "images"}
    if not any(hit.book_slug in preferred_books for hit in reranked_hits):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            0 if hit.book_slug in preferred_books else 1,
            1 if hit.book_slug == "installation_overview" else 0,
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _rebalance_mco_concept_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    preferred_order = {
        "machine_configuration": 0,
        "operators": 1,
        "machine_management": 2,
        "architecture": 3,
        "overview": 4,
    }

    def _mco_signal(hit: RetrievalHit) -> bool:
        lowered_section = (hit.section or "").lower()
        lowered_anchor = (hit.anchor or "").lower()
        lowered_text = (hit.text or "").lower()
        return (
            hit.book_slug in {"machine_configuration", "operators", "machine_management"}
            or "machine config operator" in lowered_section
            or "machine config operator" in lowered_text
            or "machine config pool" in lowered_section
            or "machine config pool" in lowered_text
            or "machineconfigpool" in lowered_section
            or "machineconfigpool" in lowered_text
            or lowered_anchor.startswith("about-mco")
            or lowered_anchor.endswith("mco")
        )

    explicit_mco_intent = has_mco_concept_intent(query)
    follow_up_mco_intent = has_follow_up_reference(query) and any(
        _mco_signal(hit) for hit in hybrid_hits[:8]
    )
    if not explicit_mco_intent and not follow_up_mco_intent:
        return reranked_hits
    if not hybrid_hits or not any(_mco_signal(hit) for hit in hybrid_hits[:8]):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)

    def _priority(hit: RetrievalHit) -> tuple[int, int]:
        lowered_section = (hit.section or "").lower()
        lowered_anchor = (hit.anchor or "").lower()
        lowered_text = (hit.text or "").lower()
        book_priority = preferred_order.get(hit.book_slug, 9)
        if hit.book_slug == "release_notes":
            noise_priority = 5
        elif hit.book_slug == "support":
            noise_priority = 4
        elif hit.book_slug == "updating_clusters" and (
            "일반 용어" in hit.section or "glossary" in lowered_section
        ):
            noise_priority = 3
        elif hit.book_slug == "postinstallation_configuration" and any(
            token in f"{lowered_section} {lowered_anchor} {lowered_text}"
            for token in ("troubleshooting", "mco")
        ):
            noise_priority = 4
        elif hit.book_slug == "postinstallation_configuration":
            noise_priority = 2
        else:
            noise_priority = 0
        return book_priority, noise_priority

    reordered.sort(
        key=lambda hit: (
            *_priority(hit),
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _rebalance_cluster_node_usage_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if not has_cluster_node_usage_intent(query):
        return reranked_hits
    if not hybrid_hits or hybrid_hits[0].book_slug != "support":
        return reranked_hits
    if not reranked_hits or reranked_hits[0].book_slug != "nodes":
        return reranked_hits
    if not any(hit.book_slug == "support" for hit in reranked_hits):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            0 if hit.book_slug == "support" else 1 if hit.book_slug == "nodes" else 2,
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _rebalance_certificate_monitor_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if not has_certificate_monitor_intent(query):
        return reranked_hits
    preferred_books = {"cli_tools", "security_and_compliance"}
    if not hybrid_hits or not any(hit.book_slug in preferred_books for hit in hybrid_hits[:5]):
        return reranked_hits
    if not reranked_hits or reranked_hits[0].book_slug in preferred_books:
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}

    def _priority(hit: RetrievalHit) -> tuple[int, int]:
        lowered_section = (hit.section or "").lower()
        lowered_anchor = (hit.anchor or "").lower()
        if hit.book_slug == "cli_tools" and "monitor-certificates" in lowered_anchor:
            return (0, 0)
        if hit.book_slug == "security_and_compliance" and any(
            token in lowered_section for token in ("만료", "expiration", "expiry")
        ):
            return (1, 0)
        if hit.book_slug == "cli_tools":
            return (2, 0)
        if hit.book_slug == "security_and_compliance":
            return (3, 0)
        if hit.book_slug == "support":
            return (4, 0)
        return (9, 0)

    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            *_priority(hit),
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _classify_etcd_backup_restore_query(query: str, hybrid_hits: list[RetrievalHit]) -> str | None:
    lowered = (query or "").lower()
    backup_signal = "백업" in query or "backup" in lowered
    restore_signal = any(token in lowered for token in ("복원", "복구", "restore", "recovery"))
    has_etcd_signal = "etcd" in lowered or any(
        hit.book_slug in {"etcd", "postinstallation_configuration"}
        for hit in hybrid_hits[:8]
    )
    if not has_etcd_signal or not has_backup_restore_intent(query):
        return None
    if backup_signal and not restore_signal:
        return "backup"
    if restore_signal:
        return "restore"
    if has_follow_up_reference(query):
        return "restore"
    return None


def _etcd_backup_priority(hit: RetrievalHit) -> int:
    lowered_section = (hit.section or "").lower()
    lowered_text = (hit.text or "").lower()
    if (
        "cluster-backup.sh" in lowered_text
        or "oc debug --as-root node" in lowered_text
        or "chroot /host" in lowered_text
    ):
        return 0
    if "etcd 데이터 백업" in lowered_section:
        return 1
    if "자동화된 etcd 백업" in lowered_section:
        return 2
    if "cluster-restore.sh" in lowered_text or "복원" in lowered_section or "restore" in lowered_text:
        return 8
    return 5


def _etcd_restore_priority(hit: RetrievalHit) -> int:
    lowered_section = (hit.section or "").lower()
    lowered_text = (hit.text or "").lower()
    if (
        "cluster-restore.sh" in lowered_text
        or "수동으로 클러스터 복원" in lowered_section
        or "이전 클러스터 상태로 복원" in lowered_section
    ):
        return 0
    if "복원 절차 테스트" in lowered_section:
        return 2
    if "cluster-backup.sh" in lowered_text or "etcd 데이터 백업" in lowered_section:
        return 5
    return 3


def _rebalance_etcd_backup_restore_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if _is_customer_pack_explicit_query(query) and any(
        str(hit.source_collection or "").strip() == "uploaded"
        for hit in (*reranked_hits, *hybrid_hits)
    ):
        return reranked_hits
    classification = _classify_etcd_backup_restore_query(query, hybrid_hits)
    if classification is None:
        return reranked_hits
    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    priority_fn = _etcd_backup_priority if classification == "backup" else _etcd_restore_priority
    if classification == "backup":
        preferred_books = {
            "backup_and_restore": 0,
            "etcd": 1,
            "postinstallation_configuration": 2,
            "hosted_control_planes": 3,
            "updating_clusters": 4,
        }
        companion_books = {"etcd", "postinstallation_configuration"}
    else:
        preferred_books = {
            "postinstallation_configuration": 0,
            "etcd": 1,
            "backup_and_restore": 2,
            "hosted_control_planes": 3,
            "updating_clusters": 4,
        }
        companion_books = {"etcd", "backup_and_restore"}
    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            priority_fn(hit),
            preferred_books.get(hit.book_slug, 9),
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )

    # etcd backup 절차는 backup_and_restore 를 primary로 유지하되,
    # dedicated etcd 또는 legacy postinstall 문서 하나는 함께 남겨 참조 폭을 유지한다.
    if classification == "backup":
        def _companion_sort_key(hit: RetrievalHit) -> tuple[int, int, int, float, float, str, str]:
            return (
                priority_fn(hit),
                preferred_books.get(hit.book_slug, 9),
                hybrid_rank.get(hit.chunk_id, 999),
                -hit.component_scores.get("pre_rerank_fused_score", hit.fused_score),
                -hit.component_scores.get("reranker_score", hit.fused_score),
                hit.book_slug,
                hit.chunk_id,
            )

        primary_book_slug = str(reordered[0].book_slug or "").strip() if reordered else ""
        companion_sources: list[tuple[str, int, RetrievalHit]] = [
            ("reranked", index, hit)
            for index, hit in enumerate(reordered)
            if hit.book_slug in companion_books and hit.book_slug != primary_book_slug
        ]
        existing_ids = {hit.chunk_id for hit in reordered}
        companion_sources.extend(
            ("hybrid", -1, hit)
            for hit in hybrid_hits
            if (
                hit.book_slug in companion_books
                and hit.book_slug != primary_book_slug
                and hit.chunk_id not in existing_ids
            )
        )
        companion_sources.sort(key=lambda item: _companion_sort_key(item[2]))

        companion_hit: RetrievalHit | None = None
        if companion_sources:
            source_name, companion_index, source_hit = companion_sources[0]
            if source_name == "reranked":
                companion_hit = reordered.pop(companion_index)
            else:
                companion_hit = copy.deepcopy(source_hit)
                companion_hit.source = "hybrid_companion_rescued"
                companion_hit.component_scores.setdefault(
                    "pre_rerank_fused_score",
                    float(companion_hit.fused_score),
                )
                companion_hit.component_scores.setdefault(
                    "reranker_score",
                    float(companion_hit.component_scores["pre_rerank_fused_score"]),
                )
        if companion_hit is not None:
            insert_at = 1 if reordered else 0
            reordered.insert(insert_at, companion_hit)
    return reordered


def _overlay_recent_preference_scores(
    *,
    root_dir,
    user_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    normalized_user_id = str(user_id or "").strip()
    if root_dir is None or not normalized_user_id:
        return {}, {}
    try:
        payload = build_wiki_overlay_signal_payload(root_dir, user_id=normalized_user_id)
    except Exception:  # noqa: BLE001
        return {}, {}
    user_focus = payload.get("user_focus") if isinstance(payload, dict) else None
    recent_targets = user_focus.get("recent_targets") if isinstance(user_focus, dict) else None
    if not isinstance(recent_targets, list):
        return {}, {}
    book_scores: dict[str, int] = {}
    entity_scores: dict[str, int] = {}
    for index, item in enumerate(recent_targets[:12]):
        if not isinstance(item, dict):
            continue
        target_ref = str(item.get("target_ref") or "").strip()
        if not target_ref:
            continue
        base_score = max(10, 80 - index * 6)
        if target_ref.startswith("book:"):
            slug = target_ref.split(":", 1)[1].strip()
            if slug:
                book_scores[slug] = max(book_scores.get(slug, 0), base_score)
        elif target_ref.startswith("section:"):
            slug = target_ref.split(":", 1)[1].split("#", 1)[0].strip()
            if slug:
                book_scores[slug] = max(book_scores.get(slug, 0), base_score - 8)
        elif target_ref.startswith("figure:"):
            parts = target_ref.split(":")
            if len(parts) >= 3 and parts[1].strip():
                book_scores[parts[1].strip()] = max(book_scores.get(parts[1].strip(), 0), base_score - 16)
        elif target_ref.startswith("entity:"):
            entity = target_ref.split(":", 1)[1].strip()
            if entity:
                entity_scores[entity] = max(entity_scores.get(entity, 0), base_score)
    return book_scores, entity_scores


def _overlay_entity_hit_score(hit: RetrievalHit, entity_scores: dict[str, int]) -> int:
    lowered_section = (hit.section or "").lower()
    lowered_text = (hit.text or "").lower()
    score = 0
    if "etcd" in lowered_section or "etcd" in lowered_text:
        score = max(score, entity_scores.get("etcd", 0))
    if "machine config" in lowered_section or "machine config" in lowered_text or "mco" in lowered_section or "mco" in lowered_text:
        score = max(score, entity_scores.get("machine-config-operator", 0))
    if "prometheus" in lowered_section or "prometheus" in lowered_text:
        score = max(score, entity_scores.get("prometheus", 0))
    if "proxy" in lowered_section or "proxy" in lowered_text:
        score = max(score, entity_scores.get("cluster-wide-proxy", 0))
    if "control plane" in lowered_section or "control plane" in lowered_text:
        score = max(score, entity_scores.get("control-plane-nodes", 0))
    return score


def _rebalance_overlay_preference_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
    context: SessionContext | None,
    root_dir,
) -> list[RetrievalHit]:
    del query
    user_id = str(getattr(context, "user_id", "") or "").strip()
    if not user_id:
        return reranked_hits
    book_scores, entity_scores = _overlay_recent_preference_scores(root_dir=root_dir, user_id=user_id)
    if not book_scores and not entity_scores:
        return reranked_hits
    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    reordered.sort(
        key=lambda hit: (
            -max(
                book_scores.get(hit.book_slug, 0),
                _overlay_entity_hit_score(hit, entity_scores),
            ),
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", 0.0),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            hit.book_slug,
            hit.chunk_id,
        )
    )
    return reordered


def _is_generic_intro_candidate(hit: RetrievalHit) -> bool:
    book_slug = str(hit.book_slug or "").strip()
    section = str(hit.section or "").strip()
    lowered_section = section.lower()

    if book_slug not in {"architecture", "overview"}:
        return False
    if any(
        token in section
        for token in (
            "라이프사이클",
            "사용자 정의 운영 체제",
            "기타 주요 기능",
            "용어집",
        )
    ):
        return False
    if any(
        token in lowered_section
        for token in (
            "lifecycle",
            "custom os",
            "glossary",
        )
    ):
        return False
    return any(
        token in section
        for token in (
            "개요",
            "소개",
            "정의",
        )
    ) or any(
        token in lowered_section
        for token in (
            "overview",
            "introduction",
            "definition",
        )
    )


def _rebalance_generic_intro_hits(
    query: str,
    *,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
) -> list[RetrievalHit]:
    if not is_generic_intro_query(query):
        return reranked_hits
    if not hybrid_hits or not reranked_hits:
        return reranked_hits
    if _is_generic_intro_candidate(reranked_hits[0]):
        return reranked_hits

    hybrid_rank = {hit.chunk_id: index for index, hit in enumerate(hybrid_hits)}
    reordered = list(reranked_hits)
    existing_ids = {hit.chunk_id for hit in reordered}
    candidate_sources: list[tuple[str, int, RetrievalHit]] = [
        ("reranked", index, hit)
        for index, hit in enumerate(reordered)
        if _is_generic_intro_candidate(hit)
    ]
    candidate_sources.extend(
        ("hybrid", -1, hit)
        for hit in hybrid_hits
        if _is_generic_intro_candidate(hit) and hit.chunk_id not in existing_ids
    )
    if not candidate_sources:
        return reranked_hits

    def _candidate_sort_key(item: tuple[str, int, RetrievalHit]) -> tuple[int, int, float, float, str, str]:
        hit = item[2]
        book_priority = 0 if hit.book_slug == "overview" else 1
        return (
            book_priority,
            hybrid_rank.get(hit.chunk_id, 999),
            -hit.component_scores.get("pre_rerank_fused_score", hit.fused_score),
            -hit.component_scores.get("reranker_score", hit.fused_score),
            str(hit.book_slug or ""),
            str(hit.chunk_id or ""),
        )

    candidate_sources.sort(key=_candidate_sort_key)
    source_name, source_index, source_hit = candidate_sources[0]
    if source_name == "reranked":
        preferred_hit = reordered.pop(source_index)
    else:
        preferred_hit = copy.deepcopy(source_hit)
        preferred_hit.source = "hybrid_intro_rescued"
        preferred_hit.component_scores.setdefault(
            "pre_rerank_fused_score",
            float(preferred_hit.fused_score),
        )
        preferred_hit.component_scores.setdefault(
            "reranker_score",
            float(preferred_hit.component_scores["pre_rerank_fused_score"]),
        )
    reordered.insert(0, preferred_hit)
    return reordered


def _top_book_slug(hits: list[RetrievalHit]) -> str:
    if not hits:
        return ""
    return str(hits[0].book_slug or "")


def _apply_rebalance_rule(
    *,
    rule_name: str,
    query: str,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
    rule_fn,
    rebalance_reasons: list[str],
) -> list[RetrievalHit]:
    before_ids = [hit.chunk_id for hit in reranked_hits]
    rebalanced_hits = rule_fn(
        query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
    )
    after_ids = [hit.chunk_id for hit in rebalanced_hits]
    if after_ids != before_ids and rule_name not in rebalance_reasons:
        rebalance_reasons.append(rule_name)
    return rebalanced_hits


def _apply_rebalance_rules(
    retriever,
    *,
    query: str,
    hybrid_hits: list[RetrievalHit],
    reranked_hits: list[RetrievalHit],
    context: SessionContext | None,
) -> tuple[list[RetrievalHit], list[str]]:
    rebalance_reasons: list[str] = []
    reranked_hits = _apply_rebalance_rule(
        rule_name="overlay_preference",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=lambda rebalance_query, *, hybrid_hits, reranked_hits: _rebalance_overlay_preference_hits(
            rebalance_query,
            hybrid_hits=hybrid_hits,
            reranked_hits=reranked_hits,
            context=context,
            root_dir=retriever.settings.root_dir,
        ),
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="registry_storage_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_registry_storage_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="registry_follow_up_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_registry_follow_up_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="mco_concept_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_mco_concept_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="cluster_node_usage_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_cluster_node_usage_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="certificate_monitor_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_certificate_monitor_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="etcd_backup_restore_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_etcd_backup_restore_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="derived_family_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_derived_family_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="generic_intro_intent",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=_rebalance_generic_intro_hits,
        rebalance_reasons=rebalance_reasons,
    )
    reranked_hits = _apply_rebalance_rule(
        rule_name="uploaded_customer_pack_priority",
        query=query,
        hybrid_hits=hybrid_hits,
        reranked_hits=reranked_hits,
        rule_fn=lambda rebalance_query, *, hybrid_hits, reranked_hits: _rebalance_uploaded_customer_pack_hits(
            rebalance_query,
            hybrid_hits=hybrid_hits,
            reranked_hits=reranked_hits,
            context=context,
        ),
        rebalance_reasons=rebalance_reasons,
    )
    return reranked_hits, rebalance_reasons


def maybe_rerank_hits(
    retriever,
    *,
    query: str,
    hybrid_hits: list[RetrievalHit],
    context: SessionContext | None,
    top_k: int,
    trace_callback,
    timings_ms: dict[str, float],
) -> tuple[list[RetrievalHit], dict[str, Any]]:
    hits = hybrid_hits[:top_k]
    reranker_trace: dict[str, Any] = {
        "enabled": retriever.reranker is not None,
        "applied": False,
        "model_applied": False,
        "mode": "skipped",
        "model": getattr(retriever.reranker, "model_name", ""),
        "top_n": getattr(retriever.reranker, "top_n", 0),
        "top1_before": _top_book_slug(hybrid_hits),
        "top1_after_model": "",
        "top1_after": _top_book_slug(hits),
        "top1_changed": False,
        "rebalance_reasons": [],
        "decision_reason": "",
        "candidate_budget": getattr(retriever.reranker, "top_n", 0),
    }
    if retriever.reranker is None or not hybrid_hits:
        return hits, reranker_trace
    try:
        apply_model, decision_reason = _should_apply_reranker_model(
            query,
            hybrid_hits=hybrid_hits,
        )
        reranker_trace["decision_reason"] = decision_reason
        candidate_budget = _rerank_candidate_budget(
            query,
            top_k=top_k,
            reranker_top_n=getattr(retriever.reranker, "top_n", 0),
        )
        if candidate_budget is not None:
            reranker_trace["candidate_budget"] = candidate_budget
        rerank_started_at = time.perf_counter()
        if apply_model:
            _emit_trace_event(
                trace_callback,
                step="rerank",
                label="리랭킹 중",
                status="running",
            )
            reranked_hits = _call_reranker(
                retriever.reranker,
                query=query,
                hybrid_hits=hybrid_hits,
                top_k=top_k,
                top_n_override=candidate_budget,
            )
            reranker_trace["top1_after_model"] = _top_book_slug(reranked_hits)
            reranker_trace["model_applied"] = True
            reranker_trace["mode"] = "model"
        else:
            reranked_hits = _prime_hits_for_rebalance(hybrid_hits)
            reranker_trace["top1_after_model"] = reranker_trace["top1_before"]
            reranker_trace["mode"] = "heuristic_only"
        reranked_hits, rebalance_reasons = _apply_rebalance_rules(
            retriever,
            query=query,
            hybrid_hits=hybrid_hits,
            reranked_hits=reranked_hits,
            context=context,
        )
        timings_ms["rerank"] = _duration_ms(rerank_started_at)
        hits = reranked_hits[:top_k]
        reranker_trace["top1_after"] = _top_book_slug(hits)
        reranker_trace["top1_changed"] = reranker_trace["top1_before"] != reranker_trace["top1_after"]
        reranker_trace.update(
            {
                "applied": bool(apply_model or rebalance_reasons or reranker_trace["top1_changed"]),
                "candidate_count": len(hybrid_hits),
                "reranked_count": (
                    min(
                        len(hybrid_hits),
                        candidate_budget
                        if candidate_budget is not None
                        else max(top_k, retriever.reranker.top_n),
                    )
                    if apply_model
                    else len(hybrid_hits)
                ),
                "rebalance_reasons": rebalance_reasons,
            }
        )
        _emit_trace_event(
            trace_callback,
            step="rerank",
            label="리랭킹 완료" if apply_model else "규칙 재정렬 완료",
            status="done",
            detail=(
                f"{hits[0].book_slug} · {hits[0].section}"
                if hits
                else "상위 근거 없음"
            ),
            duration_ms=timings_ms["rerank"],
            meta={
                "summary": _summarize_hit_list(hits, score_key="fused_score"),
                "top1_before": reranker_trace["top1_before"],
                "top1_after": reranker_trace["top1_after"],
                "top1_changed": reranker_trace["top1_changed"],
                "rebalance_reasons": reranker_trace["rebalance_reasons"],
                "mode": reranker_trace["mode"],
                "decision_reason": reranker_trace["decision_reason"],
                "candidate_budget": reranker_trace["candidate_budget"],
            },
        )
    except Exception as exc:  # noqa: BLE001
        reranker_trace["error"] = str(exc)
        _emit_trace_event(
            trace_callback,
            step="rerank",
            label="리랭킹 실패",
            status="error",
            detail=str(exc),
        )
        raise RuntimeError(f"reranker failed: {exc}") from exc
    return hits, reranker_trace
