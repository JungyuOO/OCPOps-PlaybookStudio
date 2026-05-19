from __future__ import annotations

import base64
import json
from http import HTTPStatus
from pathlib import Path

from play_book_studio.http.upload_api import (
    _safe_upload_name,
    build_upload_ingest_response,
    handle_upload_ingest,
    handle_upload_ingest_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "upload_api_tests"


def _storage_dir(name: str) -> Path:
    path = TEST_TMP / name / "storage"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_safe_upload_name_preserves_korean_document_title():
    assert _safe_upload_name("02. 스토리지(03.19).pdf") == "02. 스토리지(03.19).pdf"
    assert _safe_upload_name("../03. 네트워킹(03.19).pdf") == "03. 네트워킹(03.19).pdf"


class FakeHandler:
    def __init__(self):
        self.payload = None
        self.status = None

    def _send_json(self, payload, status=HTTPStatus.OK):
        self.payload = payload
        self.status = status


class FakeDbConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StoredDocument:
    repository_id = "11111111-1111-1111-1111-111111111111"
    document_source_id = "22222222-2222-2222-2222-222222222222"
    document_version_id = "33333333-3333-3333-3333-333333333333"
    parse_job_id = "44444444-4444-4444-4444-444444444444"
    parsed_document_id = "55555555-5555-5555-5555-555555555555"
    block_ids = ("block-1",)
    asset_ids = ()
    chunk_ids = ("chunk-1",)


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
            "created_by": "owner-1",
            "repository_id": "11111111-1111-1111-1111-111111111111",
        },
    )

    assert result["dry_run"] is True
    assert result["filename"].endswith(".md")
    assert result["document_format"] == "md"
    assert result["block_count"] == 2
    assert result["chunk_count"] == 1
    assert result["owner_user_id"] == "owner-1"
    assert result["repository_id"] == "11111111-1111-1111-1111-111111111111"
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


def test_upload_ingest_indexes_only_persisted_document(monkeypatch):
    storage_dir = _storage_dir("index_document_scope")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    calls = {}

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())

    def fake_persist(connection, parsed, chunks, **kwargs):
        calls["persist"] = {"connection": connection, "chunk_count": len(chunks), "kwargs": kwargs}
        return StoredDocument()

    def fake_index(settings, connection, **kwargs):
        calls["index"] = {"connection": connection, "kwargs": kwargs}
        return {
            "collection": "openshift_docs",
            "source_scope": kwargs["source_scope"],
            "document_source_id": kwargs["document_source_id"],
            "candidate_count": 1,
            "indexed_count": 1,
        }

    monkeypatch.setattr("play_book_studio.http.upload_api.persist_parsed_upload_document", fake_persist)
    monkeypatch.setattr("play_book_studio.http.upload_api.index_pending_document_chunks", fake_index)
    monkeypatch.setattr("play_book_studio.http.upload_api.find_document_source_by_sha", lambda *args, **kwargs: None)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "scoped.md",
            "file_bytes": b"# Scoped\n\nUse this document only.",
            "index": True,
            "created_by": "owner-1",
            "repository_id": "11111111-1111-1111-1111-111111111111",
        },
    )

    assert calls["index"]["kwargs"]["source_scope"] == "user_upload"
    assert calls["index"]["kwargs"]["document_source_id"] == StoredDocument.document_source_id
    assert result["index"]["status"] == "indexed"
    assert result["index"]["document_source_id"] == StoredDocument.document_source_id


