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
        "reranker_base_url": "",
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_timeout_seconds": 3,
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


def test_remote_bge_reranker_uses_embedding_base_url_and_reorders(monkeypatch):
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
    assert calls[0]["url"] == "http://tei.internal/v1/rerank"
    assert calls[0]["json"]["model"] == "BAAI/bge-reranker-v2-m3"
    assert calls[0]["json"]["documents"]
    assert reranked[0].component_scores["pre_rerank_fused_score"] == 0.4
    assert reranked[0].component_scores["reranker_score"] == 0.91


def test_remote_bge_reranker_falls_back_to_tei_texts_payload(monkeypatch):
    payload_keys: list[set[str]] = []

    def fake_post(url: str, **kwargs: Any) -> _Response:
        del url
        payload_keys.append(set(kwargs["json"]))
        if "documents" in kwargs["json"]:
            return _Response({"error": "unsupported schema"}, status_code=422)
        return _Response([{"index": 0, "score": 0.3}, {"index": 1, "score": 0.8}])

    monkeypatch.setattr("play_book_studio.retrieval.reranker.requests.post", fake_post)
    reranker = RemoteBgeReranker(_settings(reranker_base_url="http://tei.internal/v1/rerank"))

    reranked = reranker.rerank("배포 확인", [_hit("a", score=0.1), _hit("b", score=0.2)], top_k=2)

    assert {"documents", "query", "top_n", "return_documents", "model"} <= payload_keys[0]
    assert {"texts", "query", "raw_scores", "return_text", "truncate", "model"} <= payload_keys[1]
    assert [hit.chunk_id for hit in reranked] == ["b", "a"]


def test_rerank_document_includes_metadata_context():
    document = _build_rerank_document(_hit("route-timeout", score=0.5))

    assert "Book: networking" in document
    assert "Chapter: Networking" in document
    assert "Path: Networking > Routes > Ingress > Route timeouts" in document
    assert "Commands: oc annotate route" in document
    assert "Content:" in document


def test_parse_scores_accepts_score_arrays_and_missing_indices():
    scores = _parse_scores({"scores": [0.4, 0.9]}, expected_count=2)

    assert scores == [0.4, 0.9]

