# 정규화된 chunk를 임베딩 벡터로 바꾸는 배치 helper.
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
import threading
from typing import Iterable

import requests

from play_book_studio.config.settings import Settings


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.embedding_base_url
        self.model = settings.embedding_model
        self.device = settings.embedding_device
        self.api_key = settings.embedding_api_key
        self.batch_size = settings.embedding_batch_size
        # Query-time vector retrieval should fail fast when the embedding runtime
        # is unavailable so the chatbot can fall back to BM25 without hanging.
        self.timeout = settings.embedding_timeout_seconds
        self._single_text_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()
        if not self.base_url:
            raise RuntimeError(
                "Remote embedding endpoint is not configured. "
                "Local embedding execution is disabled."
            )

    def _cache_get_single_text(self, text: str) -> list[float] | None:
        normalized = str(text or "")
        if not normalized:
            return None
        with self._cache_lock:
            vector = self._single_text_cache.get(normalized)
            if vector is None:
                return None
            self._single_text_cache.move_to_end(normalized)
            return list(vector)

    def _cache_put_single_text(self, text: str, vector: list[float]) -> None:
        normalized = str(text or "")
        if not normalized:
            return
        with self._cache_lock:
            self._single_text_cache[normalized] = list(vector)
            self._single_text_cache.move_to_end(normalized)
            while len(self._single_text_cache) > 128:
                self._single_text_cache.popitem(last=False)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        if " " in self.api_key.strip():
            return {"Authorization": self.api_key.strip()}
        return {"Authorization": f"Bearer {self.api_key}"}

    def _candidate_models(self) -> list[str]:
        candidates: list[str] = [self.model]
        for candidate in (
            self.model.rsplit("/", 1)[-1],
            self.model.lower(),
            self.model.lower().rsplit("/", 1)[-1],
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _request_embeddings(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for model_name in self._candidate_models():
            try:
                response = requests.post(
                    f"{self.base_url}/embeddings",
                    json={"model": model_name, "input": batch},
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data")
                if not isinstance(data, list):
                    raise ValueError("Embedding response is missing a 'data' list")
                vectors = [item["embedding"] for item in data]
                return [list(map(float, vector)) for vector in vectors]
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(
            f"Failed to fetch embeddings from {self.base_url} using model '{self.model}'"
        ) from last_error

    def embed_texts(
        self,
        texts: Iterable[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        items = list(texts)
        if len(items) == 1:
            cached_vector = self._cache_get_single_text(items[0])
            if cached_vector is not None:
                if progress_callback is not None:
                    progress_callback(1, 1)
                return [cached_vector]
        vectors: list[list[float]] = []
        total_batches = (len(items) + self.batch_size - 1) // self.batch_size
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            vectors.extend(self._request_embeddings(batch))
            if progress_callback is not None:
                completed_batches = (start // self.batch_size) + 1
                progress_callback(completed_batches, total_batches)
        if len(items) == 1 and vectors:
            self._cache_put_single_text(items[0], vectors[0])
        return vectors
