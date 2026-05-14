from __future__ import annotations

import base64
import json
import sys
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from play_book_studio.http.upload_api import (
    _deferred_index_result,
    _pipeline_summary,
    build_upload_code_block_repair_response,
    build_upload_ingest_response,
    build_upload_index_retry_response,
    build_upload_page_stub_repair_response,
    build_upload_pipeline_status_response,
    build_upload_quality_recheck_response,
    build_upload_topology_retry_response,
    handle_upload_ingest,
    handle_upload_ingest_stream,
)
from play_book_studio.ingestion.document_parsing import DocumentAsset, DocumentBlock, ParsedUploadDocument

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


class FakeStreamHandler:
    def __init__(self):
        self.events = []
        self.started = False

    def _start_ndjson_stream(self):
        self.started = True

    def _stream_event(self, payload):
        self.events.append(payload)


def test_build_upload_ingest_response_dry_run_stores_file_and_chunks(monkeypatch):
    storage_dir = _storage_dir("dry_run")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    events = []

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
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert result["dry_run"] is True
    assert result["filename"].endswith(".md")
    assert result["document_format"] == "md"
    assert result["block_count"] == 2
    assert result["chunk_count"] == 1
    assert result["owner_user_id"] == "owner-1"
    assert result["repository_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["gold_build_run"]["status"] == "auto_candidate"
    assert result["gold_build_run"]["policy"].startswith("Gold Gate is a repair diagnostic")
    assert (storage_dir / result["storage_key"]).is_file()
    assert [stage for stage, _data in events] == [
        "received",
        "source_stored",
        "parse_start",
        "parsed",
        "chunk_start",
        "chunked",
        "dry_run_done",
    ]


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


def test_handle_upload_ingest_stream_reports_event_sequence(monkeypatch):
    storage_dir = _storage_dir("stream")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    handler = FakeStreamHandler()

    handle_upload_ingest_stream(
        handler,
        {
            "file_name": "stream.md",
            "content_base64": base64.b64encode(b"# Stream\n\nBody").decode("ascii"),
            "dry_run": True,
        },
        root_dir=REPO_ROOT,
    )

    assert handler.started is True
    assert [event["stage"] for event in handler.events] == [
        "received",
        "source_stored",
        "parse_start",
        "parsed",
        "chunk_start",
        "chunked",
        "dry_run_done",
        "complete",
    ]
    assert all(event.get("run_id") and event.get("event_id") and event.get("occurred_at") for event in handler.events if event["type"] == "event")
    assert handler.events[2]["pipeline_stage"] == "silver"
    assert handler.events[2]["status"] == "running"
    assert handler.events[-1]["stage"] == "complete"
    assert handler.events[-1]["pipeline_stage"] == "pipeline"


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
    assert json.loads(json.dumps(result, ensure_ascii=False))["gold_build_run"]["schema"].endswith(".v1")


def test_upload_ingest_writes_asset_files_before_persist(monkeypatch):
    storage_dir = _storage_dir("asset_files")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    asset = DocumentAsset(
        asset_id="11111111-1111-1111-1111-111111111111",
        asset_type="image",
        filename="page-001.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/11111111-1111-1111-1111-111111111111.png",
        content=b"\x89PNG\r\n\x1a\nimage",
    )
    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="visual.pdf",
        document_format="pdf",
        mime_type="application/pdf",
        sha256="source-sha",
        markdown=f"# Visual\n\n![page-001.png](asset://{asset.asset_id})",
        blocks=(
            DocumentBlock(
                block_id="block-1",
                ordinal=0,
                block_type="heading",
                markdown="# Visual",
                text="Visual",
                heading_level=1,
                section_path=("Visual",),
            ),
            DocumentBlock(
                block_id="block-2",
                ordinal=1,
                block_type="image",
                markdown=f"![page-001.png](asset://{asset.asset_id})",
                text="page-001.png",
                section_path=("Visual",),
                asset_ids=(asset.asset_id,),
            ),
        ),
        assets=(asset,),
        metadata={"byte_size": 12},
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr("play_book_studio.http.upload_api.parse_upload_document", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda _connection, _parsed, chunks, **_kwargs: SimpleNamespace(
            document_source_id="source-id",
            document_version_id="version-id",
            parse_job_id="parse-job-id",
            parsed_document_id="parsed-id",
            repository_id="repo-id",
            block_ids=["block-1", "block-2"],
            asset_ids=[asset.asset_id],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        ),
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "visual.pdf",
            "file_bytes": b"%PDF-1.7\nstub",
            "source_scope": "user_upload",
        },
    )

    assert result["asset_count"] == 1
    assert result["persisted"]["asset_file_count"] == 1
    assert (storage_dir / asset.storage_key).read_bytes() == asset.content


