from __future__ import annotations

# 운영 절차/트러블슈팅/RBAC처럼 "어떤 실행 문서군을 우선 볼지"를 정하는 조정 규칙 모음이다.

from .book_adjustment_lifecycle import apply_project_lifecycle_adjustments
from .book_adjustment_node_ops import apply_node_and_deployment_adjustments
from .book_adjustment_security import apply_security_adjustments
from .book_adjustment_troubleshooting import apply_troubleshooting_adjustments
from .corpus_scope import detect_unsupported_product


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in tokens)


def _apply_runtime_domain_adjustments(
    normalized: str,
    *,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    if _contains_any(normalized, ("operator", "subscription", "installplan", "csv", "packagemanifest", "operatorhub")):
        boosts["operators"] = max(boosts.get("operators", 1.0), 1.45)
        penalties["disconnected_environments"] = min(penalties.get("disconnected_environments", 1.0), 0.72)
        penalties["support"] = min(penalties.get("support", 1.0), 0.88)

    if _contains_any(normalized, ("prometheus", "alertmanager", "thanos", "servicemonitor", "monitoring", "cluster alert", "클러스터 알람", "알람", "메트릭")):
        boosts["monitoring"] = max(boosts.get("monitoring", 1.0), 1.5)
        boosts["observability_overview"] = max(boosts.get("observability_overview", 1.0), 1.2)
        penalties["support"] = min(penalties.get("support", 1.0), 0.78)
        penalties["backup_and_restore"] = min(penalties.get("backup_and_restore", 1.0), 0.65)

    if _contains_any(normalized, ("rolebinding", "clusterrolebinding", "serviceaccount", "auth can-i", "oauth", "권한", "인증")):
        boosts["authentication_and_authorization"] = max(boosts.get("authentication_and_authorization", 1.0), 1.5)
        boosts["security_and_compliance"] = max(boosts.get("security_and_compliance", 1.0), 1.15)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.9)

    if _contains_any(normalized, ("endpointslice", "network.operator", "cluster network", "service dns", "route", "ingresscontroller", "네트워크 설정")):
        boosts["ingress_and_load_balancing"] = max(boosts.get("ingress_and_load_balancing", 1.0), 1.35)
        boosts["networking"] = max(boosts.get("networking", 1.0), 1.25)
        boosts["networking_overview"] = max(boosts.get("networking_overview", 1.0), 1.15)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.75)

    if _contains_any(normalized, ("rhcos", "kernel argument", "pull secret", "ssh key", "fips", "disconnected", "설치 방식", "설치 전에")):
        boosts["installation_overview"] = max(boosts.get("installation_overview", 1.0), 1.35)
        boosts["installing_on_any_platform"] = max(boosts.get("installing_on_any_platform", 1.0), 1.25)
        boosts["disconnected_installation_mirroring"] = max(boosts.get("disconnected_installation_mirroring", 1.0), 1.2)


def apply_operation_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    apply_project_lifecycle_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_node_and_deployment_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_troubleshooting_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_security_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    _apply_runtime_domain_adjustments(
        normalized,
        boosts=boosts,
        penalties=penalties,
    )
    if detect_unsupported_product(normalized):
        penalties["registry"] = min(penalties.get("registry", 1.0), 0.5)
        penalties["images"] = min(penalties.get("images", 1.0), 0.5)
        penalties["installation_overview"] = min(penalties.get("installation_overview", 1.0), 0.55)
