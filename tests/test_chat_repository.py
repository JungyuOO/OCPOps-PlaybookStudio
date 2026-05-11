from __future__ import annotations

from datetime import datetime, timezone

from play_book_studio.db.chat_repository import (
    archive_chat_session,
    list_chat_quality_question_candidates,
    list_chat_messages,
    list_chat_sessions,
    persist_chat_turn,
)


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.return_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 20)]
        self.fetchall_rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return (self.return_ids.pop(0),)

    def fetchall(self):
        return list(self.fetchall_rows)


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj


def test_persist_chat_turn_upserts_session_and_messages():
    connection = FakeConnection()

    stored = persist_chat_turn(
        connection,
        client_session_id="client-session",
        anonymous_user_id="owner-hash",
        query="How do I check pods?",
        answer="Use oc get pods. [1]",
        active_repository_id="11111111-1111-1111-1111-111111111111",
        turn_id="turn-1",
        parent_turn_id="turn-0",
        rewritten_query="check pods",
        response_kind="rag",
        citations=[
            {"chunk_id": "chunk-a", "asset_id": "asset-a"},
            {"chunk_id": "chunk-a", "asset_id": "asset-a"},
            {"chunk_id": "chunk-b"},
        ],
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "INSERT INTO tenants" in sql_text
    assert "INSERT INTO workspaces" in sql_text
    assert "INSERT INTO chat_sessions" in sql_text
    assert "INSERT INTO chat_messages" in sql_text
    assert "NULLIF(%s, '')::uuid" in sql_text
    assert stored.chat_session_id.endswith("000000000003")
    assert stored.user_message_id.endswith("000000000004")
    assert stored.assistant_message_id.endswith("000000000005")
    assistant_params = connection.cursor_obj.calls[-1][1]
    assert assistant_params[1] == "assistant"
    assert assistant_params[3] == '["chunk-a", "chunk-b"]'
    assert assistant_params[4] == '["asset-a"]'


def test_persist_chat_turn_extracts_cited_asset_ids_from_asset_id_lists():
    connection = FakeConnection()

    persist_chat_turn(
        connection,
        client_session_id="client-session",
        anonymous_user_id="owner-hash",
        query="How do I inspect the image?",
        answer="Use the cited figure. [1]",
        citations=[
            {"chunk_id": "chunk-a", "asset_ids": ["asset-a", "asset-b"]},
            {"chunk_id": "chunk-b", "asset_ids": ["asset-a"]},
        ],
    )

    assistant_params = connection.cursor_obj.calls[-1][1]
    assert assistant_params[3] == '["chunk-a", "chunk-b"]'
    assert assistant_params[4] == '["asset-a", "asset-b"]'


def test_list_chat_sessions_filters_to_owner_scope():
    connection = FakeConnection()
    connection.cursor_obj.fetchall_rows = [
        (
            "chat-session-id",
            "client-session",
            "How do I check pods?",
            "active",
            "11111111-1111-1111-1111-111111111111",
            "owner-hash",
            "",
            {"mode": "chat"},
            2,
            datetime(2026, 5, 4, tzinfo=timezone.utc),
            datetime(2026, 5, 4, 1, tzinfo=timezone.utc),
        )
    ]

    sessions = list_chat_sessions(
        connection,
        anonymous_user_id="owner-hash",
        limit=10,
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "FROM chat_sessions cs" in sql_text
    assert "cs.anonymous_user_id = %s" in sql_text
    assert "cs.status = 'active'" in sql_text
    assert connection.cursor_obj.calls[0][1] == ("public", "default", "owner-hash", "", 10)
    assert sessions[0]["client_session_id"] == "client-session"
    assert sessions[0]["message_count"] == 2


def test_list_chat_messages_filters_to_owner_and_client_session():
    connection = FakeConnection()
    connection.cursor_obj.fetchall_rows = [
        (
            "message-id",
            "assistant",
            "Use oc get pods. [1]",
            ["chunk-a"],
            ["asset-a"],
            {"response_kind": "rag"},
            datetime(2026, 5, 4, tzinfo=timezone.utc),
        )
    ]

    messages = list_chat_messages(
        connection,
        anonymous_user_id="owner-hash",
        client_session_id="client-session",
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "FROM chat_messages cm" in sql_text
    assert "cs.client_session_id = %s" in sql_text
    assert "cs.status = 'active'" in sql_text
    assert connection.cursor_obj.calls[0][1] == ("public", "default", "owner-hash", "", "client-session", 200)
    assert messages[0]["message_id"] == "message-id"
    assert messages[0]["cited_chunk_ids"] == ["chunk-a"]


def test_archive_chat_session_scopes_update_to_owner_and_client_session():
    connection = FakeConnection()

    archived = archive_chat_session(
        connection,
        anonymous_user_id="owner-hash",
        client_session_id="client-session",
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert archived is True
    assert "UPDATE chat_sessions cs" in sql_text
    assert "SET status = 'archived'" in sql_text
    assert "cs.anonymous_user_id = %s" in sql_text
    assert "cs.client_session_id = %s" in sql_text
    assert "cs.status = 'active'" in sql_text
    assert connection.cursor_obj.calls[0][1] == ("public", "default", "owner-hash", "", "client-session")


def test_list_chat_quality_question_candidates_prioritizes_problematic_turns():
    connection = FakeConnection()
    connection.cursor_obj.fetchall_rows = [
        (
            "OCP 설치 어떻게 해",
            "clarification",
            "OpenShift Container Platform 설치",
            3,
            datetime(2026, 5, 4, tzinfo=timezone.utc),
        )
    ]

    candidates = list_chat_quality_question_candidates(
        connection,
        anonymous_user_id="owner-hash",
        limit=10,
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "JOIN chat_messages a" in sql_text
    assert "a.metadata->>'turn_id'" in sql_text
    assert "WHEN 'clarification' THEN 3" in sql_text
    assert "cs.anonymous_user_id = %s" in sql_text
    assert connection.cursor_obj.calls[0][1] == ("public", "default", "owner-hash", 10)
    assert candidates[0]["query"] == "OCP 설치 어떻게 해"
    assert candidates[0]["response_kind"] == "clarification"
    assert candidates[0]["occurrence_count"] == 3