def test_upload_ingest_stream_emits_topology_events_after_persist(monkeypatch):
    storage_dir = _storage_dir("topology_stream")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    events = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda _connection, _parsed, chunks, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            document_version_id="22222222-2222-2222-2222-222222222222",
            parse_job_id="33333333-3333-3333-3333-333333333333",
            parsed_document_id="44444444-4444-4444-4444-444444444444",
            repository_id="55555555-5555-5555-5555-555555555555",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "snapshot_id": "66666666-6666-6666-6666-666666666666",
            "schema_version": "wiki_topology_v1",
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "44444444-4444-4444-4444-444444444444",
            "state": "ready",
            "summary": {"state": "ready", "node_count": 2, "edge_count": 1, "blockers": []},
            "nodes": [],
            "edges": [],
            "metadata": {"storage": "postgres"},
        },
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "topology.md",
            "file_bytes": b"# Route\n\nRun `oc apply -f route.yaml`.",
            "source_scope": "user_upload",
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    stages = [stage for stage, _data in events]
    assert "topology_start" in stages
    assert stages[-5:] == ["topology_start", "topology_ready", "judge_start", "judge_completed", "complete"]
    assert result["topology"]["metadata"]["storage"] == "postgres"
    assert result["topology"]["summary"]["node_count"] == 2


