from __future__ import annotations

# 개념, MCO, 오퍼레이터, follow-up 성격의 문서군 우선순위를 조정한다.

from .ambiguity import has_logging_ambiguity
from .intents import (
    COMPARE_RE,
    LOGGING_RE,
    MCO_RE,
    MONITORING_RE,
    OBSERVABILITY_RE,
    has_hosted_control_plane_signal,
    has_machine_config_reboot_intent,
    has_mco_concept_intent,
    has_operator_concept_intent,
    is_explainer_query,
)


def apply_concept_discovery_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    observability_compare = bool(
        OBSERVABILITY_RE.search(normalized)
        and MONITORING_RE.search(normalized)
        and COMPARE_RE.search(normalized)
    )
    logging_ambiguity = has_logging_ambiguity(normalized)
    hosted_control_plane_signal = has_hosted_control_plane_signal(normalized) or has_hosted_control_plane_signal(context_text)

    if hosted_control_plane_signal:
        boosts["hosted_control_planes"] = max(boosts.get("hosted_control_planes", 1.0), 2.6)
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.14)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.06)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.46,
        )
        penalties["updating_clusters"] = min(
            penalties.get("updating_clusters", 1.0),
            0.58,
        )
        penalties["support"] = min(penalties.get("support", 1.0), 0.62)
        penalties["operators"] = min(penalties.get("operators", 1.0), 0.72)

    if observability_compare:
        boosts["observability_overview"] = max(boosts.get("observability_overview", 1.0), 1.96)
        boosts["monitoring"] = max(boosts.get("monitoring", 1.0), 1.82)
        boosts["logging"] = max(boosts.get("logging", 1.0), 1.18)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.08)
        penalties["architecture"] = min(penalties.get("architecture", 1.0), 0.52)
        penalties["support"] = min(penalties.get("support", 1.0), 0.38)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.4)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.44,
        )
        penalties["updating_clusters"] = min(
            penalties.get("updating_clusters", 1.0),
            0.46,
        )

    if logging_ambiguity:
        boosts["logging"] = max(boosts.get("logging", 1.0), 2.08)
        boosts["monitoring"] = max(boosts.get("monitoring", 1.0), 1.42)
        boosts["observability_overview"] = max(
            boosts.get("observability_overview", 1.0),
            1.34,
        )
        penalties["support"] = min(penalties.get("support", 1.0), 0.34)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.42)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.5,
        )
        penalties["validation_and_troubleshooting"] = min(
            penalties.get("validation_and_troubleshooting", 1.0),
            0.64,
        )

    if has_mco_concept_intent(normalized):
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.28)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.24)
        boosts["machine_configuration"] = max(boosts.get("machine_configuration", 1.0), 2.08)
        boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.62)
        boosts["operators"] = max(boosts.get("operators", 1.0), 1.34)
        boosts["postinstallation_configuration"] = max(
            boosts.get("postinstallation_configuration", 1.0),
            1.12,
        )
        penalties["support"] = min(penalties.get("support", 1.0), 0.54)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.58)
        penalties["edge_computing"] = min(penalties.get("edge_computing", 1.0), 0.72)
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.74,
        )
        penalties["machine_apis"] = min(penalties.get("machine_apis", 1.0), 0.55)
        penalties["images"] = min(penalties.get("images", 1.0), 0.62)
        penalties["windows_container_support_for_openshift"] = min(
            penalties.get("windows_container_support_for_openshift", 1.0),
            0.42,
        )
        penalties["hosted_control_planes"] = min(
            penalties.get("hosted_control_planes", 1.0),
            0.36,
        )
        penalties["updating_clusters"] = min(
            penalties.get("updating_clusters", 1.0),
            0.28,
        )
    elif MCO_RE.search(context_text):
        boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.12)
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.08)
        boosts["postinstallation_configuration"] = max(
            boosts.get("postinstallation_configuration", 1.0),
            1.12,
        )
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.06)
        penalties["support"] = min(penalties.get("support", 1.0), 0.72)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.56,
        )
        penalties["network_security"] = min(penalties.get("network_security", 1.0), 0.32)
        penalties["hosted_control_planes"] = min(
            penalties.get("hosted_control_planes", 1.0),
            0.18,
        )
        penalties["specialized_hardware_and_driver_enablement"] = min(
            penalties.get("specialized_hardware_and_driver_enablement", 1.0),
            0.34,
        )
        pause_control_signal = (
            "자동 재부팅" in context_text
            or "자동으로 재부팅되지 않도록" in context_text
            or "spec.paused" in context_text.lower()
        )
        reboot_reason_signal = has_machine_config_reboot_intent(normalized) or (
            ("재부팅" in context_text or "reboot" in context_text)
            and not pause_control_signal
        )
        if reboot_reason_signal:
            boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.24)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.18,
            )
            boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.1)
            boosts["updating_clusters"] = max(
                boosts.get("updating_clusters", 1.0),
                1.32,
            )
            penalties["support"] = min(penalties.get("support", 1.0), 0.88)
            penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.68)
            penalties["edge_computing"] = min(
                penalties.get("edge_computing", 1.0),
                0.48,
            )
            penalties["security_and_compliance"] = min(
                penalties.get("security_and_compliance", 1.0),
                0.68,
            )
            penalties["windows_container_support_for_openshift"] = min(
                penalties.get("windows_container_support_for_openshift", 1.0),
                0.42,
            )
            penalties["network_security"] = min(
                penalties.get("network_security", 1.0),
                0.2,
            )
            penalties["specialized_hardware_and_driver_enablement"] = min(
                penalties.get("specialized_hardware_and_driver_enablement", 1.0),
                0.2,
            )
            penalties["hosted_control_planes"] = min(
                penalties.get("hosted_control_planes", 1.0),
                0.16,
            )
            penalties["machine_apis"] = min(penalties.get("machine_apis", 1.0), 0.62)
            penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.58)
        elif pause_control_signal:
            boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.38)
            boosts["support"] = max(boosts.get("support", 1.0), 1.22)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.22,
            )
            boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.18)
            boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.12)
            penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.74)
            boosts["updating_clusters"] = max(
                boosts.get("updating_clusters", 1.0),
                1.08,
            )
            penalties["edge_computing"] = min(
                penalties.get("edge_computing", 1.0),
                0.58,
            )
            penalties["security_and_compliance"] = min(
                penalties.get("security_and_compliance", 1.0),
                0.72,
            )
            penalties["windows_container_support_for_openshift"] = min(
                penalties.get("windows_container_support_for_openshift", 1.0),
                0.46,
            )
            penalties["network_security"] = min(
                penalties.get("network_security", 1.0),
                0.24,
            )
            penalties["specialized_hardware_and_driver_enablement"] = min(
                penalties.get("specialized_hardware_and_driver_enablement", 1.0),
                0.24,
            )
            penalties["hosted_control_planes"] = min(
                penalties.get("hosted_control_planes", 1.0),
                0.28,
            )
            penalties["machine_apis"] = min(penalties.get("machine_apis", 1.0), 0.68)
            penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.62)

    if has_operator_concept_intent(normalized):
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.18)
        boosts["extensions"] = max(boosts.get("extensions", 1.0), 1.28)
        boosts["operators"] = max(boosts.get("operators", 1.0), 1.92)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.34)
        if MCO_RE.search(normalized) or MCO_RE.search(context_text):
            boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.42)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.12,
            )
            penalties["hosted_control_planes"] = min(
                penalties.get("hosted_control_planes", 1.0),
                0.44,
            )
        penalties["support"] = min(penalties.get("support", 1.0), 0.58)
        penalties["web_console"] = min(penalties.get("web_console", 1.0), 0.62)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.7)
        penalties["edge_computing"] = min(penalties.get("edge_computing", 1.0), 0.78)
        penalties["images"] = min(penalties.get("images", 1.0), 0.56)
        penalties["updating_clusters"] = min(penalties.get("updating_clusters", 1.0), 0.48)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.48,
        )
