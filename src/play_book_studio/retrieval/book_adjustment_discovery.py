from __future__ import annotations

# 개념 설명/문서 위치 찾기처럼 "어떤 문서군을 우선 볼지"를 정하는 조정 규칙 모음이다.

from .book_adjustment_discovery_concepts import apply_concept_discovery_adjustments
from .book_adjustment_discovery_locator import apply_locator_discovery_adjustments
from .book_adjustment_discovery_overview import apply_overview_discovery_adjustments


def apply_discovery_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    apply_overview_discovery_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_locator_discovery_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_concept_discovery_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
