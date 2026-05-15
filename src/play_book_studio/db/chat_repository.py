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
        values = citation.get(f"{key}s") if key == "asset_id" else None
        if not isinstance(values, list):
            values = [citation.get(key)]
        for item in values:
            value = str(item or "").strip()
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


def list_chat_sessions(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    anonymous_user_id: str = "",
    user_id: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    effective_limit = max(1, min(int(limit), 200))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                cs.id::text,
                cs.client_session_id,
                cs.title,
                cs.status,
                cs.active_repository_id::text,
                cs.anonymous_user_id,
                cs.user_id,
                cs.metadata,
                count(cm.id)::int AS message_count,
                cs.created_at,
                cs.updated_at
            FROM chat_sessions cs
            JOIN tenants t ON t.id = cs.tenant_id
            JOIN workspaces w ON w.id = cs.workspace_id
            LEFT JOIN chat_messages cm ON cm.chat_session_id = cs.id
            WHERE t.slug = %s
              AND w.slug = %s
              AND cs.anonymous_user_id = %s
              AND cs.user_id = %s
              AND cs.status = 'active'
            GROUP BY cs.id
            ORDER BY cs.updated_at DESC
            LIMIT %s
            """,
            (tenant_slug, workspace_slug, anonymous_user_id, user_id, effective_limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "chat_session_id": str(row[0]),
            "client_session_id": str(row[1] or ""),
            "title": str(row[2] or ""),
            "status": str(row[3] or ""),
            "active_repository_id": str(row[4] or ""),
            "anonymous_user_id": str(row[5] or ""),
            "user_id": str(row[6] or ""),
            "metadata": dict(row[7] or {}),
            "message_count": int(row[8] or 0),
            "created_at": row[9].isoformat() if row[9] is not None else "",
            "updated_at": row[10].isoformat() if row[10] is not None else "",
        }
        for row in rows
    ]


def list_chat_messages(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    anonymous_user_id: str = "",
    user_id: str = "",
    client_session_id: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    effective_limit = max(1, min(int(limit), 500))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                cm.id::text,
                cm.role,
                cm.content,
                cm.cited_chunk_ids,
                cm.cited_asset_ids,
                cm.metadata,
                cm.created_at
            FROM chat_messages cm
            JOIN chat_sessions cs ON cs.id = cm.chat_session_id
            JOIN tenants t ON t.id = cs.tenant_id
            JOIN workspaces w ON w.id = cs.workspace_id
            WHERE t.slug = %s
              AND w.slug = %s
              AND cs.anonymous_user_id = %s
              AND cs.user_id = %s
              AND cs.client_session_id = %s
              AND cs.status = 'active'
            ORDER BY cm.created_at ASC, cm.id ASC
            LIMIT %s
            """,
            (tenant_slug, workspace_slug, anonymous_user_id, user_id, client_session_id, effective_limit),
        )
        rows = cursor.fetchall()
    return [
        {
            "message_id": str(row[0]),
            "role": str(row[1] or ""),
            "content": str(row[2] or ""),
            "cited_chunk_ids": list(row[3] or []),
            "cited_asset_ids": list(row[4] or []),
            "metadata": dict(row[5] or {}),
            "created_at": row[6].isoformat() if row[6] is not None else "",
        }
        for row in rows
    ]


def list_chat_quality_question_candidates(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    anonymous_user_id: str = "",
    user_id: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    effective_limit = max(1, min(int(limit), 100))
    owner_filter_sql = ""
    params: list[Any] = [tenant_slug, workspace_slug]
    if anonymous_user_id:
        owner_filter_sql += " AND cs.anonymous_user_id = %s"
        params.append(anonymous_user_id)
    if user_id:
        owner_filter_sql += " AND cs.user_id = %s"
        params.append(user_id)
    params.append(effective_limit)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                u.content,
                COALESCE(a.metadata->>'response_kind', '') AS response_kind,
                COALESCE(a.metadata->>'rewritten_query', '') AS rewritten_query,
                count(*)::int AS occurrence_count,
                max(a.created_at) AS last_seen_at
            FROM chat_messages u
            JOIN chat_sessions cs ON cs.id = u.chat_session_id
            JOIN tenants t ON t.id = cs.tenant_id
            JOIN workspaces w ON w.id = cs.workspace_id
            JOIN chat_messages a ON a.chat_session_id = u.chat_session_id
              AND a.role = 'assistant'
              AND COALESCE(a.metadata->>'turn_id', '') = COALESCE(u.metadata->>'turn_id', '')
            WHERE t.slug = %s
              AND w.slug = %s
              AND cs.status = 'active'
              AND u.role = 'user'
              AND length(trim(u.content)) BETWEEN 3 AND 220
              AND COALESCE(a.metadata->>'response_kind', '') <> 'smalltalk'
              {owner_filter_sql}
            GROUP BY u.content, response_kind, rewritten_query
            ORDER BY
                CASE response_kind
                    WHEN 'clarification' THEN 3
                    WHEN 'no_answer' THEN 2
                    ELSE 1
                END DESC,
                occurrence_count DESC,
                last_seen_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cursor.fetchall()
    return [
        {
            "query": str(row[0] or ""),
            "response_kind": str(row[1] or ""),
            "rewritten_query": str(row[2] or ""),
            "occurrence_count": int(row[3] or 0),
            "last_seen_at": row[4].isoformat() if row[4] is not None else "",
        }
        for row in rows
    ]


def archive_chat_session(
    connection,
    *,
    tenant_slug: str = "public",
    workspace_slug: str = "default",
    anonymous_user_id: str = "",
    user_id: str = "",
    client_session_id: str = "",
) -> bool:
    if not str(client_session_id or "").strip():
        raise ValueError("client_session_id is required")
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chat_sessions cs
                SET status = 'archived',
                    updated_at = now(),
                    metadata = cs.metadata || jsonb_build_object('archived_at', now())
                FROM tenants t, workspaces w
                WHERE cs.tenant_id = t.id
                  AND cs.workspace_id = w.id
                  AND t.slug = %s
                  AND w.slug = %s
                  AND cs.anonymous_user_id = %s
                  AND cs.user_id = %s
                  AND cs.client_session_id = %s
                  AND cs.status = 'active'
                RETURNING cs.id
                """,
                (tenant_slug, workspace_slug, anonymous_user_id, user_id, client_session_id),
            )
            return cursor.fetchone() is not None


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
    "archive_chat_session",
    "list_chat_quality_question_candidates",
    "list_chat_messages",
    "list_chat_sessions",
    "persist_chat_turn",
]
