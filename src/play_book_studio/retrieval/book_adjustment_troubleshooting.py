from __future__ import annotations

# Pod troubleshooting/라이프사이클 같은 문제 해결 성격의 조정 규칙을 모은다.

from .intents import (
    has_crash_loop_troubleshooting_intent,
    has_pod_lifecycle_concept_intent,
    has_pod_pending_troubleshooting_intent,
)


def apply_troubleshooting_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    del context_text
    if has_pod_pending_troubleshooting_intent(normalized) or has_crash_loop_troubleshooting_intent(normalized):
        boosts["support"] = max(boosts.get("support", 1.0), 1.45)
        boosts["validation_and_troubleshooting"] = max(
            boosts.get("validation_and_troubleshooting", 1.0),
            1.22,
        )
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.12)
        penalties["workloads_apis"] = min(penalties.get("workloads_apis", 1.0), 0.58)
        penalties["monitoring_apis"] = min(penalties.get("monitoring_apis", 1.0), 0.74)
        penalties["schedule_and_quota_apis"] = min(
            penalties.get("schedule_and_quota_apis", 1.0),
            0.76,
        )
        penalties["storage_apis"] = min(penalties.get("storage_apis", 1.0), 0.78)

    if has_crash_loop_troubleshooting_intent(normalized):
        boosts["support"] = max(boosts.get("support", 1.0), 1.58)
        boosts["validation_and_troubleshooting"] = max(
            boosts.get("validation_and_troubleshooting", 1.0),
            1.26,
        )
        boosts["building_applications"] = max(
            boosts.get("building_applications", 1.0),
            1.14,
        )
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.12)
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.74,
        )
        penalties["monitoring_apis"] = min(
            penalties.get("monitoring_apis", 1.0),
            0.52,
        )
        penalties["network_apis"] = min(
            penalties.get("network_apis", 1.0),
            0.58,
        )
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.66,
        )
        penalties["specialized_hardware_and_driver_enablement"] = min(
            penalties.get("specialized_hardware_and_driver_enablement", 1.0),
            0.72,
        )
        penalties["hosted_control_planes"] = min(
            penalties.get("hosted_control_planes", 1.0),
            0.62,
        )

    if has_pod_lifecycle_concept_intent(normalized):
        boosts["architecture"] = max(boosts.get("architecture", 1.0), 1.52)
        boosts["nodes"] = max(boosts.get("nodes", 1.0), 1.24)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.18)
        boosts["building_applications"] = max(
            boosts.get("building_applications", 1.0),
            1.12,
        )
        penalties["workloads_apis"] = min(penalties.get("workloads_apis", 1.0), 0.54)
        penalties["security_and_compliance"] = min(
            penalties.get("security_and_compliance", 1.0),
            0.64,
        )
        penalties["installation_overview"] = min(
            penalties.get("installation_overview", 1.0),
            0.58,
        )
