"""Index parsed document chunks from PostgreSQL into Qdrant."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import requests

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.embedding import EmbeddingClient


@dataclass(frozen=True, slots=True)
class QdrantChunkCandidate:
    chunk_id: str
    point_id: str
    embedding_text: str
    payload: dict[str, Any]
    payload_hash: str


def load_qdrant_chunk_candidates(
    connection,
    *,
    collection: str,
    limit: int = 100,
) -> tuple[QdrantChunkCandidate, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.id::text AS chunk_id,
                c.chunk_key,
                c.ordinal,
                c.chunk_type,
                c.markdown,
                c.embedding_text,
                c.section_path,
                c.asset_ids,
                c.metadata AS chunk_metadata,
                pd.id::text AS parsed_document_id,
                pd.title AS document_title,
                pd.metadata AS parsed_metadata,
                ds.id::text AS document_source_id,
                ds.filename,
                ds.storage_key,
                ds.source_kind,
                ds.metadata AS source_metadata,
                ds.created_by
            FROM document_chunks c
            JOIN parsed_documents pd ON pd.id = c.parsed_document_id
            JOIN document_sources ds ON ds.id = pd.document_source_id
            LEFT JOIN qdrant_index_entries q
                ON q.chunk_id = c.id AND q.collection = %s
            WHERE q.chunk_id IS NULL
            ORDER BY c.created_at ASC, c.ordinal ASC
            LIMIT %s
            """,
            (collection, int(limit)),
        )
        rows = cursor.fetchall()
        columns = [item.name for item in cursor.description]
    return tuple(qdrant_candidate_from_row(dict(zip(columns, row, strict=True))) for row in rows)


def qdrant_candidate_from_row(row: dict[str, Any]) -> QdrantChunkCandidate:
    chunk_id = str(row["chunk_id"])
    payload = qdrant_payload_from_row(row)
    payload_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return QdrantChunkCandidate(
        chunk_id=chunk_id,
        point_id=chunk_id,
        embedding_text=str(row.get("embedding_text") or ""),
        payload=payload,
        payload_hash=payload_hash,
    )


def qdrant_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    section_path = _json_list(row.get("section_path"))
    asset_ids = _json_list(row.get("asset_ids"))
    chunk_metadata = _json_dict(row.get("chunk_metadata"))
    parsed_metadata = _json_dict(row.get("parsed_metadata"))
    source_metadata = _json_dict(row.get("source_metadata"))
    title = str(row.get("document_title") or row.get("filename") or "Uploaded document")
    section = str(section_path[-1] if section_path else title)
    chapter = str(section_path[0] if section_path else title)
    document_source_id = str(row.get("document_source_id") or "")
    chunk_id = str(row.get("chunk_id") or "")
    filename = str(row.get("filename") or "")
    storage_key = str(row.get("storage_key") or "")
    document_format = str(
        source_metadata.get("document_format")
        or parsed_metadata.get("document_format")
        or ""
    )
    return {
        "chunk_id": chunk_id,
        "book_slug": "uploaded-documents",
        "chapter": chapter,
        "section": section,
        "section_id": str(row.get("chunk_key") or chunk_id),
        "anchor": str(row.get("chunk_key") or chunk_id),
        "source_url": storage_key,
        "viewer_path": f"/uploads/documents/{document_source_id}/chunks/{chunk_id}",
        "text": str(row.get("embedding_text") or row.get("markdown") or ""),
        "markdown": str(row.get("markdown") or ""),
        "filename": filename,
        "document_format": document_format,
        "source_kind": str(row.get("source_kind") or "upload"),
        "chunk_type": str(row.get("chunk_type") or "document"),
        "source_id": document_source_id,
        "source_lane": "uploads",
        "source_type": "uploaded_document",
        "source_collection": "uploads",
        "review_status": "unreviewed",
        "trust_score": 0.8,
        "parsed_artifact_id": str(row.get("parsed_document_id") or ""),
        "semantic_role": "uploaded_document",
        "block_kinds": [str(row.get("chunk_type") or "document")],
        "section_path": section_path,
        "asset_ids": asset_ids,
        "created_by": str(row.get("created_by") or ""),
        "chunk_metadata": chunk_metadata,
    }


def index_pending_document_chunks(
    settings: Settings,
    connection,
    *,
    collection: str | None = None,
    limit: int = 100,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    target_collection = collection or settings.qdrant_collection
    candidates = load_qdrant_chunk_candidates(
        connection,
        collection=target_collection,
        limit=limit,
    )
    if not candidates:
        return {
            "collection": target_collection,
            "candidate_count": 0,
            "indexed_count": 0,
        }

    ensure_qdrant_collection(settings, target_collection)
    client = embedding_client or EmbeddingClient(settings)
    vectors = client.embed_texts(candidate.embedding_text for candidate in candidates)
    _upsert_candidates(settings, target_collection, candidates, vectors)
    record_qdrant_index_entries(
        connection,
        collection=target_collection,
        vector_model=settings.embedding_model,
        candidates=candidates,
    )
    return {
        "collection": target_collection,
        "candidate_count": len(candidates),
        "indexed_count": len(candidates),
    }


def ensure_qdrant_collection(settings: Settings, collection: str) -> None:
    url = f"{settings.qdrant_url}/collections/{collection}"
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


def record_qdrant_index_entries(
    connection,
    *,
    collection: str,
    vector_model: str,
    candidates: tuple[QdrantChunkCandidate, ...],
) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            for candidate in candidates:
                cursor.execute(
                    """
                    INSERT INTO qdrant_index_entries (
                        chunk_id, collection, point_id, vector_model, payload_hash
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id, collection) DO UPDATE SET
                        point_id = EXCLUDED.point_id,
                        vector_model = EXCLUDED.vector_model,
                        payload_hash = EXCLUDED.payload_hash,
                        indexed_at = now()
                    """,
                    (
                        candidate.chunk_id,
                        collection,
                        candidate.point_id,
                        vector_model,
                        candidate.payload_hash,
                    ),
                )


def _upsert_candidates(
    settings: Settings,
    collection: str,
    candidates: tuple[QdrantChunkCandidate, ...],
    vectors: list[list[float]],
) -> None:
    if len(candidates) != len(vectors):
        raise ValueError("candidate count and vector count do not match")
    points = [
        {
            "id": candidate.point_id,
            "vector": vector,
            "payload": candidate.payload,
        }
        for candidate, vector in zip(candidates, vectors, strict=True)
    ]
    for start in range(0, len(points), max(1, int(settings.qdrant_upsert_batch_size or 128))):
        batch = points[start : start + int(settings.qdrant_upsert_batch_size or 128)]
        response = requests.put(
            f"{settings.qdrant_url}/collections/{collection}/points?wait=true",
            json={"points": batch},
            timeout=max(settings.request_timeout_seconds, 120),
        )
        response.raise_for_status()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


__all__ = [
    "QdrantChunkCandidate",
    "index_pending_document_chunks",
    "load_qdrant_chunk_candidates",
    "qdrant_candidate_from_row",
    "qdrant_payload_from_row",
    "record_qdrant_index_entries",
]
