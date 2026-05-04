from __future__ import annotations

from play_book_studio.db.chat_repository import persist_chat_turn


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.return_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 20)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        return (self.return_ids.pop(0),)


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
