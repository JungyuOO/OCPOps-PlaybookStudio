# 운영/트러블슈팅 질의의 점수 조정 orchestrator.
from __future__ import annotations

from .models import RetrievalHit
from .scoring_adjustments_runtime_access import apply_access_adjustments
from .scoring_adjustments_runtime_lifecycle import apply_project_lifecycle_adjustments
from .scoring_adjustments_runtime_node import apply_node_adjustments
from .scoring_adjustments_runtime_pod import apply_pod_troubleshooting_adjustments
from .scoring_adjustments_runtime_pod_lifecycle import apply_pod_lifecycle_adjustments
from .scoring_signals import ScoreSignals


def apply_runtime_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    is_intake_doc: bool,
) -> None:
    lowered_text = hit.text.lower()
    lowered_section = hit.section.lower()

    apply_project_lifecycle_adjustments(
        hit,
        signals=signals,
        lowered_text=lowered_text,
        lowered_section=lowered_section,
    )
    apply_node_adjustments(
        hit,
        signals=signals,
        lowered_text=lowered_text,
    )
    apply_pod_troubleshooting_adjustments(
        hit,
        signals=signals,
        lowered_text=lowered_text,
        lowered_section=lowered_section,
    )
    apply_pod_lifecycle_adjustments(
        hit,
        signals=signals,
        is_intake_doc=is_intake_doc,
        lowered_text=lowered_text,
        lowered_section=lowered_section,
    )
    apply_access_adjustments(
        hit,
        signals=signals,
        lowered_text=lowered_text,
    )

    hit.raw_score = hit.fused_score