def test_upload_ingest_auto_repairs_unfenced_code_before_persist(monkeypatch):
    storage_dir = _storage_dir("auto_repair_code")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    events = []
    persisted_markdowns = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))

    def fake_persist(_connection, parsed, chunks, **_kwargs):
        persisted_markdowns.append(parsed.markdown)
        return SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            document_version_id="22222222-2222-2222-2222-222222222222",
            parse_job_id="33333333-3333-3333-3333-333333333333",
            parsed_document_id="44444444-4444-4444-4444-444444444444",
            repository_id="55555555-5555-5555-5555-555555555555",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        )

    monkeypatch.setattr("play_book_studio.http.upload_api.persist_parsed_upload_document", fake_persist)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._index_pending_with_retry",
        lambda *_args, **kwargs: {
            "collection": "openshift_docs",
            "candidate_count": kwargs["chunk_count"],
            "indexed_count": kwargs["chunk_count"],
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "snapshot_id": "66666666-6666-6666-6666-666666666666",
            "schema_version": "wiki_topology_v1",
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "44444444-4444-4444-4444-444444444444",
            "state": "ready",
            "summary": {"state": "ready", "node_count": 2, "edge_count": 1, "blockers": []},
            "nodes": [],
            "edges": [],
            "metadata": {"storage": "postgres"},
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_topology_source",
        lambda *_args, **_kwargs: {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "44444444-4444-4444-4444-444444444444",
            "source_scope": "user_upload",
            "chunks": [{"chunk_id": "chunk-1", "markdown": "```yaml\nkind: Deployment\nmetadata:\n  name: app\n```", "token_count": 8}],
            "assets": [],
            "metadata": {"gold_build_run": {"status": "gold"}},
        },
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.upsert_document_quality_snapshot", lambda _connection, *, quality: quality)
    monkeypatch.setattr("play_book_studio.http.upload_api.update_document_source_gold_build_run", lambda *_args, **_kwargs: None)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "auto-repair.md",
            "file_bytes": b"# App\n\nkind: Deployment\nmetadata:\n  name: app\nspec:\n  replicas: 1\n",
            "source_scope": "user_upload",
            "auto_repair": True,
            "index": True,
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert persisted_markdowns
    assert "```yaml" in persisted_markdowns[0]
    assert result["auto_repairs"][0]["kind"] == "code_block"
    assert [stage for stage, _data in events][:5] == [
        "received",
        "source_stored",
        "parse_start",
        "parsed",
        "repair_start",
    ]
    assert "code_block_repaired" in [stage for stage, _data in events]


def test_upload_ingest_auto_repairs_page_stub_before_chunking(monkeypatch):
    storage_dir = _storage_dir("auto_repair_page_stub")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    events = []
    persisted_markdowns = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))

    def fake_persist(_connection, parsed, chunks, **_kwargs):
        persisted_markdowns.append(parsed.markdown)
        assert all(str(chunk.markdown).strip() != "## Page 1" for chunk in chunks)
        return SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            document_version_id="22222222-2222-2222-2222-222222222222",
            parse_job_id="33333333-3333-3333-3333-333333333333",
            parsed_document_id="44444444-4444-4444-4444-444444444444",
            repository_id="55555555-5555-5555-5555-555555555555",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        )

    monkeypatch.setattr("play_book_studio.http.upload_api.persist_parsed_upload_document", fake_persist)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._index_pending_with_retry",
        lambda *_args, **kwargs: {
            "collection": "openshift_docs",
            "candidate_count": kwargs["chunk_count"],
            "indexed_count": kwargs["chunk_count"],
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "state": "ready",
            "summary": {"state": "ready", "node_count": 1, "edge_count": 0, "blockers": []},
            "nodes": [],
            "edges": [],
            "metadata": {"storage": "postgres"},
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_topology_source",
        lambda *_args, **_kwargs: {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "44444444-4444-4444-4444-444444444444",
            "source_scope": "user_upload",
            "chunks": [{"chunk_id": "chunk-1", "markdown": "# SCC\n\n본문입니다.", "token_count": 4}],
            "assets": [],
            "metadata": {"gold_build_run": {"status": "gold"}},
        },
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.upsert_document_quality_snapshot", lambda _connection, *, quality: quality)
    monkeypatch.setattr("play_book_studio.http.upload_api.update_document_source_gold_build_run", lambda *_args, **_kwargs: None)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "page-stub.md",
            "file_bytes": b"## Page 1\n\n# SCC\n\nBody",
            "source_scope": "user_upload",
            "auto_repair": True,
            "index": True,
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    stages = [stage for stage, _data in events]
    assert persisted_markdowns
    assert "## Page 1" not in persisted_markdowns[0]
    assert result["auto_repairs"][0]["kind"] == "page_stub"
    assert "page_stubs_repaired" in stages
    assert stages.index("page_stubs_repaired") < stages.index("chunk_start")


def test_upload_ingest_stream_keeps_result_when_topology_is_deferred(monkeypatch):
    storage_dir = _storage_dir("topology_deferred")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    events = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda _connection, _parsed, chunks, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            document_version_id="22222222-2222-2222-2222-222222222222",
            parse_job_id="33333333-3333-3333-3333-333333333333",
            parsed_document_id="44444444-4444-4444-4444-444444444444",
            repository_id="55555555-5555-5555-5555-555555555555",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "state": "needs_review",
            "summary": {"state": "needs_review", "node_count": 1, "edge_count": 0, "blockers": ["이미지 설명 누락"]},
            "metadata": {"storage": "transient"},
        },
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "topology-deferred.md",
            "file_bytes": b"# Deferred\n\nBody",
            "source_scope": "user_upload",
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert [stage for stage, _data in events][-5:] == ["topology_start", "topology_deferred", "judge_start", "judge_completed", "complete"]
    assert result["persisted"]["document_source_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["topology"]["metadata"]["storage"] == "transient"
    assert result["warnings"]


def test_upload_ingest_stream_keeps_result_when_topology_fails(monkeypatch):
    storage_dir = _storage_dir("topology_failed")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    events = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda _connection, _parsed, chunks, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            document_version_id="22222222-2222-2222-2222-222222222222",
            parse_job_id="33333333-3333-3333-3333-333333333333",
            parsed_document_id="44444444-4444-4444-4444-444444444444",
            repository_id="55555555-5555-5555-5555-555555555555",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        ),
    )

    def fail_topology(*_args, **_kwargs):
        raise RuntimeError("topology endpoint unavailable")

    monkeypatch.setattr("play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id", fail_topology)

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "topology-failed.md",
            "file_bytes": b"# Failed\n\nBody",
            "source_scope": "user_upload",
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert [stage for stage, _data in events][-5:] == ["topology_start", "topology_failed", "judge_start", "judge_completed", "complete"]
    assert result["persisted"]["document_source_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["topology"]["status"] == "failed"
    assert result["warnings"]


def test_upload_pipeline_status_resolves_parsed_id_from_quality(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr("play_book_studio.http.upload_api.list_upload_pipeline_events", lambda *_args, **_kwargs: [])
    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="status.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Status",
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_quality_snapshot",
        lambda *_args, **_kwargs: {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "state": "needs_repair",
        },
    )
    topology_calls = []

    def fake_topology_summary(_connection, *, document_source_id, parsed_document_id):
        topology_calls.append((document_source_id, parsed_document_id))
        return {
            "snapshot_id": "33333333-3333-3333-3333-333333333333",
            "document_source_id": document_source_id,
            "parsed_document_id": parsed_document_id,
            "state": "ready",
            "node_count": 2,
            "edge_count": 1,
            "summary": {"state": "ready", "node_count": 2, "edge_count": 1, "blockers": []},
        }

    monkeypatch.setattr("play_book_studio.http.upload_api.load_document_topology_snapshot_summary", fake_topology_summary)

    result = build_upload_pipeline_status_response(
        REPO_ROOT,
        "document_source_id=11111111-1111-1111-1111-111111111111",
        owner_user_id="owner-a",
    )

    assert result["parsed_document_id"] == "22222222-2222-2222-2222-222222222222"
    assert topology_calls == [
        (
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        )
    ]
    assert result["pipeline_summary"]["stages"]["topology"] == "completed"


def test_pipeline_summary_ignores_complete_pipeline_stage_for_topology():
    summary = _pipeline_summary(
        {
            "quality": {"state": "needs_repair"},
            "topology": {
                "snapshot_id": "33333333-3333-3333-3333-333333333333",
                "state": "ready",
                "summary": {"state": "ready", "blockers": []},
            },
        },
        events=[
            {"pipeline_stage": "topology", "status": "completed"},
            {"pipeline_stage": "pipeline", "status": "deferred"},
        ],
    )

    assert summary["stages"]["topology"] == "completed"
    assert summary["stages"]["judge"] == "deferred"


def test_upload_pipeline_status_rejects_private_upload_owner_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="private.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Private upload",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr("play_book_studio.http.upload_api.list_upload_pipeline_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )

    with pytest.raises(ValueError, match="not visible"):
        build_upload_pipeline_status_response(
            REPO_ROOT,
            "document_source_id=11111111-1111-1111-1111-111111111111",
            owner_user_id="owner-b",
        )


def test_deferred_index_result_preserves_upload_success_contract():
    result = _deferred_index_result(
        SimpleNamespace(qdrant_collection="openshift_docs"),
        {},
        source_scope="user_upload",
        document_source_id="doc-source-1",
        chunk_count=3,
        error=RuntimeError("embedding service unavailable"),
    )

    assert result == {
        "collection": "openshift_docs",
        "source_scope": "user_upload",
        "document_source_id": "doc-source-1",
        "candidate_count": 3,
        "indexed_count": 0,
        "status": "deferred",
        "retryable": True,
        "error": "embedding service unavailable",
    }


def test_upload_ingest_keeps_document_when_embedding_indexing_fails(monkeypatch):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    storage_dir = _storage_dir("deferred_index")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_dir))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))

    monkeypatch.setattr(
        "play_book_studio.http.upload_api.persist_parsed_upload_document",
        lambda _connection, _parsed, chunks, **_kwargs: SimpleNamespace(
            document_source_id="doc-source-1",
            document_version_id="doc-version-1",
            parse_job_id="parse-job-1",
            parsed_document_id="parsed-doc-1",
            repository_id="repo-1",
            block_ids=["block-1"],
            asset_ids=[],
            chunk_ids=[f"chunk-{index}" for index, _chunk in enumerate(chunks, start=1)],
        ),
    )
    index_kwargs = []

    def fail_index(*_args, **kwargs):
        index_kwargs.append(kwargs)
        raise RuntimeError("embedding service unavailable")

    monkeypatch.setattr("play_book_studio.http.upload_api.index_pending_document_chunks", fail_index)
    updated_runs = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_gold_build_run",
        lambda _connection, *, document_source_id, gold_build_run: updated_runs.append((document_source_id, gold_build_run)),
    )
    metadata_updates = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_metadata",
        lambda _connection, *, document_source_id, metadata_patch: metadata_updates.append((document_source_id, metadata_patch)),
    )

    result = build_upload_ingest_response(
        REPO_ROOT,
        {
            "file_name": "ops.md",
            "content_base64": base64.b64encode("클러스터 상태를 확인합니다.".encode("utf-8")).decode("ascii"),
            "index": True,
            "index_retry_attempts": 1,
            "source_scope": "user_upload",
        },
    )

    assert result["persisted"]["document_source_id"] == "doc-source-1"
    assert result["index"]["status"] == "deferred"
    assert result["index"]["document_source_id"] == "doc-source-1"
    assert result["index"]["indexed_count"] == 0
    assert result["index"]["retryable"] is True
    assert index_kwargs[0]["document_source_id"] == "doc-source-1"
    assert "Qdrant 인덱싱이 보류되었습니다" in result["warnings"][0]
    assert updated_runs[0][0] == "doc-source-1"
    assert updated_runs[0][1]["qdrant_index"]["status"] == "deferred"


