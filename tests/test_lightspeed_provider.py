from __future__ import annotations

from pathlib import Path

from play_book_studio.answering.lightspeed_provider import (
    LightspeedChatContext,
    build_lightspeed_citations,
    build_lightspeed_headers,
    build_lightspeed_payload,
    build_pbs_rag_context,
    is_private_pbs_citation,
    lightspeed_enabled,
    query_lightspeed,
)
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.config.settings import Settings


def test_lightspeed_enabled_uses_chat_provider(tmp_path: Path) -> None:
    assert lightspeed_enabled(Settings(root_dir=tmp_path, chat_provider="lightspeed")) is True
    assert lightspeed_enabled(Settings(root_dir=tmp_path, chat_provider="internal")) is False


def test_build_lightspeed_payload_includes_pbs_context_and_attachments() -> None:
    payload = build_lightspeed_payload(
        "왜 pod가 Pending이야?",
        LightspeedChatContext(
            conversation_id="conv-1",
            library_scope="customer:koscom",
            cluster_context={"namespace": "demo"},
            recent_events=[{"event_type": "apply", "status": "failed"}],
            attachments=[{"attachment_type": "configuration", "content_type": "application/yaml", "content": "kind: Pod"}],
        ),
    )

    assert payload["query"].startswith("왜 pod가 Pending이야?")
    assert "PBS supplemental context follows" in payload["query"]
    assert "customer:koscom" in payload["query"]
    assert "kind: Pod" in payload["query"]
    assert payload["conversation_id"] == "conv-1"
    assert "attachments" not in payload
    assert "pbs_context" not in payload


def test_build_pbs_rag_context_keeps_only_private_uploaded_context() -> None:
    official = Citation(
        index=1,
        chunk_id="official-1",
        book_slug="openshift-docs",
        section="PVC",
        anchor="pvc",
        source_url="https://docs.openshift.com/container-platform/latest/storage/pvc.html",
        viewer_path="/docs/openshift/storage/pvc",
        excerpt="Official OpenShift PVC guidance",
        source_collection="core",
    )
    uploaded = Citation(
        index=2,
        chunk_id="upload-1",
        book_slug="uploaded-documents",
        section="KOSCOM PVC",
        anchor="koscom-pvc",
        source_url="internal://customer/koscom/pvc-pending",
        viewer_path="/uploads/koscom/pvc-pending.md",
        excerpt="KOSCOM cluster uses a custom storage class named managed-nfs-storage.",
        source_collection="uploaded",
        cli_commands=("oc describe pvc <pvc-name> -n <namespace>",),
        k8s_objects=("PersistentVolumeClaim",),
    )
    result = AnswerResult(
        query="PVC Pending",
        mode="rag",
        answer="Use the customer storage class note.",
        rewritten_query="PVC Pending",
        citations=[official, uploaded],
        retrieval_trace={"retriever": "pbs"},
    )

    context = build_pbs_rag_context(result)

    assert is_private_pbs_citation(uploaded) is True
    assert is_private_pbs_citation(official) is False
    assert context["mode"] == "lightspeed-rag-with-pbs-private-context"
    assert context["private_context_available"] is True
    assert [item["index"] for item in context["citations"]] == [2]
    assert "OpenShift Lightspeed's built-in knowledge" in context["instruction"]


def test_build_lightspeed_headers_adds_bearer_token(tmp_path: Path) -> None:
    headers = build_lightspeed_headers(Settings(root_dir=tmp_path, ols_auth_token="secret-token"))

    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Content-Type"] == "application/json"


def test_build_lightspeed_citations_maps_referenced_documents() -> None:
    citations = build_lightspeed_citations(
        {
            "referenced_documents": [
                {
                    "title": "Pods",
                    "section": "Viewing pods",
                    "url": "https://docs.openshift.com/container-platform/latest/nodes/pods.html",
                    "excerpt": "Use oc get pods to list pods.",
                }
            ]
        }
    )

    assert len(citations) == 1
    assert citations[0].book_slug == "openshift-lightspeed"
    assert citations[0].source_collection == "openshift_lightspeed"
    assert citations[0].source_url == "https://docs.openshift.com/container-platform/latest/nodes/pods.html"
    assert citations[0].viewer_path == "https://docs.openshift.com/container-platform/latest/nodes/pods.html"
    assert citations[0].section == "Viewing pods"


