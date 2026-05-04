"""PostgreSQL corpus readiness summaries for deployment/runtime checks."""

from __future__ import annotations

from typing import Any


def load_corpus_status(connection, *, collection: str) -> dict[str, Any]:
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
            FROM qdrant_index_entries
            WHERE collection = %s
            """,
            (collection,),
        )
        qdrant_entries = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute(
            """
            SELECT count(1)::int
            FROM document_chunks c
            LEFT JOIN qdrant_index_entries q
                ON q.chunk_id = c.id AND q.collection = %s
            WHERE q.chunk_id IS NULL
            """,
            (collection,),
        )
        missing_qdrant_entries = int((cursor.fetchone() or [0])[0] or 0)

    expected_scopes = ("official_docs", "study_docs")
    return {
        "database": "postgres",
        "collection": collection,
        "source_counts": source_counts,
        "chunk_counts": chunk_counts,
        "total_sources": sum(source_counts.values()),
        "total_chunks": total_chunks,
        "qdrant_index_entries": qdrant_entries,
        "missing_qdrant_index_entries": missing_qdrant_entries,
        "qdrant_index_parity": total_chunks == qdrant_entries and missing_qdrant_entries == 0,
        "has_official_docs": chunk_counts.get("official_docs", 0) > 0,
        "has_study_docs": chunk_counts.get("study_docs", 0) > 0,
        "ready_scopes": [scope for scope in expected_scopes if chunk_counts.get(scope, 0) > 0],
        "ready": all(chunk_counts.get(scope, 0) > 0 for scope in expected_scopes)
        and total_chunks > 0
        and total_chunks == qdrant_entries
        and missing_qdrant_entries == 0,
    }


def disabled_corpus_status() -> dict[str, Any]:
    return {
        "database": "disabled",
        "collection": "",
        "source_counts": {},
        "chunk_counts": {},
        "total_sources": 0,
        "total_chunks": 0,
        "qdrant_index_entries": 0,
        "missing_qdrant_index_entries": 0,
        "qdrant_index_parity": False,
        "has_official_docs": False,
        "has_study_docs": False,
        "ready_scopes": [],
        "ready": False,
    }


def build_corpus_status(
    *,
    database_url: str,
    collection: str,
) -> dict[str, Any]:
    if not database_url.strip():
        return disabled_corpus_status()
    import psycopg

    try:
        with psycopg.connect(database_url) as connection:
            return load_corpus_status(connection, collection=collection)
    except Exception as exc:  # noqa: BLE001
        payload = disabled_corpus_status()
        payload["database"] = "error"
        payload["collection"] = collection
        payload["error"] = str(exc)
        return payload


__all__ = [
    "build_corpus_status",
    "disabled_corpus_status",
    "load_corpus_status",
]
