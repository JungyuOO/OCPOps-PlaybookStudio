from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan


def test_postinstall_cluster_status_query_does_not_expand_to_node_troubleshooting_subqueries() -> None:
    plan = build_retrieval_plan(
        "OpenShift 설치 후 클러스터 Operator와 노드 상태를 확인하는 기본 절차는 뭐야?",
        context=SessionContext(),
        candidate_k=10,
    )

    assert plan.decomposed_queries == [
        "OpenShift 설치 후 클러스터 Operator와 노드 상태를 확인하는 기본 절차는 뭐야?"
    ]
    assert not any("journalctl" in query.lower() for query in plan.rewritten_queries)
    assert not any("node-logs" in query.lower() for query in plan.rewritten_queries)
