from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.chat_quality_api as chat_quality_api
from play_book_studio.http.chat_quality_api import build_chat_quality_query_insights


def test_chat_quality_query_insights_is_analysis_only(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_quality_api,
        "load_settings",
        lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        chat_quality_api.psycopg if hasattr(chat_quality_api, "psycopg") else chat_quality_api,
        "psycopg",
        None,
        raising=False,
    )

    def fake_connect(_database_url):
        return FakeConnection()

    def fake_candidates(_connection, *, limit=20):
        assert limit == 7
        return [
            {
                "query": "Secret 컨피그가 계속 오류뜨는데 왜이래",
                "response_kind": "clarification",
                "rewritten_query": "Secret ConfigMap troubleshooting",
                "occurrence_count": 2,
                "last_seen_at": "2026-05-11T00:00:00+00:00",
            }
        ]

    monkeypatch.setitem(
        __import__("sys").modules,
        "psycopg",
        SimpleNamespace(connect=fake_connect),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "play_book_studio.db.chat_repository",
        SimpleNamespace(list_chat_quality_question_candidates=fake_candidates),
    )

    payload = build_chat_quality_query_insights(Path("."), "limit=7")

    assert payload["ready"] is True
    assert payload["usage"] == "analysis_only_not_rag_input"
    assert payload["insights"][0]["query"] == "Secret 컨피그가 계속 오류뜨는데 왜이래"
    assert payload["insights"][0]["recommended_action"] == "review_query_understanding_or_retrieval"


def test_chat_quality_query_insights_reports_unconfigured_database(monkeypatch) -> None:
    monkeypatch.setattr(
        chat_quality_api,
        "load_settings",
        lambda _root: SimpleNamespace(database_url=""),
    )

    payload = build_chat_quality_query_insights(Path("."))

    assert payload["ready"] is False
    assert payload["reason"] == "database_url_unconfigured"
    assert payload["insights"] == []
