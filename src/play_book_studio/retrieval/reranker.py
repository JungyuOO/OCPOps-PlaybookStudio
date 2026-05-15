"""Second-stage remote BGE reranker for hybrid retrieval candidates."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from play_book_studio.config.settings import Settings

from .models import RetrievalHit


DEFAULT_RERANKER_MODEL = "dragonkue/bge-reranker-v2-m3-ko"
RERANKER_SOURCE = "hybrid_reranked"
MAX_RERANK_DOCUMENT_CHARS = 1800


def _build_rerank_document(hit: RetrievalHit) -> str:
    """Include source metadata so semantic rerankers can separate similar tokens."""
    path = " > ".join(part for part in (*hit.toc_path, *hit.section_path) if part)
    commands = ", ".join(command for command in hit.cli_commands if command)
    objects = ", ".join(obj for obj in hit.k8s_objects if obj)
    errors = ", ".join(error for error in hit.error_strings if error)
    content = hit.text.strip()
    if len(content) > MAX_RERANK_DOCUMENT_CHARS:
        content = content[:MAX_RERANK_DOCUMENT_CHARS].rsplit(" ", 1)[0].strip()
    parts = [
        f"Book: {hit.book_slug.strip()}" if hit.book_slug.strip() else "",
        f"Chapter: {hit.chapter.strip()}" if hit.chapter.strip() else "",
        f"Section: {hit.section.strip()}" if hit.section.strip() else "",
        f"Heading: {hit.heading_title.strip()}" if hit.heading_title.strip() else "",
        f"Path: {path}" if path else "",
        f"Chunk type: {hit.chunk_type.strip()}" if hit.chunk_type.strip() else "",
        f"Commands: {commands}" if commands else "",
        f"Kubernetes/OpenShift objects: {objects}" if objects else "",
        f"Errors: {errors}" if errors else "",
        "Content:",
        content,
    ]
    return "\n".join(part for part in parts if part)


def _rerank_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/rerank"):
        return base
    if base.endswith("/v1"):
        base = base.removesuffix("/v1")
    return f"{base}/rerank"


def _score_from_item(item: Any) -> float | None:
    if isinstance(item, dict):
        for key in ("relevance_score", "score", "raw_score", "logit"):
            if key in item:
                return float(item[key])
        return None
    if isinstance(item, (int, float)):
        return float(item)
    return None


def _index_from_item(item: Any, fallback: int) -> int:
    if isinstance(item, dict):
        for key in ("index", "document_index", "id"):
            if key in item:
                return int(item[key])
    return fallback


def _iter_result_items(payload: Any) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "result", "documents", "scores"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("reranker response did not include a supported result list")


def _parse_scores(payload: Any, *, expected_count: int) -> list[float]:
    items = list(_iter_result_items(payload))
    scores: list[float | None] = [None] * expected_count
    for fallback_index, item in enumerate(items):
        index = _index_from_item(item, fallback_index)
        if index < 0 or index >= expected_count:
            continue
        score = _score_from_item(item)
        if score is not None:
            scores[index] = score

    present_scores = [score for score in scores if score is not None]
    if not present_scores:
        raise ValueError("reranker response did not include numeric scores")
    floor_score = min(present_scores) - 1.0
    return [float(score if score is not None else floor_score) for score in scores]


class RemoteBgeReranker:
    """Calls the internal BGE reranker endpoint instead of loading a local model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.reranker_base_url.strip().rstrip("/")
        self.endpoint = _rerank_endpoint(self.base_url)
        self.model_name = settings.reranker_model or DEFAULT_RERANKER_MODEL
        self.top_n = max(2, settings.reranker_top_n)
        self.batch_size = max(1, settings.reranker_batch_size)
        self.max_parallel_requests = max(1, settings.reranker_max_parallel_requests)
        self.timeout_seconds = max(1.0, settings.reranker_timeout_seconds)
        self.api_key = settings.reranker_api_key or settings.embedding_api_key

    @property
    def enabled(self) -> bool:
        return bool(self.settings.reranker_enabled)

    def warmup(self) -> bool:
        if not self.enabled:
            return False
        self._request_scores("warmup", ["warmup"])
        return True

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payloads(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        openai_style: dict[str, Any] = {
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }
        tei_style: dict[str, Any] = {
            "query": query,
            "texts": documents,
            "raw_scores": True,
            "return_text": False,
            "truncate": True,
        }
        if self.model_name:
            openai_style["model"] = self.model_name
            tei_style["model"] = self.model_name
        return [tei_style, openai_style]

    def _request_score_batch(self, query: str, documents: list[str]) -> list[float]:
        if not self.endpoint:
            raise RuntimeError("RERANKER_BASE_URL must be set")

        errors: list[str] = []
        for payload in self._payloads(query, documents):
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            if response.ok:
                return _parse_scores(response.json(), expected_count=len(documents))
            errors.append(f"{response.status_code} {response.text[:500]}")
            if response.status_code not in {400, 404, 415, 422}:
                break
        raise RuntimeError(f"BGE reranker request failed: {'; '.join(errors)}")

    def _request_scores(self, query: str, documents: list[str]) -> list[float]:
        batches = [
            documents[start:start + self.batch_size]
            for start in range(0, len(documents), self.batch_size)
        ]
        if len(batches) == 1 or self.max_parallel_requests == 1:
            scores: list[float] = []
            for batch in batches:
                scores.extend(self._request_score_batch(query, batch))
            return scores

        max_workers = min(self.max_parallel_requests, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            batch_scores = executor.map(lambda batch: self._request_score_batch(query, batch), batches)
        return [score for scores in batch_scores for score in scores]

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
        top_n_override: int | None = None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []

        rerank_limit = top_n_override if top_n_override is not None else self.top_n
        rerank_count = min(len(hits), max(top_k, rerank_limit))
        primary_candidates = [copy.deepcopy(hit) for hit in hits[:rerank_count]]
        remainder = [copy.deepcopy(hit) for hit in hits[rerank_count:]]

        documents = [_build_rerank_document(hit) for hit in primary_candidates]
        scores = self._request_scores(query, documents)

        for hit, score in zip(primary_candidates, scores, strict=True):
            hit.component_scores["pre_rerank_fused_score"] = float(hit.fused_score)
            hit.component_scores["reranker_score"] = float(score)
            hit.fused_score = float(score)
            hit.raw_score = float(score)
            hit.source = RERANKER_SOURCE

        primary_candidates.sort(
            key=lambda item: (
                -item.component_scores.get("reranker_score", item.fused_score),
                -item.component_scores.get("pre_rerank_fused_score", 0.0),
                item.book_slug,
                item.chunk_id,
            )
        )

        return primary_candidates + remainder
