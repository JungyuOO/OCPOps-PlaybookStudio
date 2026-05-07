from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings


def _status_message(status: str, indexed_count: int, chunk_count: int) -> str:
    if status in {"failed", "error"}:
        return "문서 처리에 실패했습니다."
    if status not in {"completed", "done", "ready"}:
        return "문서 파싱중입니다."
    if chunk_count and indexed_count < chunk_count:
        return "인덱싱중입니다."
    return "문서 준비가 완료되었습니다."


def build_document_status_response(root_dir: Path, query: str) -> dict[str, Any]:
    database_url = load_settings(root_dir).database_url.strip()
    if not database_url:
        return {"database": "disabled", "count": 0, "items": []}

    params = parse_qs(query, keep_blank_values=False)
    repository_id = str((params.get("repository_id") or [""])[0] or "").strip()
    document_source_id = str((params.get("document_source_id") or params.get("id") or [""])[0] or "").strip()

    where = ["1=1"]
    values: list[Any] = []
    if repository_id:
        where.append("ds.repository_id = %s::uuid")
        values.append(repository_id)
    if document_source_id:
        where.append("ds.id = %s::uuid")
        values.append(document_source_id)
    values.append(50)

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    ds.id::text AS document_source_id,
                    ds.repository_id::text AS repository_id,
                    ds.filename AS title,
                    ds.filename AS original_filename,
                    ds.source_scope,
                    ds.visibility,
                    pj.id::text AS parse_job_id,
                    COALESCE(pj.status, '') AS parse_status,
                    COALESCE(pj.error_message, '') AS error_message,
                    COALESCE(chunk_counts.chunk_count, 0) AS chunk_count,
                    COALESCE(index_counts.indexed_count, 0) AS indexed_count,
                    GREATEST(
                        COALESCE(pj.completed_at, pj.started_at, pj.created_at, ds.created_at),
                        ds.created_at
                    ) AS updated_at
                FROM document_sources ds
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM parse_jobs pj
                    WHERE pj.document_source_id = ds.id
                    ORDER BY pj.created_at DESC
                    LIMIT 1
                ) pj ON TRUE
                LEFT JOIN LATERAL (
                    SELECT count(*)::int AS chunk_count
                    FROM parsed_documents pd
                    JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                    WHERE pd.document_source_id = ds.id
                ) chunk_counts ON TRUE
                LEFT JOIN LATERAL (
                    SELECT count(*)::int AS indexed_count
                    FROM parsed_documents pd
                    JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                    JOIN qdrant_index_entries q ON q.chunk_id = dc.id
                    WHERE pd.document_source_id = ds.id
                ) index_counts ON TRUE
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                values,
            )
            rows = cursor.fetchall()

    items = []
    for row in rows:
        status = str(row.get("parse_status") or "queued")
        chunk_count = int(row.get("chunk_count") or 0)
        indexed_count = int(row.get("indexed_count") or 0)
        ready = status in {"completed", "done", "ready"} and (not chunk_count or indexed_count >= chunk_count)
        items.append({
            **dict(row),
            "ready": ready,
            "status": "ready" if ready else status,
            "message": _status_message(status, indexed_count, chunk_count),
        })

    return {
        "database": "postgres",
        "count": len(items),
        "items": items,
        "latest": items[0] if items else None,
    }


def handle_document_status(handler: Any, query: str, *, root_dir: Path) -> None:
    try:
        payload = build_document_status_response(root_dir, query)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"document status load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


__all__ = ["build_document_status_response", "handle_document_status"]
