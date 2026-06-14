"""PostgreSQL read helpers for official document source metadata."""

from __future__ import annotations

from typing import Any


def load_official_manifest_entries(connection_or_url: Any) -> list[dict[str, Any]]:
    """Return manifest-shaped official document metadata from canonical DB rows."""

    if isinstance(connection_or_url, str):
        database_url = connection_or_url.strip()
        if not database_url:
            return []
        try:
            import psycopg
        except Exception:  # noqa: BLE001
            return []
        try:
            with psycopg.connect(database_url) as connection:
                return load_official_manifest_entries(connection)
        except Exception:  # noqa: BLE001
            return []

    connection = connection_or_url
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COALESCE(NULLIF(ds.metadata->>'book_slug', ''), ds.filename) AS book_slug,
                    COALESCE(NULLIF(pd.title, ''), NULLIF(ds.metadata->>'title', ''), ds.filename) AS title,
                    COALESCE(NULLIF(ds.metadata->>'viewer_path', ''), '') AS viewer_path,
                    COALESCE(NULLIF(ds.metadata->>'source_url', ''), NULLIF(ds.metadata->>'resolved_source_url', ''), '') AS source_url,
                    COALESCE(NULLIF(ds.metadata->>'source_relative_path', ''), NULLIF(ds.metadata->>'source_path', ''), '') AS source_relative_path,
                    ds.source_kind,
                    ds.source_scope,
                    ds.visibility,
                    ds.metadata,
                    count(dc.id)::int AS chunk_count,
                    count(DISTINCT NULLIF(dc.source_anchor, ''))::int AS section_count
                FROM document_sources ds
                LEFT JOIN LATERAL (
                    SELECT id, title
                    FROM parsed_documents
                    WHERE document_source_id = ds.id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) pd ON true
                LEFT JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                WHERE ds.source_scope = 'official_docs'
                GROUP BY ds.id, pd.title
                ORDER BY book_slug
                """
            )
            rows = cursor.fetchall()
    except Exception:  # noqa: BLE001
        return []

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for (
        book_slug,
        title,
        viewer_path,
        source_url,
        source_relative_path,
        source_kind,
        source_scope,
        visibility,
        metadata,
        chunk_count,
        section_count,
    ) in rows:
        slug = str(book_slug or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        meta = metadata if isinstance(metadata, dict) else {}
        topic_path = _list_field(meta.get("topic_path") or meta.get("section_path") or meta.get("toc_path"))
        section_family = _list_field(meta.get("section_family"))
        entries.append(
            {
                "book_slug": slug,
                "title": str(title or slug.replace("_", " ").title()).strip(),
                "viewer_path": str(viewer_path or f"/playbooks/wiki-runtime/active/{slug}/index.html").strip(),
                "docs_viewer_path": str(viewer_path or f"/playbooks/wiki-runtime/active/{slug}/index.html").strip(),
                "source_url": str(source_url or "").strip(),
                "source_candidate_path": str(source_url or "").strip(),
                "source_relative_path": str(source_relative_path or "").strip(),
                "source_kind": str(meta.get("source_kind") or source_kind or "").strip(),
                "source_scope": str(source_scope or "official_docs").strip(),
                "source_lane": str(meta.get("source_lane") or "official_docs").strip(),
                "visibility": str(visibility or "global_shared").strip(),
                "grade": str(meta.get("grade") or "Gold").strip(),
                "approval_state": str(meta.get("approval_state") or meta.get("approval_status") or "approved").strip(),
                "publication_state": str(meta.get("publication_state") or "published").strip(),
                "parser_backend": str(meta.get("parser_backend") or meta.get("parser_name") or "postgres").strip(),
                "topic_path": topic_path,
                "section_family": section_family,
                "source_relative_paths": _list_field(meta.get("source_relative_paths")),
                "chunk_count": int(chunk_count or 0),
                "section_count": int(section_count or chunk_count or 0),
                "metadata": dict(meta),
            }
        )
    return entries


def _list_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    normalized = str(value).strip()
    return [normalized] if normalized else []


__all__ = ["load_official_manifest_entries"]