def test_upload_index_retry_requires_document_source_id(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    with pytest.raises(ValueError, match="document_source_id is required"):
        build_upload_index_retry_response(
            REPO_ROOT,
            {
                "source_scope": "user_upload",
                "chunk_count": 1,
            },
        )

    with pytest.raises(ValueError, match="document_source_id must be a valid UUID"):
        build_upload_index_retry_response(
            REPO_ROOT,
            {
                "document_source_id": "not-a-uuid",
                "source_scope": "user_upload",
                "chunk_count": 1,
            },
        )


def test_upload_index_retry_rejects_private_upload_owner_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="private.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Private upload",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )

    with pytest.raises(ValueError, match="not visible"):
        build_upload_index_retry_response(
            REPO_ROOT,
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "source_scope": "user_upload",
                "created_by": "owner-b",
            },
        )


def test_upload_topology_retry_rejects_private_upload_owner_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="private.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Private upload",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )

    with pytest.raises(ValueError, match="not visible"):
        build_upload_topology_retry_response(
            REPO_ROOT,
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "created_by": "owner-b",
            },
        )


def test_upload_quality_recheck_rejects_private_upload_owner_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="private.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Private upload",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )

    with pytest.raises(ValueError, match="not visible"):
        build_upload_quality_recheck_response(
            REPO_ROOT,
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "created_by": "owner-b",
            },
        )


