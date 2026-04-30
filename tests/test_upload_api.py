from __future__ import annotations

import base64
import json
from http import HTTPStatus
from pathlib import Path

from play_book_studio.app.upload_api import build_upload_ingest_response, handle_upload_ingest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "upload_api_tests"


def _storage_dir(name: str) -> Path:
    path = TEST_TMP / name / "storage"
    path.mkdir(parents=True, exist_ok=True)
    return path


class FakeHandler:
    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=HTTPStatus.OK):
        self.payload = payload
        self.status = status


def test_build_upload_ingest_response_dry_run_stores_file_and_chunks(monkeypatch):
    storage_dir = _storage_dir("dry_run")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "ops guide.md",
            "content_base64": base64.b64encode(b"# Operations\n\nCheck health.").decode("ascii"),
            "dry_run": True,
            "chunk_max_chars": 80,
            "chunk_overlap_blocks": 0,
        },
    )

    assert result["dry_run"] is True
    assert result["filename"].endswith(".md")
    assert result["document_format"] == "md"
    assert result["block_count"] == 2
    assert result["chunk_count"] == 1
    assert (storage_dir / result["storage_key"]).is_file()


def test_handle_upload_ingest_reports_bad_base64():
    handler = FakeHandler()

    handle_upload_ingest(
        handler,
        {
            "file_name": "bad.md",
            "content_base64": "not-base64",
            "dry_run": True,
        },
        root_dir=REPO_ROOT,
    )

    assert handler.status == HTTPStatus.BAD_REQUEST
    assert "content_base64" in handler.payload["error"]


def test_upload_ingest_response_is_json_serializable(monkeypatch):
    storage_dir = _storage_dir("serializable")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "serializable.md",
            "file_bytes": b"# Title\n\nBody",
            "dry_run": True,
        },
    )

    assert json.loads(json.dumps(result, ensure_ascii=False))["filename"] == "serializable.md"
