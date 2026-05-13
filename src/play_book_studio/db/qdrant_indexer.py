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
    source_scope: str = "",
    limit: int = 100,
) -> tuple[QdrantChunkCandidate, ...]:
    scope = source_scope.strip()
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
                c.section_number,
                c.heading_title,
                c.source_anchor,
                c.toc_path,
                c.asset_ids,
                c.repository_id::text AS repository_id,
                c.owner_user_id,
                c.visibility,
                c.source_scope,
                c.chunk_role,
                c.parent_chunk_id::text AS parent_chunk_id,
                c.child_chunk_ids,
                c.navigation_only,
                c.beginner_narrative,
                c.starter_question_candidates,
                c.followup_question_candidates,
                c.question_candidates_version,
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
                AND (%s = '' OR c.source_scope = %s)
            ORDER BY c.created_at ASC, c.ordinal ASC
            LIMIT %s
            """,
            (collection, scope, scope, int(limit)),
        )
        rows = cursor.fetchall()
        columns = [item.name for item in cursor.description]
    return tuple(qdrant_candidate_from_row(dict(zip(columns, row, strict=True))) for row in rows)


def load_qdrant_payload_refresh_candidates(
    connection,
    *,
    collection: str,
    source_scope: str = "",
    limit: int = 1000,
) -> tuple[QdrantChunkCandidate, ...]:
    scope = source_scope.strip()
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
                c.section_number,
                c.heading_title,
                c.source_anchor,
                c.toc_path,
                c.asset_ids,
                c.repository_id::text AS repository_id,
                c.owner_user_id,
                c.visibility,
                c.source_scope,
                c.chunk_role,
                c.parent_chunk_id::text AS parent_chunk_id,
                c.child_chunk_ids,
                c.navigation_only,
                c.beginner_narrative,
                c.starter_question_candidates,
                c.followup_question_candidates,
                c.question_candidates_version,
                c.metadata AS chunk_metadata,
                pd.id::text AS parsed_document_id,
                pd.title AS document_title,
                pd.metadata AS parsed_metadata,
                ds.id::text AS document_source_id,
                ds.filename,
                ds.storage_key,
                ds.source_kind,
                ds.metadata AS source_metadata,
                ds.created_by,
                q.payload_hash AS indexed_payload_hash
            FROM document_chunks c
            JOIN parsed_documents pd ON pd.id = c.parsed_document_id
            JOIN document_sources ds ON ds.id = pd.document_source_id
            JOIN qdrant_index_entries q
                ON q.chunk_id = c.id AND q.collection = %s
            WHERE (%s = '' OR c.source_scope = %s)
            ORDER BY q.indexed_at ASC, c.ordinal ASC
            LIMIT %s
            """,
            (collection, scope, scope, int(limit)),
        )
        rows = cursor.fetchall()
        columns = [item.name for item in cursor.description]
    stale: list[QdrantChunkCandidate] = []
    for row in rows:
        row_dict = dict(zip(columns, row, strict=True))
        candidate = qdrant_candidate_from_row(row_dict)
        if candidate.payload_hash != str(row_dict.get("indexed_payload_hash") or ""):
            stale.append(candidate)
    return tuple(stale)


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
    toc_path = _json_list(row.get("toc_path"))
    asset_ids = _json_list(row.get("asset_ids"))
    child_chunk_ids = _json_list(row.get("child_chunk_ids"))
    starter_question_candidates = _string_list(row.get("starter_question_candidates"))
    followup_question_candidates = _string_list(row.get("followup_question_candidates"))
    chunk_metadata = _json_dict(row.get("chunk_metadata"))
    parsed_metadata = _json_dict(row.get("parsed_metadata"))
    source_metadata = _json_dict(row.get("source_metadata"))
    title = str(row.get("document_title") or row.get("filename") or "Uploaded document")
    section = str(chunk_metadata.get("section") or (section_path[-1] if section_path else title))
    chapter = str(chunk_metadata.get("chapter") or (section_path[0] if section_path else title))
    document_source_id = str(row.get("document_source_id") or "")
    chunk_id = str(row.get("chunk_id") or "")
    filename = str(row.get("filename") or "")
    storage_key = str(row.get("storage_key") or "")
    source_scope = str(row.get("source_scope") or source_metadata.get("source_scope") or "user_upload")
    document_format = str(
        source_metadata.get("document_format")
        or parsed_metadata.get("document_format")
        or ""
    )
    book_slug = str(chunk_metadata.get("book_slug") or source_metadata.get("book_slug") or "")
    if not book_slug:
        book_slug = "uploaded-documents" if source_scope == "user_upload" else source_scope
    source_lane = str(
        chunk_metadata.get("source_lane")
        or source_metadata.get("source_lane")
        or ("uploads" if source_scope == "user_upload" else source_scope)
    )
    source_type = str(
        chunk_metadata.get("source_type")
        or source_metadata.get("source_type")
        or ("uploaded_document" if source_scope == "user_upload" else source_scope)
    )
    source_collection = str(
        chunk_metadata.get("source_collection")
        or source_metadata.get("source_collection")
        or ("uploads" if source_scope == "user_upload" else "core")
    )
    source_id = str(chunk_metadata.get("source_id") or source_metadata.get("source_id") or document_source_id)
    source_url = str(chunk_metadata.get("source_url") or source_metadata.get("source_url") or storage_key)
    viewer_path = str(
        chunk_metadata.get("viewer_path")
        or source_metadata.get("viewer_path")
        or f"/uploads/documents/{document_source_id}/chunks/{chunk_id}"
    )
    learning_metadata = _learning_metadata(chunk_metadata, parsed_metadata, source_metadata)
    return {
        "chunk_id": chunk_id,
        "book_slug": book_slug,
        "chapter": chapter,
        "section": section,
        "section_id": str(chunk_metadata.get("section_id") or row.get("chunk_key") or chunk_id),
        "anchor": str(chunk_metadata.get("anchor") or row.get("source_anchor") or row.get("chunk_key") or chunk_id),
        "source_url": source_url,
        "viewer_path": viewer_path,
        "text": str(row.get("embedding_text") or row.get("markdown") or ""),
        "markdown": str(row.get("markdown") or ""),
        "filename": filename,
        "document_format": document_format,
        "source_kind": str(row.get("source_kind") or "upload"),
        "chunk_type": str(row.get("chunk_type") or "document"),
        "source_id": source_id,
        "document_source_id": document_source_id,
        "source_lane": source_lane,
        "source_type": source_type,
        "source_collection": source_collection,
        "review_status": str(chunk_metadata.get("review_status") or source_metadata.get("review_status") or "unreviewed"),
        "trust_score": float(chunk_metadata.get("trust_score") or source_metadata.get("trust_score") or 0.8),
        "parsed_artifact_id": str(
            chunk_metadata.get("parsed_artifact_id")
            or source_metadata.get("parsed_artifact_id")
            or row.get("parsed_document_id")
            or ""
        ),
        "semantic_role": str(chunk_metadata.get("semantic_role") or "uploaded_document"),
        "block_kinds": _string_list(chunk_metadata.get("block_kinds")) or [str(row.get("chunk_type") or "document")],
        "section_path": section_path,
        "section_number": str(row.get("section_number") or ""),
        "heading_title": str(row.get("heading_title") or ""),
        "source_anchor": str(row.get("source_anchor") or ""),
        "toc_path": toc_path,
        "asset_ids": asset_ids,
        "chunk_role": str(row.get("chunk_role") or chunk_metadata.get("chunk_role") or "leaf"),
        "parent_chunk_id": str(row.get("parent_chunk_id") or chunk_metadata.get("parent_chunk_id") or ""),
        "child_chunk_ids": child_chunk_ids or _string_list(chunk_metadata.get("child_chunk_ids")),
        "navigation_only": bool(row.get("navigation_only") or chunk_metadata.get("navigation_only") or False),
        "beginner_narrative": str(row.get("beginner_narrative") or chunk_metadata.get("beginner_narrative") or ""),
        "starter_question_candidates": starter_question_candidates
        or _string_list(chunk_metadata.get("starter_question_candidates")),
        "followup_question_candidates": followup_question_candidates
        or _string_list(chunk_metadata.get("followup_question_candidates")),
        "question_candidates_version": int(
            row.get("question_candidates_version") or chunk_metadata.get("question_candidates_version") or 0
        ),
        "repository_id": str(row.get("repository_id") or ""),
        "visibility": str(row.get("visibility") or source_metadata.get("visibility") or "workspace_shared"),
        "owner_user_id": str(row.get("owner_user_id") or ""),
        "source_scope": source_scope,
        "created_by": str(row.get("created_by") or ""),
        "cli_commands": _string_list(chunk_metadata.get("cli_commands")),
        "error_strings": _string_list(chunk_metadata.get("error_strings")),
        "k8s_objects": _string_list(chunk_metadata.get("k8s_objects")),
        "operator_names": _string_list(chunk_metadata.get("operator_names")),
        "verification_hints": _string_list(chunk_metadata.get("verification_hints")),
        "learning": learning_metadata,
        "chunk_metadata": chunk_metadata,
    }


