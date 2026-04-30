"""Persistence helpers for parsed upload documents."""

from __future__ import annotations

import json
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
    block_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]


def build_parsed_document_rows(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...] | None = None,
    *,
    storage_key: str = "",
    created_by: str = "",
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
) -> StoredParsedDocument:
    rows = build_parsed_document_rows(
        parsed,
        chunks,
        storage_key=storage_key,
        created_by=created_by,
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


def _upsert_document_source(cursor, *, tenant_id: str, workspace_id: str, row: dict[str, Any]) -> str:
    cursor.execute(
        """
        INSERT INTO document_sources (
            tenant_id, workspace_id, source_kind, filename, mime_type, sha256,
            storage_key, byte_size, access_policy, metadata, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (workspace_id, sha256) DO UPDATE SET
            filename = EXCLUDED.filename,
            mime_type = EXCLUDED.mime_type,
            storage_key = EXCLUDED.storage_key,
            byte_size = EXCLUDED.byte_size,
            metadata = EXCLUDED.metadata,
            created_by = EXCLUDED.created_by
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
            text, markdown, section_path, bbox, table_data, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
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
            asset_ids, metadata
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
            %s::jsonb, %s::jsonb
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
            _json(row["asset_ids"]),
            _json(row["metadata"]),
        ),
    )
    return _fetch_id(cursor)


__all__ = [
    "ParsedDocumentRows",
    "StoredParsedDocument",
    "build_parsed_document_rows",
    "persist_parsed_upload_document",
]
