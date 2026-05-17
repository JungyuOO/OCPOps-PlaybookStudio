"""Load the official embedding-only chunk projection into Qdrant."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import Settings
from play_book_studio.db.qdrant_indexer import (
    QDRANT_PAYLOAD_VERSION,
    QdrantChunkCandidate,
    qdrant_payload_from_row,
    record_qdrant_index_entries,
)
from play_book_studio.ingestion.embedding import EmbeddingClient
from play_book_studio.ingestion.official_gold_import import (
    OFFICIAL_EMBEDDING_CHUNKS_VERSION,
    OFFICIAL_TEXT_LAYERS_VERSION,
    _chunk_metadata,
    _flatten_keyword_text,
    _heading_title,
    _load_gold_chunk_rows,
    _normalized_chunk_text,
    _section_number,
    _section_path,
    _source_anchor,
    _source_key,
    _source_metadata,
    _source_title,
    _stable_uuid,
    _toc_path,
    _uuid_from_row_chunk_id,
)


ARABIC_RE = r"[\u0600-\u06ff]"


def build_official_embedding_qdrant_candidates(
    *,
    chunks_path: Path,
    embedding_chunks_path: Path,
    limit: int = 0,
) -> tuple[QdrantChunkCandidate, ...]:
    source_rows = _load_gold_chunk_rows(chunks_path, limit=0)
    source_by_chunk_id = {_uuid_from_row_chunk_id(row): row for row in source_rows}
    source_by_raw_chunk_id = {str(row.get("chunk_id") or "").strip(): row for row in source_rows}
    grouped = _group_source_rows(source_rows)

    candidates: list[QdrantChunkCandidate] = []
    for ordinal, embedding_row in enumerate(_load_embedding_rows(embedding_chunks_path, limit=limit)):
        chunk_id = str(embedding_row.get("chunk_id") or "").strip()
        source_chunk_id = str(embedding_row.get("source_chunk_id") or "").strip()
        source_row = source_by_chunk_id.get(chunk_id) or source_by_raw_chunk_id.get(source_chunk_id)
        if source_row is None:
            continue
        embedding_text = str(embedding_row.get("embedding_text") or embedding_row.get("text") or "").strip()
        if not embedding_text:
            continue
        normalized_text = str(embedding_row.get("normalized_text") or "").strip() or _flatten_keyword_text(
            embedding_text
        )
        payload_row = _payload_row_from_embedding(
            source_row,
            embedding_row,
            embedding_text=embedding_text,
            normalized_text=normalized_text,
            ordinal=ordinal,
            source_rows=grouped.get(_source_key(source_row), [source_row]),
            chunks_path=chunks_path,
            embedding_chunks_path=embedding_chunks_path,
        )
        payload = qdrant_payload_from_row(payload_row)
        payload_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        candidates.append(
            QdrantChunkCandidate(
                chunk_id=chunk_id,
                point_id=chunk_id,
                embedding_text=embedding_text,
                payload=payload,
                payload_hash=payload_hash,
                payload_version=QDRANT_PAYLOAD_VERSION,
            )
        )
    return tuple(candidates)


def official_embedding_target_point_ids(
    *,
    chunks_path: Path,
    embedding_chunks_path: Path,
) -> tuple[list[str], list[str]]:
    source_rows = _load_gold_chunk_rows(chunks_path, limit=0)
    source_ids = [_uuid_from_row_chunk_id(row) for row in source_rows]
    embedding_ids = [
        str(row.get("chunk_id") or "").strip()
        for row in _load_embedding_rows(embedding_chunks_path, limit=0)
        if str(row.get("chunk_id") or "").strip()
    ]
    embedding_id_set = set(embedding_ids)
    skipped_ids = [chunk_id for chunk_id in source_ids if chunk_id not in embedding_id_set]
    return embedding_ids, skipped_ids


def upsert_official_embedding_chunks_to_qdrant(
    settings: Settings,
    *,
    chunks_path: Path,
    embedding_chunks_path: Path,
    collection: str | None = None,
    limit: int = 0,
    delete_skipped: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    target_collection = collection or settings.qdrant_collection
    candidates = build_official_embedding_qdrant_candidates(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_chunks_path,
        limit=limit,
    )
    _validate_candidates(candidates, expected_vector_size=settings.qdrant_vector_size, validate_vectors=False)
    target_ids, skipped_ids = official_embedding_target_point_ids(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_chunks_path,
    )
    if limit > 0:
        target_ids = target_ids[:limit]
        skipped_ids = []

    summary: dict[str, Any] = {
        "collection": target_collection,
        "qdrant_url": settings.qdrant_url,
        "chunks_path": str(chunks_path.resolve()),
        "embedding_chunks_path": str(embedding_chunks_path.resolve()),
        "schema_version": OFFICIAL_EMBEDDING_CHUNKS_VERSION,
        "candidate_count": len(candidates),
        "target_embedding_point_count": len(target_ids),
        "skipped_source_point_count": len(skipped_ids),
        "delete_skipped": bool(delete_skipped),
        "dry_run": bool(dry_run),
        "quality": _candidate_quality_summary(candidates),
        "upserted_count": 0,
        "deleted_skipped_count": 0,
    }
    if dry_run:
        return summary

    ensure_qdrant_collection(settings, target_collection)
    client = embedding_client or EmbeddingClient(settings)
    batch_size = max(1, int(settings.embedding_batch_size or 32))
    upserted = 0
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        vectors = client.embed_texts(candidate.embedding_text for candidate in batch)
        _validate_vectors(vectors, expected_vector_size=settings.qdrant_vector_size)
        _upsert_candidates(settings, target_collection, batch, vectors)
        upserted += len(batch)
        if progress_callback is not None:
            progress_callback("upsert", min(start + len(batch), len(candidates)), len(candidates))
    deleted_count = 0
    if delete_skipped and skipped_ids:
        deleted_count = delete_qdrant_points(settings, target_collection, skipped_ids)
        if progress_callback is not None:
            progress_callback("delete_skipped", deleted_count, len(skipped_ids))

    summary["upserted_count"] = upserted
    summary["deleted_skipped_count"] = deleted_count
    return summary


def sync_official_embedding_chunks_to_database(
    connection,
    *,
    chunks_path: Path,
    embedding_chunks_path: Path,
) -> dict[str, Any]:
    source_layers_by_id = {
        _uuid_from_row_chunk_id(row): (
            str(row.get("text") or ""),
            _normalized_chunk_text(row),
        )
        for row in _load_gold_chunk_rows(chunks_path, limit=0)
    }
    embedding_rows = _load_embedding_rows(embedding_chunks_path, limit=0)
    embedding_by_id = {
        str(row.get("chunk_id") or "").strip(): (
            str(row.get("embedding_text") or row.get("text") or "").strip(),
            str(row.get("normalized_text") or "").strip()
            or _flatten_keyword_text(str(row.get("embedding_text") or row.get("text") or "").strip()),
        )
        for row in embedding_rows
        if str(row.get("chunk_id") or "").strip()
    }
    _target_ids, skipped_ids = official_embedding_target_point_ids(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_chunks_path,
    )
    updated_count = 0
    suppressed_count = 0
    with connection.transaction():
        with connection.cursor() as cursor:
            for chunk_id, (embedding_text, normalized_text) in embedding_by_id.items():
                raw_text, markdown = source_layers_by_id.get(chunk_id, ("", ""))
                cursor.execute(
                    """
                    UPDATE document_chunks
                    SET markdown = %s,
                        embedding_text = %s,
                        token_count = %s,
                        metadata = jsonb_set(
                            jsonb_set(
                                coalesce(metadata, '{}'::jsonb),
                                '{normalized_text}',
                                to_jsonb(%s::text),
                                true
                            ),
                            '{text_layers}',
                            coalesce(metadata->'text_layers', '{}'::jsonb)
                                || jsonb_build_object(
                                    'version', to_jsonb(%s::text),
                                    'raw_text', to_jsonb(%s::text),
                                    'markdown', to_jsonb(%s::text),
                                    'normalized_text', to_jsonb(%s::text),
                                    'embedding_text', to_jsonb(%s::text),
                                    'quality_warnings', '[]'::jsonb,
                                    'rechunk_status', 'kept'
                                ),
                            true
                        )
                    WHERE id = %s::uuid
                      AND source_scope = 'official_docs'
                    """,
                    (
                        markdown,
                        embedding_text,
                        len(embedding_text.split()),
                        normalized_text,
                        OFFICIAL_TEXT_LAYERS_VERSION,
                        raw_text,
                        markdown,
                        normalized_text,
                        embedding_text,
                        chunk_id,
                    ),
                )
                updated_count += int(cursor.rowcount or 0)
            for chunk_id in skipped_ids:
                raw_text, markdown = source_layers_by_id.get(chunk_id, ("", ""))
                cursor.execute(
                    """
                    UPDATE document_chunks
                    SET markdown = %s,
                        embedding_text = '',
                        token_count = 0,
                        navigation_only = true,
                        metadata = jsonb_set(
                            jsonb_set(
                                coalesce(metadata, '{}'::jsonb),
                                '{normalized_text}',
                                to_jsonb(''::text),
                                true
                            ),
                            '{text_layers}',
                            coalesce(metadata->'text_layers', '{}'::jsonb)
                                || jsonb_build_object(
                                    'version', to_jsonb(%s::text),
                                    'raw_text', to_jsonb(%s::text),
                                    'markdown', to_jsonb(%s::text),
                                    'normalized_text', '',
                                    'embedding_text', '',
                                    'quality_warnings', jsonb_build_array('suppressed_from_embedding_chunks'),
                                    'rechunk_status', 'suppressed'
                                ),
                            true
                        )
                    WHERE id = %s::uuid
                      AND source_scope = 'official_docs'
                    """,
                    (
                        markdown,
                        OFFICIAL_TEXT_LAYERS_VERSION,
                        raw_text,
                        markdown,
                        chunk_id,
                    ),
                )
                suppressed_count += int(cursor.rowcount or 0)
    return {
        "embedding_chunks_path": str(embedding_chunks_path.resolve()),
        "updated_embedding_text_count": updated_count,
        "suppressed_embedding_text_count": suppressed_count,
    }


def record_official_embedding_qdrant_index_entries(
    connection,
    settings: Settings,
    *,
    chunks_path: Path,
    embedding_chunks_path: Path,
    collection: str,
    limit: int = 0,
) -> dict[str, Any]:
    candidates = build_official_embedding_qdrant_candidates(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_chunks_path,
        limit=limit,
    )
    _target_ids, skipped_ids = official_embedding_target_point_ids(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_chunks_path,
    )
    if limit > 0:
        skipped_ids = []
    if skipped_ids:
        with connection.transaction():
            with connection.cursor() as cursor:
                for chunk_id in skipped_ids:
                    cursor.execute(
                        """
                        DELETE FROM qdrant_index_entries
                        WHERE collection = %s
                          AND chunk_id = %s::uuid
                        """,
                        (collection, chunk_id),
                    )
    record_qdrant_index_entries(
        connection,
        collection=collection,
        vector_model=settings.embedding_model,
        candidates=tuple(candidates),
    )
    return {
        "collection": collection,
        "recorded_index_entry_count": len(candidates),
        "deleted_skipped_index_entry_count": len(skipped_ids),
    }


def ensure_qdrant_collection(settings: Settings, collection: str) -> None:
    url = f"{settings.qdrant_url}/collections/{collection}"
    response = requests.get(url, timeout=settings.request_timeout_seconds)
    if response.status_code == 200:
        return
    create = requests.put(
        url,
        json={"vectors": {"size": settings.qdrant_vector_size, "distance": settings.qdrant_distance}},
        timeout=settings.request_timeout_seconds,
    )
    create.raise_for_status()


def delete_qdrant_points(settings: Settings, collection: str, point_ids: list[str]) -> int:
    deleted = 0
    batch_size = max(1, int(settings.qdrant_upsert_batch_size or 128))
    for start in range(0, len(point_ids), batch_size):
        batch = point_ids[start : start + batch_size]
        response = requests.post(
            f"{settings.qdrant_url}/collections/{collection}/points/delete?wait=true",
            json={"points": batch},
            timeout=max(settings.request_timeout_seconds, 120),
        )
        response.raise_for_status()
        deleted += len(batch)
    return deleted


def _payload_row_from_embedding(
    source_row: dict[str, Any],
    embedding_row: dict[str, Any],
    *,
    embedding_text: str,
    normalized_text: str,
    ordinal: int,
    source_rows: list[dict[str, Any]],
    chunks_path: Path,
    embedding_chunks_path: Path,
) -> dict[str, Any]:
    section_path = _section_path(source_row)
    source_key = _source_key(source_row)
    chunk_id = str(embedding_row.get("chunk_id") or _uuid_from_row_chunk_id(source_row))
    markdown = _normalized_chunk_text(source_row)
    chunk_metadata = _chunk_metadata(source_row)
    chunk_metadata["normalized_text"] = normalized_text
    chunk_metadata["text_layers"] = {
        "version": OFFICIAL_TEXT_LAYERS_VERSION,
        "markdown": markdown,
        "normalized_text": normalized_text,
        "embedding_text": embedding_text,
        "source_embedding_chunks_path": str(embedding_chunks_path.resolve()),
        "quality_warnings": [],
        "rechunk_status": "unchanged",
    }
    source_metadata = _source_metadata(source_key, source_rows, chunks_path)
    return {
        "chunk_id": chunk_id,
        "chunk_key": str(source_row.get("section_id") or source_row.get("anchor") or chunk_id),
        "ordinal": int(source_row.get("ordinal") if source_row.get("ordinal") is not None else ordinal),
        "chunk_type": str(embedding_row.get("chunk_type") or source_row.get("chunk_type") or "reference"),
        "markdown": markdown,
        "embedding_text": embedding_text,
        "section_path": section_path,
        "section_number": _section_number(source_row),
        "heading_title": _heading_title(source_row, section_path),
        "source_anchor": _source_anchor(source_row),
        "toc_path": _toc_path(source_row),
        "asset_ids": source_row.get("asset_ids") or [],
        "repository_id": "",
        "owner_user_id": "",
        "visibility": "global_shared",
        "source_scope": "official_docs",
        "chunk_role": str(embedding_row.get("chunk_role") or source_row.get("chunk_role") or "leaf"),
        "parent_chunk_id": str(embedding_row.get("parent_chunk_id") or source_row.get("parent_chunk_id") or ""),
        "child_chunk_ids": source_row.get("child_chunk_ids") or [],
        "navigation_only": bool(embedding_row.get("navigation_only") or source_row.get("navigation_only") or False),
        "beginner_narrative": str(source_row.get("beginner_narrative") or ""),
        "starter_question_candidates": source_row.get("starter_question_candidates") or [],
        "followup_question_candidates": source_row.get("followup_question_candidates") or [],
        "question_candidates_version": int(source_row.get("question_candidates_version") or 0),
        "chunk_metadata": chunk_metadata,
        "parsed_document_id": str(source_row.get("parsed_artifact_id") or _stable_uuid("official-gold-parsed-document", source_key)),
        "document_title": _source_title(source_rows),
        "parsed_metadata": {"document_format": "official_gold_jsonl", "source_key": source_key},
        "document_source_id": _stable_uuid("official-gold-source", source_key),
        "filename": f"{str(source_row.get('book_slug') or source_key)}.jsonl",
        "storage_key": str(chunks_path.resolve()),
        "source_kind": "official_gold",
        "source_metadata": source_metadata,
        "created_by": "",
    }


def _load_embedding_rows(path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.resolve().open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def _group_source_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_source_key(row), []).append(row)
    return grouped


def _candidate_quality_summary(candidates: tuple[QdrantChunkCandidate, ...]) -> dict[str, int]:
    counts = {
        "empty_text": 0,
        "internal_marker_or_fence": 0,
        "html_anchor_or_docs_url": 0,
        "percent_encoded": 0,
        "broken_dot_placeholder": 0,
        "html_entity_angle": 0,
        "tab": 0,
        "arabic": 0,
        "embedding_not_flat": 0,
        "quote": 0,
        "raw_text_payload_keys": 0,
        "payload_text_mismatch": 0,
        "normalized_not_flat": 0,
    }
    for candidate in candidates:
        text = candidate.embedding_text
        payload_text = str(candidate.payload.get("text") or "")
        text_fields = candidate.payload.get("text_fields") if isinstance(candidate.payload.get("text_fields"), dict) else {}
        normalized_text = str(text_fields.get("normalized_text") or "")
        payload_embedding_text = str(text_fields.get("embedding_text") or "")
        payload_dump = json.dumps(candidate.payload, ensure_ascii=False)
        if not text.strip():
            counts["empty_text"] += 1
        if any(marker in text for marker in ("[CODE", "[/CODE]", "[TABLE", "[/TABLE]", "```")):
            counts["internal_marker_or_fence"] += 1
        if "<a href" in text.lower() or "docs.redhat.com" in text or "/docs/ocp/" in text:
            counts["html_anchor_or_docs_url"] += 1
        if re.search(r"%[0-9A-Fa-f]{2}", text):
            counts["percent_encoded"] += 1
        if re.search(r"<\.\s*[A-Za-z_]", text):
            counts["broken_dot_placeholder"] += 1
        if "&lt;" in text or "&gt;" in text or "& lt;" in text or "& gt;" in text:
            counts["html_entity_angle"] += 1
        if "\t" in text:
            counts["tab"] += 1
        if re.search(ARABIC_RE, text):
            counts["arabic"] += 1
        if "\n" in text or "\r" in text or "\t" in text:
            counts["embedding_not_flat"] += 1
        if '"' in text or "'" in text:
            counts["quote"] += 1
        if '"raw_text"' in payload_dump:
            counts["raw_text_payload_keys"] += 1
        if payload_text != payload_embedding_text or payload_embedding_text != text:
            counts["payload_text_mismatch"] += 1
        if "\n" in normalized_text or "\t" in normalized_text or "|" in normalized_text:
            counts["normalized_not_flat"] += 1
    return counts


def _validate_candidates(
    candidates: tuple[QdrantChunkCandidate, ...],
    *,
    expected_vector_size: int,
    validate_vectors: bool,
) -> None:
    if not candidates:
        raise ValueError("No official embedding Qdrant candidates were loaded")
    ids = [candidate.point_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("Official embedding Qdrant candidates contain duplicate point ids")
    quality = _candidate_quality_summary(candidates)
    hard_failures = {key: value for key, value in quality.items() if value}
    if hard_failures:
        raise ValueError(f"Embedding chunk quality gate failed: {hard_failures}")
    if validate_vectors:
        _validate_vectors([], expected_vector_size=expected_vector_size)


def _validate_vectors(vectors: list[list[float]], *, expected_vector_size: int) -> None:
    for index, vector in enumerate(vectors):
        if len(vector) != expected_vector_size:
            raise ValueError(f"Vector at batch offset {index} has size {len(vector)}, expected {expected_vector_size}")
        if any(not math.isfinite(float(value)) for value in vector):
            raise ValueError(f"Vector at batch offset {index} contains NaN or Inf")


def _upsert_candidates(
    settings: Settings,
    collection: str,
    candidates: tuple[QdrantChunkCandidate, ...],
    vectors: list[list[float]],
) -> None:
    if len(candidates) != len(vectors):
        raise ValueError("candidate count and vector count do not match")
    points = [
        {"id": candidate.point_id, "vector": vector, "payload": candidate.payload}
        for candidate, vector in zip(candidates, vectors, strict=True)
    ]
    batch_size = max(1, int(settings.qdrant_upsert_batch_size or 128))
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        response = requests.put(
            f"{settings.qdrant_url}/collections/{collection}/points?wait=true",
            json={"points": batch},
            timeout=max(settings.request_timeout_seconds, 120),
        )
        response.raise_for_status()


__all__ = [
    "build_official_embedding_qdrant_candidates",
    "delete_qdrant_points",
    "official_embedding_target_point_ids",
    "record_official_embedding_qdrant_index_entries",
    "sync_official_embedding_chunks_to_database",
    "upsert_official_embedding_chunks_to_qdrant",
]