def _learning_metadata(
    chunk_metadata: dict[str, Any],
    parsed_metadata: dict[str, Any],
    source_metadata: dict[str, Any],
) -> dict[str, Any]:
    source_learning = source_metadata.get("learning")
    parsed_learning = parsed_metadata.get("learning")
    chunk_learning = chunk_metadata.get("learning")
    payload = {
        "document": source_learning if isinstance(source_learning, dict) else {},
        "parsed_document": parsed_learning if isinstance(parsed_learning, dict) else {},
        "chunk": chunk_learning if isinstance(chunk_learning, dict) else {},
    }
    refs: dict[str, Any] = {}
    for source in (payload["document"], payload["parsed_document"], payload["chunk"]):
        for key in ("prerequisite_refs", "next_refs", "related_refs", "lab_refs"):
            value = source.get(key)
            if isinstance(value, list) and value and key not in refs:
                refs[key] = value
    if refs:
        payload["refs"] = refs
    return payload


def index_pending_document_chunks(
    settings: Settings,
    connection,
    *,
    collection: str | None = None,
    source_scope: str = "",
    limit: int = 100,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    target_collection = collection or settings.qdrant_collection
    candidates = load_qdrant_chunk_candidates(
        connection,
        collection=target_collection,
        source_scope=source_scope,
        limit=limit,
    )
    if not candidates:
        return {
            "collection": target_collection,
            "source_scope": source_scope.strip(),
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
        "source_scope": source_scope.strip(),
        "candidate_count": len(candidates),
        "indexed_count": len(candidates),
    }


def backfill_existing_qdrant_index_entries(
    settings: Settings,
    connection,
    *,
    collection: str | None = None,
    limit: int = 1000,
    batch_size: int = 256,
) -> dict[str, Any]:
    """Record index entries for DB chunks whose Qdrant points already exist."""
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
            "existing_count": 0,
            "missing_count": 0,
            "recorded_count": 0,
        }

    existing_point_ids: set[str] = set()
    effective_batch_size = max(1, int(batch_size or 256))
    for start in range(0, len(candidates), effective_batch_size):
        batch = candidates[start : start + effective_batch_size]
        existing_point_ids.update(
            fetch_existing_qdrant_point_ids(
                settings,
                collection=target_collection,
                point_ids=[candidate.point_id for candidate in batch],
            )
        )
    existing_candidates = tuple(
        candidate for candidate in candidates if candidate.point_id in existing_point_ids
    )
    if existing_candidates:
        record_qdrant_index_entries(
            connection,
            collection=target_collection,
            vector_model=settings.embedding_model,
            candidates=existing_candidates,
        )
    return {
        "collection": target_collection,
        "candidate_count": len(candidates),
        "existing_count": len(existing_candidates),
        "missing_count": len(candidates) - len(existing_candidates),
        "recorded_count": len(existing_candidates),
    }


