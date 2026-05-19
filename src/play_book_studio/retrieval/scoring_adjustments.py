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
    if normalized_term.startswith("oc get events") and "oc events" in text:
        return True
    if normalized_term.startswith("oc get endpointslice") and (
        "oc get endpointslice" in text or "oc get endpointslices" in text
    ):
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


_DOMAIN_BOOK_SLUGS = {
    "backup_restore": {"backup_and_restore", "etcd"},
    "install": {
        "installation_overview",
        "installing_on_any_platform",
        "disconnected_environments",
        "cli_tools",
        "support",
    },
    "logging": {"logging", "observability_overview", "support", "cli_tools"},
    "monitoring": {
        "monitoring",
        "monitoring_alerts_admin",
        "monitoring_metrics_admin",
        "monitoring_troubleshooting",
        "observability_overview",
        "operators",
    },
    "networking": {"ingress_and_load_balancing", "networking", "advanced_networking"},
    "security": {"authentication_and_authorization", "security_and_compliance", "images", "cli_tools"},
    "storage": {"storage"},
    "registry": {"registry", "images"},
    "operators": {"operators", "postinstallation_configuration"},
    "etcd": {"etcd", "backup_and_restore"},
    "node_ops": {"nodes", "machine_management", "support"},
}


_PROVIDER_TERMS = {
    "azure": ("azure", "azure file", "azure disk", "microsoft azure"),
    "vsphere": ("vsphere", "vmware"),
    "rhosp": ("rhosp", "openstack", "red hat openstack"),
    "aws": ("aws", "amazon", "ebs", "efs"),
    "gcp": ("gcp", "google cloud"),
}


def _query_provider_signals(query: str) -> set[str]:
    lowered = (query or "").lower()
    return {
        provider
        for provider, terms in _PROVIDER_TERMS.items()
        if any(term in lowered for term in terms)
    }


def _hit_provider_signals(hit: RetrievalHit) -> set[str]:
    text = _hit_search_text(hit)
    return {
        provider
        for provider, terms in _PROVIDER_TERMS.items()
        if any(term in text for term in terms)
    }


def _hit_matches_query_domain(hit: RetrievalHit, *, signals: ScoreSignals) -> bool:
    classification = signals.structured_query_signals.classification
    domain = str(classification.get("domain") or "").strip()
    book_candidates = {
        str(item or "").strip()
        for item in classification.get("book_slug_candidates", ())
        if str(item or "").strip()
    }
    allowed_books = set(book_candidates)
    allowed_books.update(_DOMAIN_BOOK_SLUGS.get(domain, set()))
    return not allowed_books or hit.book_slug in allowed_books


def _apply_provider_scope_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    query_providers = _query_provider_signals(signals.query)
    hit_providers = _hit_provider_signals(hit)
    if not hit_providers:
        return
    if query_providers & hit_providers:
        hit.fused_score *= 1.08
        hit.component_scores["provider_signal_match_boost"] = 1.08
        return
    if not query_providers:
        hit.fused_score *= 0.72
        hit.component_scores["provider_specific_without_query_penalty"] = 0.72


def _apply_intent_profile_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    profile = signals.intent_profile
    if not profile.needs_command or profile.confidence < 0.7:
        return
    if not _hit_matches_query_domain(hit, signals=signals):
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


def _metadata_signal_commands(metadata_filter: dict[str, object] | None) -> tuple[str, ...]:
    if not metadata_filter:
        return ()
    boosts = metadata_filter.get("_intent_signal_boosts")
    if not isinstance(boosts, dict):
        return ()
    commands = boosts.get("commands")
    if not isinstance(commands, tuple | list):
        return ()
    return tuple(str(command or "").strip() for command in commands if str(command or "").strip())


def _structured_signal_commands(
    signals: ScoreSignals,
    metadata_filter: dict[str, object] | None = None,
) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for command in _metadata_signal_commands(metadata_filter):
        lowered = command.lower()
        if lowered not in seen:
            merged.append(command)
            seen.add(lowered)
    search_signals = signals.structured_query_signals.search_signals
    commands = search_signals.get("commands", ()) if isinstance(search_signals, dict) else ()
    if not isinstance(commands, tuple | list):
        return tuple(merged)
    for command in commands:
        cleaned = str(command or "").strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            merged.append(cleaned)
            seen.add(lowered)
    return tuple(merged)


