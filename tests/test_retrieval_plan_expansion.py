from __future__ import annotations

from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever_plan import build_retrieval_plan


class _DriftingSignalClient:
    def generate(self, _messages: list[dict[str, str]], *, max_tokens: int) -> str:
        return """
        {
          "normalized_query": "운영 장애 분석에서 증상과 근거는 어떤 순서로 정리하나요?",
          "classification": {
            "domain": "troubleshooting",
            "book_slug_candidates": ["validation_and_troubleshooting"],
            "platform": "any_platform",
            "ocp_version": "4.20",
            "locale": "ko"
          },
          "search_signals": {
            "objects": [],
            "error_states": [],
            "intent_labels": ["troubleshoot"],
            "answer_shapes": ["troubleshooting_flow"],
            "command_families": [],
            "primary_topics": ["root cause analysis"],
            "cluster_phase": [],
            "execution_target": [],
            "commands": [],
            "secondary_topics": [],
            "components": []
          },
          "confidence": {"domain": 0.95},
          "embedding_queries": [
            "OpenShift troubleshooting methodology symptoms evidence cause resolution",
            "how to document troubleshooting events and root cause analysis"
          ]
        }
        """


class _InstallSignalClient:
    def generate(self, _messages: list[dict[str, str]], *, max_tokens: int) -> str:
        return """
        {
          "normalized_query": "OpenShift 설치 방식과 준비 항목은 어떻게 구분하나요?",
          "classification": {
            "domain": "install",
            "book_slug_candidates": ["installation_overview"],
            "platform": "any_platform",
            "ocp_version": "4.20",
            "locale": "ko"
          },
          "search_signals": {
            "objects": [],
            "error_states": [],
            "intent_labels": ["install", "compare_options"],
            "answer_shapes": ["decision_guide"],
            "command_families": [],
            "primary_topics": ["installation method"],
            "cluster_phase": [],
            "execution_target": [],
            "commands": [],
            "secondary_topics": ["Assisted Installer", "Agent-based Installer", "IPI", "UPI"],
            "components": []
          },
          "confidence": {"domain": 0.95},
          "embedding_queries": [
            "OpenShift installation methods comparison Assisted Installer Agent-based IPI UPI SNO",
            "OpenShift installation prerequisites and requirements by installation type"
          ]
        }
        """


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


def test_study_docs_scope_keeps_user_query_and_skips_official_metadata_filter() -> None:
    plan = build_retrieval_plan(
        "운영 장애 분석에서 증상과 근거는 어떤 순서로 정리하나요?",
        context=SessionContext(preferred_source_scope="study_docs"),
        candidate_k=10,
        llm_client=_DriftingSignalClient(),
    )

    assert plan.retrieval_queries == [plan.rewritten_query]
    assert "운영 장애 분석" in plan.retrieval_queries[0]
    assert plan.metadata_filter == {}


def test_llm_query_expansion_preserves_normalized_query_first() -> None:
    plan = build_retrieval_plan(
        "OpenShift 설치 방식과 준비 항목은 어떻게 구분하나요?",
        context=SessionContext(preferred_source_scope="official_docs"),
        candidate_k=10,
        llm_client=_InstallSignalClient(),
    )

    assert plan.retrieval_queries
    assert plan.retrieval_queries[0].startswith("OpenShift 설치 방식과 준비 항목")
