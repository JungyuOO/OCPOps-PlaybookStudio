from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.retrieval.vector import VectorRetriever, _pgvector_filter_sql, hit_from_payload


class _EmbeddingClient:
    def embed_texts(self, texts) -> list[list[float]]:
        assert list(texts) == ["PVC Pending oc_get"]
        return [[0.1, 0.2, 0.3]]


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_vector_retriever_uses_pgvector_filter(monkeypatch) -> None:
    settings = Settings(
        root_dir=Path("."),
        database_url="postgresql://example",
        embedding_base_url="http://embedding.test/v1",
    )
    retriever = VectorRetriever(settings)
    retriever.embedding_client = _EmbeddingClient()  # type: ignore[assignment]
    seen: dict[str, Any] = {}

    def fake_search_pgvector(connection, *, vector, top_k, query_filter):
        seen["connection"] = connection
        seen["vector"] = vector
        seen["top_k"] = top_k
        seen["query_filter"] = query_filter
        return [
            hit_from_payload(
                {
                    "chunk_id": "pvc-pending",
                    "book_slug": "storage",
                    "text": "PVC Pending troubleshooting",
                },
                source="vector",
                score=0.88,
            )
        ], {"sql_filter_applied": True, "sql_filter_keys": ["source.enabled_for_chat", "classification.domain"]}

    query_filter = {
        "must": [
            {"key": "source.enabled_for_chat", "match": {"value": True}},
            {"key": "classification.domain", "match": {"value": "storage"}},
        ]
    }
    monkeypatch.setattr("psycopg.connect", lambda _url: _Connection())
    monkeypatch.setattr(retriever, "_search_pgvector", fake_search_pgvector)

    hits, runtime = retriever.search_with_trace(
        "PVC Pending oc_get",
        top_k=3,
        query_filter=query_filter,
    )

    assert hits[0].chunk_id == "pvc-pending"
    assert seen["vector"] == [0.1, 0.2, 0.3]
    assert seen["top_k"] == 3
    assert seen["query_filter"] == query_filter
    assert runtime["backend"] == "pgvector"
    assert runtime["metadata_filter_applied"] is True
    assert runtime["metadata_filter"] == query_filter
    assert runtime["embedding_ms"] >= 0
    assert runtime["vector_db_ms"] >= 0
    assert runtime["hydrate_ms"] >= 0
    assert runtime["request_timeout_seconds"] == settings.request_timeout_seconds


def test_pgvector_filter_sql_translates_scope_filters() -> None:
    sql, params, runtime = _pgvector_filter_sql(
        {
            "must": [
                {"key": "document_source_id", "match": {"value": "11111111-1111-1111-1111-111111111111"}},
                {"key": "repository_id", "match": {"value": "22222222-2222-2222-2222-222222222222"}},
                {"key": "source_scope", "match": {"value": "user_upload"}},
            ]
        }
    )

    assert "ds.id = %s::uuid" in sql
    assert "c.repository_id = %s::uuid" in sql
    assert "c.source_scope = %s" in sql
    assert params == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "user_upload",
    ]
    assert runtime["sql_filter_applied"] is True
