from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from play_book_studio.app.learning_api import build_learning_paths_response, handle_learning_paths

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "learning_api_tests"


class DummyHandler:
    def __init__(self) -> None:
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=HTTPStatus.OK):
        self.payload = payload
        self.status = status


def test_build_learning_paths_response_returns_empty_when_database_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    TEST_TMP.mkdir(parents=True, exist_ok=True)

    payload = build_learning_paths_response(TEST_TMP, "")

    assert payload["schema"] == "learning_path_catalog_v1"
    assert payload["source"] == "postgres.learning_paths"
    assert payload["count"] == 0
    assert payload["paths"] == []
    assert payload["unavailable_reason"] == "DATABASE_URL is not configured"


def test_handle_learning_paths_sends_catalog_payload(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    handler = DummyHandler()

    handle_learning_paths(handler, "limit=3", root_dir=TEST_TMP)

    assert handler.status == HTTPStatus.OK
    assert handler.payload["schema"] == "learning_path_catalog_v1"
