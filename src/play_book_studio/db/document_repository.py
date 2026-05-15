"""Persistence helpers for parsed upload documents."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from play_book_studio.ingestion.document_parsing import (
    DocumentChunk,
    ParsedUploadDocument,
    build_document_chunks,
)


@dataclass(frozen=True, slots=True)
class ParsedDocumentRows:
    source: dict[str, Any]
    parsed_document: dict[str, Any]
    blocks: tuple[dict[str, Any], ...]
    assets: tuple[dict[str, Any], ...]
    chunks: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class StoredParsedDocument:
    document_source_id: str
    document_version_id: str
    parse_job_id: str
    parsed_document_id: str
    repository_id: str
    block_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]


def build_parsed_document_rows(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...] | None = None,
    *,
    storage_key: str = "",
    created_by: str = "",
    repository_id: str = "",
    visibility: str = "",
    source_scope: str = "user_upload",
) -> ParsedDocumentRows:
    document_chunks = chunks if chunks is not None else build_document_chunks(parsed)
    block_id_by_asset_id = _block_id_by_asset_id(parsed)
    storage_key = storage_key or f"uploads/sources/{parsed.document_id}/{parsed.filename}"
    source = {
        "source_kind": "upload",
        "filename": parsed.filename,
        "mime_type": parsed.mime_type,
        "sha256": parsed.sha256,
        "storage_key": storage_key,
        "byte_size": int(parsed.metadata.get("byte_size") or 0),
        "access_policy": {},
        "repository_id": repository_id,
        "owner_user_id": created_by,
        "visibility": visibility or ("private_user" if created_by else "workspace_shared"),
        "source_scope": source_scope or "user_upload",
        "metadata": {
            "document_id": parsed.document_id,
            "document_format": parsed.document_format,
            **dict(parsed.metadata),
        },
        "created_by": created_by,
    }
    parsed_document = {
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "title": _title_from_parsed(parsed),
        "markdown": parsed.markdown,
        "metadata": {
            "document_id": parsed.document_id,
            "document_format": parsed.document_format,
            "status": parsed.status,
            **dict(parsed.metadata),
        },
        "outline": _outline_from_blocks(parsed),
        "warnings": list(parsed.warnings),
    }
    blocks = tuple(
        {
            "id": block.block_id,
            "ordinal": block.ordinal,
            "block_type": block.block_type,
            "heading_level": block.heading_level,
            "page_number": block.metadata.get("page_number"),
            "text": block.text,
            "markdown": block.markdown,
            "section_path": list(block.section_path),
            "section_number": block.section_number,
            "heading_title": block.heading_title,
            "source_anchor": block.source_anchor,
            "toc_path": list(block.toc_path),
            "bbox": block.metadata.get("bbox") or {},
            "table_data": block.metadata.get("table_data") or {},
            "metadata": {
                **dict(block.metadata),
                "asset_ids": list(block.asset_ids),
            },
        }
        for block in parsed.blocks
    )
    assets = tuple(
        {
            "id": asset.asset_id,
            "block_id": block_id_by_asset_id.get(asset.asset_id),
            "asset_type": asset.asset_type,
            "mime_type": asset.mime_type,
            "storage_key": asset.storage_key,
            "sha256": asset.sha256,
            "width": asset.metadata.get("width"),
            "height": asset.metadata.get("height"),
            "page_number": asset.page_number,
            "bbox": asset.metadata.get("bbox") or {},
            "caption_text": asset.metadata.get("caption_text") or "",
            "ocr_text": asset.ocr_text,
            "qwen_description": asset.description,
            "qwen_model": asset.metadata.get("qwen_model") or "",
            "metadata": {
                **dict(asset.metadata),
                "filename": asset.filename,
            },
        }
        for asset in parsed.assets
    )
    chunk_rows = tuple(
        {
            "id": chunk.chunk_id,
            "chunk_key": chunk.chunk_key,
            "ordinal": chunk.ordinal,
            "chunk_type": chunk.metadata.get("chunk_type") or "document",
            "markdown": chunk.markdown,
            "embedding_text": chunk.embedding_text,
            "token_count": _approx_token_count(chunk.embedding_text),
            "page_start": chunk.metadata.get("page_start"),
            "page_end": chunk.metadata.get("page_end"),
            "section_path": list(chunk.section_path),
            "section_number": chunk.section_number,
            "heading_title": chunk.heading_title,
            "source_anchor": chunk.source_anchor,
            "toc_path": list(chunk.toc_path),
            "asset_ids": list(chunk.asset_ids),
            "metadata": {
                **dict(chunk.metadata),
                "block_ordinals": list(chunk.block_ordinals),
            },
        }
        for chunk in document_chunks
    )
    return ParsedDocumentRows(
        source=source,
        parsed_document=parsed_document,
        blocks=blocks,
        assets=assets,
        chunks=chunk_rows,
    )


def persist_parsed_upload_document(
    connection,
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...] | None = None,
    *,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    storage_key: str = "",
    created_by: str = "",
    repository_id: str = "",
    repository_slug: str = "",
    repository_title: str = "",
    repository_kind: str = "",
    visibility: str = "",
    source_scope: str = "user_upload",
) -> StoredParsedDocument:
    rows = build_parsed_document_rows(
        parsed,
        chunks,
        storage_key=storage_key,
        created_by=created_by,
        repository_id=repository_id,
        visibility=visibility,
        source_scope=source_scope,
    )
    with connection.transaction():
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_slug=tenant_slug, tenant_name=tenant_name)
            workspace_id = _upsert_workspace(
                cursor,
                tenant_id=tenant_id,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
            )
            source_repository_id = rows.source["repository_id"]
            if not source_repository_id:
                source_repository_id = _upsert_repository(
                    cursor,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    owner_user_id=created_by,
                    slug=repository_slug or ("personal-uploads" if created_by else "workspace-uploads"),
                    title=repository_title or ("My Uploads" if created_by else "Workspace Uploads"),
                    repository_kind=repository_kind or ("personal" if created_by else "workspace"),
                    visibility=rows.source["visibility"],
                )
                rows.source["repository_id"] = source_repository_id
            source_id = _upsert_document_source(
                cursor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                row=rows.source,
            )
            version_id = _insert_document_version(cursor, source_id=source_id, row=rows.source)
            parse_job_id = _insert_parse_job(
                cursor,
                source_id=source_id,
                version_id=version_id,
                parsed=parsed,
            )
            parsed_document_id = _insert_parsed_document(
                cursor,
                source_id=source_id,
                version_id=version_id,
                parse_job_id=parse_job_id,
                row=rows.parsed_document,
            )
            block_ids = tuple(
                _insert_document_block(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in rows.blocks
            )
            asset_ids = tuple(
                _insert_document_asset(
                    cursor,
                    source_id=source_id,
                    parsed_document_id=parsed_document_id,
                    row=row,
                )
                for row in rows.assets
            )
            chunk_ids = tuple(
                _insert_document_chunk(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in rows.chunks
            )
    return StoredParsedDocument(
        document_source_id=source_id,
        document_version_id=version_id,
        parse_job_id=parse_job_id,
        parsed_document_id=parsed_document_id,
        repository_id=source_repository_id,
        block_ids=block_ids,
        asset_ids=asset_ids,
        chunk_ids=chunk_ids,
    )


def _block_id_by_asset_id(parsed: ParsedUploadDocument) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for block in parsed.blocks:
        for asset_id in block.asset_ids:
            mapping.setdefault(asset_id, block.block_id)
    return mapping


def _title_from_parsed(parsed: ParsedUploadDocument) -> str:
    for block in parsed.blocks:
        if block.block_type == "heading" and block.text:
            return block.text
    return parsed.filename


def _outline_from_blocks(parsed: ParsedUploadDocument) -> list[dict[str, Any]]:
    return [
        {
            "ordinal": block.ordinal,
            "heading_level": block.heading_level,
            "text": block.text,
            "section_path": list(block.section_path),
            "section_number": block.section_number,
            "heading_title": block.heading_title,
            "source_anchor": block.source_anchor,
            "toc_path": list(block.toc_path),
        }
        for block in parsed.blocks
        if block.block_type == "heading"
    ]


def _approx_token_count(text: str) -> int:
    return len([part for part in text.split() if part])


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _fetch_id(cursor) -> str:
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("expected INSERT ... RETURNING id to return one row")
    return str(row[0])


def _upsert_tenant(cursor, *, tenant_slug: str, tenant_name: str) -> str:
    cursor.execute(
        """
        INSERT INTO tenants (slug, name)
        VALUES (%s, %s)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (tenant_slug, tenant_name),
    )
    return _fetch_id(cursor)