def test_build_lightspeed_citations_maps_ols_doc_url_shape() -> None:
    citations = build_lightspeed_citations(
        {
            "referenced_documents": [
                {
                    "doc_title": "Pod [v1]",
                    "doc_url": "https://docs.openshift.com/container-platform/4.20/rest_api/workloads_apis/pod-v1.html",
                }
            ]
        }
    )

    assert len(citations) == 1
    assert citations[0].section == "Pod [v1]"
    assert citations[0].source_url == "https://docs.openshift.com/container-platform/4.20/rest_api/workloads_apis/pod-v1.html"
    assert citations[0].viewer_path == "https://docs.openshift.com/container-platform/4.20/rest_api/workloads_apis/pod-v1.html"


def test_query_lightspeed_returns_configuration_error_without_endpoint(tmp_path: Path) -> None:
    result = query_lightspeed(Settings(root_dir=tmp_path, chat_provider="lightspeed"), "hello")

    assert result.response_kind == "configuration_error"
    assert "not configured" in result.answer
    assert result.retrieval_trace["provider"] == "lightspeed"
    assert result.retrieval_trace["configured"] is False


def test_query_lightspeed_normalizes_transport_response(tmp_path: Path) -> None:
    calls: list[tuple[str, dict, dict, float]] = []

    def fake_transport(url: str, payload: dict, headers: dict, timeout_seconds: float) -> dict:
        calls.append((url, payload, headers, timeout_seconds))
        return {"response": "PVC Pending은 StorageClass와 provisioner event를 확인하세요.", "conversation_id": "conv-2"}

    settings = Settings(
        root_dir=tmp_path,
        chat_provider="lightspeed",
        ols_base_url="https://ols.example.test",
        ols_auth_token="secret-token",
        ols_timeout_seconds=3,
    )

    result = query_lightspeed(settings, "PVC Pending 원인?", transport=fake_transport)

    assert result.response_kind == "lightspeed"
    assert result.answer == "PVC Pending은 StorageClass와 provisioner event를 확인하세요."
    assert result.retrieval_trace["endpoint"] == "https://ols.example.test/v1/query"
    assert result.retrieval_trace["conversation_id"] == "conv-2"
    assert calls == [
        (
            "https://ols.example.test/v1/query",
            {"query": "PVC Pending 원인?"},
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer secret-token",
            },
            3.0,
        )
    ]


def test_query_lightspeed_preserves_referenced_documents_as_citations(tmp_path: Path) -> None:
    def fake_transport(url: str, payload: dict, headers: dict, timeout_seconds: float) -> dict:
        return {
            "response": "Use oc get pods to list pods.",
            "conversation_id": "conv-docs",
            "referenced_documents": [
                {
                    "title": "Pods",
                    "section": "Viewing pods",
                    "url": "https://docs.openshift.com/container-platform/latest/nodes/pods.html",
                    "excerpt": "Use oc get pods to list pods.",
                }
            ],
        }

    result = query_lightspeed(
        Settings(
            root_dir=tmp_path,
            chat_provider="lightspeed",
            ols_base_url="https://ols.example.test",
        ),
        "how do I list pods?",
        transport=fake_transport,
    )

    assert result.response_kind == "lightspeed"
    assert result.answer == "Use oc get pods to list pods."
    assert result.retrieval_trace["referenced_documents"] == 1
    assert result.citations[0].source_collection == "openshift_lightspeed"
    assert result.citations[0].source_url == "https://docs.openshift.com/container-platform/latest/nodes/pods.html"
    assert result.cited_indices == [1]
