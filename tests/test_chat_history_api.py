from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from play_book_studio.app import chat_history_api

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_chat_history_sessions_response_is_disabled_without_database(monkeypatch):
    monkeypatch.setattr(chat_history_api, "load_settings", lambda _root_dir: SimpleNamespace(database_url=""))

    payload = chat_history_api.build_chat_history_sessions_response(
        REPO_ROOT,
        "",
        owner_user_id="owner-hash",
    )

    assert payload == {"database": "disabled", "count": 0, "sessions": []}


def test_chat_history_messages_requires_client_session_id(monkeypatch):
    monkeypatch.setattr(chat_history_api, "load_settings", lambda _root_dir: SimpleNamespace(database_url="postgresql://db"))

    with pytest.raises(ValueError, match="client_session_id"):
        chat_history_api.build_chat_history_messages_response(
            REPO_ROOT,
            "",
            owner_user_id="owner-hash",
        )