def _upsert_workspace(cursor, *, tenant_id: str, workspace_slug: str, workspace_name: str) -> str:
    cursor.execute(
        """
        INSERT INTO workspaces (tenant_id, slug, name)
        VALUES (%s, %s, %s)
        ON CONFLICT (tenant_id, slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (tenant_id, workspace_slug, workspace_name),
    )
    return _fetch_id(cursor)


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-._")
    return slug or fallback


def _upsert_repository(
    cursor,
    *,
    tenant_id: str,
    workspace_id: str,
    owner_user_id: str,
    slug: str,
    title: str,
    repository_kind: str,
    visibility: str,
) -> str:
    cursor.execute(
        """
        INSERT INTO repositories (
            tenant_id, workspace_id, owner_user_id, slug, title,
            repository_kind, visibility, metadata, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, now())
        ON CONFLICT (
            (COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid)),
            (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid)),
            owner_user_id,
            slug
        ) DO UPDATE SET
            title = EXCLUDED.title,
            repository_kind = EXCLUDED.repository_kind,
            visibility = EXCLUDED.visibility,
            updated_at = now()
        RETURNING id
        """,
        (
            tenant_id,
            workspace_id,
            owner_user_id,
            _safe_slug(slug, fallback="uploads"),
            title,
            repository_kind,
            visibility,
        ),
    )
    return _fetch_id(cursor)


def _upsert_document_source(cursor, *, tenant_id: str, workspace_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO document_sources (
            tenant_id, workspace_id, source_kind, filename, mime_type, sha256,
            storage_key, byte_size, access_policy, metadata, created_by,
            repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s,
            NULLIF(%s, '')::uuid, %s, %s, %s
        )
        ON CONFLICT (workspace_id, sha256) DO UPDATE SET
            filename = EXCLUDED.filename,
            mime_type = EXCLUDED.mime_type,
            storage_key = EXCLUDED.storage_key,
            byte_size = EXCLUDED.byte_size,
            metadata = EXCLUDED.metadata,
            created_by = EXCLUDED.created_by,
            repository_id = EXCLUDED.repository_id,
            owner_user_id = EXCLUDED.owner_user_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope
        RETURNING id
        """,
        (
            tenant_id,
            workspace_id,
            row["source_kind"],
            row["filename"],
            row["mime_type"],
            row["sha256"],
            row["storage_key"],
            row["byte_size"],
            _json(row["access_policy"]),
            _json(row["metadata"]),
            row["created_by"],
            row["repository_id"],
            row["owner_user_id"],
            row["visibility"],
            row["source_scope"],
        ),
    )
    return _fetch_id(cursor)


