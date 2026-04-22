from __future__ import annotations

# backup/certificate 계열의 core 점수 규칙.

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_backup_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    lowered_text = hit.text.lower()
    lowered_section = hit.section.lower()
    context_text = signals.context_text

    if signals.certificate_monitor_intent:
        if hit.book_slug == "cli_tools":
            hit.fused_score *= 1.22
        if (
            "monitor-certificates" in lowered_text
            or "oc adm ocp-certificates" in lowered_text
            or "monitor-certificates" in lowered_section
        ):
            hit.fused_score *= 1.4
        if "csr" in lowered_text:
            hit.fused_score *= 0.72
        if hit.book_slug == "security_and_compliance" and "만료" in hit.section:
            hit.fused_score *= 0.82

    if signals.backup_restore_intent:
        if "cluster-backup.sh" in lowered_text:
            hit.fused_score *= 1.26
        if "oc debug --as-root node" in lowered_text or "chroot /host" in lowered_text:
            hit.fused_score *= 1.12
        if "snapshot save" in lowered_text:
            hit.fused_score *= 1.05
        if "cluster-restore.sh" in lowered_text or "restore.sh" in lowered_text:
            hit.fused_score *= 1.18
        if not signals.hosted_signal and "etcd" in context_text and hit.book_slug == "hosted_control_planes":
            hit.fused_score *= 0.24
        if hit.book_slug == "postinstallation_configuration" and (
            "etcd 작업" in hit.chapter or "이전 클러스터 상태로 복원" in hit.section
        ):
            hit.fused_score *= 1.16
        if hit.book_slug == "updating_clusters" and "업데이트 전 etcd 백업" in hit.section:
            hit.fused_score *= 0.84
        if "velero" in lowered_text or "oadp" in lowered_text or "hosted cluster" in lowered_text:
            hit.fused_score *= 0.46 if not signals.hosted_signal else 1.0
