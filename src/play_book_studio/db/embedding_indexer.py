"""Index PostgreSQL document chunks into pgvector-backed chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.embedding import EmbeddingClient
from play_book_studio.retrieval.payload import (
    retrieval_payload_from_row,
    retrieval_payload_hash,
    text_hash,
    vector_literal,
)


@dataclass(frozen=True, slots=True)
class EmbeddingChunkCandidate:
    chunk_id: str
    embedding_text: str
    embedding_text_hash: str
    payload: dict[str, Any]
    payload_hash: str


def _uuid_or_empty(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return ""


def load_embedding_chunk_candidates(
    connection,
    *,
    model: str,
    source_scope: str = "",
    document_source_id: str = "",
    limit: int = 100,
) -> tuple[EmbeddingChunkCandidate, ...]:
    scope = source_scope.strip()
    raw_source_id = str(document_source_id or "").strip()
    source_id = _uuid_or_empty(raw_source_id)
    if raw_source_id and not source_id:
        raise ValueError("document_source_id must be a valid UUID")
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
                ce.embedding_text_hash AS indexed_embedding_text_hash,
                ce.payload_hash AS indexed_payload_hash
            FROM document_chunks c
            JOIN parsed_documents pd ON pd.id = c.parsed_document_id
            JOIN document_sources ds ON ds.id = pd.document_source_id
            LEFT JOIN chunk_embeddings ce
                ON ce.chunk_id = c.id AND ce.model = %s
            WHERE length(btrim(COALESCE(c.embedding_text, ''))) > 0
                AND (%s = '' OR c.source_scope = %s)
                AND (%s = '' OR ds.id = %s::uuid)
                AND (
                    c.source_scope <> 'user_upload'
                    OR pd.id = (
                        SELECT latest_pd.id
                        FROM parsed_documents latest_pd
                        WHERE latest_pd.document_source_id = ds.id
                        ORDER BY latest_pd.created_at DESC, latest_pd.id DESC
                        LIMIT 1
                    )
                )
                AND (
                    ce.chunk_id IS NULL
                    OR ce.embedding_text_hash <> encode(digest(c.embedding_text, 'sha256'), 'hex')
                )
            ORDER BY c.created_at ASC, c.ordinal ASC
            LIMIT %s
            """,
            (model, scope, scope, source_id, source_id or None, int(limit)),
        )
        rows = cursor.fetchall()
        columns = _cursor_column_names(cursor)

    candidates: list[EmbeddingChunkCandidate] = []
    for row in rows:
        row_dict = dict(zip(columns, row, strict=True))
        payload = retrieval_payload_from_row(row_dict)
        candidate = EmbeddingChunkCandidate(
            chunk_id=str(row_dict["chunk_id"]),
            embedding_text=str(row_dict.get("embedding_text") or ""),
            embedding_text_hash=text_hash(str(row_dict.get("embedding_text") or "")),
            payload=payload,
            payload_hash=retrieval_payload_hash(payload),
        )
        if (
            candidate.embedding_text_hash != str(row_dict.get("indexed_embedding_text_hash") or "")
            or candidate.payload_hash != str(row_dict.get("indexed_payload_hash") or "")
        ):
            candidates.append(candidate)
    return tuple(candidates)


def load_stale_embedding_count(connection, *, model: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(1)::int
            FROM chunk_embeddings ce
            JOIN document_chunks c ON c.id = ce.chunk_id
            WHERE ce.model = %s
              AND ce.embedding_text_hash <> encode(digest(c.embedding_text, 'sha256'), 'hex')
            """,
            (model,),
        )
        return int((cursor.fetchone() or [0])[0] or 0)


def upsert_chunk_embeddings(
    connection,
    *,
    model: str,
    candidates: tuple[EmbeddingChunkCandidate, ...],
    vectors: list[list[float]],
) -> None:
    if len(candidates) != len(vectors):
        raise ValueError("candidate count and vector count do not match")
    with connection.transaction():
        with connection.cursor() as cursor:
            for candidate, vector in zip(candidates, vectors, strict=True):
                cursor.execute(
                    """
                    INSERT INTO chunk_embeddings (
                        chunk_id, model, embedding, embedding_text_hash, payload_hash
                    )
                    VALUES (%s, %s, %s::vector, %s, %s)
                    ON CONFLICT (chunk_id, model) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        embedding_text_hash = EXCLUDED.embedding_text_hash,
                        payload_hash = EXCLUDED.payload_hash,
                        updated_at = now()
                    """,
                    (
                        candidate.chunk_id,
                        model,
                        vector_literal(vector),
                        candidate.embedding_text_hash,
                        candidate.payload_hash,
                    ),
                )


def index_pending_document_chunks(
    settings: Settings,
    connection,
    *,
    collection: str | None = None,
    source_scope: str = "",
    document_source_id: str = "",
    limit: int = 100,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    del collection
    model = settings.embedding_model
    candidates = load_embedding_chunk_candidates(
        connection,
        model=model,
        source_scope=source_scope,
        document_source_id=document_source_id,
        limit=limit,
    )
    if not candidates:
        return {
            "backend": "pgvector",
            "model": model,
            "source_scope": source_scope.strip(),
            "document_source_id": _uuid_or_empty(document_source_id),
            "candidate_count": 0,
            "indexed_count": 0,
        }
    client = embedding_client or EmbeddingClient(settings)
    vectors = client.embed_texts(candidate.embedding_text for candidate in candidates)
    upsert_chunk_embeddings(
        connection,
        model=model,
        candidates=candidates,
        vectors=vectors,
    )
    return {
        "backend": "pgvector",
        "model": model,
        "source_scope": source_scope.strip(),
        "document_source_id": _uuid_or_empty(document_source_id),
        "candidate_count": len(candidates),
        "indexed_count": len(candidates),
    }


def _cursor_column_names(cursor) -> list[str]:
    names: list[str] = []
    for item in cursor.description:
        name = getattr(item, "name", None)
        names.append(str(name if name is not None else item[0]))
    return names


__all__ = [
    "EmbeddingChunkCandidate",
    "index_pending_document_chunks",
    "load_embedding_chunk_candidates",
    "load_stale_embedding_count",
    "upsert_chunk_embeddings",
]
