from __future__ import annotations

import base64
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings
from play_book_studio.db.document_repository import (
    get_or_create_document_topology_snapshot_by_id,
    load_document_reader,
    list_document_repositories,
    summarize_document_topology_scope,
)


def _bool_query(value: str, *, default: bool = True) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_document_repositories_response(
    root_dir: Path,
    query: str,
    *,
    owner_user_id: str = "",
) -> dict[str, Any]:
    params = parse_qs(query, keep_blank_values=False)
    settings = load_settings(root_dir)
    database_url = str((params.get("database_url") or [""])[0] or settings.database_url or "").strip()
    if not database_url:
        return {
            "database": "disabled",
            "repositories": [],
            "count": 0,
        }

    import psycopg

    tenant_slug = str((params.get("tenant_slug") or ["public"])[0] or "public").strip()
    workspace_slug = str((params.get("workspace_slug") or ["default"])[0] or "default").strip()
    include_shared = _bool_query(str((params.get("include_shared") or ["true"])[0]), default=True)
    with psycopg.connect(database_url) as connection:
        repositories = list_document_repositories(
            connection,
            tenant_slug=tenant_slug,
            workspace_slug=workspace_slug,
            owner_user_id=owner_user_id,
            include_shared=include_shared,
            collection=settings.qdrant_collection,
        )
    return {
        "database": "postgres",
        "tenant_slug": tenant_slug,
        "workspace_slug": workspace_slug,
        "owner_user_id": owner_user_id,
        "count": len(repositories),
        "repositories": repositories,
    }


def handle_document_repositories(
    handler: Any,
    query: str,
    *,
    root_dir: Path,
    owner_user_id: str = "",
) -> None:
    try:
        payload = build_document_repositories_response(root_dir, query, owner_user_id=owner_user_id)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"document repositories load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


def build_document_reader_response(root_dir: Path, query: str, *, owner_user_id: str = "") -> dict[str, Any]:
    params = parse_qs(query, keep_blank_values=False)
    settings = load_settings(root_dir)
    database_url = str((params.get("database_url") or [""])[0] or settings.database_url or "").strip()
    if not database_url:
        return {
            "database": "disabled",
            "document": None,
        }

    document_source_id = str((params.get("document_source_id") or [""])[0] or "").strip()
    parsed_document_id = str((params.get("parsed_document_id") or [""])[0] or "").strip()
    tenant_slug = str((params.get("tenant_slug") or ["public"])[0] or "public").strip()
    workspace_slug = str((params.get("workspace_slug") or ["default"])[0] or "default").strip()
    include_shared = _bool_query(str((params.get("include_shared") or ["true"])[0]), default=True)
    limit = int(str((params.get("limit") or ["80"])[0] or "80"))
    offset = int(str((params.get("offset") or ["0"])[0] or "0"))

    import psycopg

    with psycopg.connect(database_url) as connection:
        document = load_document_reader(
            connection,
            tenant_slug=tenant_slug,
            workspace_slug=workspace_slug,
            owner_user_id=owner_user_id,
            include_shared=include_shared,
            document_source_id=document_source_id,
            parsed_document_id=parsed_document_id,
            limit=limit,
            offset=offset,
        )
    if document is not None:
        try:
            with psycopg.connect(database_url) as connection:
                document["topology"] = get_or_create_document_topology_snapshot_by_id(
                    connection,
                    document_source_id=str(document.get("document_source_id") or ""),
                    parsed_document_id=str(document.get("parsed_document_id") or ""),
                )
        except Exception as exc:  # noqa: BLE001
            document["topology"] = {
                "schema_version": "",
                "document_source_id": str(document.get("document_source_id") or ""),
                "parsed_document_id": str(document.get("parsed_document_id") or ""),
                "summary": {
                    "state": "needs_review",
                    "blockers": [f"Topology snapshot을 불러오지 못했습니다: {exc}"],
                    "node_count": 0,
                    "edge_count": 0,
                },
                "nodes": [],
                "edges": [],
                "metadata": {"storage": "unavailable", "snapshot_error": str(exc)},
            }
        _attach_reader_asset_data_urls(settings, document)
    return {
        "database": "postgres",
        "tenant_slug": tenant_slug,
        "workspace_slug": workspace_slug,
        "owner_user_id": owner_user_id,
        "document": document,
    }


def _source_scope_from_public_scope(scope: str) -> str:
    normalized = str(scope or "").strip().lower()
    if normalized in {"official", "ocp", "official_docs"}:
        return "official_docs"
    if normalized in {"customer", "study", "study_docs"}:
        return "study_docs"
    if normalized in {"uploads", "upload", "user", "user_upload"}:
        return "user_upload"
    return normalized


def build_document_topology_response(root_dir: Path, query: str, *, owner_user_id: str = "") -> dict[str, Any]:
    params = parse_qs(query, keep_blank_values=False)
    settings = load_settings(root_dir)
    database_url = str((params.get("database_url") or [""])[0] or settings.database_url or "").strip()
    if not database_url:
        return {
            "database": "disabled",
            "schema_version": "",
            "source_scope": _source_scope_from_public_scope(str((params.get("scope") or [""])[0])),
            "document_count": 0,
            "snapshot_count": 0,
        }
    source_scope = _source_scope_from_public_scope(str((params.get("scope") or [""])[0]))
    tenant_slug = str((params.get("tenant_slug") or ["public"])[0] or "public").strip()
    workspace_slug = str((params.get("workspace_slug") or ["default"])[0] or "default").strip()
    include_shared = _bool_query(str((params.get("include_shared") or ["true"])[0]), default=True)
    limit = int(str((params.get("limit") or ["200"])[0] or "200"))

    import psycopg

    with psycopg.connect(database_url) as connection:
        summary = summarize_document_topology_scope(
            connection,
            source_scope=source_scope,
            tenant_slug=tenant_slug,
            workspace_slug=workspace_slug,
            owner_user_id=owner_user_id,
            include_shared=include_shared,
            limit=limit,
        )
    return {
        "database": "postgres",
        "tenant_slug": tenant_slug,
        "workspace_slug": workspace_slug,
        "owner_user_id": owner_user_id,
        **summary,
    }


def _attach_reader_asset_data_urls(settings: Any, document: dict[str, Any]) -> None:
    assets = document.get("assets")
    if not isinstance(assets, list) or not assets:
        return
    storage_root = settings.object_storage_dir.resolve()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        storage_key = str(asset.get("storage_key") or "").strip()
        mime_type = str(asset.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream"
        if not storage_key or not mime_type.startswith("image/"):
            continue
        target = (storage_root / storage_key).resolve()
        if storage_root not in target.parents or not target.is_file():
            asset["available"] = False
            continue
        body = target.read_bytes()
        asset["available"] = True
        asset["byte_size"] = len(body)
        asset["data_url"] = f"data:{mime_type};base64,{base64.b64encode(body).decode('ascii')}"


def handle_document_reader(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    try:
        payload = build_document_reader_response(root_dir, query, owner_user_id=owner_user_id)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"document reader load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    if payload.get("database") == "postgres" and payload.get("document") is None:
        handler._send_json({"error": "document not found"}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(payload)


def handle_document_topology(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    try:
        payload = build_document_topology_response(root_dir, query, owner_user_id=owner_user_id)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"document topology load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


__all__ = [
    "build_document_reader_response",
    "build_document_repositories_response",
    "build_document_topology_response",
    "handle_document_reader",
    "handle_document_repositories",
    "handle_document_topology",
]