def test_upload_ingest_emits_eight_stage_events_and_writes_report(monkeypatch):
    storage_dir = _storage_dir("stage_report")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    events = []

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda connection, parsed, chunks, **kwargs: StoredDocument(),
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.find_document_source_by_sha", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.index_pending_document_chunks",
        lambda settings, connection, **kwargs: {
            "collection": "openshift_docs",
            "source_scope": kwargs["source_scope"],
            "document_source_id": kwargs["document_source_id"],
            "candidate_count": 1,
            "indexed_count": 1,
        },
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "stage-report.md",
            "file_bytes": b"# Stage report\n\nCheck upload flow.",
            "index": True,
            "created_by": "owner-1",
        },
        progress_callback=events.append,
    )

    stage_names = [event["stage"] for event in events if event.get("type") == "stage"]
    for expected in ("received", "store", "parse", "chunk", "persist", "index", "scope", "ready"):
        assert expected in stage_names
    terminal_events = [
        event
        for event in events
        if event.get("type") == "stage" and event.get("status") != "running"
    ]
    assert terminal_events
    assert all("started_at" in event for event in terminal_events)
    assert all("finished_at" in event for event in terminal_events)

    report = result["report"]
    assert report["document_source_id"] == StoredDocument.document_source_id
    report_path = storage_dir / report["storage_key"]
    assert report_path.is_file()
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["basic_index_ready"] is True
    assert report_payload["answer_ready"] is False
    assert report_payload["ready_for_chat"] is False
    assert report_payload["quality_gate"]["verified_for_answer"] is False
    assert report_payload["counts"]["indexed_count"] == 1
    assert [event["stage"] for event in report_payload["stages"] if event["stage"] == "ready"]


def test_upload_ingest_preserves_document_when_indexing_fails(monkeypatch):
    storage_dir = _storage_dir("index_failure")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda connection, parsed, chunks, **kwargs: StoredDocument(),
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.find_document_source_by_sha", lambda *args, **kwargs: None)

    def fail_index(*args, **kwargs):
        raise RuntimeError("Failed to fetch embeddings from http://tei.cywell.co.kr/v1")

    monkeypatch.setattr("play_book_studio.http.upload_api.index_pending_document_chunks", fail_index)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "saved-but-not-indexed.md",
            "file_bytes": b"# Saved\n\nIndex may fail.",
            "index": True,
        },
    )

    assert result["persisted"]["document_source_id"] == StoredDocument.document_source_id
    assert result["index"]["status"] == "failed"
    assert result["index"]["document_source_id"] == StoredDocument.document_source_id
    assert "Failed to fetch embeddings" in result["index"]["error"]
    assert any("검색 인덱싱 실패" in warning for warning in result["warnings"])


def test_upload_ingest_zero_index_candidates_is_not_basic_ready(monkeypatch):
    storage_dir = _storage_dir("zero_index_candidates")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda connection, parsed, chunks, **kwargs: StoredDocument(),
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.find_document_source_by_sha", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.index_pending_document_chunks",
        lambda settings, connection, **kwargs: {
            "collection": "openshift_docs",
            "source_scope": kwargs["source_scope"],
            "document_source_id": kwargs["document_source_id"],
            "candidate_count": 0,
            "indexed_count": 0,
        },
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "no-candidates.md",
            "file_bytes": b"# No candidates\n\nThis should not be marked ready.",
            "index": True,
            "created_by": "owner-1",
        },
    )

    assert result["index"]["status"] == "no_candidates"
    assert result["basic_index_ready"] is False
    assert result["answer_ready"] is False
    assert result["ready_for_chat"] is False
    ready_events = [event for event in result["stage_events"] if event["stage"] == "ready"]
    assert ready_events[-1]["status"] == "warning"


