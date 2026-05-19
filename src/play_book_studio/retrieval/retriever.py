"""Play Book Studio의 hybrid retrieval 오케스트레이션.

BM25, vector search, fusion 이후 shaping이 모두 여기에 있다.
답이 엉뚱한 근거를 물고 오면 `query.py` 다음으로 가장 먼저 볼 파일이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from play_book_studio.config.settings import Settings

from .bm25 import BM25Index
from .graph_runtime import RetrievalGraphRuntime
from .intake_overlay import (
    customer_pack_books_fingerprint,
    load_customer_pack_overlay_index,
)
from .models import RetrievalResult, SessionContext
from .vector import VectorRetriever

if TYPE_CHECKING:
    from .reranker import RemoteBgeReranker


def _build_reranker(settings: Settings, *, enabled: bool) -> "RemoteBgeReranker | None":
    if not enabled:
        return None
    from .reranker import RemoteBgeReranker

    return RemoteBgeReranker(settings)


def _load_bm25_index(settings: Settings) -> BM25Index:
    if settings.database_url.strip():
        try:
            return BM25Index.from_postgres(settings.database_url)
        except Exception:  # noqa: BLE001
            return BM25Index.from_rows([])
    return BM25Index.from_jsonl(settings.retrieval_bm25_corpus_path)


class ChatRetriever:
    """answerer와 eval이 공통으로 사용하는 메인 retrieval 런타임."""

    def __init__(
        self,
        settings: Settings,
        bm25_index: BM25Index,
        *,
        vector_retriever: VectorRetriever | None = None,
        reranker: RemoteBgeReranker | None = None,
        graph_runtime: RetrievalGraphRuntime | None = None,
    ) -> None:
        self.settings = settings
        self.bm25_index = bm25_index
        self.vector_retriever = vector_retriever
        self.reranker = reranker
        self.graph_runtime = graph_runtime or RetrievalGraphRuntime(settings)
        self.query_signal_llm_client = None
        self._customer_pack_overlay_fingerprint: tuple[tuple[str, int], ...] = ()
        self._customer_pack_overlay_index: BM25Index | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        enable_vector: bool = True,
        enable_reranker: bool | None = None,
    ) -> "ChatRetriever":
        bm25_index = _load_bm25_index(settings)
        vector_retriever = VectorRetriever(settings) if enable_vector else None
        reranker_enabled = settings.reranker_enabled if enable_reranker is None else enable_reranker
        reranker = _build_reranker(settings, enabled=reranker_enabled)
        return cls(
            settings,
            bm25_index,
            vector_retriever=vector_retriever,
            reranker=reranker,
            graph_runtime=RetrievalGraphRuntime(settings),
        )

    def customer_pack_overlay_index(self) -> BM25Index | None:
        fingerprint = customer_pack_books_fingerprint(self.settings.customer_pack_books_dir)
        if fingerprint != self._customer_pack_overlay_fingerprint:
            self._customer_pack_overlay_fingerprint = fingerprint
            self._customer_pack_overlay_index = load_customer_pack_overlay_index(
                str(self.settings.customer_pack_books_dir),
                fingerprint,
            )
        return self._customer_pack_overlay_index

    def default_log_path(self) -> Path:
        return self.settings.retrieval_log_path

    def append_log(self, result: RetrievalResult, log_path: Path | None = None) -> Path:
        target = log_path or self.default_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
        return target

    def retrieve(
        self,
        query: str,
        *,
        context: SessionContext | None = None,
        top_k: int = 8,
        candidate_k: int = 40,
        use_bm25: bool = True,
        use_vector: bool = True,
        trace_callback=None,
    ) -> RetrievalResult:
        from .hybrid_search import hybrid_search

        context = context or SessionContext()
        search = hybrid_search(
            query,
            bm25_index=self.bm25_index if use_bm25 else None,
            vector_retriever=self.vector_retriever if use_vector else None,
            candidate_k=candidate_k,
            top_k=top_k,
            database_url=getattr(self.settings, "database_url", ""),
            context=context,
        )
        hits = search.hits
        reranker_failed = False
        reranker_applied = False
        if self.reranker is not None and self.reranker.enabled and hits:
            try:
                hits = self.reranker.rerank(search.normalized_query, hits, top_k=top_k)[:top_k]
                reranker_applied = True
            except Exception:  # noqa: BLE001
                reranker_failed = True
                hits = search.hits

        return RetrievalResult(
            query=query,
            normalized_query=search.normalized_query,
            rewritten_query=search.normalized_query,
            top_k=top_k,
            candidate_k=candidate_k,
            context=context.to_dict(),
            hits=hits,
            trace={
                "retrieval_query_count": 1,
                "bm25_count": search.bm25_count,
                "vector_count": search.vector_count,
                "vector_failed": search.vector_failed,
                "reranker_applied": reranker_applied,
                "reranker_failed": reranker_failed,
            },
        )