def _insert_document_version(cursor, *, source_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO document_versions (document_source_id, version_no, source_sha256, storage_key)
        VALUES (
            %s,
            COALESCE((SELECT max(version_no) + 1 FROM document_versions WHERE document_source_id = %s), 1),
            %s,
            %s
        )
        RETURNING id
        """,
        (source_id, source_id, row["sha256"], row["storage_key"]),
    )
    return _fetch_id(cursor)


def _insert_parse_job(
    cursor,
    *,
    source_id: str,
    version_id: str,
    parsed: ParsedUploadDocument,
) -> str:
    cursor.execute(
        """
        INSERT INTO parse_jobs (
            document_source_id, document_version_id, parser_name, parser_version,
            status, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        RETURNING id
        """,
        (source_id, version_id, parsed.parser_name, parsed.parser_version, parsed.status),
    )
    return _fetch_id(cursor)


def _insert_parsed_document(
    cursor,
    *,
    source_id: str,
    version_id: str,
    parse_job_id: str,
    row: dict[str, Any],
) -> str:
    parsed_document_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO parsed_documents (
            id, document_source_id, document_version_id, parse_job_id,
            parser_name, parser_version, title, markdown, metadata, outline, warnings
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            parsed_document_id,
            source_id,
            version_id,
            parse_job_id,
            row["parser_name"],
            row["parser_version"],
            row["title"],
            row["markdown"],
            _json(row["metadata"]),
            _json(row["outline"]),
            _json(row["warnings"]),
        ),
    )
    return _fetch_id(cursor)


def _insert_document_block(cursor, *, parsed_document_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO document_blocks (
            id, parsed_document_id, ordinal, block_type, heading_level, page_number,
            text, markdown, section_path, section_number, heading_title, source_anchor,
            toc_path, bbox, table_data, metadata
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
            %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb
        )
        RETURNING id
        """,
        (
            row["id"],
            parsed_document_id,
            row["ordinal"],
            row["block_type"],
            row["heading_level"],
            row["page_number"],
            row["text"],
            row["markdown"],
            _json(row["section_path"]),
            row["section_number"],
            row["heading_title"],
            row["source_anchor"],
            _json(row["toc_path"]),
            _json(row["bbox"]),
            _json(row["table_data"]),
            _json(row["metadata"]),
        ),
    )
    return _fetch_id(cursor)


def _insert_document_asset(
    cursor,
    *,
    source_id: str,
    parsed_document_id: str,
    row: dict[str, Any],
) -> str:
    cursor.execute(
        """
        INSERT INTO document_assets (
            id, document_source_id, parsed_document_id, block_id, asset_type,
            mime_type, storage_key, sha256, width, height, page_number, bbox,
            caption_text, ocr_text, qwen_description, qwen_model, metadata
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s, %s::jsonb
        )
        RETURNING id
        """,
        (
            row["id"],
            source_id,
            parsed_document_id,
            row["block_id"],
            row["asset_type"],
            row["mime_type"],
            row["storage_key"],
            row["sha256"],
            row["width"],
            row["height"],
            row["page_number"],
            _json(row["bbox"]),
            row["caption_text"],
            row["ocr_text"],
            row["qwen_description"],
            row["qwen_model"],
            _json(row["metadata"]),
        ),
    )
    return _fetch_id(cursor)


def _insert_document_chunk(cursor, *, parsed_document_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO document_chunks (
            id, parsed_document_id, chunk_key, ordinal, chunk_type, markdown,
            embedding_text, token_count, page_start, page_end, section_path,
            section_number, heading_title, source_anchor, toc_path,
            asset_ids, metadata, repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
            (
                SELECT ds.repository_id
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ),
            COALESCE((
                SELECT ds.owner_user_id
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ), ''),
            COALESCE((
                SELECT ds.visibility
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ), 'workspace_shared'),
            COALESCE((
                SELECT ds.source_scope
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ), 'user_upload')
        )
        RETURNING id
        """,
        (
            row["id"],
            parsed_document_id,
            row["chunk_key"],
            row["ordinal"],
            row["chunk_type"],
            row["markdown"],
            row["embedding_text"],
            row["token_count"],
            row["page_start"],
            row["page_end"],
            _json(row["section_path"]),
            row["section_number"],
            row["heading_title"],
            row["source_anchor"],
            _json(row["toc_path"]),
            _json(row["asset_ids"]),
            _json(row["metadata"]),
            parsed_document_id,
            parsed_document_id,
            parsed_document_id,
            parsed_document_id,
        ),
    )
    return _fetch_id(cursor)


def list_document_repositories(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    owner_user_id: str = "",
    include_shared: bool = True,
) -> list[dict[str, Any]]:
    shared_visibility_sql = "r.visibility IN ('workspace_shared', 'global_shared')"
    scope_sql = f"({shared_visibility_sql} OR r.owner_user_id = %s)" if include_shared else "r.owner_user_id = %s"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                r.id::text,
                r.slug,
                r.title,
                r.repository_kind,
                r.visibility,
                r.owner_user_id,
                r.metadata,
                count(ds.id)::int AS document_count,
                max(ds.created_at) AS last_document_at,
                r.updated_at
            FROM repositories r
            JOIN tenants t ON t.id = r.tenant_id
            JOIN workspaces w ON w.id = r.workspace_id
            LEFT JOIN document_sources ds ON ds.repository_id = r.id
            WHERE t.slug = %s
              AND w.slug = %s
              AND {scope_sql}
            GROUP BY r.id
            ORDER BY
                CASE WHEN r.visibility IN ('global_shared', 'workspace_shared') THEN 0 ELSE 1 END,
                r.updated_at DESC,
                r.title ASC
            """,
            (tenant_slug, workspace_slug, owner_user_id),
        )
        rows = cursor.fetchall()
        repository_ids = [str(row[0]) for row in rows]
        documents_by_repository: dict[str, list[dict[str, Any]]] = {repository_id: [] for repository_id in repository_ids}
        if repository_ids:
            cursor.execute(
                """
                SELECT
                    ds.repository_id::text,
                    ds.id::text,
                    COALESCE(pd.id::text, '') AS parsed_document_id,
                    COALESCE(NULLIF(pd.title, ''), ds.filename) AS title,
                    ds.filename,
                    ds.source_kind,
                    ds.mime_type,
                    ds.source_scope,
                    ds.visibility,
                    ds.metadata,
                    COALESCE(pj.status, CASE WHEN pd.id IS NULL THEN 'pending' ELSE 'completed' END) AS parse_status,
                    count(dc.id)::int AS chunk_count,
                    count(qie.chunk_id)::int AS indexed_chunk_count,
                    ds.created_at,
                    COALESCE(max(pd.created_at), ds.created_at) AS updated_at
                FROM document_sources ds
                LEFT JOIN LATERAL (
                    SELECT parsed_documents.*
                    FROM parsed_documents
                    WHERE parsed_documents.document_source_id = ds.id
                    ORDER BY parsed_documents.created_at DESC
                    LIMIT 1
                ) pd ON TRUE
                LEFT JOIN LATERAL (
                    SELECT parse_jobs.status
                    FROM parse_jobs
                    WHERE parse_jobs.document_source_id = ds.id
                    ORDER BY parse_jobs.created_at DESC
                    LIMIT 1
                ) pj ON TRUE
                LEFT JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                LEFT JOIN qdrant_index_entries qie ON qie.chunk_id = dc.id
                WHERE ds.repository_id = ANY(%s::uuid[])
                GROUP BY
                    ds.repository_id,
                    ds.id,
                    pd.id,
                    pd.title,
                    ds.filename,
                    ds.source_kind,
                    ds.mime_type,
                    ds.source_scope,
                    ds.visibility,
                    ds.metadata,
                    pj.status,
                    ds.created_at
                ORDER BY ds.created_at DESC, title ASC
                """,
                (repository_ids,),
            )
            for doc_row in cursor.fetchall():
                repository_id = str(doc_row[0])
                documents_by_repository.setdefault(repository_id, []).append(
                    {
                        "document_source_id": str(doc_row[1]),
                        "parsed_document_id": str(doc_row[2] or ""),
                        "title": str(doc_row[3] or ""),
                        "filename": str(doc_row[4] or ""),
                        "source_kind": str(doc_row[5] or ""),
                        "mime_type": str(doc_row[6] or ""),
                        "source_scope": str(doc_row[7] or ""),
                        "visibility": str(doc_row[8] or ""),
                        "metadata": dict(doc_row[9] or {}),
                        "parse_status": str(doc_row[10] or ""),
                        "chunk_count": int(doc_row[11] or 0),
                        "indexed_chunk_count": int(doc_row[12] or 0),
                        "created_at": doc_row[13].isoformat() if doc_row[13] is not None else "",
                        "updated_at": doc_row[14].isoformat() if doc_row[14] is not None else "",
                    }
                )
    return [
        {
            "repository_id": str(row[0]),
            "slug": str(row[1] or ""),
            "title": str(row[2] or ""),
            "repository_kind": str(row[3] or ""),
            "visibility": str(row[4] or ""),
            "owner_user_id": str(row[5] or ""),
            "metadata": dict(row[6] or {}),
            "document_count": int(row[7] or 0),
            "documents": documents_by_repository.get(str(row[0]), []),
            "last_document_at": row[8].isoformat() if row[8] is not None else "",
            "updated_at": row[9].isoformat() if row[9] is not None else "",
        }
        for row in rows
    ]


def _uuid_or_empty(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return ""


def load_document_reader(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    owner_user_id: str = "",
    include_shared: bool = True,
    document_source_id: str = "",
    parsed_document_id: str = "",
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any] | None:
    source_id = _uuid_or_empty(document_source_id)
    parsed_id = _uuid_or_empty(parsed_document_id)
    if not source_id and not parsed_id:
        raise ValueError("document_source_id or parsed_document_id is required")

    chunk_limit = max(1, min(int(limit or 80), 200))
    chunk_offset = max(0, int(offset or 0))
    markdown_preview_limit = 6000
    shared_visibility_sql = "r.visibility IN ('workspace_shared', 'global_shared')"
    scope_sql = f"({shared_visibility_sql} OR r.owner_user_id = %s)" if include_shared else "r.owner_user_id = %s"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                ds.id::text AS document_source_id,
                COALESCE(pd.id::text, '') AS parsed_document_id,
                COALESCE(NULLIF(pd.title, ''), ds.filename) AS title,
                ds.filename,
                ds.source_kind,
                ds.mime_type,
                ds.source_scope,
                ds.visibility,
                ds.metadata AS source_metadata,
                CASE
                    WHEN %s = 0 THEN left(COALESCE(pd.markdown, ''), %s)
                    ELSE ''
                END AS markdown,
                COALESCE(pd.metadata, '{{}}'::jsonb) AS parsed_metadata,
                COALESCE(pd.outline, '[]'::jsonb) AS outline,
                ds.created_at,
                COALESCE(pd.created_at, ds.created_at) AS updated_at,
                char_length(COALESCE(pd.markdown, ''))::int AS markdown_total_chars,
                char_length(COALESCE(pd.markdown, '')) > %s AS markdown_truncated
            FROM document_sources ds
            JOIN repositories r ON r.id = ds.repository_id
            JOIN tenants t ON t.id = r.tenant_id
            JOIN workspaces w ON w.id = r.workspace_id
            LEFT JOIN LATERAL (
                SELECT parsed_documents.*
                FROM parsed_documents
                WHERE parsed_documents.document_source_id = ds.id
                  AND (%s = '' OR parsed_documents.id = %s::uuid)
                ORDER BY parsed_documents.created_at DESC
                LIMIT 1
            ) pd ON TRUE
            WHERE t.slug = %s
              AND w.slug = %s
              AND {scope_sql}
              AND (
                (%s <> '' AND ds.id = %s::uuid AND (%s = '' OR pd.id IS NOT NULL))
                OR
                (%s = '' AND %s <> '' AND pd.id = %s::uuid)
              )
            LIMIT 1
            """,
            (
                chunk_offset,
                markdown_preview_limit,
                markdown_preview_limit,
                parsed_id,
                parsed_id or None,
                tenant_slug,
                workspace_slug,
                owner_user_id,
                source_id,
                source_id or None,
                parsed_id,
                source_id,
                parsed_id,
                parsed_id or None,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        resolved_source_id = str(row[0])
        resolved_parsed_id = str(row[1] or "")
        total_chunks = 0
        chunks: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        if resolved_parsed_id:
            cursor.execute(
                "SELECT count(*)::int FROM document_chunks WHERE parsed_document_id = %s::uuid",
                (resolved_parsed_id,),
            )
            total_chunks = int((cursor.fetchone() or [0])[0] or 0)
            cursor.execute(
                """
                SELECT
                    id::text,
                    chunk_key,
                    ordinal,
                    chunk_type,
                    markdown,
                    embedding_text,
                    token_count,
                    page_start,
                    page_end,
                    section_path,
                    section_number,
                    heading_title,
                    source_anchor,
                    toc_path,
                    asset_ids,
                    metadata
                FROM document_chunks
                WHERE parsed_document_id = %s::uuid
                ORDER BY ordinal ASC, created_at ASC
                LIMIT %s OFFSET %s
                """,
                (resolved_parsed_id, chunk_limit, chunk_offset),
            )
            for chunk_row in cursor.fetchall():
                chunks.append(
                    {
                        "chunk_id": str(chunk_row[0]),
                        "chunk_key": str(chunk_row[1] or ""),
                        "ordinal": int(chunk_row[2] or 0),
                        "chunk_type": str(chunk_row[3] or ""),
                        "markdown": str(chunk_row[4] or ""),
                        "text": str(chunk_row[5] or chunk_row[4] or ""),
                        "token_count": int(chunk_row[6] or 0),
                        "page_start": chunk_row[7],
                        "page_end": chunk_row[8],
                        "section_path": list(chunk_row[9] or []),
                        "section_number": str(chunk_row[10] or ""),
                        "heading_title": str(chunk_row[11] or ""),
                        "source_anchor": str(chunk_row[12] or ""),
                        "toc_path": list(chunk_row[13] or []),
                        "asset_ids": list(chunk_row[14] or []),
                        "metadata": dict(chunk_row[15] or {}),
                    }
                )
        cursor.execute(
            """
            SELECT
                id::text,
                asset_type,
                mime_type,
                storage_key,
                sha256,
                width,
                height,
                page_number,
                caption_text,
                ocr_text,
                qwen_description,
                qwen_model,
                metadata
            FROM document_assets
            WHERE document_source_id = %s::uuid
              AND (%s = '' OR parsed_document_id = %s::uuid)
            ORDER BY COALESCE(page_number, 0), created_at ASC, id ASC
            """,
            (resolved_source_id, resolved_parsed_id, resolved_parsed_id or None),
        )
        for asset_row in cursor.fetchall():
            metadata = dict(asset_row[12] or {})
            assets.append(
                {
                    "asset_id": str(asset_row[0]),
                    "asset_type": str(asset_row[1] or ""),
                    "mime_type": str(asset_row[2] or ""),
                    "storage_key": str(asset_row[3] or ""),
                    "sha256": str(asset_row[4] or ""),
                    "width": asset_row[5],
                    "height": asset_row[6],
                    "page_number": asset_row[7],
                    "caption_text": str(asset_row[8] or ""),
                    "ocr_text": str(asset_row[9] or ""),
                    "qwen_description": str(asset_row[10] or ""),
                    "qwen_model": str(asset_row[11] or ""),
                    "filename": str(metadata.get("filename") or ""),
                    "metadata": metadata,
                }
            )

    return {
        "document_source_id": resolved_source_id,
        "parsed_document_id": resolved_parsed_id,
        "title": str(row[2] or ""),
        "filename": str(row[3] or ""),
        "source_kind": str(row[4] or ""),
        "mime_type": str(row[5] or ""),
        "source_scope": str(row[6] or ""),
        "visibility": str(row[7] or ""),
        "metadata": dict(row[8] or {}),
        "markdown": str(row[9] or ""),
        "parsed_metadata": dict(row[10] or {}),
        "outline": list(row[11] or []),
        "created_at": row[12].isoformat() if row[12] is not None else "",
        "updated_at": row[13].isoformat() if row[13] is not None else "",
        "markdown_total_chars": int(row[14] or 0),
        "markdown_truncated": bool(row[15]),
        "total_chunks": total_chunks,
        "limit": chunk_limit,
        "offset": chunk_offset,
        "has_more": chunk_offset + len(chunks) < total_chunks,
        "assets": assets,
        "chunks": chunks,
    }


__all__ = [
    "ParsedDocumentRows",
    "StoredParsedDocument",
    "build_parsed_document_rows",
    "list_document_repositories",
    "load_document_reader",
    "persist_parsed_upload_document",
]
