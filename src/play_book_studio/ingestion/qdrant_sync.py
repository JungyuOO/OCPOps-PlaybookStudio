"""Stream official chunk vectors into Qdrant with an explicit sync report."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import Settings

from play_book_studio.contextual_enrichment import contextual_search_text

from .embedding import EmbeddingClient
from .models import ChunkRecord
from .qdrant_store import ensure_collection, upsert_chunks
from .validation import qdrant_count


def _iter_chunk_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _chunk_records(rows: list[dict[str, Any]]) -> list[ChunkRecord]:
    allowed = {field.name for field in fields(ChunkRecord)}
    return [
        ChunkRecord(**{key: value for key, value in row.items() if key in allowed})
        for row in rows
    ]


def recreate_qdrant_collection(settings: Settings) -> None:
    url = f"{settings.qdrant_url}/collections/{settings.qdrant_collection}"
    response = requests.delete(url, timeout=settings.request_timeout_seconds)
    if response.status_code not in {200, 202, 404}:
        response.raise_for_status()
    original_recreate = settings.qdrant_recreate_collection
    try:
        settings.qdrant_recreate_collection = False
        ensure_collection(settings)
    finally:
        settings.qdrant_recreate_collection = original_recreate


def sync_qdrant_from_chunks(
    settings: Settings,
    *,
    recreate: bool = False,
    limit: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    rows = _iter_chunk_rows(settings.chunks_path)
    if limit is not None:
        rows = rows[: max(int(limit), 0)]
    expected_count = len(rows)
    if recreate:
        recreate_qdrant_collection(settings)
    else:
        original_recreate = settings.qdrant_recreate_collection
        try:
            settings.qdrant_recreate_collection = False
            ensure_collection(settings)
        finally:
            settings.qdrant_recreate_collection = original_recreate

    client = EmbeddingClient(settings)
    batch_size = max(int(settings.embedding_batch_size or 32), 1)
    upserted_count = 0
    total_batches = (expected_count + batch_size - 1) // batch_size
    for start in range(0, expected_count, batch_size):
        batch_rows = rows[start : start + batch_size]
        batch_records = _chunk_records(batch_rows)
        vectors = client.embed_texts(
            (contextual_search_text(record.to_dict()) for record in batch_records)
        )
        upserted_count += upsert_chunks(settings, batch_records, vectors)
        if progress_callback is not None:
            progress_callback(
                {
                    "completed_batches": (start // batch_size) + 1,
                    "total_batches": total_batches,
                    "upserted_count": upserted_count,
                    "expected_count": expected_count,
                }
            )

    count_after = qdrant_count(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.request_timeout_seconds,
    )
    return {
        "status": "ok" if count_after == expected_count else "fail",
        "recreate": recreate,
        "chunks_path": str(settings.chunks_path),
        "qdrant_url": settings.qdrant_url,
        "qdrant_collection": settings.qdrant_collection,
        "expected_count": expected_count,
        "upserted_count": upserted_count,
        "qdrant_count_after": count_after,
    }
