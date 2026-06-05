from __future__ import annotations

from pathlib import Path

from play_book_studio.answering.lightspeed_provider import (
    LightspeedChatContext,
    build_lightspeed_headers,
    build_lightspeed_payload,
    lightspeed_enabled,
    query_lightspeed,
)
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

    assert payload["query"] == "왜 pod가 Pending이야?"
    assert payload["conversation_id"] == "conv-1"
    assert payload["attachments"][0]["content_type"] == "application/yaml"
    assert payload["pbs_context"]["library_scope"] == "customer:koscom"
    assert payload["pbs_context"]["cluster_context"] == {"namespace": "demo"}
    assert payload["pbs_context"]["recent_events"] == [{"event_type": "apply", "status": "failed"}]


def test_build_lightspeed_headers_adds_bearer_token(tmp_path: Path) -> None:
    headers = build_lightspeed_headers(Settings(root_dir=tmp_path, ols_auth_token="secret-token"))

    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Content-Type"] == "application/json"


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
