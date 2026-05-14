from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

from play_book_studio.http import repository_api

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


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_document_reader_response_passes_owner_scope_and_pagination(monkeypatch):
    calls = {}

    class FakePsycopg:
        @staticmethod
        def connect(database_url):
            calls["database_url"] = database_url
            return _FakeConnection()

    def fake_load_document_reader(connection, **kwargs):
        calls["connection"] = connection
        calls["kwargs"] = kwargs
        return {
            "document_source_id": kwargs["document_source_id"],
            "chunks": [],
        }

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    monkeypatch.setattr(repository_api, "load_settings", lambda _root_dir: SimpleNamespace(database_url="postgresql://unit"))
    monkeypatch.setattr(repository_api, "load_document_reader", fake_load_document_reader)

    payload = repository_api.build_document_reader_response(
        REPO_ROOT,
        "document_source_id=11111111-1111-1111-1111-111111111111&limit=20&offset=40&include_shared=false",
        owner_user_id="owner-1",
    )

    assert payload["database"] == "postgres"
    assert payload["owner_user_id"] == "owner-1"
    assert calls["database_url"] == "postgresql://unit"
    assert calls["kwargs"] == {
        "tenant_slug": "public",
        "workspace_slug": "default",
        "owner_user_id": "owner-1",
        "include_shared": False,
        "document_source_id": "11111111-1111-1111-1111-111111111111",
        "parsed_document_id": "",
        "limit": 20,
        "offset": 40,
    }


def test_document_reader_response_inlines_image_asset_data_urls(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    asset_path = storage_dir / "uploads/assets/asset-1.png"
    asset_path.parent.mkdir(parents=True)
    asset_body = b"\x89PNG\r\n\x1a\nasset"
    asset_path.write_bytes(asset_body)

    class FakePsycopg:
        @staticmethod
        def connect(_database_url):
            return _FakeConnection()

    def fake_load_document_reader(_connection, **kwargs):
        return {
            "document_source_id": kwargs["document_source_id"],
            "chunks": [],
            "assets": [
                {
                    "asset_id": "asset-1",
                    "asset_type": "image",
                    "mime_type": "image/png",
                    "storage_key": "uploads/assets/asset-1.png",
                    "sha256": "sha",
                    "filename": "page-001.png",
                    "page_number": 1,
                    "metadata": {},
                }
            ],
        }

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    monkeypatch.setattr(
        repository_api,
        "load_settings",
        lambda _root_dir: SimpleNamespace(database_url="postgresql://unit", object_storage_dir=storage_dir),
    )
    monkeypatch.setattr(repository_api, "load_document_reader", fake_load_document_reader)

    payload = repository_api.build_document_reader_response(
        REPO_ROOT,
        "document_source_id=11111111-1111-1111-1111-111111111111",
        owner_user_id="owner-1",
    )

    inline_asset = payload["document"]["assets"][0]
    assert inline_asset["available"] is True
    assert inline_asset["byte_size"] == len(asset_body)
    assert inline_asset["data_url"] == f"data:image/png;base64,{base64.b64encode(asset_body).decode('ascii')}"


def test_document_reader_response_marks_missing_or_unsafe_assets_unavailable(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()

    class FakePsycopg:
        @staticmethod
        def connect(_database_url):
            return _FakeConnection()

    def fake_load_document_reader(_connection, **kwargs):
        return {
            "document_source_id": kwargs["document_source_id"],
            "chunks": [],
            "assets": [
                {
                    "asset_id": "asset-1",
                    "asset_type": "image",
                    "mime_type": "image/png",
                    "storage_key": "../outside.png",
                    "sha256": "sha",
                    "metadata": {},
                }
            ],
        }

    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg)
    monkeypatch.setattr(
        repository_api,
        "load_settings",
        lambda _root_dir: SimpleNamespace(database_url="postgresql://unit", object_storage_dir=storage_dir),
    )
    monkeypatch.setattr(repository_api, "load_document_reader", fake_load_document_reader)

    payload = repository_api.build_document_reader_response(
        REPO_ROOT,
        "document_source_id=11111111-1111-1111-1111-111111111111",
        owner_user_id="owner-1",
    )

    inline_asset = payload["document"]["assets"][0]
    assert inline_asset["available"] is False
    assert "data_url" not in inline_asset
