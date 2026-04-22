# 일반 개념/문서 탐색 쿼리의 점수 조정 facade.
from __future__ import annotations

from .models import RetrievalHit
from .scoring_adjustments_core_backup import apply_backup_core_adjustments
from .scoring_adjustments_core_discovery import apply_discovery_core_adjustments
from .scoring_adjustments_core_operator import apply_operator_core_adjustments
from .scoring_signals import ScoreSignals


def apply_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    apply_discovery_core_adjustments(hit, signals=signals)
    apply_operator_core_adjustments(hit, signals=signals)
    apply_backup_core_adjustments(hit, signals=signals)
