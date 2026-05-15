"""Backfill deterministic metadata spine onto existing document chunks."""

from __future__ import annotations

import json
from typing import Any

from play_book_studio.ingestion.metadata_spine import build_chunk_metadata_spine


def _json(value: Any) -> str:
    return json.dumps(_sanitize_postgres_value(value), ensure_ascii=False)


def _sanitize_postgres_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {str(key): _sanitize_postgres_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_postgres_value(item) for item in value]
    return value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return (value.strip(),)
        return _string_tuple(parsed)
    return ()


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _merge_metadata(existing: dict[str, Any], spine: dict[str, Any]) -> dict[str, Any]:
    merged = {**existing, **spine}
    # Keep provenance compact and inspectable instead of burying this as a silent mutation.
    merged["metadata_spine_source"] = "deterministic_backfill"
    return merged


def backfill_metadata_spine(
    connection,
    *,
    source_scope: str = "",
    limit: int = 0,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Fill answer-ready metadata on existing chunks.

    This intentionally uses deterministic rules only. It updates chunk metadata, then
    Qdrant payload refresh can propagate those fields to vector search payloads.
    """

    scope = source_scope.strip()
    effective_limit = max(0, int(limit or 0))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.id::text,
                COALESCE(c.markdown, '') AS markdown,
                COALESCE(c.embedding_text, '') AS embedding_text,
                COALESCE(c.section_path, '[]'::jsonb) AS section_path,
                COALESCE(c.chunk_type, '') AS chunk_type,
                COALESCE(c.metadata, '{}'::jsonb) AS metadata,
                COALESCE(c.source_scope, ds.source_scope, '') AS source_scope,
                COALESCE(c.heading_title, '') AS heading_title,
                COALESCE(ds.filename, '') AS filename
            FROM document_chunks c
            JOIN parsed_documents pd ON pd.id = c.parsed_document_id
            JOIN document_sources ds ON ds.id = pd.document_source_id
            WHERE (%s = '' OR c.source_scope = %s)
              AND (%s OR COALESCE(c.metadata->>'metadata_spine_schema', '') <> 'metadata_spine_v1')
            ORDER BY c.created_at ASC, c.ordinal ASC
            LIMIT CASE WHEN %s > 0 THEN %s ELSE 2147483647 END
            """,
            (scope, scope, bool(force), effective_limit, effective_limit),
        )
        rows = cursor.fetchall()

    scanned = len(rows)
    updated = 0
    by_scope: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    updates: list[tuple[str, str]] = []

    for row in rows:
        (
            chunk_id,
            markdown,
            embedding_text,
            section_path,
            chunk_type,
            metadata,
            row_scope,
            heading_title,
            filename,
        ) = row
        existing = _dict(metadata)
        path = _string_tuple(section_path)
        if heading_title and heading_title not in path:
            path = (*path, str(heading_title))
        text = str(embedding_text or markdown or "")
        spine = build_chunk_metadata_spine(
            text,
            section_path=path,
            filename=str(filename or ""),
            source_scope=str(row_scope or ""),
            block_kinds=_string_tuple(existing.get("block_kinds")) or (str(chunk_type or ""),),
            existing_metadata=existing,
        )
        merged = _merge_metadata(existing, spine)
        if merged == existing:
            continue
        updated += 1
        row_scope_key = str(row_scope or "")
        by_scope[row_scope_key] = by_scope.get(row_scope_key, 0) + 1
        confidence = str(spine.get("metadata_confidence") or "low")
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
        role = str(spine.get("semantic_role") or "concept")
        role_counts[role] = role_counts.get(role, 0) + 1
        if len(examples) < 8:
            examples.append(
                {
                    "chunk_id": str(chunk_id),
                    "source_scope": row_scope_key,
                    "topic": spine.get("topic"),
                    "semantic_role": role,
                    "metadata_confidence": confidence,
                    "k8s_objects": list(spine.get("k8s_objects") or [])[:5],
                    "cli_commands": list(spine.get("cli_commands") or [])[:3],
                    "answerable_questions": list(spine.get("answerable_questions") or [])[:2],
                }
            )
        updates.append((_json(merged), str(chunk_id)))

    if updates and not dry_run:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE document_chunks
                SET metadata = %s::jsonb
                WHERE id = %s::uuid
                """,
                updates,
            )
        connection.commit()

    return {
        "schema": "metadata_spine_backfill_v1",
        "source_scope": scope,
        "dry_run": bool(dry_run),
        "force": bool(force),
        "scanned_count": scanned,
        "updated_count": updated,
        "updated_by_scope": by_scope,
        "metadata_confidence": confidence_counts,
        "semantic_roles": role_counts,
        "examples": examples,
    }


__all__ = ["backfill_metadata_spine"]
