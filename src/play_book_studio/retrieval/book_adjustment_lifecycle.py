from __future__ import annotations

# 프로젝트 종료/finalizer/etcd 복구처럼 lifecycle 성격의 문서군 조정 규칙을 모은다.

from .intents import (
    ETCD_RE,
    has_backup_restore_intent,
    has_hosted_control_plane_signal,
    has_project_finalizer_intent,
    has_project_terminating_intent,
)


def apply_project_lifecycle_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    if has_project_terminating_intent(normalized):
        boosts["building_applications"] = max(boosts.get("building_applications", 1.0), 1.16)
        boosts["support"] = max(boosts.get("support", 1.0), 1.32)
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.6)

    if has_project_finalizer_intent(normalized):
        boosts["support"] = max(boosts.get("support", 1.0), 1.52)
        penalties["building_applications"] = min(
            penalties.get("building_applications", 1.0),
            0.88,
        )
        penalties["cli_tools"] = min(penalties.get("cli_tools", 1.0), 0.45)

    if (
        has_backup_restore_intent(normalized)
        and ETCD_RE.search(context_text)
        and not ETCD_RE.search(normalized)
    ):
        boosts["postinstallation_configuration"] = max(
            boosts.get("postinstallation_configuration", 1.0),
            1.6,
        )
        boosts["etcd"] = max(boosts.get("etcd", 1.0), 1.2)
        if not has_hosted_control_plane_signal(normalized):
            penalties["hosted_control_planes"] = min(
                penalties.get("hosted_control_planes", 1.0),
                0.25,
            )