def refresh_stale_qdrant_payloads(
    settings: Settings,
    connection,
    *,
    collection: str | None = None,
    source_scope: str = "",
    limit: int = 1000,
    batch_size: int = 256,
) -> dict[str, Any]:
    """Overwrite Qdrant payloads when DB-derived payload hashes changed."""
    target_collection = collection or settings.qdrant_collection
    scope = source_scope.strip()
    candidates = load_qdrant_payload_refresh_candidates(
        connection,
        collection=target_collection,
        source_scope=scope,
        limit=limit,
    )
    if not candidates:
        return {
            "collection": target_collection,
            "source_scope": scope,
            "candidate_count": 0,
            "existing_count": 0,
            "missing_count": 0,
            "refreshed_count": 0,
        }

    existing_point_ids: set[str] = set()
    effective_batch_size = max(1, int(batch_size or 256))
    for start in range(0, len(candidates), effective_batch_size):
        batch = candidates[start : start + effective_batch_size]
        existing_point_ids.update(
            fetch_existing_qdrant_point_ids(
                settings,
                collection=target_collection,
                point_ids=[candidate.point_id for candidate in batch],
            )
        )
    existing_candidates = tuple(
        candidate for candidate in candidates if candidate.point_id in existing_point_ids
    )
    if existing_candidates:
        overwrite_qdrant_payloads(
            settings,
            target_collection,
            existing_candidates,
            batch_size=effective_batch_size,
        )
        record_qdrant_index_entries(
            connection,
            collection=target_collection,
            vector_model=settings.embedding_model,
            candidates=existing_candidates,
        )
    return {
        "collection": target_collection,
        "source_scope": scope,
        "candidate_count": len(candidates),
        "existing_count": len(existing_candidates),
        "missing_count": len(candidates) - len(existing_candidates),
        "refreshed_count": len(existing_candidates),
    }


