from __future__ import annotations

# RBAC/인증서처럼 접근 제어와 검증 성격의 조정 규칙을 모은다.

from .intents import (
    ROLE_API_STYLE_RE,
    has_certificate_monitor_intent,
    has_project_scoped_rbac_intent,
    has_rbac_assignment_intent,
    has_rbac_intent,
)


def apply_security_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    effective_text = " ".join(part for part in (normalized, context_text) if part).strip()
    rbac_intent = has_rbac_intent(effective_text)
    project_scoped_rbac = has_project_scoped_rbac_intent(effective_text)
    rbac_assignment = has_rbac_assignment_intent(effective_text)
    prefers_rbac_api_docs = bool(ROLE_API_STYLE_RE.search(normalized))

    if rbac_intent:
        boosts["authentication_and_authorization"] = max(
            boosts.get("authentication_and_authorization", 1.0),
            1.42,
        )
        boosts["security_and_compliance"] = max(
            boosts.get("security_and_compliance", 1.0),
            1.08,
        )
        if project_scoped_rbac:
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.14,
            )
        if rbac_assignment:
            boosts["tutorials"] = max(boosts.get("tutorials", 1.0), 1.18)
        if not prefers_rbac_api_docs:
            penalties["role_apis"] = min(penalties.get("role_apis", 1.0), 0.72)
            penalties["project_apis"] = min(penalties.get("project_apis", 1.0), 0.84)

    if has_certificate_monitor_intent(normalized):
        boosts["cli_tools"] = max(boosts.get("cli_tools", 1.0), 1.55)
        boosts["security_and_compliance"] = max(
            boosts.get("security_and_compliance", 1.0),
            1.06,
        )
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.88,
        )
        penalties["cert_manager_operator_for_red_hat_openshift"] = min(
            penalties.get("cert_manager_operator_for_red_hat_openshift", 1.0),
            0.75,
        )
