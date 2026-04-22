from __future__ import annotations

# 문서 위치 찾기, 업데이트, 백업/복구 계열의 문서군 우선순위를 조정한다.

from .intents import (
    ETCD_RE,
    has_backup_restore_intent,
    has_doc_locator_intent,
    has_hosted_control_plane_signal,
    has_update_doc_locator_intent,
)


def apply_locator_discovery_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    combined = f"{normalized} {context_text}".strip()
    lowered_combined = combined.lower()
    has_etcd_signal = bool(ETCD_RE.search(normalized) or ETCD_RE.search(context_text))
    backup_signal = bool("백업" in combined or "backup" in lowered_combined)
    restore_signal = bool(
        "복원" in combined
        or "복구" in combined
        or "restore" in lowered_combined
        or "recovery" in lowered_combined
    )
    troubleshooting_locator_signal = any(
        token in normalized
        for token in (
            "문제 해결",
            "트러블슈팅",
            "문제가 생기면",
            "문제 생기면",
            "문제가 나면",
            "오류가 나면",
            "장애가 나면",
        )
    )

    if has_doc_locator_intent(normalized):
        boosts["web_console"] = 1.35 if "콘솔" in normalized else boosts.get("web_console", 1.0)
        if troubleshooting_locator_signal:
            boosts["validation_and_troubleshooting"] = max(
                boosts.get("validation_and_troubleshooting", 1.0),
                1.35,
            )
            boosts["support"] = max(boosts.get("support", 1.0), 1.25)
            penalties["release_notes"] = min(penalties.get("release_notes", 1.0), 0.52)
        if "보안" in normalized or "컴플라이언스" in normalized:
            boosts["security_and_compliance"] = 1.35
            penalties["security_apis"] = 0.78
        if "위키" in normalized or "wiki" in lowered_combined:
            penalties["web_console"] = min(penalties.get("web_console", 1.0), 0.44)
        if has_backup_restore_intent(normalized):
            boosts["backup_and_restore"] = 1.55
            boosts["etcd"] = max(boosts.get("etcd", 1.0), 1.1)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.2,
            )
            if not has_hosted_control_plane_signal(normalized):
                penalties["hosted_control_planes"] = min(
                    penalties.get("hosted_control_planes", 1.0),
                    0.35,
                )

    if has_update_doc_locator_intent(normalized):
        boosts["updating_clusters"] = max(boosts.get("updating_clusters", 1.0), 1.72)
        boosts["release_notes"] = max(boosts.get("release_notes", 1.0), 1.38)
        boosts["overview"] = max(boosts.get("overview", 1.0), 1.08)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.34)
        penalties["web_console"] = min(penalties.get("web_console", 1.0), 0.44)
        penalties["building_applications"] = min(
            penalties.get("building_applications", 1.0),
            0.62,
        )
        penalties["validation_and_troubleshooting"] = min(
            penalties.get("validation_and_troubleshooting", 1.0),
            0.74,
        )
        penalties["config_apis"] = min(penalties.get("config_apis", 1.0), 0.42)
        penalties["specialized_hardware_and_driver_enablement"] = min(
            penalties.get("specialized_hardware_and_driver_enablement", 1.0),
            0.48,
        )

    if has_etcd_signal and (has_backup_restore_intent(normalized) or (backup_signal or restore_signal)):
        if backup_signal and not restore_signal:
            boosts["etcd"] = max(boosts.get("etcd", 1.0), 1.22)
            boosts["backup_and_restore"] = max(boosts.get("backup_and_restore", 1.0), 1.08)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                1.85,
            )
            boosts["updating_clusters"] = max(boosts.get("updating_clusters", 1.0), 1.18)
            penalties.pop("etcd", None)
            penalties.pop("backup_and_restore", None)
            if not has_hosted_control_plane_signal(combined):
                penalties["hosted_control_planes"] = min(
                    penalties.get("hosted_control_planes", 1.0),
                    0.28,
                )
        else:
            boosts["etcd"] = max(boosts.get("etcd", 1.0), 1.08)
            boosts["backup_and_restore"] = max(boosts.get("backup_and_restore", 1.0), 1.05)
            boosts["postinstallation_configuration"] = max(
                boosts.get("postinstallation_configuration", 1.0),
                2.15,
            )
            boosts["updating_clusters"] = max(boosts.get("updating_clusters", 1.0), 1.18)
            penalties["etcd"] = min(penalties.get("etcd", 1.0), 0.9)
            if not has_hosted_control_plane_signal(combined):
                penalties["hosted_control_planes"] = min(
                    penalties.get("hosted_control_planes", 1.0),
                    0.28,
                )
                penalties["edge_computing"] = min(
                    penalties.get("edge_computing", 1.0),
                    0.72,
                )
