from __future__ import annotations

# 개념 설명/문서 개요/비교 질문처럼 문서군 우선순위를 조정하는 규칙을 분리한다.

from .intents import (
    COMPARE_RE,
    INGRESS_RE,
    KUBERNETES_RE,
    ROUTE_RE,
    has_openshift_kubernetes_compare_intent,
    has_route_ingress_compare_intent,
    is_generic_intro_query,
)


def apply_overview_discovery_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    route_ingress_compare = has_route_ingress_compare_intent(normalized) or (
        bool(KUBERNETES_RE.search(normalized))
        and bool(COMPARE_RE.search(normalized) or "차이도" in normalized)
        and bool(ROUTE_RE.search(context_text))
        and bool(INGRESS_RE.search(context_text))
    )

    if route_ingress_compare:
        boosts["networking_overview"] = max(boosts.get("networking_overview", 1.0), 1.72)
        boosts["ingress_and_load_balancing"] = max(
            boosts.get("ingress_and_load_balancing", 1.0),
            1.84,
        )
        penalties["architecture"] = min(penalties.get("architecture", 1.0), 0.34)
        penalties["overview"] = min(penalties.get("overview", 1.0), 0.44)
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.46,
        )
        penalties["support"] = min(penalties.get("support", 1.0), 0.58)
        penalties["tutorials"] = min(penalties.get("tutorials", 1.0), 0.66)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.42)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.48,
        )

    if is_generic_intro_query(normalized):
        boosts["architecture"] = 1.35
        boosts["overview"] = 1.18
        penalties["tutorials"] = 0.62
        penalties["cli_tools"] = 0.64
        penalties["support"] = 0.72
        penalties["networking_overview"] = 0.68
        penalties["observability_overview"] = 0.8
        penalties["api_overview"] = 0.78
        penalties["project_apis"] = 0.82
        penalties["release_notes"] = 0.55

    if has_openshift_kubernetes_compare_intent(normalized) and not route_ingress_compare:
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.28)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.24)
        boosts["security_and_compliance"] = max(
            boosts.get("security_and_compliance", 1.0),
            1.2,
        )
        penalties["tutorials"] = min(penalties.get("tutorials", 1.0), 0.65)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.7)
        penalties["support"] = min(penalties.get("support", 1.0), 0.72)
        penalties["postinstallation_configuration"] = min(
            penalties.get("postinstallation_configuration", 1.0),
            0.72,
        )
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.58)
