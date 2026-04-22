from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_node_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    lowered_text: str,
) -> None:
    if signals.node_drain_intent:
        if hit.book_slug in {"nodes", "support"}:
            hit.fused_score *= 1.16
        if "oc adm drain" in lowered_text:
            hit.fused_score *= 1.28
        if "ignore-daemonsets" in lowered_text or "delete-emptydir-data" in lowered_text:
            hit.fused_score *= 1.08
        if hit.book_slug in {"updating_clusters", "installation_overview"}:
            hit.fused_score *= 0.54
        if "kubectl drain" in lowered_text and "oc adm drain" not in lowered_text:
            hit.fused_score *= 0.76
        if "cordon" in lowered_text and "drain" not in lowered_text:
            hit.fused_score *= 0.84

    if signals.cluster_node_usage_intent:
        if hit.book_slug in {"support", "nodes"}:
            hit.fused_score *= 1.14
        if "oc adm top nodes" in lowered_text:
            hit.fused_score *= 1.3
        if "oc adm top node" in lowered_text:
            hit.fused_score *= 1.08
        if "oc top pods" in lowered_text or "kubectl top pods" in lowered_text:
            hit.fused_score *= 0.72
