# chunk/vector를 Qdrant에 적재할 때 쓰는 저장소 어댑터.
from __future__ import annotations

from collections.abc import Callable

import requests

from .models import ChunkRecord
from play_book_studio.config.settings import Settings


def ensure_collection(settings: Settings) -> None:
    url = f"{settings.qdrant_url}/collections/{settings.qdrant_collection}"
    response = requests.get(url, timeout=settings.request_timeout_seconds)
    if response.status_code == 200 and settings.qdrant_recreate_collection:
        delete = requests.delete(url, timeout=settings.request_timeout_seconds)
        delete.raise_for_status()
        response = requests.get(url, timeout=settings.request_timeout_seconds)
    if response.status_code == 200:
        return
    create = requests.put(
        url,
        json={
            "vectors": {
                "size": settings.qdrant_vector_size,
                "distance": settings.qdrant_distance,
            }
        },
        timeout=settings.request_timeout_seconds,
    )
    create.raise_for_status()


def upsert_chunks(
    settings: Settings,
    chunks: list[ChunkRecord],
    vectors: list[list[float]],
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    if len(chunks) != len(vectors):
        raise ValueError("Chunk count and vector count do not match")

    total = 0
    total_batches = (len(chunks) + settings.qdrant_upsert_batch_size - 1) // settings.qdrant_upsert_batch_size
    for start in range(0, len(chunks), settings.qdrant_upsert_batch_size):
        points = []
        batch_chunks = chunks[start : start + settings.qdrant_upsert_batch_size]
        batch_vectors = vectors[start : start + settings.qdrant_upsert_batch_size]
        for chunk, vector in zip(batch_chunks, batch_vectors, strict=True):
            payload = chunk.to_dict()
            payload.pop("token_count", None)
            payload.pop("ordinal", None)
            points.append({"id": chunk.chunk_id, "vector": vector, "payload": payload})

        response = requests.put(
            f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points?wait=true",
            json={"points": points},
            timeout=max(settings.request_timeout_seconds, 120),
        )
        response.raise_for_status()
        total += len(points)
        if progress_callback is not None:
            completed_batches = (start // settings.qdrant_upsert_batch_size) + 1
            progress_callback(completed_batches, total_batches)
    return total
