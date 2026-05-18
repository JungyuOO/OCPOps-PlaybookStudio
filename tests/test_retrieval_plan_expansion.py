from __future__ import annotations

from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan


def test_retrieval_plan_uses_query_signal_expansion_without_decompose_fanout() -> None:
    plan = build_retrieval_plan(
        "PVC가 Peding중인데 뭐 확인해야될까?",
        context=SessionContext(),
        candidate_k=10,
    )

    assert plan.normalized_query
    assert 1 <= len(plan.retrieval_queries) <= 2
    assert plan.decomposed_queries == plan.retrieval_queries
    combined = " ".join(plan.retrieval_queries)
    assert "PVC" in combined or "PersistentVolumeClaim" in combined
    assert "Pending" in combined


def test_retrieval_plan_does_not_expand_simple_node_status_into_logs() -> None:
    plan = build_retrieval_plan(
        "Node 상태는 어떤 명령으로 먼저 확인하나요?",
        context=SessionContext(),
        candidate_k=10,
    )

    combined = " ".join(plan.retrieval_queries)
    assert len(plan.retrieval_queries) <= 2
    assert "journalctl" not in combined
    assert "node-logs" not in combined
