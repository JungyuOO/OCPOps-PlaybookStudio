from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings
from play_book_studio.db.chat_repository import list_chat_messages, list_chat_sessions


def _int_query(value: str, *, default: int, upper: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return max(1, min(parsed, upper))


def _database_url(root_dir: Path) -> str:
    return load_settings(root_dir).database_url.strip()


def build_chat_history_sessions_response(
    root_dir: Path,
    query: str,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    database_url = _database_url(root_dir)
    if not database_url:
        return {"database": "disabled", "count": 0, "sessions": []}
    params = parse_qs(query, keep_blank_values=False)
    tenant_slug = str((params.get("tenant_slug") or ["public"])[0] or "public").strip()
    workspace_slug = str((params.get("workspace_slug") or ["default"])[0] or "default").strip()
    user_id = str((params.get("user_id") or [""])[0] or "").strip()
    limit = _int_query(str((params.get("limit") or ["50"])[0]), default=50, upper=200)

    import psycopg

    with psycopg.connect(database_url) as connection:
        sessions = list_chat_sessions(
            connection,
            tenant_slug=tenant_slug,
            workspace_slug=workspace_slug,
            anonymous_user_id=owner_user_id,
            user_id=user_id,
            limit=limit,
        )
    return {
        "database": "postgres",
        "tenant_slug": tenant_slug,
        "workspace_slug": workspace_slug,
        "owner_user_id": owner_user_id,
        "count": len(sessions),
        "sessions": sessions,
    }


def build_chat_history_messages_response(
    root_dir: Path,
    query: str,
    *,
    owner_user_id: str,
) -> dict[str, Any]:
    database_url = _database_url(root_dir)
    if not database_url:
        return {"database": "disabled", "count": 0, "messages": []}
    params = parse_qs(query, keep_blank_values=False)
    client_session_id = str((params.get("client_session_id") or params.get("session_id") or [""])[0] or "").strip()
    if not client_session_id:
        raise ValueError("client_session_id is required")
    tenant_slug = str((params.get("tenant_slug") or ["public"])[0] or "public").strip()
    workspace_slug = str((params.get("workspace_slug") or ["default"])[0] or "default").strip()
    user_id = str((params.get("user_id") or [""])[0] or "").strip()
    limit = _int_query(str((params.get("limit") or ["200"])[0]), default=200, upper=500)

    import psycopg

    with psycopg.connect(database_url) as connection:
        messages = list_chat_messages(
            connection,
            tenant_slug=tenant_slug,
            workspace_slug=workspace_slug,
            anonymous_user_id=owner_user_id,
            user_id=user_id,
            client_session_id=client_session_id,
            limit=limit,
        )
    return {
        "database": "postgres",
        "tenant_slug": tenant_slug,
        "workspace_slug": workspace_slug,
        "owner_user_id": owner_user_id,
        "client_session_id": client_session_id,
        "count": len(messages),
        "messages": messages,
    }


def handle_chat_history_sessions(
    handler: Any,
    query: str,
    *,
    root_dir: Path,
    owner_user_id: str,
) -> None:
    try:
        payload = build_chat_history_sessions_response(root_dir, query, owner_user_id=owner_user_id)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"chat history sessions load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


def handle_chat_history_messages(
    handler: Any,
    query: str,
    *,
    root_dir: Path,
    owner_user_id: str,
) -> None:
    try:
        payload = build_chat_history_messages_response(root_dir, query, owner_user_id=owner_user_id)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"chat history messages load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


__all__ = [
    "build_chat_history_messages_response",
    "build_chat_history_sessions_response",
    "handle_chat_history_messages",
    "handle_chat_history_sessions",
]
