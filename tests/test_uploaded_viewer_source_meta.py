from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from urllib.parse import urlencode

import psycopg

from play_book_studio.http import server_routes_viewer


class _CaptureHandler:
    def __init__(self, owner_hash: str) -> None:
        self.calls: list[tuple[HTTPStatus, dict[str, object]]] = []
        self.owner_hash = owner_hash

    def _session_owner(self) -> SimpleNamespace:
        return SimpleNamespace(owner_hash=self.owner_hash)

    def _send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.calls.append((status, payload))


class _FakeCursor:
    def __init__(self, expected_owner: str) -> None:
        self.expected_owner = expected_owner
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, _sql: str, params: tuple[object, ...]) -> None:
        self.params = params

    def fetchone(self) -> dict[str, object] | None:
        owner_param = str(self.params[-1] or "")
        if owner_param != self.expected_owner:
            return None
        return {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "filename": "03. 네트워킹(03.19).pdf",
            "storage_key": "storage/uploads/sources/03-networking.pdf",
            "owner_user_id": self.expected_owner,
            "visibility": "private_user",
            "source_scope": "user_upload",
            "source_metadata": {},
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "title": "네트워킹",
            "parser_name": "internal_upload_parser",
            "parsed_metadata": {},
            "chunk_id": "33333333-3333-3333-3333-333333333333",
            "heading_title": "Service",
            "source_anchor": "chunk-service",
            "chunk_section_path": ["네트워킹", "Service"],
        }


class _FakeConnection:
    def __init__(self, expected_owner: str) -> None:
        self.cursor_obj = _FakeCursor(expected_owner)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_uploaded_document_source_meta_uses_current_owner_scope(monkeypatch, tmp_path):
    owner_hash = "owner-hash-for-viewer"

    monkeypatch.setattr(
        server_routes_viewer,
        "load_settings",
        lambda _root_dir: SimpleNamespace(database_url="postgresql://unit-test"),
    )
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda _database_url, row_factory=None: _FakeConnection(owner_hash),
    )

    handler = _CaptureHandler(owner_hash)
    server_routes_viewer.handle_source_meta(
        handler,
        urlencode(
            {
                "viewer_path": (
                    "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html"
                    "#chunk-service"
                )
            }
        ),
        root_dir=tmp_path,
    )

    assert len(handler.calls) == 1
    status, payload = handler.calls[0]
    assert status == HTTPStatus.OK
    assert payload["book_slug"] == "uploaded-documents"
    assert payload["book_title"] == "네트워킹"
    assert payload["section"] == "Service"
    assert payload["section_path"] == ["네트워킹", "Service"]
    assert payload["anchor"] == "33333333-3333-3333-3333-333333333333"
    assert payload["viewer_path"] == (
        "/uploads/documents/11111111-1111-1111-1111-111111111111/index.html"
        "#33333333-3333-3333-3333-333333333333"
    )
    assert payload["source_collection"] == "uploads"
    assert payload["boundary_truth"] == "private_user_upload_runtime"