def test_upload_topology_retry_requires_index_parity_for_ok(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="partial-index.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Partial index",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {"state": "ready", "summary": {"state": "ready", "blockers": []}, "metadata": {"storage": "postgres"}},
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._quality_recheck_for_document",
        lambda *_args, **_kwargs: {
            "quality": {"state": "gold_ready", "score": 100, "blockers": []},
            "gold_build_run": {"status": "gold", "final_grade": "Gold", "diagnostics": [], "repair_actions": []},
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._refresh_gold_index_verification",
        lambda *_args, **_kwargs: [
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "filename": "partial-index.md",
                "chunk_count": 3,
                "indexed_chunk_count": 2,
                "gold_build_run": {"status": "repairing", "final_grade": "Gold Build Repair"},
            }
        ],
    )

    result = build_upload_topology_retry_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "created_by": "owner-a",
        },
    )

    assert result["ok"] is False
    assert result["index"]["status"] == "deferred"
    assert result["gold_build_run"]["status"] == "repairing"


def test_upload_quality_recheck_requires_index_parity_for_ok(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="partial-index.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Partial index",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._quality_recheck_for_document",
        lambda *_args, **_kwargs: {
            "quality": {"state": "gold_ready", "score": 100, "blockers": []},
            "gold_build_run": {"status": "gold", "final_grade": "Gold", "diagnostics": [], "repair_actions": []},
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._refresh_gold_index_verification",
        lambda *_args, **_kwargs: [
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "filename": "partial-index.md",
                "chunk_count": 3,
                "indexed_chunk_count": 2,
                "gold_build_run": {"status": "repairing", "final_grade": "Gold Build Repair"},
            }
        ],
    )

    result = build_upload_quality_recheck_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "created_by": "owner-a",
        },
    )

    assert result["ok"] is False
    assert result["index"]["status"] == "deferred"
    assert result["gold_build_run"]["status"] == "repairing"


