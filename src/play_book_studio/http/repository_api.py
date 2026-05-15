from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings
from play_book_studio.db.document_repository import list_document_repositories


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


__all__ = [
    "build_document_repositories_response",
    "handle_document_repositories",
]
