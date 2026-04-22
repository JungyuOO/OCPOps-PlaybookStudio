from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_project_lifecycle_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    lowered_text: str,
    lowered_section: str,
) -> None:
    if signals.project_terminating_intent:
        if hit.book_slug == "building_applications" and "프로젝트 삭제" in hit.section:
            hit.fused_score *= 1.05
        if hit.book_slug == "support" and "종료 중" in hit.text:
            hit.fused_score *= 1.2
        if "oc adm prune" in lowered_text or "prune" in lowered_section:
            hit.fused_score *= 0.42

    if signals.project_finalizer_intent:
        if hit.book_slug == "support":
            hit.fused_score *= 1.26
        if (
            "terminating" in lowered_text
            or "error resolving resource" in lowered_text
            or "custom resource" in lowered_text
            or "crd" in lowered_text
        ):
            hit.fused_score *= 1.24
        if "oc adm prune" in lowered_text or hit.book_slug == "cli_tools":
            hit.fused_score *= 0.38
