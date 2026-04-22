from __future__ import annotations

# 운영 절차/트러블슈팅/RBAC처럼 "어떤 실행 문서군을 우선 볼지"를 정하는 조정 규칙 모음이다.

from .book_adjustment_lifecycle import apply_project_lifecycle_adjustments
from .book_adjustment_node_ops import apply_node_and_deployment_adjustments
from .book_adjustment_security import apply_security_adjustments
from .book_adjustment_troubleshooting import apply_troubleshooting_adjustments
from .corpus_scope import detect_unsupported_product


def apply_operation_adjustments(
    normalized: str,
    *,
    context_text: str,
    boosts: dict[str, float],
    penalties: dict[str, float],
) -> None:
    apply_project_lifecycle_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_node_and_deployment_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_troubleshooting_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    apply_security_adjustments(
        normalized,
        context_text=context_text,
        boosts=boosts,
        penalties=penalties,
    )
    if detect_unsupported_product(normalized):
        penalties["registry"] = min(penalties.get("registry", 1.0), 0.5)
        penalties["images"] = min(penalties.get("images", 1.0), 0.5)
        penalties["installation_overview"] = min(penalties.get("installation_overview", 1.0), 0.55)
