from __future__ import annotations

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.answering.route_classifier import (
    build_route_probe,
    classify_route,
    should_include_private_context,
)


def _result_with_uploaded_citation() -> AnswerResult:
    return AnswerResult(
        query="PVC Pending",
        mode="ops",
        answer="",
        rewritten_query="PVC Pending",
        citations=[
            Citation(
                index=1,
                chunk_id="upload-1",
                book_slug="uploaded-documents",
                section="KOSCOM PVC Pending",
                anchor="koscom-pvc",
                source_url="internal://customer/koscom/pvc-pending",
                viewer_path="/uploads/koscom/pvc-pending.md",
                excerpt="KOSCOM PVC Pending cases use managed-nfs-storage and require provisioner checks.",
                source_collection="uploaded",
                cli_commands=("oc describe pvc <pvc-name> -n <namespace>",),
                k8s_objects=("PersistentVolumeClaim",),
            )
        ],
    )


def test_private_probe_can_route_without_explicit_private_doc_words() -> None:
    probe = build_route_probe(_result_with_uploaded_citation())

    decision = classify_route("PVC Pending이면 뭘 먼저 봐야 해?", probe=probe)

    assert decision.primary_route == "private_docs"
    assert decision.private_docs_relevance == "strong"
    assert "private_docs" in decision.context_lanes
    assert should_include_private_context(decision, probe) is True


def test_llm_classifier_can_keep_general_command_help_on_official_docs() -> None:
    class FakeClient:
        def generate(self, messages, trace_callback=None, *, max_tokens=None):  # noqa: ANN001
            return """
            {
              "primary_route": "official_docs",
              "context_lanes": ["official_docs"],
              "private_docs_relevance": "none",
              "live_cluster_relevance": "none",
              "terminal_event_relevance": "none",
              "risk_level": "none",
              "confidence": 0.91,
              "reason": "general OpenShift command help"
            }
            """

    probe = build_route_probe(
        AnswerResult(
            query="pod list command",
            mode="ops",
            answer="",
            rewritten_query="pod list command",
            citations=[],
        )
    )

    decision = classify_route("pod 리스트 확인하는 명령어가 뭐야?", probe=probe, llm_client=FakeClient())

    assert decision.classifier == "llm"
    assert decision.primary_route == "official_docs"
    assert decision.context_lanes == ["official_docs"]


def test_mutating_cluster_request_routes_to_action_request() -> None:
    probe = build_route_probe(
        AnswerResult(
            query="apply yaml",
            mode="ops",
            answer="",
            rewritten_query="apply yaml",
            citations=[],
        )
    )

    decision = classify_route("이 deployment yaml을 oc apply로 반영해줘", probe=probe)

    assert decision.primary_route == "action_request"
    assert decision.risk_level == "write"
    assert "live_cluster" in decision.context_lanes
    assert "yaml_diff" in decision.context_lanes
