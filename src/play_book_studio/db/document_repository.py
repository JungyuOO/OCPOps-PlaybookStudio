"""Persistence helpers for parsed upload documents."""

from __future__ import annotations

import json
import re
import uuid
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from play_book_studio.ingestion.document_parsing import (
    DocumentAsset,
    DocumentChunk,
    ParsedUploadDocument,
    build_document_chunks,
)
from play_book_studio.wiki_topology import TOPOLOGY_SCHEMA_VERSION, build_document_topology


_SOURCE_RUNTIME_METADATA_KEYS = frozenset({"pending_qdrant_cleanup"})


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


@dataclass(frozen=True, slots=True)
class LoadedParsedDocumentForRepair:
    document_source_id: str
    document_version_id: str
    parse_job_id: str
    parsed_document_id: str
    repository_id: str
    storage_key: str
    owner_user_id: str
    visibility: str
    source_scope: str
    parsed: ParsedUploadDocument


@dataclass(frozen=True, slots=True)
class ReplacedParsedDocumentContent:
    document_source_id: str
    parsed_document_id: str
    block_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    old_qdrant_point_ids: tuple[str, ...]
    old_qdrant_points_by_collection: dict[str, tuple[str, ...]]


def _document_metadata_without_runtime_state(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(metadata or {}).items() if key not in _SOURCE_RUNTIME_METADATA_KEYS}


def _merge_repair_document_metadata(source_metadata: dict[str, Any], parsed_metadata: dict[str, Any]) -> dict[str, Any]:
    merged = {**dict(source_metadata or {}), **_document_metadata_without_runtime_state(parsed_metadata)}
    for key in _SOURCE_RUNTIME_METADATA_KEYS:
        if key in source_metadata:
            merged[key] = source_metadata[key]
        else:
            merged.pop(key, None)
    return merged


