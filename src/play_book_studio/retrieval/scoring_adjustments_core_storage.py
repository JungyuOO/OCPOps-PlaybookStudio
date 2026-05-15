from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def _hit_text(hit: RetrievalHit) -> str:
    return "\n".join(
        (
            hit.book_slug,
            hit.chapter,
            hit.section,
            hit.heading_title,
            hit.text,
            " ".join(hit.section_path),
            " ".join(hit.toc_path),
            " ".join(hit.cli_commands),
            " ".join(hit.k8s_objects),
        )
    ).lower()


def _query_has_vsphere_storage(query: str) -> bool:
    lowered = (query or "").lower()
    return any(token in lowered for token in ("vsphere", "vmware")) and (
        any(token in lowered for token in ("pvc", "pv", "volume", "storage", "provision"))
        or any(token in query for token in ("볼륨", "스토리지", "프로비저닝"))
    )


def _query_has_dynamic_provisioning(query: str) -> bool:
    lowered = (query or "").lower()
    return "dynamic" in lowered or "동적" in query


def _query_has_static_provisioning(query: str) -> bool:
    lowered = (query or "").lower()
    return "static" in lowered or "정적" in query or "연결" in query


def apply_storage_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    query = signals.query
    if not _query_has_vsphere_storage(query):
        return

    text = _hit_text(hit)
    if "azure file" in text or "azure disk" in text:
        hit.fused_score *= 0.34
        hit.component_scores["vsphere_storage_cloud_mismatch_penalty"] = 0.34
        return

    if "vsphere" in text or "vmware" in text:
        hit.fused_score *= 2.2
        hit.component_scores["vsphere_storage_match_boost"] = 2.2

    if hit.book_slug == "storage":
        hit.fused_score *= 1.28
        hit.component_scores["vsphere_storage_book_boost"] = 1.28

    if any(token in text for token in ("pvc.yaml", "pv1.yaml", "pvc1.yaml", "oc create -f")):
        hit.fused_score *= 1.55
        hit.component_scores["vsphere_storage_command_file_boost"] = 1.55

    if _query_has_dynamic_provisioning(query):
        if any(token in text for token in ("동적으로 프로비저닝", "dynamic provisioning", "thin-csi", "thin storageclass", "pvc.yaml")):
            hit.fused_score *= 1.65
            hit.component_scores["vsphere_dynamic_provisioning_boost"] = 1.65
        if any(token in text for token in ("정적으로 프로비저닝", "static provisioning", "pv1.yaml", "pvc1.yaml")):
            hit.fused_score *= 0.72
            hit.component_scores["vsphere_dynamic_static_mismatch_penalty"] = 0.72

    if _query_has_static_provisioning(query):
        if any(token in text for token in ("정적으로 프로비저닝", "static provisioning", "vmdk", "pv1.yaml", "pvc1.yaml")):
            hit.fused_score *= 1.72
            hit.component_scores["vsphere_static_provisioning_boost"] = 1.72
        if any(token in text for token in ("동적으로 프로비저닝", "dynamic provisioning", "thin-csi", "pvc.yaml")):
            hit.fused_score *= 0.76
            hit.component_scores["vsphere_static_dynamic_mismatch_penalty"] = 0.76
