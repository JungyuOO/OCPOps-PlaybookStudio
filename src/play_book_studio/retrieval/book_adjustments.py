from __future__ import annotations

# 질문별 문서군 boost/penalty 조정 진입점이다.
# 실제 규칙은 개념/문서탐색 묶음과 운영/트러블슈팅 묶음으로 분리해 관리한다.

from .book_adjustment_discovery import apply_discovery_adjustments
from .book_adjustment_operations import apply_operation_adjustments
from .models import SessionContext
from .text_utils import collapse_spaces as _collapse_spaces


def query_book_adjustments(
    query: str,
    *,
    context: SessionContext | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    normalized = _collapse_spaces(query)
    boosts: dict[str, float] = {}
    penalties: dict[str, float] = {}
    context = context or SessionContext()
    context_text = _collapse_spaces(
        " ".join(
            [
                context.current_topic or "",
                *context.open_entities,
                context.user_goal or "",
                context.unresolved_question or "",
            ]
        )
    )

    apply_discovery_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_operation_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )

    return boosts, penalties
