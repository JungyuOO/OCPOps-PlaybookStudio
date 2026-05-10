# hit 하나에 적용할 fusion 점수 조정 규칙을 조립한다.
from __future__ import annotations

from .models import RetrievalHit
from .query import contains_hangul
from .scoring_adjustments_core import apply_core_adjustments
from .scoring_adjustments_runtime import apply_runtime_adjustments
from .scoring_signals import ScoreSignals
from play_book_studio.config.corpus_policy import is_reference_heavy_book_slug


def _has_shell_command_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in (
            "oc ",
            "kubectl ",
            "openshift-install ",
            "oc adm ",
            "journalctl ",
            "systemctl ",
            "helm ",
            "curl ",
        )
    )


def _query_matches_hit_object(query: str, hit: RetrievalHit) -> bool:
    lowered_query = (query or "").lower()
    if not lowered_query:
        return False
    object_terms = {
        str(item or "").strip().lower()
        for item in hit.k8s_objects
        if str(item or "").strip()
    }
    object_terms.update(
        token
        for token in (
            "namespace",
            "namespaces",
            "project",
            "projects",
            "pod",
            "pods",
            "event",
            "events",
            "route",
            "routes",
            "pvc",
            "persistentvolumeclaim",
            "clusteroperator",
            "clusteroperators",
        )
        if token in (hit.text or "").lower()
    )
    aliases = {
        "namespace": ("namespace", "namespaces", "네임스페이스", "프로젝트"),
        "namespaces": ("namespace", "namespaces", "네임스페이스", "프로젝트"),
        "project": ("project", "projects", "프로젝트", "네임스페이스"),
        "projects": ("project", "projects", "프로젝트", "네임스페이스"),
        "pod": ("pod", "pods", "파드"),
        "pods": ("pod", "pods", "파드"),
        "event": ("event", "events", "이벤트"),
        "events": ("event", "events", "이벤트"),
        "route": ("route", "routes", "라우트"),
        "routes": ("route", "routes", "라우트"),
        "pvc": ("pvc", "persistentvolumeclaim", "persistent volume claim"),
        "persistentvolumeclaim": ("pvc", "persistentvolumeclaim", "persistent volume claim"),
    }
    return any(
        any(alias in lowered_query for alias in aliases.get(term, (term,)))
        for term in object_terms
    )


def apply_hit_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    book_source_count: int,
) -> None:
    is_intake_doc = hit.viewer_path.startswith("/playbooks/customer-packs/")
    lowered_text = hit.text.lower()

    if book_source_count >= 2:
        hit.fused_score *= 1.1
    elif (
        contains_hangul(signals.query)
        and "vector_score" in hit.component_scores
        and "bm25_score" not in hit.component_scores
    ):
        hit.fused_score *= 0.95

    # intake overlay는 현재 기본 retrieval 경로에서 비활성화했다.
    # overlay 점수 우대는 opt-in 경로가 다시 살아날 때만 되돌린다.

    if contains_hangul(signals.query):
        if contains_hangul(hit.text):
            hit.fused_score *= 1.05
        else:
            hit.fused_score *= 0.85

    if is_reference_heavy_book_slug(hit.book_slug):
        if signals.concept_like_intent and not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.34
        elif not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.82

    if signals.command_request_intent:
        if hit.cli_commands:
            hit.fused_score *= 1.35
            hit.component_scores["command_intent_cli_commands_boost"] = 1.35
        elif _has_shell_command_text(hit.text):
            hit.fused_score *= 1.12
            hit.component_scores["command_intent_shell_text_boost"] = 1.12
        else:
            hit.fused_score *= 0.92
            hit.component_scores["command_intent_no_command_penalty"] = 0.92
        if hit.chunk_type in {"command", "procedure"}:
            hit.fused_score *= 1.08
            hit.component_scores["command_intent_chunk_type_boost"] = 1.08
        if _query_matches_hit_object(signals.query, hit):
            hit.fused_score *= 1.12
            hit.component_scores["command_intent_object_match_boost"] = 1.12

    apply_core_adjustments(hit, signals=signals)

    if hit.book_slug in signals.book_boosts:
        hit.fused_score *= signals.book_boosts[hit.book_slug]
    if hit.book_slug in signals.book_penalties:
        hit.fused_score *= signals.book_penalties[hit.book_slug]

    apply_runtime_adjustments(
        hit,
        signals=signals,
        is_intake_doc=is_intake_doc,
    )

    hit.raw_score = hit.fused_score

