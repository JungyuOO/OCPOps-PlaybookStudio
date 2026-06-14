# 정규화된 chunk를 임베딩 벡터로 바꾸는 배치 helper.
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
import hashlib
import json
import threading
from typing import Iterable

import requests

from play_book_studio.config.settings import Settings


class EmbeddingClient:
    _global_single_text_cache: OrderedDict[str, list[float]] = OrderedDict()
    _global_cache_lock = threading.Lock()
    _loaded_disk_cache_paths: set[str] = set()

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.embedding_base_url
        self.model = settings.embedding_model
        self.device = settings.embedding_device
        self.api_key = settings.embedding_api_key
        self.batch_size = settings.embedding_batch_size
        # Query-time vector retrieval should fail fast when the embedding runtime
        # is unavailable so the chatbot can fall back to BM25 without hanging.
        self.timeout = settings.embedding_timeout_seconds
        self.cache_path = settings.retrieval_dir / "embedding_cache.jsonl"
        if not self.base_url:
            raise RuntimeError(
                "Remote embedding endpoint is not configured. "
                "Local embedding execution is disabled."
            )

    def _single_text_cache_key(self, text: str) -> str:
        return "\n".join([str(self.base_url or ""), str(self.model or ""), str(text or "")])

    def _single_text_cache_digest(self, text: str) -> str:
        return hashlib.sha256(self._single_text_cache_key(text).encode("utf-8")).hexdigest()

    def _load_disk_cache_once(self) -> None:
        path_key = str(self.cache_path)
        with self._global_cache_lock:
            if path_key in self._loaded_disk_cache_paths:
                return
            self._loaded_disk_cache_paths.add(path_key)
        if not self.cache_path.exists():
            return
        loaded: list[tuple[str, list[float]]] = []
        try:
            with self.cache_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = str(payload.get("key") or "")
                    vector = payload.get("vector")
                    if not key or not isinstance(vector, list):
                        continue
                    try:
                        loaded.append((key, [float(value) for value in vector]))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return
        with self._global_cache_lock:
            for key, vector in loaded:
                self._global_single_text_cache[key] = vector
                self._global_single_text_cache.move_to_end(key)
            while len(self._global_single_text_cache) > 1024:
                self._global_single_text_cache.popitem(last=False)

    def _cache_get_single_text(self, text: str) -> list[float] | None:
        if not str(text or ""):
            return None
        self._load_disk_cache_once()
        cache_key = self._single_text_cache_digest(text)
        with self._global_cache_lock:
            vector = self._global_single_text_cache.get(cache_key)
            if vector is None:
                return None
            self._global_single_text_cache.move_to_end(cache_key)
            return list(vector)

    def _cache_put_single_text(self, text: str, vector: list[float]) -> None:
        if not str(text or ""):
            return
        cache_key = self._single_text_cache_digest(text)
        with self._global_cache_lock:
            self._global_single_text_cache[cache_key] = list(vector)
            self._global_single_text_cache.move_to_end(cache_key)
            while len(self._global_single_text_cache) > 1024:
                self._global_single_text_cache.popitem(last=False)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"key": cache_key, "vector": list(map(float, vector))},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        except OSError:
            return

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