def test_upload_index_retry_replays_pending_qdrant_cleanup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="pending-cleanup.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Pending cleanup",
        metadata={
            "pending_qdrant_cleanup": {
                "status": "deferred",
                "collections": {
                    "openshift_docs": {
                        "status": "deferred",
                        "point_ids": ["old-point-1"],
                    }
                },
            }
        },
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(parsed=parsed),
    )
    delete_calls = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.delete_qdrant_points",
        lambda _settings, *, collection, point_ids: delete_calls.append((collection, tuple(point_ids)))
        or {"collection": collection, "requested_count": 1, "deleted_count": 1},
    )
    metadata_updates = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_metadata",
        lambda _connection, *, document_source_id, metadata_patch: metadata_updates.append((document_source_id, metadata_patch)),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._index_pending_with_retry",
        lambda *_args, **_kwargs: {"collection": "openshift_docs", "candidate_count": 1, "indexed_count": 1},
    )
    monkeypatch.setattr("play_book_studio.http.upload_api._refresh_gold_index_verification", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {"state": "ready", "summary": {"state": "ready", "blockers": []}, "metadata": {"storage": "postgres"}},
    )

    result = build_upload_index_retry_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "source_scope": "user_upload",
        },
    )

    assert delete_calls == [("openshift_docs", ("old-point-1",))]
    assert metadata_updates == [
        ("11111111-1111-1111-1111-111111111111", {"pending_qdrant_cleanup": None})
    ]
    assert result["qdrant_cleanup"]["status"] == "completed"
    assert result["index"]["indexed_count"] == 1


def test_code_block_repair_rejects_private_upload_owner_mismatch(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="private.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Private upload\n\nkind: Deployment\nmetadata:\n  name: my-app\n",
    )
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )

    with pytest.raises(ValueError, match="not visible"):
        build_upload_code_block_repair_response(
            REPO_ROOT,
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "parsed_document_id": "22222222-2222-2222-2222-222222222222",
                "dry_run": True,
                "created_by": "owner-b",
            },
        )


def test_code_block_repair_dry_run_does_not_mutate(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    parsed = ParsedUploadDocument(
        document_id="doc-1",
        filename="deployment.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Deployment\n\nkind: Deployment\nmetadata:\n  name: my-app\nspec:\n  replicas: 1\n",
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            filename="deployment.md",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_quality_snapshot",
        lambda *_args, **_kwargs: {"state": "needs_repair", "blockers": [{"id": "code_loss"}]},
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_topology_snapshot_summary",
        lambda *_args, **_kwargs: {"state": "ready"},
    )

    def fail_replace(*_args, **_kwargs):
        raise AssertionError("dry_run must not replace persisted document content")

    monkeypatch.setattr("play_book_studio.http.upload_api.replace_parsed_document_content", fail_replace)

    result = build_upload_code_block_repair_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "dry_run": True,
            "created_by": "owner-a",
        },
    )

    assert result["repair_status"] == "dry_run_changed"
    assert result["changed_block_count"] == 1
    assert result["diff_summary"][0]["language"] == "yaml"


def test_code_block_repair_apply_rebuilds_and_reindexes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    parsed = ParsedUploadDocument(
        document_id="33333333-3333-3333-3333-333333333333",
        filename="deployment.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Deployment\n\nkind: Deployment\nmetadata:\n  name: my-app\nspec:\n  replicas: 1\n",
        metadata={"byte_size": 120},
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            storage_key="uploads/sources/deployment.md",
            owner_user_id="owner",
            repository_id="44444444-4444-4444-4444-444444444444",
            visibility="private_user",
            source_scope="user_upload",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.load_document_quality_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("play_book_studio.http.upload_api.load_document_topology_snapshot_summary", lambda *_args, **_kwargs: None)
    replaced_payloads = []

    def fake_replace(_connection, **kwargs):
        replaced_payloads.append(kwargs)
        assert "```yaml" in kwargs["parsed"].markdown
        return SimpleNamespace(
            block_ids=("block-1", "block-2"),
            chunk_ids=tuple(chunk.chunk_id for chunk in kwargs["chunks"]),
            old_qdrant_point_ids=("old-point-1",),
            old_qdrant_points_by_collection={
                "openshift_docs": ("old-point-1",),
                "secondary_docs": ("old-point-2",),
            },
        )

    monkeypatch.setattr("play_book_studio.http.upload_api.replace_parsed_document_content", fake_replace)
    delete_calls = []

    def fake_delete(_settings, *, collection, point_ids):
        delete_calls.append((collection, tuple(point_ids)))
        return {"collection": collection, "requested_count": len(point_ids), "deleted_count": len(point_ids)}

    monkeypatch.setattr(
        "play_book_studio.http.upload_api.delete_qdrant_points",
        fake_delete,
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._index_pending_with_retry",
        lambda *_args, **kwargs: {
            "collection": "openshift_docs",
            "candidate_count": kwargs["chunk_count"],
            "indexed_count": kwargs["chunk_count"],
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "snapshot_id": "55555555-5555-5555-5555-555555555555",
            "state": "ready",
            "summary": {"state": "ready", "blockers": []},
            "metadata": {"storage": "postgres"},
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._quality_recheck_for_document",
        lambda *_args, **_kwargs: {
            "quality": {"state": "gold_ready", "score": 100, "blockers": []},
            "gold_build_run": {"status": "gold", "final_grade": "Gold", "diagnostics": [], "repair_actions": []},
        },
    )
    updated_runs = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_gold_build_run",
        lambda _connection, *, document_source_id, gold_build_run: updated_runs.append((document_source_id, gold_build_run)),
    )
    metadata_updates = []
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_metadata",
        lambda _connection, *, document_source_id, metadata_patch: metadata_updates.append((document_source_id, metadata_patch)),
    )
    events = []

    result = build_upload_code_block_repair_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "dry_run": False,
            "created_by": "owner",
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert result["repair_status"] == "applied"
    assert result["ok"] is True
    assert replaced_payloads
    assert [stage for stage, _data in events] == [
        "repair_start",
        "code_block_repaired",
        "reindex_start",
        "indexed",
        "topology_start",
        "topology_ready",
        "judge_start",
        "judge_completed",
        "complete",
    ]
    assert updated_runs[-1][1]["status"] == "gold"
    assert delete_calls == [
        ("openshift_docs", ("old-point-1",)),
        ("secondary_docs", ("old-point-2",)),
    ]
    assert result["qdrant_cleanup"]["deleted_count"] == 2
    assert metadata_updates[-1] == (
        "11111111-1111-1111-1111-111111111111",
        {"pending_qdrant_cleanup": None},
    )


