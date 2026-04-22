from __future__ import annotations

# 노드/배포/재부팅처럼 운영 작업 성격의 문서군 조정 규칙을 모은다.

from .intents import (
    MCO_RE,
    has_cluster_node_usage_intent,
    has_deployment_scaling_intent,
    has_machine_config_reboot_intent,
    has_node_drain_intent,
)


def apply_node_and_deployment_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    if has_node_drain_intent(normalized):
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.45)
        boosts["support"] = max(boosts.get("support", 1.0), 1.18)
        penalties["updating_clusters"] = min(
            penalties.get("updating_clusters", 1.0),
            0.62,
        )
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.74,
        )
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.76)

    if has_cluster_node_usage_intent(normalized):
        boosts["support"] = max(boosts.get("support", 1.0), 1.5)
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.18)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.8)

    if has_machine_config_reboot_intent(normalized) or (
        MCO_RE.search(context_text) and "재부팅" in normalized
    ):
        boosts["machine_management"] = max(boosts.get("machine_management", 1.0), 1.18)
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.08)
        boosts["updating_clusters"] = max(boosts.get("updating_clusters", 1.0), 1.48)
        boosts["postinstallation_configuration"] = max(
            boosts.get("postinstallation_configuration", 1.0),
            1.24,
        )
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.12)
        penalties["support"] = min(penalties.get("support", 1.0), 0.82)
        penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.42)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.72)
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.46,
        )
        penalties["specialized_hardware_and_driver_enablement"] = min(
            penalties.get("specialized_hardware_and_driver_enablement", 1.0),
            0.18,
        )
        penalties["network_security"] = min(penalties.get("network_security", 1.0), 0.22)
        penalties["windows_container_support_for_openshift"] = min(
            penalties.get("windows_container_support_for_openshift", 1.0),
            0.28,
        )
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.55,
        )
        penalties["hosted_control_planes"] = min(
            penalties.get("hosted_control_planes", 1.0),
            0.42,
        )

    if has_deployment_scaling_intent(normalized) or has_deployment_scaling_intent(context_text):
        boosts["cli_tools"] = max(boosts.get("cli_tools", 1.0), 1.82)
        boosts["building_applications"] = max(boosts.get("building_applications", 1.0), 1.35)
        penalties["authentication_and_authorization"] = min(
            penalties.get("authentication_and_authorization", 1.0),
            0.32,
        )
        penalties["postinstallation_configuration"] = min(
            penalties.get("postinstallation_configuration", 1.0),
            0.38,
        )
        penalties["machine_management"] = min(
            penalties.get("machine_management", 1.0),
            0.46,
        )
        penalties["nodes"] = min(penalties.get("nodes", 1.0), 0.72)
