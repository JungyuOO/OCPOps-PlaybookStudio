from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_node_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    lowered_text: str,
) -> None:
    search_text = "\n".join(
        str(part or "").lower()
        for part in (
            lowered_text,
            hit.section,
            hit.heading_title,
            " ".join(hit.cli_commands),
            " ".join(hit.k8s_objects),
        )
    )

    profile = signals.intent_profile
    if (
        profile.target_object == "node"
        and profile.task == "status"
        and profile.intent == "command_lookup"
    ):
        if "oc get nodes" in search_text:
            hit.fused_score *= 1.55
            hit.component_scores["node_status_command_lookup_boost"] = 1.55
        elif "oc describe node" in search_text:
            hit.fused_score *= 1.18
            hit.component_scores["node_status_describe_followup_boost"] = 1.18

        if any(token in search_text for token in ("selector", "선택기", "-l <key>", "label selector")):
            hit.fused_score *= 0.38
            hit.component_scores["node_status_selector_mismatch_penalty"] = 0.38

        if any(
            token in search_text
            for token in (
                "oc ssh",
                "journalctl",
                "systemctl",
                "crio",
                "kubelet",
                "oc adm node-logs",
            )
        ):
            hit.fused_score *= 0.42
            hit.component_scores["node_status_deep_troubleshooting_penalty"] = 0.42

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
