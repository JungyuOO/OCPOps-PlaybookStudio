from __future__ import annotations

from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.retriever import ChatRetriever


def _hit(chunk_id):
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug="nodes",
        chapter="",
        section="",
        anchor="",
        source_url="",
        viewer_path="",
        text="",
        source="bm25",
        raw_score=1.0,
    )


class _FakeBM25:
    def search(self, query, top_k=10):
        return [_hit("a"), _hit("b")]


def test_retrieve_uses_hybrid_search_without_fanout():
    retriever = ChatRetriever.__new__(ChatRetriever)
    retriever.bm25_index = _FakeBM25()
    retriever.vector_retriever = None
    retriever.reranker = None
    retriever.settings = type("Settings", (), {"database_url": ""})()

    result = retriever.retrieve("노드 상태", top_k=8)

    assert [hit.chunk_id for hit in result.hits] == ["a", "b"]
    assert result.trace["retrieval_query_count"] == 1
    assert result.trace["bm25_count"] == 2
