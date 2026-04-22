from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def apply_access_adjustments(
    hit: RetrievalHit,
    *,
    signals: ScoreSignals,
    lowered_text: str,
) -> None:
    if signals.oc_login_intent:
        if hit.book_slug == "cli_tools":
            hit.fused_score *= 1.2
        if "oc login" in lowered_text:
            hit.fused_score *= 1.28

    if signals.rbac_intent:
        if (
            "rbac" in lowered_text
            or "rolebinding" in lowered_text
            or "역할 바인딩" in hit.text
            or "로컬 바인딩" in hit.text
        ):
            hit.fused_score *= 1.06
        if signals.project_scoped_rbac and (
            "프로젝트" in hit.text
            or "네임스페이스" in hit.text
            or "project" in lowered_text
            or "namespace" in lowered_text
        ):
            hit.fused_score *= 1.05
        if signals.rbac_assignment and (
            "oc adm policy" in lowered_text
            or "add-role-to-user" in lowered_text
            or "rolebinding" in lowered_text
        ):
            hit.fused_score *= 1.08
