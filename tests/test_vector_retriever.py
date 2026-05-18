from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.retrieval.vector import VectorRetriever


class _EmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["PVC Pending oc_get"]
        return [[0.1, 0.2, 0.3]]


class _Response:
    ok = True
    text = "ok"

    def json(self) -> dict[str, Any]:
        return {
            "result": [
                {
                    "score": 0.88,
                    "payload": {
                        "chunk_id": "pvc-pending",
                        "book_slug": "storage",
                        "text": "PVC Pending troubleshooting",
                    },
                }
            ]
        }


def test_vector_retriever_sends_qdrant_metadata_filter(monkeypatch) -> None:
    settings = Settings(
        root_dir=Path("."),
        embedding_base_url="http://embedding.test/v1",
        qdrant_url="http://qdrant.test",
        qdrant_collection="ocp_docs",
    )
    retriever = VectorRetriever(settings)
    retriever.embedding_client = _EmbeddingClient()  # type: ignore[assignment]
    requests: list[dict[str, Any]] = []

    def fake_post(url: str, *, json: dict[str, Any], timeout: float) -> _Response:
        requests.append({"url": url, "json": json, "timeout": timeout})
        return _Response()

    query_filter = {
        "must": [
            {"key": "source.enabled_for_chat", "match": {"value": True}},
            {"key": "classification.domain", "match": {"value": "storage"}},
        ]
    }
    monkeypatch.setattr("play_book_studio.retrieval.vector.requests.post", fake_post)

    hits, runtime = retriever.search_with_trace(
        "PVC Pending oc_get",
        top_k=3,
        query_filter=query_filter,
    )

    assert hits[0].chunk_id == "pvc-pending"
    assert requests[0]["json"]["filter"] == query_filter
    assert requests[0]["json"]["limit"] == 3
    assert runtime["metadata_filter_applied"] is True
    assert runtime["metadata_filter"] == query_filter
    assert runtime["embedding_ms"] >= 0
    assert runtime["qdrant_ms"] >= 0
    assert runtime["hydrate_ms"] >= 0
    assert runtime["request_timeout_seconds"] == settings.request_timeout_seconds
