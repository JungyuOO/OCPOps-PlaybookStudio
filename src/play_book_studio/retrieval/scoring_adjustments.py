# hit 하나에 적용할 fusion 점수 조정 규칙을 조립한다.
from __future__ import annotations

import re

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


_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\{[^}]+\}|\[[^\]]+\]")


def _hit_search_text(hit: RetrievalHit) -> str:
    return "\n".join(
        (
            hit.text or "",
            hit.section or "",
            hit.heading_title or "",
            hit.chapter or "",
            " ".join(hit.cli_commands),
            " ".join(hit.k8s_objects),
            " ".join(hit.verification_hints),
        )
    ).lower()


def _term_matches_text(term: str, text: str) -> bool:
    normalized_term = re.sub(r"\s+", " ", (term or "").strip().lower())
    if not normalized_term:
        return False
    if normalized_term in text:
        return True
    without_placeholders = _PLACEHOLDER_RE.sub(" ", normalized_term)
    if without_placeholders.strip() and without_placeholders.strip() in text:
        return True
    if without_placeholders.strip().endswith("s") and without_placeholders.strip()[:-1] in text:
        return True
    if without_placeholders.strip() and f"{without_placeholders.strip()}s" in text:
        return True
    tokens = [
        token
        for token in re.split(r"[^a-z0-9_.-]+", without_placeholders)
        if len(token) >= 2 and token not in {"name", "namespace", "operator"}
    ]
    if tokens and all((token in text or f"{token}s" in text) for token in tokens):
        return True
    return len(tokens) >= 2 and all(token in text for token in tokens)


def _apply_intent_profile_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    profile = signals.intent_profile
    if not profile.needs_command or profile.confidence < 0.7:
        return

    search_text = _hit_search_text(hit)
    if any(_term_matches_text(command, search_text) for command in profile.primary_commands):
        hit.fused_score *= 1.42
        hit.component_scores["intent_profile_primary_command_boost"] = 1.42
        return

    has_command_surface = bool(hit.cli_commands or _has_shell_command_text(search_text))
    if profile.primary_commands and has_command_surface:
        hit.fused_score *= 0.88
        hit.component_scores["intent_profile_command_mismatch_penalty"] = 0.88
        return

    if any(_term_matches_text(term, search_text) for term in profile.evidence_terms):
        hit.fused_score *= 1.16
        hit.component_scores["intent_profile_evidence_boost"] = 1.16
        return

    if has_command_surface:
        hit.fused_score *= 0.88
        hit.component_scores["intent_profile_command_mismatch_penalty"] = 0.88


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


def _normalized_terms(values: tuple[str, ...]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        cleaned = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
        if cleaned:
            terms.add(cleaned)
    return terms


def _command_families_for_hit(hit: RetrievalHit, search_text: str) -> set[str]:
    families: set[str] = set()
    command_text = "\n".join((*hit.cli_commands, search_text)).lower()
    if "oc get" in command_text:
        families.add("oc_get")
    if "oc describe" in command_text:
        families.add("oc_describe")
    if "oc adm" in command_text:
        families.add("oc_adm")
    if "oc debug" in command_text:
        families.add("oc_debug")
    if "openshift-install" in command_text:
        families.add("openshift_install")
    return families


def _apply_structured_signal_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    structured = signals.structured_query_signals
    search_signals = structured.search_signals
    search_text = _hit_search_text(hit)

    query_objects = _normalized_terms(search_signals.get("objects", ()))
    hit_objects = _normalized_terms(hit.k8s_objects)
    if query_objects and (query_objects & hit_objects or any(term in search_text for term in query_objects)):
        hit.fused_score *= 1.08
        hit.component_scores["v014_object_signal_boost"] = 1.08

    query_errors = {
        str(item or "").strip().lower()
        for item in search_signals.get("error_states", ())
        if str(item or "").strip()
    }
    hit_errors = {
        str(item or "").strip().lower()
        for item in hit.error_strings
        if str(item or "").strip()
    }
    if query_errors and (query_errors & hit_errors or any(error in search_text for error in query_errors)):
        hit.fused_score *= 1.12
        hit.component_scores["v014_error_state_signal_boost"] = 1.12

    query_families = set(search_signals.get("command_families", ()))
    hit_families = _command_families_for_hit(hit, search_text)
    if query_families and query_families & hit_families:
        hit.fused_score *= 1.06
        hit.component_scores["v014_command_family_signal_boost"] = 1.06

    answer_shapes = set(search_signals.get("answer_shapes", ()))
    if answer_shapes & {"command", "step_by_step", "checklist", "troubleshooting_flow"}:
        if hit.chunk_type in {"command", "procedure", "troubleshooting"}:
            hit.fused_score *= 1.05
            hit.component_scores["v014_answer_shape_chunk_boost"] = 1.05

    book_candidates = {
        str(item or "").strip()
        for item in structured.classification.get("book_slug_candidates", ())
        if str(item or "").strip()
    }
    if hit.book_slug in book_candidates:
        hit.fused_score *= 1.04
        hit.component_scores["v014_book_candidate_signal_boost"] = 1.04


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

    _apply_intent_profile_adjustments(hit, signals=signals)
    _apply_structured_signal_adjustments(hit, signals=signals)

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