def build_parsed_document_rows(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...] | None = None,
    *,
    storage_key: str = "",
    created_by: str = "",
    repository_id: str = "",
    visibility: str = "",
    source_scope: str = "user_upload",
    gold_build_run: dict[str, Any] | None = None,
) -> ParsedDocumentRows:
    created_by = _sanitize_postgres_text(created_by)
    repository_id = _sanitize_postgres_text(repository_id)
    visibility = _sanitize_postgres_text(visibility)
    source_scope = _sanitize_postgres_text(source_scope) or "user_upload"
    storage_key = _sanitize_postgres_text(storage_key)
    document_chunks = chunks if chunks is not None else build_document_chunks(parsed)
    block_id_by_asset_id = _block_id_by_asset_id(parsed)
    storage_key = storage_key or f"uploads/sources/{parsed.document_id}/{parsed.filename}"
    content_sha256 = _sanitize_postgres_text(parsed.sha256)
    database_sha256 = content_sha256
    if source_scope == "user_upload" and created_by:
        database_sha256 = hashlib.sha256(f"{content_sha256}:{created_by}".encode("utf-8")).hexdigest()
    source = {
        "source_kind": "upload",
        "filename": parsed.filename,
        "mime_type": parsed.mime_type,
        "sha256": database_sha256,
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
            "content_sha256": content_sha256,
            **({"gold_build_run": gold_build_run} if gold_build_run else {}),
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
        source=_sanitize_postgres_row(source),
        parsed_document=_sanitize_postgres_row(parsed_document),
        blocks=tuple(_sanitize_postgres_row(row) for row in blocks),
        assets=tuple(_sanitize_postgres_row(row) for row in assets),
        chunks=tuple(_sanitize_postgres_row(row) for row in chunk_rows),
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
    gold_build_run: dict[str, Any] | None = None,
) -> StoredParsedDocument:
    tenant_slug = _sanitize_postgres_text(tenant_slug) or "public"
    tenant_name = _sanitize_postgres_text(tenant_name) or "Public"
    workspace_slug = _sanitize_postgres_text(workspace_slug) or "default"
    workspace_name = _sanitize_postgres_text(workspace_name) or "Default"
    storage_key = _sanitize_postgres_text(storage_key)
    created_by = _sanitize_postgres_text(created_by)
    repository_id = _sanitize_postgres_text(repository_id)
    repository_slug = _sanitize_postgres_text(repository_slug)
    repository_title = _sanitize_postgres_text(repository_title)
    repository_kind = _sanitize_postgres_text(repository_kind)
    visibility = _sanitize_postgres_text(visibility)
    source_scope = _sanitize_postgres_text(source_scope) or "user_upload"
    rows = build_parsed_document_rows(
        parsed,
        chunks,
        storage_key=storage_key,
        created_by=created_by,
        repository_id=repository_id,
        visibility=visibility,
        source_scope=source_scope,
        gold_build_run=gold_build_run,
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
            if rows.source["source_scope"] == "user_upload" and created_by:
                source_repository_id = ""
                rows.source["repository_id"] = ""
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
            block_rows, asset_rows, chunk_rows, parsed_markdown = _remap_child_row_ids_for_parse(rows, parsed_document_id)
            if parsed_markdown != rows.parsed_document["markdown"]:
                cursor.execute(
                    """
                    UPDATE parsed_documents
                    SET markdown = %s
                    WHERE id = %s
                    """,
                    (parsed_markdown, parsed_document_id),
                )
            block_ids = tuple(
                _insert_document_block(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in block_rows
            )
            asset_ids = tuple(
                _insert_document_asset(
                    cursor,
                    source_id=source_id,
                    parsed_document_id=parsed_document_id,
                    row=row,
                )
                for row in asset_rows
            )
            chunk_ids = tuple(
                _insert_document_chunk(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in chunk_rows
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


def load_parsed_document_for_repair(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str = "",
) -> LoadedParsedDocumentForRepair | None:
    source_id = _uuid_or_empty(document_source_id)
    parsed_id = _uuid_or_empty(parsed_document_id)
    if not source_id and not parsed_id:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ds.id::text,
                COALESCE(pd.id::text, '') AS parsed_document_id,
                COALESCE(pd.document_version_id::text, '') AS document_version_id,
                COALESCE(pd.parse_job_id::text, '') AS parse_job_id,
                COALESCE(ds.repository_id::text, '') AS repository_id,
                ds.storage_key,
                ds.owner_user_id,
                ds.visibility,
                ds.source_scope,
                ds.filename,
                ds.mime_type,
                ds.sha256,
                ds.metadata,
                pd.parser_name,
                pd.parser_version,
                pd.markdown,
                pd.metadata,
                pd.warnings
            FROM document_sources ds
            LEFT JOIN LATERAL (
                SELECT parsed_documents.*
                FROM parsed_documents
                WHERE parsed_documents.document_source_id = ds.id
                  AND (%s = '' OR parsed_documents.id = %s::uuid)
                ORDER BY parsed_documents.created_at DESC
                LIMIT 1
            ) pd ON TRUE
            WHERE (
                (%s <> '' AND ds.id = %s::uuid AND pd.id IS NOT NULL)
                OR
                (%s = '' AND %s <> '' AND pd.id = %s::uuid)
            )
            LIMIT 1
            """,
            (
                parsed_id,
                parsed_id or None,
                source_id,
                source_id or None,
                source_id,
                parsed_id,
                parsed_id or None,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        resolved_source_id = str(row[0] or "")
        resolved_parsed_id = str(row[1] or "")
        source_metadata = dict(row[12] or {})
        parsed_metadata = dict(row[16] or {})
        cursor.execute(
            """
            SELECT
                id::text,
                asset_type,
                mime_type,
                storage_key,
                sha256,
                page_number,
                caption_text,
                ocr_text,
                qwen_description,
                metadata
            FROM document_assets
            WHERE document_source_id = %s::uuid
              AND parsed_document_id = %s::uuid
            ORDER BY COALESCE(page_number, 0), created_at ASC, id ASC
            """,
            (resolved_source_id, resolved_parsed_id),
        )
        assets = tuple(
            DocumentAsset(
                asset_id=str(asset_row[0] or ""),
                asset_type=str(asset_row[1] or "image"),
                filename=str((asset_row[9] or {}).get("filename") or Path(str(asset_row[3] or "")).name),
                mime_type=str(asset_row[2] or ""),
                sha256=str(asset_row[4] or ""),
                storage_key=str(asset_row[3] or ""),
                description=str(asset_row[8] or asset_row[6] or ""),
                ocr_text=str(asset_row[7] or ""),
                page_number=asset_row[5],
                metadata=dict(asset_row[9] or {}),
            )
            for asset_row in cursor.fetchall()
        )
    document_id = str(parsed_metadata.get("document_id") or source_metadata.get("document_id") or resolved_source_id)
    document_format = str(parsed_metadata.get("document_format") or source_metadata.get("document_format") or "unknown")
    parsed = ParsedUploadDocument(
        document_id=document_id,
        filename=str(row[9] or ""),
        document_format=document_format,  # type: ignore[arg-type]
        mime_type=str(row[10] or ""),
        sha256=str(source_metadata.get("content_sha256") or row[11] or ""),
        markdown=str(row[15] or ""),
        assets=assets,
        parser_name=str(row[13] or "internal_upload_parser"),
        parser_version=str(row[14] or "0.1"),
        warnings=tuple(str(item) for item in (row[17] or []) if str(item).strip()),
        metadata=_merge_repair_document_metadata(source_metadata, parsed_metadata),
    )
    return LoadedParsedDocumentForRepair(
        document_source_id=resolved_source_id,
        document_version_id=str(row[2] or ""),
        parse_job_id=str(row[3] or ""),
        parsed_document_id=resolved_parsed_id,
        repository_id=str(row[4] or ""),
        storage_key=str(row[5] or ""),
        owner_user_id=str(row[6] or ""),
        visibility=str(row[7] or ""),
        source_scope=str(row[8] or "user_upload"),
        parsed=parsed,
    )


def replace_parsed_document_content(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str,
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...],
    storage_key: str = "",
    owner_user_id: str = "",
    repository_id: str = "",
    visibility: str = "",
    source_scope: str = "user_upload",
    gold_build_run: dict[str, Any] | None = None,
    collection: str = "",
) -> ReplacedParsedDocumentContent:
    parsed_for_storage = replace(parsed, metadata=_document_metadata_without_runtime_state(parsed.metadata))
    rows = build_parsed_document_rows(
        parsed_for_storage,
        chunks,
        storage_key=storage_key,
        created_by=owner_user_id,
        repository_id=repository_id,
        visibility=visibility,
        source_scope=source_scope,
        gold_build_run=gold_build_run,
    )
    points_by_collection: dict[str, list[str]] = {}
    block_ids: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    block_rows, asset_rows, chunk_rows = _remap_child_row_ids_for_replace(rows, parsed_document_id)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT qie.collection, qie.point_id
                FROM qdrant_index_entries qie
                JOIN document_chunks dc ON dc.id = qie.chunk_id
                WHERE dc.parsed_document_id = %s::uuid
                ORDER BY dc.ordinal ASC
                """,
                (parsed_document_id,),
            )
            for row in cursor.fetchall():
                row_collection = str(row[0] or "").strip()
                point_id = str(row[1] or "").strip()
                if row_collection and point_id:
                    points_by_collection.setdefault(row_collection, []).append(point_id)
            cursor.execute(
                """
                DELETE FROM qdrant_index_entries
                WHERE chunk_id IN (
                    SELECT id FROM document_chunks WHERE parsed_document_id = %s::uuid
                )
                """,
                (parsed_document_id,),
            )
            cursor.execute("DELETE FROM document_chunks WHERE parsed_document_id = %s::uuid", (parsed_document_id,))
            cursor.execute(
                "UPDATE document_assets SET block_id = NULL WHERE parsed_document_id = %s::uuid",
                (parsed_document_id,),
            )
            cursor.execute("DELETE FROM document_blocks WHERE parsed_document_id = %s::uuid", (parsed_document_id,))
            cursor.execute(
                """
                UPDATE parsed_documents
                SET
                    parser_name = %s,
                    parser_version = %s,
                    title = %s,
                    markdown = %s,
                    metadata = %s::jsonb,
                    outline = %s::jsonb,
                    warnings = %s::jsonb
                WHERE id = %s::uuid
                  AND document_source_id = %s::uuid
                """,
                (
                    rows.parsed_document["parser_name"],
                    rows.parsed_document["parser_version"],
                    rows.parsed_document["title"],
                    rows.parsed_document["markdown"],
                    _json(rows.parsed_document["metadata"]),
                    _json(rows.parsed_document["outline"]),
                    _json(rows.parsed_document["warnings"]),
                    parsed_document_id,
                    document_source_id,
                ),
            )
            block_ids = tuple(
                _insert_document_block(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in block_rows
            )
            asset_block_by_id = {str(row.get("id") or ""): str(row.get("block_id") or "") for row in asset_rows}
            for asset_id, block_id in asset_block_by_id.items():
                cursor.execute(
                    """
                    UPDATE document_assets
                    SET block_id = NULLIF(%s, '')::uuid
                    WHERE id = %s::uuid
                      AND parsed_document_id = %s::uuid
                    """,
                    (block_id, asset_id, parsed_document_id),
                )
            chunk_ids = tuple(
                _insert_document_chunk(cursor, parsed_document_id=parsed_document_id, row=row)
                for row in chunk_rows
            )
            if gold_build_run is not None:
                cursor.execute(
                    """
                    UPDATE document_sources
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                    WHERE id = %s::uuid
                    """,
                    (_json({"gold_build_run": gold_build_run}), document_source_id),
                )
            cursor.execute(
                """
                DELETE FROM document_topology_snapshots
                WHERE document_source_id = %s::uuid
                  AND parsed_document_id = %s::uuid
                """,
                (document_source_id, parsed_document_id),
            )
    return ReplacedParsedDocumentContent(
        document_source_id=document_source_id,
        parsed_document_id=parsed_document_id,
        block_ids=block_ids,
        chunk_ids=chunk_ids,
        old_qdrant_point_ids=tuple(dict.fromkeys(points_by_collection.get(collection, []))),
        old_qdrant_points_by_collection={
            key: tuple(dict.fromkeys(value))
            for key, value in points_by_collection.items()
        },
    )


def update_document_source_gold_build_run(
    connection,
    *,
    document_source_id: str,
    gold_build_run: dict[str, Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE document_sources
            SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
            WHERE id = %s::uuid
            """,
            (_json({"gold_build_run": gold_build_run}), document_source_id),
        )


def update_document_source_metadata(
    connection,
    *,
    document_source_id: str,
    metadata_patch: dict[str, Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE document_sources
            SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
            WHERE id = %s::uuid
            """,
            (_json(metadata_patch), document_source_id),
        )


def _block_id_by_asset_id(parsed: ParsedUploadDocument) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for block in parsed.blocks:
        for asset_id in block.asset_ids:
            mapping.setdefault(asset_id, block.block_id)
    return mapping


def _remap_child_row_ids_for_parse(
    rows: ParsedDocumentRows,
    parsed_document_id: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], str]:
    block_id_map = {
        str(row.get("id") or ""): _parse_scoped_uuid(parsed_document_id, str(row.get("id") or "block"))
        for row in rows.blocks
    }
    asset_id_map = {
        str(row.get("id") or ""): _parse_scoped_uuid(parsed_document_id, str(row.get("id") or "asset"))
        for row in rows.assets
    }
    chunk_id_map = {
        str(row.get("id") or ""): _parse_scoped_uuid(parsed_document_id, str(row.get("id") or "chunk"))
        for row in rows.chunks
    }
    block_rows = tuple(
        {
            **row,
            "id": block_id_map.get(str(row.get("id") or ""), str(row.get("id") or "")),
            "markdown": _replace_asset_refs(str(row.get("markdown") or ""), asset_id_map),
            "text": _replace_asset_refs(str(row.get("text") or ""), asset_id_map),
            "metadata": _remap_asset_ids_in_metadata(row.get("metadata"), asset_id_map),
        }
        for row in rows.blocks
    )
    asset_rows = tuple(
        {
            **row,
            "id": asset_id_map.get(str(row.get("id") or ""), str(row.get("id") or "")),
            "block_id": block_id_map.get(str(row.get("block_id") or ""), str(row.get("block_id") or "")),
        }
        for row in rows.assets
    )
    chunk_rows = tuple(
        {
            **row,
            "id": chunk_id_map.get(str(row.get("id") or ""), str(row.get("id") or "")),
            "markdown": _replace_asset_refs(str(row.get("markdown") or ""), asset_id_map),
            "embedding_text": _replace_asset_refs(str(row.get("embedding_text") or ""), asset_id_map),
            "asset_ids": [
                asset_id_map.get(str(asset_id or ""), str(asset_id or ""))
                for asset_id in row.get("asset_ids") or []
            ],
            "metadata": _remap_asset_ids_in_metadata(row.get("metadata"), asset_id_map),
        }
        for row in rows.chunks
    )
    parsed_markdown = _replace_asset_refs(str(rows.parsed_document.get("markdown") or ""), asset_id_map)
    return block_rows, asset_rows, chunk_rows, parsed_markdown


def _remap_child_row_ids_for_replace(
    rows: ParsedDocumentRows,
    parsed_document_id: str,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    block_id_map = {
        str(row.get("id") or ""): _parse_scoped_uuid(parsed_document_id, str(row.get("id") or "block"))
        for row in rows.blocks
    }
    chunk_id_map = {
        str(row.get("id") or ""): _parse_scoped_uuid(parsed_document_id, str(row.get("id") or "chunk"))
        for row in rows.chunks
    }
    block_rows = tuple(
        {
            **row,
            "id": block_id_map.get(str(row.get("id") or ""), str(row.get("id") or "")),
        }
        for row in rows.blocks
    )
    asset_rows = tuple(
        {
            **row,
            "block_id": block_id_map.get(str(row.get("block_id") or ""), str(row.get("block_id") or "")),
        }
        for row in rows.assets
    )
    chunk_rows = tuple(
        {
            **row,
            "id": chunk_id_map.get(str(row.get("id") or ""), str(row.get("id") or "")),
        }
        for row in rows.chunks
    )
    return block_rows, asset_rows, chunk_rows


def _parse_scoped_uuid(parsed_document_id: str, child_id: str) -> str:
    try:
        namespace = uuid.UUID(parsed_document_id)
    except ValueError:
        namespace = uuid.NAMESPACE_URL
    return str(uuid.uuid5(namespace, child_id or uuid.uuid4().hex))


def _remap_asset_ids_in_metadata(metadata: Any, asset_id_map: dict[str, str]) -> dict[str, Any]:
    mapped = dict(metadata or {})
    asset_ids = mapped.get("asset_ids")
    if isinstance(asset_ids, list):
        mapped["asset_ids"] = [asset_id_map.get(str(asset_id or ""), str(asset_id or "")) for asset_id in asset_ids]
    return mapped


def _replace_asset_refs(text: str, asset_id_map: dict[str, str]) -> str:
    next_text = text
    for old_id, new_id in asset_id_map.items():
        if old_id and new_id and old_id != new_id:
            next_text = next_text.replace(f"asset://{old_id}", f"asset://{new_id}")
    return next_text


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
    return json.dumps(_sanitize_postgres_value(value), ensure_ascii=False)


def _sanitize_postgres_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _sanitize_postgres_value(value) for key, value in row.items()}


def _sanitize_postgres_text(value: Any) -> str:
    return str(value or "").replace("\x00", "")


def _sanitize_postgres_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {
            _sanitize_postgres_value(key): _sanitize_postgres_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_postgres_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_postgres_value(item) for item in value)
    return value


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
    collection: str = "",
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
                LEFT JOIN qdrant_index_entries qie
                    ON qie.chunk_id = dc.id
                   AND (%s = '' OR qie.collection = %s)
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
                (collection, collection, repository_ids),
            )
            for doc_row in cursor.fetchall():
                repository_id = str(doc_row[0])
                source_metadata = dict(doc_row[9] or {})
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
                        "metadata": source_metadata,
                        "gold_build_run": source_metadata.get("gold_build_run") if isinstance(source_metadata.get("gold_build_run"), dict) else {},
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


def document_topology_source_fingerprint(document: dict[str, Any]) -> str:
    """Hash the stable source identity for a topology snapshot."""

    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    parsed_metadata = document.get("parsed_metadata") if isinstance(document.get("parsed_metadata"), dict) else {}
    source_hash = (
        str(metadata.get("source_fingerprint") or "").strip()
        or str(metadata.get("content_sha256") or "").strip()
        or str(metadata.get("sha256") or "").strip()
        or str(parsed_metadata.get("content_sha256") or "").strip()
    )
    payload = {
        "document_source_id": str(document.get("document_source_id") or ""),
        "parsed_document_id": str(document.get("parsed_document_id") or ""),
        "document_version_id": str(document.get("document_version_id") or ""),
        "source_hash": source_hash,
        "filename": str(document.get("filename") or ""),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def document_topology_input_fingerprint(document: dict[str, Any]) -> str:
    """Hash the exact persisted fields consumed by the topology builder."""

    payload = {
        "schema_version": TOPOLOGY_SCHEMA_VERSION,
        "document_source_id": str(document.get("document_source_id") or ""),
        "document_version_id": str(document.get("document_version_id") or ""),
        "parsed_document_id": str(document.get("parsed_document_id") or ""),
        "title": str(document.get("title") or ""),
        "filename": str(document.get("filename") or ""),
        "source_kind": str(document.get("source_kind") or ""),
        "mime_type": str(document.get("mime_type") or ""),
        "source_scope": str(document.get("source_scope") or ""),
        "visibility": str(document.get("visibility") or ""),
        "total_chunks": int(document.get("total_chunks") or 0),
        "has_more": bool(document.get("has_more")),
        "metadata": document.get("metadata") if isinstance(document.get("metadata"), dict) else {},
        "parsed_metadata": document.get("parsed_metadata") if isinstance(document.get("parsed_metadata"), dict) else {},
        "outline": document.get("outline") if isinstance(document.get("outline"), list) else [],
        "chunks": [
            {
                "chunk_id": str(chunk.get("chunk_id") or ""),
                "chunk_key": str(chunk.get("chunk_key") or ""),
                "ordinal": int(chunk.get("ordinal") or 0),
                "chunk_type": str(chunk.get("chunk_type") or ""),
                "markdown": str(chunk.get("markdown") or ""),
                "embedding_text": str(chunk.get("text") or ""),
                "token_count": int(chunk.get("token_count") or 0),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "section_path": list(chunk.get("section_path") or []),
                "section_number": str(chunk.get("section_number") or ""),
                "heading_title": str(chunk.get("heading_title") or ""),
                "source_anchor": str(chunk.get("source_anchor") or ""),
                "toc_path": list(chunk.get("toc_path") or []),
                "asset_ids": list(chunk.get("asset_ids") or []),
                "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {},
            }
            for chunk in document.get("chunks") or []
            if isinstance(chunk, dict)
        ],
        "assets": [
            {
                "asset_id": str(asset.get("asset_id") or ""),
                "asset_type": str(asset.get("asset_type") or ""),
                "mime_type": str(asset.get("mime_type") or ""),
                "storage_key": str(asset.get("storage_key") or ""),
                "sha256": str(asset.get("sha256") or ""),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "filename": str(asset.get("filename") or ""),
                "caption_text": str(asset.get("caption_text") or ""),
                "ocr_text": str(asset.get("ocr_text") or ""),
                "qwen_description": str(asset.get("qwen_description") or ""),
                "qwen_model": str(asset.get("qwen_model") or ""),
                "page_number": asset.get("page_number"),
                "metadata": asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {},
            }
            for asset in document.get("assets") or []
            if isinstance(asset, dict)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_topology_snapshot(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str,
    schema_version: str = TOPOLOGY_SCHEMA_VERSION,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id::text,
                source_fingerprint,
                input_fingerprint,
                state,
                partial,
                node_count,
                edge_count,
                topology,
                summary,
                nodes,
                edges,
                blockers,
                metadata,
                created_at,
                updated_at
            FROM document_topology_snapshots
            WHERE document_source_id = %s::uuid
              AND parsed_document_id = %s::uuid
              AND schema_version = %s
            LIMIT 1
            """,
            (document_source_id, parsed_document_id, schema_version),
        )
        row = cursor.fetchone()
        if row is not None:
            cursor.execute(
                """
                UPDATE document_topology_snapshots
                SET last_used_at = now()
                WHERE id = %s::uuid
                """,
                (row[0],),
            )
    if row is None:
        return None
    topology = dict(row[7] or {})
    return {
        **topology,
        "snapshot_id": str(row[0] or ""),
        "schema_version": schema_version,
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "source_fingerprint": str(row[1] or ""),
        "input_fingerprint": str(row[2] or ""),
        "state": str(row[3] or ""),
        "partial": bool(row[4]),
        "node_count": int(row[5] or 0),
        "edge_count": int(row[6] or 0),
        "summary": dict(row[8] or {}),
        "nodes": list(row[9] or []),
        "edges": list(row[10] or []),
        "blockers": list(row[11] or []),
        "metadata": dict(row[12] or {}),
        "created_at": row[13].isoformat() if row[13] is not None else "",
        "updated_at": row[14].isoformat() if row[14] is not None else "",
    }


def _load_topology_snapshot_summary(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str,
    schema_version: str = TOPOLOGY_SCHEMA_VERSION,
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id::text,
                state,
                partial,
                node_count,
                edge_count,
                summary,
                blockers,
                updated_at
            FROM document_topology_snapshots
            WHERE document_source_id = %s::uuid
              AND parsed_document_id = %s::uuid
              AND schema_version = %s
            LIMIT 1
            """,
            (document_source_id, parsed_document_id, schema_version),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    summary = dict(row[5] or {})
    return {
        "snapshot_id": str(row[0] or ""),
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "schema_version": schema_version,
        "state": str(row[1] or summary.get("state") or ""),
        "partial": bool(row[2]),
        "node_count": int(row[3] or summary.get("node_count") or 0),
        "edge_count": int(row[4] or summary.get("edge_count") or 0),
        "summary": summary,
        "blockers": list(row[6] or summary.get("blockers") or []),
        "updated_at": row[7].isoformat() if row[7] is not None else "",
    }


def load_document_topology_snapshot_summary(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str,
    schema_version: str = TOPOLOGY_SCHEMA_VERSION,
) -> dict[str, Any] | None:
    return _load_topology_snapshot_summary(
        connection,
        document_source_id=document_source_id,
        parsed_document_id=parsed_document_id,
        schema_version=schema_version,
    )


def _upsert_topology_snapshot(
    connection,
    *,
    topology: dict[str, Any],
    source_fingerprint: str,
    input_fingerprint: str,
) -> dict[str, Any]:
    summary = topology.get("summary") if isinstance(topology.get("summary"), dict) else {}
    state = str(summary.get("state") or "")
    blockers = summary.get("blockers") if isinstance(summary.get("blockers"), list) else []
    partial = bool(summary.get("partial"))
    node_count = int(summary.get("node_count") or 0)
    edge_count = int(summary.get("edge_count") or 0)
    metadata = {
        "source": "wiki_topology.build_document_topology",
        "partial": partial,
        "storage": "postgres",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO document_topology_snapshots (
                document_source_id,
                document_version_id,
                parsed_document_id,
                schema_version,
                source_fingerprint,
                input_fingerprint,
                state,
                partial,
                node_count,
                edge_count,
                topology,
                summary,
                nodes,
                edges,
                blockers,
                metadata
            )
            VALUES (
                %s::uuid,
                NULLIF(%s, '')::uuid,
                %s::uuid,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb
            )
            ON CONFLICT (document_source_id, parsed_document_id, schema_version)
            DO UPDATE SET
                document_version_id = EXCLUDED.document_version_id,
                source_fingerprint = EXCLUDED.source_fingerprint,
                input_fingerprint = EXCLUDED.input_fingerprint,
                state = EXCLUDED.state,
                partial = EXCLUDED.partial,
                node_count = EXCLUDED.node_count,
                edge_count = EXCLUDED.edge_count,
                topology = EXCLUDED.topology,
                summary = EXCLUDED.summary,
                nodes = EXCLUDED.nodes,
                edges = EXCLUDED.edges,
                blockers = EXCLUDED.blockers,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id::text, created_at, updated_at
            """,
            (
                str(topology.get("document_source_id") or ""),
                str(topology.get("document_version_id") or ""),
                str(topology.get("parsed_document_id") or ""),
                str(topology.get("schema_version") or TOPOLOGY_SCHEMA_VERSION),
                source_fingerprint,
                input_fingerprint,
                state,
                partial,
                node_count,
                edge_count,
                json.dumps(topology, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(topology.get("nodes") or [], ensure_ascii=False),
                json.dumps(topology.get("edges") or [], ensure_ascii=False),
                json.dumps(blockers, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        row = cursor.fetchone()
    return {
        **topology,
        "snapshot_id": str(row[0] or "") if row else "",
        "source_fingerprint": source_fingerprint,
        "input_fingerprint": input_fingerprint,
        "state": state,
        "partial": partial,
        "node_count": node_count,
        "edge_count": edge_count,
        "blockers": blockers,
        "metadata": metadata,
        "created_at": row[1].isoformat() if row and row[1] is not None else "",
        "updated_at": row[2].isoformat() if row and row[2] is not None else "",
    }


def _transient_topology_snapshot(
    document: dict[str, Any],
    *,
    source_fingerprint: str,
    input_fingerprint: str,
    storage_reason: str,
) -> dict[str, Any]:
    topology = build_document_topology(document).to_dict()
    topology["document_version_id"] = str(document.get("document_version_id") or "")
    summary = topology.get("summary") if isinstance(topology.get("summary"), dict) else {}
    return {
        **topology,
        "source_fingerprint": source_fingerprint,
        "input_fingerprint": input_fingerprint,
        "state": str(summary.get("state") or ""),
        "partial": bool(summary.get("partial")),
        "node_count": int(summary.get("node_count") or 0),
        "edge_count": int(summary.get("edge_count") or 0),
        "blockers": list(summary.get("blockers") or []),
        "metadata": {
            "source": "wiki_topology.build_document_topology",
            "storage": "transient",
            "storage_reason": storage_reason,
        },
    }


def get_or_create_document_topology_snapshot(
    connection,
    document: dict[str, Any],
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    document_source_id = _uuid_or_empty(str(document.get("document_source_id") or ""))
    parsed_document_id = _uuid_or_empty(str(document.get("parsed_document_id") or ""))
    if not document_source_id or not parsed_document_id:
        source_fingerprint = document_topology_source_fingerprint(document)
        input_fingerprint = document_topology_input_fingerprint(document)
        return _transient_topology_snapshot(
            document,
            source_fingerprint=source_fingerprint,
            input_fingerprint=input_fingerprint,
            storage_reason="missing_document_identity",
        )

    source_fingerprint = document_topology_source_fingerprint(document)
    input_fingerprint = document_topology_input_fingerprint(document)
    try:
        if not force_refresh:
            current = _load_topology_snapshot(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
            )
            if (
                current
                and current.get("source_fingerprint") == source_fingerprint
                and current.get("input_fingerprint") == input_fingerprint
            ):
                return current
        topology = build_document_topology(document).to_dict()
        topology["document_version_id"] = str(document.get("document_version_id") or "")
        summary = topology.get("summary") if isinstance(topology.get("summary"), dict) else {}
        if bool(summary.get("partial")):
            return _transient_topology_snapshot(
                document,
                source_fingerprint=source_fingerprint,
                input_fingerprint=input_fingerprint,
                storage_reason="partial_topology_not_persisted",
            )
        return _upsert_topology_snapshot(
            connection,
            topology=topology,
            source_fingerprint=source_fingerprint,
            input_fingerprint=input_fingerprint,
        )
    except Exception as exc:  # noqa: BLE001
        snapshot = _transient_topology_snapshot(
            document,
            source_fingerprint=source_fingerprint,
            input_fingerprint=input_fingerprint,
            storage_reason="snapshot_error",
        )
        snapshot["metadata"] = {**dict(snapshot.get("metadata") or {}), "snapshot_error": str(exc)}
        return snapshot


def _latest_document_ids_for_scope(
    connection,
    *,
    source_scope: str,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    owner_user_id: str = "",
    include_shared: bool = True,
    limit: int = 200,
) -> list[tuple[str, str]]:
    shared_visibility_sql = "r.visibility IN ('workspace_shared', 'global_shared')"
    scope_sql = f"({shared_visibility_sql} OR r.owner_user_id = %s)" if include_shared else "r.owner_user_id = %s"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT ds.id::text, COALESCE(pd.id::text, '') AS parsed_document_id
            FROM repositories r
            JOIN tenants t ON t.id = r.tenant_id
            JOIN workspaces w ON w.id = r.workspace_id
            JOIN document_sources ds ON ds.repository_id = r.id
            LEFT JOIN LATERAL (
                SELECT parsed_documents.*
                FROM parsed_documents
                WHERE parsed_documents.document_source_id = ds.id
                ORDER BY parsed_documents.created_at DESC
                LIMIT 1
            ) pd ON TRUE
            WHERE t.slug = %s
              AND w.slug = %s
              AND {scope_sql}
              AND (%s = '' OR ds.source_scope = %s)
              AND pd.id IS NOT NULL
            ORDER BY ds.created_at DESC
            LIMIT %s
            """,
            (tenant_slug, workspace_slug, owner_user_id, source_scope, source_scope, max(1, min(limit, 500))),
        )
        return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]


def load_document_topology_source(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str = "",
    chunk_limit: int = 20000,
) -> dict[str, Any] | None:
    source_id = _uuid_or_empty(document_source_id)
    parsed_id = _uuid_or_empty(parsed_document_id)
    if not source_id and not parsed_id:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ds.id::text,
                COALESCE(pd.id::text, '') AS parsed_document_id,
                COALESCE(pd.document_version_id::text, '') AS document_version_id,
                COALESCE(NULLIF(pd.title, ''), ds.filename) AS title,
                ds.filename,
                ds.source_kind,
                ds.mime_type,
                ds.source_scope,
                ds.visibility,
                ds.metadata,
                COALESCE(pd.metadata, '{}'::jsonb) AS parsed_metadata,
                COALESCE(pd.outline, '[]'::jsonb) AS outline,
                ds.created_at,
                COALESCE(pd.created_at, ds.created_at) AS updated_at
            FROM document_sources ds
            LEFT JOIN LATERAL (
                SELECT parsed_documents.*
                FROM parsed_documents
                WHERE parsed_documents.document_source_id = ds.id
                  AND (%s = '' OR parsed_documents.id = %s::uuid)
                ORDER BY parsed_documents.created_at DESC
                LIMIT 1
            ) pd ON TRUE
            WHERE (
                (%s <> '' AND ds.id = %s::uuid AND (%s = '' OR pd.id IS NOT NULL))
                OR
                (%s = '' AND %s <> '' AND pd.id = %s::uuid)
            )
            LIMIT 1
            """,
            (
                parsed_id,
                parsed_id or None,
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
        resolved_document_version_id = str(row[2] or "")
        chunks: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        total_chunk_count = 0
        if resolved_parsed_id:
            cursor.execute(
                """
                SELECT count(*)::int
                FROM document_chunks
                WHERE parsed_document_id = %s::uuid
                """,
                (resolved_parsed_id,),
            )
            count_row = cursor.fetchone()
            total_chunk_count = int(count_row[0] or 0) if count_row else 0
            bounded_chunk_limit = max(1, min(int(chunk_limit or 20000), 20000))
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
                LIMIT %s
                """,
                (resolved_parsed_id, bounded_chunk_limit),
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
        "document_version_id": resolved_document_version_id,
        "title": str(row[3] or ""),
        "filename": str(row[4] or ""),
        "source_kind": str(row[5] or ""),
        "mime_type": str(row[6] or ""),
        "source_scope": str(row[7] or ""),
        "visibility": str(row[8] or ""),
        "metadata": dict(row[9] or {}),
        "parsed_metadata": dict(row[10] or {}),
        "outline": list(row[11] or []),
        "created_at": row[12].isoformat() if row[12] is not None else "",
        "updated_at": row[13].isoformat() if row[13] is not None else "",
        "total_chunks": total_chunk_count,
        "has_more": total_chunk_count > len(chunks),
        "assets": assets,
        "chunks": chunks,
    }


def get_or_create_document_topology_snapshot_by_id(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str = "",
    force_refresh: bool = False,
) -> dict[str, Any] | None:
    document = load_document_topology_source(
        connection,
        document_source_id=document_source_id,
        parsed_document_id=parsed_document_id,
    )
    if document is None:
        return None
    return get_or_create_document_topology_snapshot(
        connection,
        document,
        force_refresh=force_refresh,
    )


def insert_upload_pipeline_event(
    connection,
    *,
    run_id: str,
    event_id: str,
    stage: str,
    event: str,
    status: str,
    payload: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    document_source_id: str = "",
    parsed_document_id: str = "",
    occurred_at: str = "",
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO upload_pipeline_events (
                run_id,
                event_id,
                document_source_id,
                parsed_document_id,
                stage,
                event,
                status,
                occurred_at,
                payload,
                evidence
            )
            VALUES (
                %s,
                %s,
                NULLIF(%s, '')::uuid,
                NULLIF(%s, '')::uuid,
                %s,
                %s,
                %s,
                COALESCE(NULLIF(%s, '')::timestamptz, now()),
                %s::jsonb,
                %s::jsonb
            )
            ON CONFLICT (run_id, event_id)
            DO UPDATE SET
                document_source_id = COALESCE(EXCLUDED.document_source_id, upload_pipeline_events.document_source_id),
                parsed_document_id = COALESCE(EXCLUDED.parsed_document_id, upload_pipeline_events.parsed_document_id),
                stage = EXCLUDED.stage,
                event = EXCLUDED.event,
                status = EXCLUDED.status,
                occurred_at = EXCLUDED.occurred_at,
                payload = EXCLUDED.payload,
                evidence = EXCLUDED.evidence
            RETURNING id::text, occurred_at
            """,
            (
                run_id,
                event_id,
                _uuid_or_empty(document_source_id),
                _uuid_or_empty(parsed_document_id),
                stage,
                event,
                status,
                occurred_at,
                _json(payload or {}),
                _json(evidence or {}),
            ),
        )
        row = cursor.fetchone()
    return {
        "id": str(row[0] or "") if row else "",
        "run_id": run_id,
        "event_id": event_id,
        "document_source_id": _uuid_or_empty(document_source_id),
        "parsed_document_id": _uuid_or_empty(parsed_document_id),
        "stage": stage,
        "event": event,
        "status": status,
        "occurred_at": row[1].isoformat() if row and row[1] is not None else occurred_at,
        "payload": payload or {},
        "evidence": evidence or {},
    }


def bind_upload_pipeline_events(
    connection,
    *,
    run_id: str,
    document_source_id: str,
    parsed_document_id: str = "",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE upload_pipeline_events
            SET
                document_source_id = NULLIF(%s, '')::uuid,
                parsed_document_id = NULLIF(%s, '')::uuid
            WHERE run_id = %s
            """,
            (_uuid_or_empty(document_source_id), _uuid_or_empty(parsed_document_id), run_id),
        )


def list_upload_pipeline_events(
    connection,
    *,
    document_source_id: str = "",
    parsed_document_id: str = "",
    run_id: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                run_id,
                event_id,
                COALESCE(document_source_id::text, ''),
                COALESCE(parsed_document_id::text, ''),
                stage,
                event,
                status,
                occurred_at,
                payload,
                evidence
            FROM upload_pipeline_events
            WHERE (%s = '' OR run_id = %s)
              AND (%s = '' OR document_source_id = %s::uuid)
              AND (%s = '' OR parsed_document_id = %s::uuid)
            ORDER BY occurred_at ASC, created_at ASC
            LIMIT %s
            """,
            (
                run_id,
                run_id,
                _uuid_or_empty(document_source_id),
                _uuid_or_empty(document_source_id) or None,
                _uuid_or_empty(parsed_document_id),
                _uuid_or_empty(parsed_document_id) or None,
                max(1, min(int(limit or 200), 1000)),
            ),
        )
        rows = cursor.fetchall()
    return [
        {
            "run_id": str(row[0] or ""),
            "event_id": str(row[1] or ""),
            "document_source_id": str(row[2] or ""),
            "parsed_document_id": str(row[3] or ""),
            "stage": str(row[4] or ""),
            "event": str(row[5] or ""),
            "status": str(row[6] or ""),
            "occurred_at": row[7].isoformat() if row[7] is not None else "",
            "payload": dict(row[8] or {}),
            "evidence": dict(row[9] or {}),
        }
        for row in rows
    ]


def upsert_document_quality_snapshot(connection, *, quality: dict[str, Any]) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO document_quality_snapshots (
                document_source_id,
                parsed_document_id,
                schema_version,
                state,
                score,
                checks,
                blockers,
                warnings,
                metadata
            )
            VALUES (
                %s::uuid,
                %s::uuid,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb
            )
            ON CONFLICT (document_source_id, parsed_document_id, schema_version)
            DO UPDATE SET
                state = EXCLUDED.state,
                score = EXCLUDED.score,
                checks = EXCLUDED.checks,
                blockers = EXCLUDED.blockers,
                warnings = EXCLUDED.warnings,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            RETURNING id::text, created_at, updated_at
            """,
            (
                _uuid_or_empty(str(quality.get("document_source_id") or "")),
                _uuid_or_empty(str(quality.get("parsed_document_id") or "")),
                str(quality.get("schema_version") or ""),
                str(quality.get("state") or ""),
                float(quality.get("score") or 0),
                _json(quality.get("checks") or []),
                _json(quality.get("blockers") or []),
                _json(quality.get("warnings") or []),
                _json(quality.get("metadata") or {}),
            ),
        )
        row = cursor.fetchone()
    return {
        **quality,
        "snapshot_id": str(row[0] or "") if row else "",
        "created_at": row[1].isoformat() if row and row[1] is not None else "",
        "updated_at": row[2].isoformat() if row and row[2] is not None else "",
    }


def load_document_quality_snapshot(
    connection,
    *,
    document_source_id: str,
    parsed_document_id: str = "",
    schema_version: str = "",
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id::text,
                document_source_id::text,
                parsed_document_id::text,
                schema_version,
                state,
                score,
                checks,
                blockers,
                warnings,
                metadata,
                created_at,
                updated_at
            FROM document_quality_snapshots
            WHERE document_source_id = %s::uuid
              AND (%s = '' OR parsed_document_id = %s::uuid)
              AND (%s = '' OR schema_version = %s)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                _uuid_or_empty(document_source_id),
                _uuid_or_empty(parsed_document_id),
                _uuid_or_empty(parsed_document_id) or None,
                schema_version,
                schema_version,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "snapshot_id": str(row[0] or ""),
        "document_source_id": str(row[1] or ""),
        "parsed_document_id": str(row[2] or ""),
        "schema_version": str(row[3] or ""),
        "state": str(row[4] or ""),
        "score": float(row[5] or 0),
        "checks": list(row[6] or []),
        "blockers": list(row[7] or []),
        "warnings": list(row[8] or []),
        "metadata": dict(row[9] or {}),
        "created_at": row[10].isoformat() if row[10] is not None else "",
        "updated_at": row[11].isoformat() if row[11] is not None else "",
    }


def summarize_document_topology_scope(
    connection,
    *,
    source_scope: str = "",
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    owner_user_id: str = "",
    include_shared: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    document_ids = _latest_document_ids_for_scope(
        connection,
        source_scope=source_scope,
        tenant_slug=tenant_slug,
        workspace_slug=workspace_slug,
        owner_user_id=owner_user_id,
        include_shared=include_shared,
        limit=limit,
    )
    snapshots: list[dict[str, Any]] = []
    blockers: list[str] = []
    for document_source_id, parsed_document_id in document_ids:
        snapshot = _load_topology_snapshot_summary(
            connection,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
        )
        if snapshot is None:
            snapshot = get_or_create_document_topology_snapshot_by_id(
                connection,
                document_source_id=document_source_id,
                parsed_document_id=parsed_document_id,
            )
        if snapshot:
            snapshots.append(snapshot)
            blockers.extend(str(item) for item in snapshot.get("blockers") or [] if str(item).strip())

    node_count = sum(int(snapshot.get("summary", {}).get("node_count") or 0) for snapshot in snapshots)
    edge_count = sum(int(snapshot.get("summary", {}).get("edge_count") or 0) for snapshot in snapshots)
    asset_count = sum(int(snapshot.get("summary", {}).get("asset_count") or 0) for snapshot in snapshots)
    described_asset_count = sum(int(snapshot.get("summary", {}).get("described_asset_count") or 0) for snapshot in snapshots)
    concept_count = sum(int(snapshot.get("summary", {}).get("concept_count") or 0) for snapshot in snapshots)
    command_count = sum(int(snapshot.get("summary", {}).get("command_count") or 0) for snapshot in snapshots)
    ready_count = sum(1 for snapshot in snapshots if str(snapshot.get("state") or "") == "ready")
    needs_review_count = len(snapshots) - ready_count
    blocker_counts: dict[str, int] = {}
    for blocker in blockers:
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    top_blockers = [
        {"message": message, "count": count}
        for message, count in sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    return {
        "schema_version": TOPOLOGY_SCHEMA_VERSION,
        "source_scope": source_scope,
        "document_count": len(document_ids),
        "snapshot_count": len(snapshots),
        "ready_count": ready_count,
        "needs_review_count": needs_review_count,
        "node_count": node_count,
        "edge_count": edge_count,
        "asset_count": asset_count,
        "described_asset_count": described_asset_count,
        "missing_asset_description_count": max(0, asset_count - described_asset_count),
        "image_description_coverage": round(described_asset_count / asset_count, 4) if asset_count else 1.0,
        "concept_count": concept_count,
        "command_count": command_count,
        "blockers": top_blockers,
        "documents": [
            {
                "document_source_id": snapshot.get("document_source_id"),
                "parsed_document_id": snapshot.get("parsed_document_id"),
                "state": snapshot.get("state"),
                "summary": snapshot.get("summary"),
                "updated_at": snapshot.get("updated_at"),
            }
            for snapshot in snapshots[:50]
        ],
    }


__all__ = [
    "ParsedDocumentRows",
    "LoadedParsedDocumentForRepair",
    "ReplacedParsedDocumentContent",
    "StoredParsedDocument",
    "bind_upload_pipeline_events",
    "build_parsed_document_rows",
    "_merge_repair_document_metadata",
    "document_topology_input_fingerprint",
    "document_topology_source_fingerprint",
    "get_or_create_document_topology_snapshot",
    "get_or_create_document_topology_snapshot_by_id",
    "insert_upload_pipeline_event",
    "list_upload_pipeline_events",
    "load_document_quality_snapshot",
    "load_document_reader",
    "load_parsed_document_for_repair",
    "load_document_topology_snapshot_summary",
    "load_document_topology_source",
    "list_document_repositories",
    "persist_parsed_upload_document",
    "replace_parsed_document_content",
    "summarize_document_topology_scope",
    "update_document_source_gold_build_run",
    "update_document_source_metadata",
    "upsert_document_quality_snapshot",
]
