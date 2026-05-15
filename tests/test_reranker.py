from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.reranker import (
    RemoteBgeReranker,
    _build_rerank_document,
    _parse_scores,
)
from play_book_studio.retrieval.retriever_rerank import maybe_rerank_hits


class _Response:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.ok = status_code < 400

    def json(self) -> Any:
        return self._payload


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "root_dir": Path("."),
        "reranker_enabled": True,
        "embedding_base_url": "http://tei.internal/v1",
        "reranker_base_url": "http://reranker.internal",
        "reranker_model": "dragonkue/bge-reranker-v2-m3-ko",
        "reranker_timeout_seconds": 3,
        "reranker_batch_size": 8,
        "reranker_max_parallel_requests": 4,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _hit(chunk_id: str, *, score: float, book_slug: str = "networking") -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="Networking",
        section="Route timeouts",
        anchor=chunk_id,
        source_url="https://docs.example.test",
        viewer_path="/docs/example",
        text="Configure HAProxy router timeout annotations for OpenShift Route resources.",
        source="hybrid",
        raw_score=score,
        fused_score=score,
        heading_title="Route timeout configuration",
        toc_path=("Networking", "Routes"),
        section_path=("Ingress", "Route timeouts"),
        cli_commands=("oc annotate route",),
        k8s_objects=("Route",),
        error_strings=("timeout",),
    )


def test_remote_bge_reranker_uses_reranker_base_url_and_reorders(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        calls.append({"url": url, **kwargs})
        return _Response(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.12},
                ]
            }
        )

    monkeypatch.setattr("play_book_studio.retrieval.reranker.requests.post", fake_post)
    reranker = RemoteBgeReranker(_settings())

    hits = [_hit("wrong", score=0.9, book_slug="support"), _hit("right", score=0.4)]
    reranked = reranker.rerank("Route timeout 어디서 확인해?", hits, top_k=2)

    assert [hit.chunk_id for hit in reranked] == ["right", "wrong"]
    assert calls[0]["url"] == "http://reranker.internal/rerank"
    assert calls[0]["json"]["model"] == "dragonkue/bge-reranker-v2-m3-ko"
    assert calls[0]["json"]["texts"]
    assert reranked[0].component_scores["pre_rerank_fused_score"] == 0.4
    assert reranked[0].component_scores["reranker_score"] == 0.91


