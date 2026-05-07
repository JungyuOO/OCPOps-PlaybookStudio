from __future__ import annotations


def is_cross_document_follow_query(query: str) -> bool:
    normalized = str(query or "").lower()
    if not normalized:
        return False
    has_document_target = any(
        token in normalized
        for token in ("문서", "docs", "documentation", "playbook", "플레이북", "가이드")
    )
    mentions_monitoring = any(token in normalized for token in ("monitoring", "모니터링"))
    mentions_operator = any(token in normalized for token in ("operator", "operators", "오퍼레이터"))
    follow_signal = any(
        token in normalized
        for token in ("같이", "함께", "연계", "연결", "따라", "어떻게", "together", "combine", "follow")
    )
    incident_signal = any(
        token in normalized
        for token in ("장애", "문제", "이슈", "incident", "failure", "trouble")
    )
    return has_document_target and mentions_monitoring and mentions_operator and (follow_signal or incident_signal)


def is_document_sequence_query(query: str) -> bool:
    normalized = str(query or "").lower()
    if not normalized:
        return False
    if is_cross_document_follow_query(normalized):
        return True
    has_document_target = any(
        token in normalized
        for token in ("문서", "docs", "documentation", "playbook", "플레이북", "가이드")
    )
    has_sequence_signal = any(
        token in normalized
        for token in ("순서", "순서대로", "먼저 읽", "읽어야", "먼저 봐", "roadmap", "sequence", "order")
    )
    return has_document_target and has_sequence_signal


__all__ = ["is_cross_document_follow_query", "is_document_sequence_query"]
