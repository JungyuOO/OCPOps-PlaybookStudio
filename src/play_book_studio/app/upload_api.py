from __future__ import annotations

import base64
import re
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.db.document_repository import persist_parsed_upload_document
from play_book_studio.db.qdrant_indexer import index_pending_document_chunks
from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document


def _bool_payload(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_payload(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _file_bytes_from_payload(payload: dict[str, Any]) -> bytes:
    file_bytes = payload.get("file_bytes")
    if isinstance(file_bytes, (bytes, bytearray)):
        return bytes(file_bytes)
    content_base64 = str(payload.get("content_base64") or "").strip()
    if not content_base64:
        raise ValueError("file_bytes or content_base64 is required")
    try:
        return base64.b64decode(content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("content_base64 is not valid base64") from exc


def _safe_upload_name(file_name: str) -> str:
    source = Path(str(file_name or "upload").strip()).name
    suffix = Path(source).suffix
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source).stem).strip("-._")
    return f"{safe_stem or 'upload'}{suffix or '.bin'}"


def _store_uploaded_file(root_dir: Path, payload: dict[str, Any]) -> tuple[Path, str, int]:
    settings = load_settings(root_dir)
    content = _file_bytes_from_payload(payload)
    if not content:
        raise ValueError("uploaded file is empty")
    file_name = _safe_upload_name(str(payload.get("file_name") or "upload"))
    upload_id = uuid.uuid4().hex
    storage_key = f"uploads/sources/{upload_id}/{file_name}"
    target = (settings.object_storage_dir / storage_key).resolve()
    storage_root = settings.object_storage_dir.resolve()
    if storage_root not in target.parents:
        raise ValueError("invalid upload path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target, storage_key, len(content)


def build_upload_ingest_response(
    root_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    source_path, storage_key, byte_size = _store_uploaded_file(root_dir, payload)
    parsed = parse_upload_document(source_path)
    chunks = build_document_chunks(
        parsed,
        max_chars=_int_payload(payload.get("chunk_max_chars"), default=1800),
        overlap_blocks=_int_payload(payload.get("chunk_overlap_blocks"), default=1),
    )
    dry_run = _bool_payload(payload.get("dry_run"), default=False)
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "filename": parsed.filename,
        "storage_key": storage_key,
        "byte_size": byte_size,
        "document_format": parsed.document_format,
        "mime_type": parsed.mime_type,
        "sha256": parsed.sha256,
        "block_count": len(parsed.blocks),
        "asset_count": len(parsed.assets),
        "chunk_count": len(chunks),
        "warnings": list(parsed.warnings),
        "sections": [list(chunk.section_path) for chunk in chunks if chunk.section_path],
    }
    if dry_run:
        return result

    database_url = str(payload.get("database_url") or settings.database_url or "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required for upload ingestion")

    import psycopg

    with psycopg.connect(database_url) as connection:
        persisted = persist_parsed_upload_document(
            connection,
            parsed,
            chunks,
            tenant_slug=str(payload.get("tenant_slug") or "public"),
            tenant_name=str(payload.get("tenant_name") or "Public"),
            workspace_slug=str(payload.get("workspace_slug") or "default"),
            workspace_name=str(payload.get("workspace_name") or "Default"),
            storage_key=storage_key,
            created_by=str(payload.get("created_by") or ""),
        )
        result["persisted"] = {
            "document_source_id": persisted.document_source_id,
            "document_version_id": persisted.document_version_id,
            "parse_job_id": persisted.parse_job_id,
            "parsed_document_id": persisted.parsed_document_id,
            "block_count": len(persisted.block_ids),
            "asset_count": len(persisted.asset_ids),
            "chunk_count": len(persisted.chunk_ids),
        }
        if _bool_payload(payload.get("index"), default=False):
            result["index"] = index_pending_document_chunks(
                settings,
                connection,
                collection=str(payload.get("collection") or "").strip() or None,
                limit=_int_payload(payload.get("index_limit"), default=max(100, len(chunks))),
            )
    return result


def handle_upload_ingest(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        result = build_upload_ingest_response(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"upload ingestion failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(result)


__all__ = [
    "build_upload_ingest_response",
    "handle_upload_ingest",
]
