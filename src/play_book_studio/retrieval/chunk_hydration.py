"""Hydrate retrieval hits with canonical PostgreSQL document chunk rows."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from play_book_studio.db.qdrant_indexer import qdrant_payload_from_row

from .models import RetrievalHit
from .vector import hit_from_payload


def hydrate_retrieval_hits(connection, hits: list[RetrievalHit]) -> list[RetrievalHit]:
    """Return hits rebuilt from canonical DB rows when their chunk still exists."""
    if not hits:
        return []

    ordered_chunk_ids = _ordered_unique_chunk_ids(hits)
    rows_by_chunk_id = load_document_chunk_payload_rows(
        connection,
        chunk_ids=ordered_chunk_ids,
    )
    hydrated: list[RetrievalHit] = []
    for hit in hits:
        row = rows_by_chunk_id.get(hit.chunk_id)
        if row is None:
            hydrated.append(hit)
            continue
        canonical = hit_from_payload(
            qdrant_payload_from_row(row),
            source=hit.source,
            score=hit.raw_score,
        )
        hydrated.append(
            replace(
                canonical,
                fused_score=hit.fused_score,
                component_scores=dict(hit.component_scores),
            )
        )
    return hydrated


def load_document_chunk_payload_rows(
    connection,
    *,
    chunk_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Load qdrant-payload-compatible chunk rows keyed by chunk id."""
    clean_chunk_ids = _ordered_unique_text_values(chunk_ids)
    if not clean_chunk_ids:
        return {}

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
            WHERE c.id::text = ANY(%s)
            """,
            (clean_chunk_ids,),
        )
        rows = cursor.fetchall()
        columns = _cursor_column_names(cursor)
    return {
        str(row_dict["chunk_id"]): row_dict
        for row_dict in (dict(zip(columns, row, strict=True)) for row in rows)
    }


def _ordered_unique_chunk_ids(hits: list[RetrievalHit]) -> list[str]:
    return _ordered_unique_text_values([hit.chunk_id for hit in hits])


def _ordered_unique_text_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _cursor_column_names(cursor) -> list[str]:
    names: list[str] = []
    for item in cursor.description:
        name = getattr(item, "name", None)
        names.append(str(name if name is not None else item[0]))
    return names


__all__ = [
    "hydrate_retrieval_hits",
    "load_document_chunk_payload_rows",
]