def fetch_existing_qdrant_point_ids(
    settings: Settings,
    *,
    collection: str,
    point_ids: list[str],
) -> set[str]:
    if not point_ids:
        return set()
    response = requests.post(
        f"{settings.qdrant_url}/collections/{collection}/points",
        json={
            "ids": point_ids,
            "with_payload": False,
            "with_vector": False,
        },
        timeout=max(settings.request_timeout_seconds, 30),
    )
    response.raise_for_status()
    result = response.json().get("result") or []
    return {str(point.get("id")) for point in result if isinstance(point, dict) and point.get("id")}


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


def overwrite_qdrant_payloads(
    settings: Settings,
    collection: str,
    candidates: tuple[QdrantChunkCandidate, ...],
    *,
    batch_size: int = 256,
) -> None:
    effective_batch_size = max(1, int(batch_size or 256))
    for start in range(0, len(candidates), effective_batch_size):
        batch = candidates[start : start + effective_batch_size]
        response = requests.post(
            f"{settings.qdrant_url}/collections/{collection}/points/batch?wait=true",
            json={
                "operations": [
                    {
                        "overwrite_payload": {
                            "points": [candidate.point_id],
                            "payload": candidate.payload,
                        }
                    }
                    for candidate in batch
                ]
            },
            timeout=max(settings.request_timeout_seconds, 120),
        )
        response.raise_for_status()


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


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _json_list(value) if str(item).strip()]


__all__ = [
    "QdrantChunkCandidate",
    "backfill_existing_qdrant_index_entries",
    "fetch_existing_qdrant_point_ids",
    "index_pending_document_chunks",
    "load_qdrant_chunk_candidates",
    "load_qdrant_payload_refresh_candidates",
    "overwrite_qdrant_payloads",
    "qdrant_candidate_from_row",
    "qdrant_payload_from_row",
    "record_qdrant_index_entries",
    "refresh_stale_qdrant_payloads",
]
