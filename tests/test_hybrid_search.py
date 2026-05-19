from __future__ import annotations

from play_book_studio.retrieval.hybrid_search import hybrid_search
from play_book_studio.retrieval.models import RetrievalHit


def _hit(chunk_id, *, book_slug="nodes", raw_score=1.0):
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="",
        section="",
        anchor="",
        source_url="",
        viewer_path="",
        text="",
        source="x",
        raw_score=raw_score,
    )


class _FakeBM25:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=10):
        return self._hits[:top_k]


class _FakeVector:
    def __init__(self, hits, *, fail=False):
        self._hits = hits
        self._fail = fail

    def search(self, query, top_k=10, query_filter=None):
        if self._fail:
            raise RuntimeError("vector down")
        return self._hits[:top_k]


def test_hybrid_search_merges_bm25_and_vector_to_top_k():
    result = hybrid_search(
        "노드 상태",
        bm25_index=_FakeBM25([_hit("a"), _hit("b")]),
        vector_retriever=_FakeVector([_hit("b"), _hit("c")]),
        candidate_k=40,
        top_k=8,
    )
    ids = [hit.chunk_id for hit in result.hits]
    assert set(ids) == {"a", "b", "c"}
    assert len(result.hits) <= 8


def test_hybrid_search_falls_back_to_bm25_when_vector_fails():
    result = hybrid_search(
        "노드 상태",
        bm25_index=_FakeBM25([_hit("a")]),
        vector_retriever=_FakeVector([], fail=True),
        candidate_k=40,
        top_k=8,
    )
    assert [hit.chunk_id for hit in result.hits] == ["a"]
    assert result.vector_failed is True


def test_hybrid_search_hydrates_only_final_hits(monkeypatch):
    hydrated_calls = []

    def fake_hydrate(hits, *, database_url):
        hydrated_calls.append(len(hits))
        return hits

    import play_book_studio.retrieval.hybrid_search as hybrid_search_module

    monkeypatch.setattr(hybrid_search_module, "hydrate_final_hits", fake_hydrate)

    bm25 = _FakeBM25([_hit(f"b{i}") for i in range(40)])
    vector = _FakeVector([_hit(f"v{i}") for i in range(40)])
    result = hybrid_search(
        "q",
        bm25_index=bm25,
        vector_retriever=vector,
        candidate_k=40,
        top_k=8,
        database_url="postgres://x",
    )

    assert len(result.hits) == 8
    assert hydrated_calls == [8]