def test_remote_bge_reranker_falls_back_to_tei_texts_payload(monkeypatch):
    payload_keys: list[set[str]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        del url
        payload_keys.append(set(kwargs["json"]))
        if "texts" in kwargs["json"]:
            return _Response({"error": "unsupported schema"}, status_code=422)
        return _Response([{"index": 0, "score": 0.3}, {"index": 1, "score": 0.8}])

    monkeypatch.setattr("play_book_studio.retrieval.reranker.requests.post", fake_post)
    reranker = RemoteBgeReranker(_settings(reranker_base_url="http://tei.internal/v1/rerank"))

    reranked = reranker.rerank("배포 확인", [_hit("a", score=0.1), _hit("b", score=0.2)], top_k=2)

    assert {"texts", "query", "raw_scores", "return_text", "truncate", "model"} <= payload_keys[0]
    assert {"documents", "query", "top_n", "return_documents", "model"} <= payload_keys[1]
    assert [hit.chunk_id for hit in reranked] == ["b", "a"]


def test_remote_bge_reranker_respects_batch_size(monkeypatch):
    batches: list[list[str]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        del url
        texts = kwargs["json"]["texts"]
        batches.append(texts)
        return _Response([{"index": index, "score": float(index)} for index, _ in enumerate(texts)])

    monkeypatch.setattr("play_book_studio.retrieval.reranker.requests.post", fake_post)
    reranker = RemoteBgeReranker(
        _settings(reranker_base_url="http://tei.internal", reranker_batch_size=2)
    )

    hits = [_hit(str(index), score=0.1) for index in range(5)]
    reranked = reranker.rerank("batch safely", hits, top_k=2, top_n_override=5)

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert [hit.chunk_id for hit in reranked[:3]] == ["1", "3", "0"]


def test_remote_bge_reranker_can_disable_parallel_batches(monkeypatch):
    batches: list[list[str]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        del url
        texts = kwargs["json"]["texts"]
        batches.append(texts)
        return _Response([{"index": 0, "score": float(len(batches))}])

    monkeypatch.setattr("play_book_studio.retrieval.reranker.requests.post", fake_post)
    reranker = RemoteBgeReranker(
        _settings(
            reranker_base_url="http://tei.internal",
            reranker_batch_size=1,
            reranker_max_parallel_requests=1,
        )
    )

    hits = [_hit(str(index), score=0.1) for index in range(3)]
    reranked = reranker.rerank("sequential fallback", hits, top_k=2, top_n_override=3)

    assert [batch[0] for batch in batches] == [
        _build_rerank_document(hits[0]),
        _build_rerank_document(hits[1]),
        _build_rerank_document(hits[2]),
    ]
    assert [hit.chunk_id for hit in reranked[:3]] == ["2", "1", "0"]


def test_maybe_rerank_hits_falls_back_to_hybrid_on_reranker_error():
    class FailingReranker:
        model_name = "failing-reranker"
        top_n = 4

        def rerank(self, query: str, hits: list[RetrievalHit], **kwargs: Any) -> list[RetrievalHit]:
            del query, hits, kwargs
            raise TimeoutError("remote reranker timed out")

    class Retriever:
        reranker = FailingReranker()
        settings = _settings(reranker_candidate_k=5)

    trace_events: list[dict[str, Any]] = []
    timings_ms: dict[str, float] = {}
    hybrid_hits = [
        _hit("node-status", score=0.4, book_slug="nodes"),
        _hit("route-timeout", score=0.3, book_slug="networking"),
    ]

    hits, trace = maybe_rerank_hits(
        Retriever(),
        query="노드 상태는 처음에 어디서 확인하면 돼?",
        hybrid_hits=hybrid_hits,
        context=None,
        top_k=2,
        trace_callback=trace_events.append,
        timings_ms=timings_ms,
    )

    assert [hit.chunk_id for hit in hits] == ["node-status", "route-timeout"]
    assert trace["mode"] == "error_fallback"
    assert "remote reranker timed out" in trace["error"]
    assert trace_events[-1]["status"] == "done"
    assert trace_events[-1]["step"] == "rerank"


def test_maybe_rerank_hits_uses_configured_candidate_budget():
    class CapturingReranker:
        model_name = "capturing-reranker"
        top_n = 5

        def __init__(self) -> None:
            self.top_n_override = 0

        def rerank(self, query: str, hits: list[RetrievalHit], **kwargs: Any) -> list[RetrievalHit]:
            del query
            self.top_n_override = int(kwargs["top_n_override"])
            return list(reversed(hits[: self.top_n_override])) + hits[self.top_n_override :]

    class Retriever:
        reranker = CapturingReranker()
        settings = _settings(reranker_candidate_k=5)

    hybrid_hits = [_hit(str(index), score=1.0 - index / 10) for index in range(10)]

    hits, trace = maybe_rerank_hits(
        Retriever(),
        query="PVC Pending",
        hybrid_hits=hybrid_hits,
        context=None,
        top_k=5,
        trace_callback=lambda _event: None,
        timings_ms={},
    )

    assert Retriever.reranker.top_n_override == 5
    assert trace["candidate_budget"] == 5
    assert trace["reranked_count"] == 5
    assert [hit.chunk_id for hit in hits] == ["4", "3", "2", "1", "0"]


def test_rerank_document_includes_metadata_context():
    document = _build_rerank_document(_hit("route-timeout", score=0.5))

    assert "Book: networking" in document
    assert "Chapter: Networking" in document
    assert "Path: Networking > Routes > Ingress > Route timeouts" in document
    assert "Commands: oc annotate route" in document
    assert "Content:" in document


def test_rerank_document_truncates_long_content():
    hit = _hit("long", score=0.5)
    hit.text = " ".join(["content"] * 1000)

    document = _build_rerank_document(hit)

    assert len(document) < 2400
    assert "Book: networking" in document
    assert "Content:" in document


def test_parse_scores_accepts_score_arrays_and_missing_indices():
    scores = _parse_scores({"scores": [0.4, 0.9]}, expected_count=2)

    assert scores == [0.4, 0.9]
