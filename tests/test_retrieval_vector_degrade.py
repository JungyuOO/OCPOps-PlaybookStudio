from __future__ import annotations

from pathlib import Path

from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever

REPO_ROOT = Path(__file__).resolve().parents[1]


class BrokenVectorRetriever:
    def search_with_trace(self, *args, **kwargs):
        raise RuntimeError("Failed to fetch embeddings from http://tei.example/v1")

    def search(self, *args, **kwargs):
        raise RuntimeError("Failed to fetch embeddings from http://tei.example/v1")


def _bm25_rows() -> list[dict]:
    return [
        {
            "chunk_id": "chunk-pay",
            "book_slug": "uploaded-documents",
            "section": "결제 API 장애 점검 기준",
            "anchor": "pay",
            "text": "오리은행 결제 API Route 503 장애는 ori-pay-prod namespace의 pay-api Route를 확인한다.",
            "source_scope": "user_upload",
            "visibility": "workspace_shared",
        },
        {
            "chunk_id": "chunk-etc",
            "book_slug": "networking",
            "section": "Route 구성",
            "anchor": "route",
            "text": "Route는 외부 트래픽을 Service로 전달한다.",
            "source_scope": "official_docs",
            "visibility": "workspace_shared",
        },
    ]


def test_vector_failure_degrades_to_bm25_only(monkeypatch):
    monkeypatch.setenv("GRAPH_ENABLED", "false")
    monkeypatch.setenv("ENTITY_GRAPH_ENABLED", "false")
    monkeypatch.setenv("QUERY_SIGNAL_LLM_ENABLED", "false")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    settings = load_settings(REPO_ROOT)

    retriever = ChatRetriever(
        settings,
        BM25Index.from_rows(_bm25_rows()),
        vector_retriever=BrokenVectorRetriever(),
        reranker=None,
    )

    result = retriever.retrieve(
        "오리은행 결제 API Route가 503이면 어떤 namespace부터 확인해?",
        context=SessionContext(),
        top_k=3,
        candidate_k=5,
        use_vector=True,
    )

    assert result.hits, "BM25 hits must survive a vector outage"
    assert {hit.chunk_id for hit in result.hits} >= {"chunk-pay"}
    assert any("vector search degraded" in warning for warning in result.trace["warnings"])
    assert result.trace["vector_runtime"].get("status") == "failed"
    assert "Failed to fetch embeddings" in str(result.trace["vector_runtime"].get("error"))