def test_code_block_repair_no_change_does_not_bypass_gold_gate(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    parsed = ParsedUploadDocument(
        document_id="33333333-3333-3333-3333-333333333333",
        filename="already-fenced.md",
        document_format="md",
        mime_type="text/markdown",
        sha256="sha",
        markdown="# Deployment\n\n```yaml\nkind: Deployment\nmetadata:\n  name: my-app\n```\n",
        metadata={"byte_size": 120},
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_quality_snapshot",
        lambda *_args, **_kwargs: {
            "state": "gold_ready",
            "metadata": {"gold_build_status": "gold"},
            "blockers": [],
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_topology_snapshot_summary",
        lambda *_args, **_kwargs: {"state": "needs_review", "metadata": {"storage": "postgres"}},
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._refresh_gold_index_verification",
        lambda *_args, **_kwargs: [
            {
                "document_source_id": "11111111-1111-1111-1111-111111111111",
                "filename": "already-fenced.md",
                "chunk_count": 3,
                "indexed_chunk_count": 2,
                "gold_build_run": {"status": "needs_manual_repair"},
            }
        ],
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {"state": "needs_review", "summary": {"state": "needs_review"}, "metadata": {"storage": "postgres"}},
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._quality_recheck_for_document",
        lambda *_args, **_kwargs: {
            "quality": {"state": "gold_ready", "score": 100, "blockers": []},
            "gold_build_run": {"status": "gold", "final_grade": "Gold", "diagnostics": [], "repair_actions": []},
        },
    )

    def fail_replace(*_args, **_kwargs):
        raise AssertionError("no-change repair must not rebuild persisted content")

    monkeypatch.setattr("play_book_studio.http.upload_api.replace_parsed_document_content", fail_replace)

    result = build_upload_code_block_repair_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "dry_run": False,
            "created_by": "owner-a",
        },
    )

    assert result["repair_status"] == "no_change"
    assert result["ok"] is False
    assert result["index"]["status"] == "deferred"
    assert result["pipeline_summary"]["overall_status"] == "deferred"
    assert result["pipeline_summary"]["stages"]["bronze"] == "completed"
    assert result["pipeline_summary"]["stages"]["silver"] == "completed"
    assert result["pipeline_summary"]["stages"]["gold"] == "deferred"