def _structured_signal_values(signals: ScoreSignals, key: str) -> tuple[str, ...]:
    search_signals = signals.structured_query_signals.search_signals
    values = search_signals.get(key, ()) if isinstance(search_signals, dict) else ()
    if not isinstance(values, tuple | list):
        return ()
    return tuple(str(value or "").strip() for value in values if str(value or "").strip())


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
    metadata_filter: dict[str, object] | None = None,
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

    classification = signals.structured_query_signals.classification
    domain = str(classification.get("domain") or "").strip()
    domain_confidence = signals.structured_query_signals.confidence.get("domain", 0.0)
    if domain == "storage" and domain_confidence >= 0.85:
        if _hit_matches_query_domain(hit, signals=signals):
            hit.fused_score *= 1.18
            hit.component_scores["domain_match_boost"] = 1.18
        else:
            hit.fused_score *= 0.48
            hit.component_scores["domain_mismatch_penalty"] = 0.48
    elif domain in _DOMAIN_BOOK_SLUGS and domain not in {"troubleshooting"} and domain_confidence >= 0.85:
        if _hit_matches_query_domain(hit, signals=signals):
            hit.fused_score *= 1.14
            hit.component_scores["domain_match_boost"] = 1.14
        elif signals.command_request_intent:
            hit.fused_score *= 0.72
            hit.component_scores["domain_mismatch_penalty"] = 0.72

    intent_labels = {value.lower() for value in _structured_signal_values(signals, "intent_labels")}
    lowered_query = (signals.query or "").lower()
    lowered_section = (hit.section or "").lower()
    lowered_search_text = _hit_search_text(hit)
    has_etcd_backup_intent = (
        "backup" in intent_labels
        or "backup" in lowered_query
        or "백업" in signals.query
    ) and ("etcd" in lowered_query or domain in {"etcd", "backup_restore"})
    if has_etcd_backup_intent:
        if hit.book_slug == "backup_and_restore" and (
            "automated etcd backup" in lowered_section
            or "creating a single automated etcd backup" in lowered_section
            or "backing up etcd" in lowered_section
            or "etcd backup" in lowered_section
        ):
            hit.fused_score *= 2.2
            hit.component_scores["etcd_backup_section_boost"] = 2.2
        elif "cluster-backup.sh" in lowered_search_text or "/usr/local/bin/cluster-backup.sh" in lowered_search_text:
            hit.fused_score *= 1.45
            hit.component_scores["etcd_backup_command_boost"] = 1.45

        is_replacement_query = any(
            term in lowered_query
            for term in ("replace", "replacement", "restore", "crash", "loop", "member", "복구", "교체")
        )
        is_replacement_hit = any(
            term in lowered_section
            for term in ("replacing", "replacement", "unhealthy", "crashloop", "crash loop", "restore")
        )
        if not is_replacement_query and is_replacement_hit:
            hit.fused_score *= 0.5
            hit.component_scores["etcd_backup_replacement_penalty"] = 0.5

    if is_reference_heavy_book_slug(hit.book_slug):
        if signals.concept_like_intent and not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.34
        elif not signals.doc_locator_intent and not signals.structured_query_terms:
            hit.fused_score *= 0.82

    if signals.command_request_intent:
        signal_commands = _structured_signal_commands(signals, metadata_filter)
        has_command_surface = bool(hit.cli_commands or _has_shell_command_text(hit.text))
        if signal_commands and any(_term_matches_text(command, _hit_search_text(hit)) for command in signal_commands):
            hit.fused_score *= 2.25
            hit.component_scores["structured_signal_command_exact_boost"] = 2.25
        elif signal_commands and has_command_surface:
            hit.fused_score *= 0.7
            hit.component_scores["structured_signal_command_mismatch_penalty"] = 0.7

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

    _apply_provider_scope_adjustments(hit, signals=signals)

    _apply_intent_profile_adjustments(hit, signals=signals)

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

