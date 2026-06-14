from __future__ import annotations

from .domain_lexicon import query_matches_domain, query_matches_dynamic_variant, query_matches_static_variant
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
        or query_matches_domain(query or "", "storage")
    )


def _query_has_dynamic_provisioning(query: str) -> bool:
    return query_matches_dynamic_variant(query or "", "storage")


def _query_has_static_provisioning(query: str) -> bool:
    return query_matches_static_variant(query or "", "storage")


def apply_storage_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    query = signals.query
    if not query_matches_domain(query or "", "storage"):
        return

    text = _hit_text(hit)
    has_vsphere_storage = _query_has_vsphere_storage(query)
    if has_vsphere_storage and ("azure file" in text or "azure disk" in text):
        hit.fused_score *= 0.34
        hit.component_scores["vsphere_storage_cloud_mismatch_penalty"] = 0.34
        return

    if has_vsphere_storage and ("vsphere" in text or "vmware" in text):
        hit.fused_score *= 2.2
        hit.component_scores["vsphere_storage_match_boost"] = 2.2

    if hit.book_slug == "storage":
        hit.fused_score *= 1.28
        hit.component_scores["storage_book_boost"] = 1.28

    if any(token in text for token in ("pvc.yaml", "pv1.yaml", "pvc1.yaml", "oc create -f")):
        hit.fused_score *= 1.55
        hit.component_scores["storage_command_file_boost"] = 1.55

    if _query_has_dynamic_provisioning(query):
        if any(token in text for token in ("동적 프로비저닝", "dynamic provisioning", "thin-csi", "thin storageclass", "pvc.yaml")):
            hit.fused_score *= 1.65
            key = "vsphere_dynamic_provisioning_boost" if has_vsphere_storage else "storage_dynamic_provisioning_boost"
            hit.component_scores[key] = 1.65
        if any(token in text for token in ("정적 프로비저닝", "정적으로 프로비저닝", "static provisioning", "pv1.yaml", "pvc1.yaml")):
            hit.fused_score *= 0.72
            hit.component_scores["storage_dynamic_static_mismatch_penalty"] = 0.72

    if _query_has_static_provisioning(query):
        if any(
            token in text
            for token in (
                "정적 프로비저닝",
                "정적으로 프로비저닝",
                "static provisioning",
                "persistentvolume",
                "persistentvolumeclaim",
                "pv1.yaml",
                "pvc1.yaml",
            )
        ):
            hit.fused_score *= 1.72
            key = "vsphere_static_provisioning_boost" if has_vsphere_storage else "storage_static_provisioning_boost"
            hit.component_scores[key] = 1.72
        if any(token in text for token in ("동적 프로비저닝", "dynamic provisioning", "thin-csi", "pvc.yaml")):
            hit.fused_score *= 0.76
            key = "vsphere_static_dynamic_mismatch_penalty" if has_vsphere_storage else "storage_static_dynamic_mismatch_penalty"
            hit.component_scores[key] = 0.76