def test_upload_ingest_reports_duplicate_without_reprocessing(monkeypatch):
    storage_dir = _storage_dir("duplicate")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())

    captured_lookup: dict[str, object] = {}

    def duplicate_lookup(*args, **kwargs):
        captured_lookup.update(kwargs)
        return {
            "document_source_id": "22222222-2222-2222-2222-222222222222",
            "repository_id": "11111111-1111-1111-1111-111111111111",
            "filename": "duplicate.md",
            "title": "Duplicate",
            "source_scope": "user_upload",
            "owner_user_id": "stable-owner",
            "visibility": "private_user",
            "parsed_document_id": "55555555-5555-5555-5555-555555555555",
            "chunk_count": 3,
            "indexed_count": 3,
        }

    monkeypatch.setattr(
        "play_book_studio.http.upload_api.find_document_source_by_sha",
        duplicate_lookup,
    )

    def fail_persist(*args, **kwargs):
        raise AssertionError("duplicate should not be reprocessed without force_reingest")

    monkeypatch.setattr("play_book_studio.http.upload_api.persist_parsed_upload_document", fail_persist)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "duplicate.md",
            "file_bytes": b"# Duplicate\n\nAlready uploaded.",
            "index": True,
            "created_by": "stable-owner",
        },
    )

    assert captured_lookup["owner_user_id"] == "stable-owner"
    assert result["duplicate"]["exists"] is True
    assert result["index"]["status"] == "duplicate_existing_indexed"
    assert result["basic_index_ready"] is True
    assert result["answer_ready"] is False
    assert result["persisted"]["document_source_id"] == "22222222-2222-2222-2222-222222222222"


def test_upload_ingest_allows_same_file_for_different_owner_by_scoping_sha(monkeypatch):
    storage_dir = _storage_dir("duplicate_other_owner")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda database_url: FakeDbConnection())

    lookup_calls: list[dict[str, object]] = []

    def duplicate_lookup(*args, **kwargs):
        lookup_calls.append(dict(kwargs))
        return None

    monkeypatch.setattr(
        "play_book_studio.http.upload_api.find_document_source_by_sha",
        duplicate_lookup,
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda connection, parsed, chunks, **kwargs: StoredDocument(),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.index_pending_document_chunks",
        lambda settings, connection, **kwargs: {
            "collection": "openshift_docs",
            "source_scope": kwargs["source_scope"],
            "document_source_id": kwargs["document_source_id"],
            "candidate_count": 1,
            "indexed_count": 1,
        },
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "duplicate.md",
            "file_bytes": b"# Duplicate\n\nAlready uploaded elsewhere.",
            "index": True,
            "created_by": "stable-owner",
        },
    )

    assert result["persisted"]["document_source_id"] == StoredDocument.document_source_id
    assert result["db_sha256"] != result["sha256"]
    assert lookup_calls
    assert lookup_calls[0]["owner_user_id"] == "stable-owner"
    assert lookup_calls[0]["sha256"] == result["db_sha256"]


def test_handle_upload_ingest_report_reads_saved_report(monkeypatch):
    storage_dir = _storage_dir("report_read")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    document_source_id = "22222222-2222-2222-2222-222222222222"
    report_dir = storage_dir / "uploads" / "reports" / document_source_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "ingestion-report.json").write_text(
        json.dumps(
            {
                "schema_version": "user_upload_ingestion_report_v1",
                "document_source_id": document_source_id,
                "stages": [{"type": "stage", "stage": "ready", "status": "done"}],
            }
        ),
        encoding="utf-8",
    )
    handler = FakeHandler()
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._upload_document_access_allowed",
        lambda *args, **kwargs: True,
    )

    handle_upload_ingest_report(
        handler,
        f"document_source_id={document_source_id}",
        root_dir=REPO_ROOT,
        owner_user_id="owner-1",
    )

    assert handler.status == HTTPStatus.OK
    assert handler.payload["document_source_id"] == document_source_id
    assert handler.payload["stages"][0]["stage"] == "ready"


def test_handle_upload_ingest_report_rejects_invisible_document(monkeypatch):
    storage_dir = _storage_dir("report_forbidden")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    document_source_id = "22222222-2222-2222-2222-222222222222"
    handler = FakeHandler()
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._upload_document_access_allowed",
        lambda *args, **kwargs: False,
    )

    handle_upload_ingest_report(
        handler,
        f"document_source_id={document_source_id}",
        root_dir=REPO_ROOT,
        owner_user_id="owner-1",
    )

    assert handler.status == HTTPStatus.FORBIDDEN
