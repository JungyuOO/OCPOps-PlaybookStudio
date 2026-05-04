"""Postgres persistence for chat sessions and turns."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StoredChatTurn:
    chat_session_id: str
    user_message_id: str
    assistant_message_id: str


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


def _citation_ids(citations: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for citation in citations:
        value = str(citation.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def _upsert_chat_session(
    cursor,
    *,
    tenant_id: str,
    workspace_id: str,
    anonymous_user_id: str,
    user_id: str,
    client_session_id: str,
    active_repository_id: str,
    title: str,
    metadata: dict[str, Any],
) -> str:
    cursor.execute(
        """
        INSERT INTO chat_sessions (
            tenant_id, workspace_id, anonymous_user_id, user_id, client_session_id,
            active_repository_id, title, status, metadata, updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, NULLIF(%s, '')::uuid, %s, 'active', %s::jsonb, now()
        )
        ON CONFLICT (
            (COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid)),
            anonymous_user_id,
            user_id,
            client_session_id
        ) DO UPDATE SET
            active_repository_id = COALESCE(EXCLUDED.active_repository_id, chat_sessions.active_repository_id),
            title = CASE
                WHEN chat_sessions.title = '' THEN EXCLUDED.title
                ELSE chat_sessions.title
            END,
            status = 'active',
            metadata = chat_sessions.metadata || EXCLUDED.metadata,
            updated_at = now()
        RETURNING id
        """,
        (
            tenant_id,
            workspace_id,
            anonymous_user_id,
            user_id,
            client_session_id,
            active_repository_id,
            title,
            _json(metadata),
        ),
    )
    return _fetch_id(cursor)


def _insert_chat_message(
    cursor,
    *,
    chat_session_id: str,
    role: str,
    content: str,
    cited_chunk_ids: list[str],
    cited_asset_ids: list[str],
    metadata: dict[str, Any],
) -> str:
    cursor.execute(
        """
        INSERT INTO chat_messages (
            chat_session_id, role, content, cited_chunk_ids, cited_asset_ids, metadata
        )
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            chat_session_id,
            role,
            content,
            _json(cited_chunk_ids),
            _json(cited_asset_ids),
            _json(metadata),
        ),
    )
    return _fetch_id(cursor)


def persist_chat_turn(
    connection,
    *,
    client_session_id: str,
    anonymous_user_id: str,
    query: str,
    answer: str,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    user_id: str = "",
    active_repository_id: str = "",
    turn_id: str = "",
    parent_turn_id: str = "",
    mode: str = "chat",
    response_kind: str = "",
    rewritten_query: str = "",
    citations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> StoredChatTurn:
    citation_payloads = [dict(item) for item in (citations or []) if isinstance(item, dict)]
    cited_chunk_ids = _citation_ids(citation_payloads, "chunk_id")
    cited_asset_ids = _citation_ids(citation_payloads, "asset_id")
    session_metadata = {
        "mode": mode,
        **dict(metadata or {}),
    }
    user_metadata = {
        "turn_id": turn_id,
        "parent_turn_id": parent_turn_id,
        "message_kind": "query",
        "mode": mode,
    }
    assistant_metadata = {
        "turn_id": turn_id,
        "parent_turn_id": parent_turn_id,
        "message_kind": "answer",
        "mode": mode,
        "response_kind": response_kind,
        "rewritten_query": rewritten_query,
        "citations": citation_payloads,
    }
    with connection.transaction():
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_slug=tenant_slug, tenant_name=tenant_name)
            workspace_id = _upsert_workspace(
                cursor,
                tenant_id=tenant_id,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
            )
            chat_session_id = _upsert_chat_session(
                cursor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                anonymous_user_id=anonymous_user_id,
                user_id=user_id,
                client_session_id=client_session_id,
                active_repository_id=active_repository_id,
                title=query[:120],
                metadata=session_metadata,
            )
            user_message_id = _insert_chat_message(
                cursor,
                chat_session_id=chat_session_id,
                role="user",
                content=query,
                cited_chunk_ids=[],
                cited_asset_ids=[],
                metadata=user_metadata,
            )
            assistant_message_id = _insert_chat_message(
                cursor,
                chat_session_id=chat_session_id,
                role="assistant",
                content=answer,
                cited_chunk_ids=cited_chunk_ids,
                cited_asset_ids=cited_asset_ids,
                metadata=assistant_metadata,
            )
    return StoredChatTurn(
        chat_session_id=chat_session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )


__all__ = [
    "StoredChatTurn",
    "persist_chat_turn",
]