def test_page_stub_repair_dry_run_does_not_mutate(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    parsed = ParsedUploadDocument(
        document_id="doc-page",
        filename="rbac.pdf",
        document_format="pdf",
        mime_type="application/pdf",
        sha256="sha",
        markdown="# RBAC\n\n<!-- page: 6 -->\n## Page 6\n\n본문\n\n<!-- page: 8 -->\n## Page 8\n\n다음 본문\n",
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            source_scope="user_upload",
            visibility="private_user",
            owner_user_id="owner-a",
            filename="rbac.pdf",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_quality_snapshot",
        lambda *_args, **_kwargs: {"state": "needs_repair", "blockers": [{"id": "page_stub"}]},
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_document_topology_snapshot_summary",
        lambda *_args, **_kwargs: {"state": "ready"},
    )

    def fail_replace(*_args, **_kwargs):
        raise AssertionError("dry_run must not replace persisted document content")

    monkeypatch.setattr("play_book_studio.http.upload_api.replace_parsed_document_content", fail_replace)

    result = build_upload_page_stub_repair_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "dry_run": True,
            "created_by": "owner-a",
        },
    )

    assert result["repair_status"] == "dry_run_changed"
    assert result["repair_kind"] == "page_stub"
    assert result["changed_block_count"] == 2
    assert result["diff_summary"][0]["page_number"] == 6


def test_page_stub_repair_apply_rebuilds_reindexes_and_rechecks(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unit-test")

    parsed = ParsedUploadDocument(
        document_id="33333333-3333-3333-3333-333333333333",
        filename="rbac.pdf",
        document_format="pdf",
        mime_type="application/pdf",
        sha256="sha",
        markdown="# RBAC\n\n<!-- page: 6 -->\n## Page 6\n\n본문\n\n<!-- page: 8 -->\n## Page 8\n\n다음 본문\n",
        metadata={"byte_size": 120},
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self):
            return None

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda _database_url: FakeConnection()))
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.load_parsed_document_for_repair",
        lambda *_args, **_kwargs: SimpleNamespace(
            document_source_id="11111111-1111-1111-1111-111111111111",
            parsed_document_id="22222222-2222-2222-2222-222222222222",
            storage_key="uploads/sources/rbac.pdf",
            owner_user_id="owner",
            repository_id="44444444-4444-4444-4444-444444444444",
            visibility="private_user",
            source_scope="user_upload",
            parsed=parsed,
        ),
    )
    monkeypatch.setattr("play_book_studio.http.upload_api.load_document_quality_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("play_book_studio.http.upload_api.load_document_topology_snapshot_summary", lambda *_args, **_kwargs: None)
    replaced_payloads = []

    def fake_replace(_connection, **kwargs):
        replaced_payloads.append(kwargs)
        assert "## Page 6" not in kwargs["parsed"].markdown
        assert "본문" in kwargs["parsed"].markdown
        return SimpleNamespace(
            block_ids=("block-1", "block-2"),
            chunk_ids=tuple(chunk.chunk_id for chunk in kwargs["chunks"]),
            old_qdrant_point_ids=("old-point-1",),
            old_qdrant_points_by_collection={"openshift_docs": ("old-point-1",)},
        )

    monkeypatch.setattr("play_book_studio.http.upload_api.replace_parsed_document_content", fake_replace)
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.delete_qdrant_points",
        lambda _settings, *, collection, point_ids: {
            "collection": collection,
            "requested_count": len(point_ids),
            "deleted_count": len(point_ids),
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._index_pending_with_retry",
        lambda *_args, **kwargs: {
            "collection": "openshift_docs",
            "candidate_count": kwargs["chunk_count"],
            "indexed_count": kwargs["chunk_count"],
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.get_or_create_document_topology_snapshot_by_id",
        lambda *_args, **_kwargs: {
            "snapshot_id": "55555555-5555-5555-5555-555555555555",
            "state": "ready",
            "summary": {"state": "ready", "blockers": []},
            "metadata": {"storage": "postgres"},
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api._quality_recheck_for_document",
        lambda *_args, **_kwargs: {
            "quality": {"state": "gold_ready", "score": 100, "blockers": []},
            "gold_build_run": {"status": "gold", "final_grade": "Gold", "diagnostics": [], "repair_actions": []},
        },
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_gold_build_run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "play_book_studio.http.upload_api.update_document_source_metadata",
        lambda *_args, **_kwargs: None,
    )
    events = []

    result = build_upload_page_stub_repair_response(
        REPO_ROOT,
        {
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "dry_run": False,
            "created_by": "owner",
        },
        emit_event=lambda stage, data: events.append((stage, data)),
    )

    assert result["repair_status"] == "applied"
    assert result["ok"] is True
    assert replaced_payloads
    assert [stage for stage, _data in events] == [
        "repair_start",
        "page_stubs_repaired",
        "reindex_start",
        "indexed",
        "topology_start",
        "topology_ready",
        "judge_start",
        "judge_completed",
        "complete",
    ]
