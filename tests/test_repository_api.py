from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from play_book_studio.app import repository_api

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_document_repositories_response_is_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(repository_api, "load_settings", lambda _root_dir: SimpleNamespace(database_url=""))

    payload = repository_api.build_document_repositories_response(
        REPO_ROOT,
        "",
        owner_user_id="owner-1",
    )

    assert payload["database"] == "disabled"
    assert payload["count"] == 0
    assert payload["repositories"] == []
