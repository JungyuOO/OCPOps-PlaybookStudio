"""PostgreSQL corpus readiness summaries for deployment/runtime checks."""

from __future__ import annotations

from typing import Any


def load_corpus_status(connection, *, embedding_model: str) -> dict[str, Any]:
    model = embedding_model.strip()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_scope, count(1)::int
            FROM document_sources
            GROUP BY source_scope
            ORDER BY source_scope
            """
        )
        source_counts = {str(row[0] or ""): int(row[1] or 0) for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT source_scope, count(1)::int
            FROM document_chunks
            GROUP BY source_scope
            ORDER BY source_scope
            """
        )
        chunk_counts = {str(row[0] or ""): int(row[1] or 0) for row in cursor.fetchall()}
        cursor.execute(
            """
            SELECT count(1)::int
            FROM document_chunks
            """
        )
        total_chunks = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            """
            SELECT count(1)::int
            FROM document_chunks
            WHERE length(btrim(COALESCE(embedding_text, ''))) > 0
            """
        )
        indexable_chunks = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            """
            SELECT count(1)::int
            FROM chunk_embeddings
            WHERE model = %s
            """,
            (model,),
        )
        embedding_entries = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            """
            SELECT count(1)::int
            FROM document_chunks c
            LEFT JOIN chunk_embeddings ce
                ON ce.chunk_id = c.id AND ce.model = %s
            WHERE length(btrim(COALESCE(c.embedding_text, ''))) > 0
                AND ce.chunk_id IS NULL
            """,
            (model,),
        )
        missing_embedding_entries = int((cursor.fetchone() or [0])[0] or 0)
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
        stale_embedding_entries = int((cursor.fetchone() or [0])[0] or 0)

    expected_scopes = ("official_docs", "study_docs")
    embedding_index_parity = (
        indexable_chunks == embedding_entries
        and missing_embedding_entries == 0
        and stale_embedding_entries == 0
    )
    return {
        "database": "postgres",
        "vector_backend": "pgvector",
        "embedding_model": model,
        "source_counts": source_counts,
        "chunk_counts": chunk_counts,
        "total_sources": sum(source_counts.values()),
        "total_chunks": total_chunks,
        "indexable_chunks": indexable_chunks,
        "non_indexable_chunks": max(total_chunks - indexable_chunks, 0),
        "embedding_index_entries": embedding_entries,
        "missing_embedding_index_entries": missing_embedding_entries,
        "stale_embedding_index_entries": stale_embedding_entries,
        "embedding_index_parity": embedding_index_parity,
        "has_official_docs": chunk_counts.get("official_docs", 0) > 0,
        "has_study_docs": chunk_counts.get("study_docs", 0) > 0,
        "ready_scopes": [scope for scope in expected_scopes if chunk_counts.get(scope, 0) > 0],
        "ready": all(chunk_counts.get(scope, 0) > 0 for scope in expected_scopes)
        and indexable_chunks > 0
        and embedding_index_parity,
    }


def disabled_corpus_status() -> dict[str, Any]:
    return {
        "database": "disabled",
        "vector_backend": "pgvector",
        "embedding_model": "",
        "source_counts": {},
        "chunk_counts": {},
        "total_sources": 0,
        "total_chunks": 0,
        "indexable_chunks": 0,
        "non_indexable_chunks": 0,
        "embedding_index_entries": 0,
        "missing_embedding_index_entries": 0,
        "stale_embedding_index_entries": 0,
        "embedding_index_parity": False,
        "has_official_docs": False,
        "has_study_docs": False,
        "ready_scopes": [],
        "ready": False,
    }


def build_corpus_status(
    *,
    database_url: str,
    embedding_model: str,
) -> dict[str, Any]:
    if not database_url.strip():
        return disabled_corpus_status()
    import psycopg

    try:
        with psycopg.connect(database_url) as connection:
            return load_corpus_status(connection, embedding_model=embedding_model)
    except Exception as exc:  # noqa: BLE001
        payload = disabled_corpus_status()
        payload["database"] = "error"
        payload["embedding_model"] = embedding_model.strip()
        payload["error"] = str(exc)
        return payload


__all__ = [
    "build_corpus_status",
    "disabled_corpus_status",
    "load_corpus_status",
]
