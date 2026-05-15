from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from play_book_studio.db.document_repository import (
    _merge_repair_document_metadata,
    bind_upload_pipeline_events,
    build_parsed_document_rows,
    insert_upload_pipeline_event,
    list_upload_pipeline_events,
    list_document_repositories,
    persist_parsed_upload_document,
    update_document_source_gold_build_run,
)
from play_book_studio.ingestion.document_parsing import (
    DocumentAsset,
    DocumentBlock,
    ParsedUploadDocument,
    build_document_chunks,
)


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.return_ids = [f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 40)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchone(self):
        last_sql = self.calls[-1][0] if self.calls else ""
        if "RETURNING id::text, occurred_at" in last_sql:
            return (self.return_ids.pop(0), datetime(2026, 5, 14, 2, 30, tzinfo=UTC))
        return (self.return_ids.pop(0),)

    def fetchall(self):
        last_sql = self.calls[-1][0] if self.calls else ""
        if "FROM upload_pipeline_events" in last_sql:
            return [
                (
                    "run-1",
                    "0001-received",
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                    "bronze",
                    "received",
                    "running",
                    datetime(2026, 5, 14, 2, 30, tzinfo=UTC),
                    {"filename": "ops.md"},
                    {"source": "unit"},
                )
            ]
        if "FROM document_sources ds" in last_sql:
            return []
        return [
            (
                "99999999-9999-9999-9999-999999999999",
                "personal-uploads",
                "My Uploads",
                "personal",
                "private_user",
                "tester",
                {"purpose": "unit"},
                2,
                None,
                None,
            )
        ]


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj


def test_repair_metadata_uses_source_runtime_cleanup_state():
    pending_cleanup = {
        "status": "deferred",
        "collections": {
            "openshift_docs": {
                "status": "deferred",
                "point_ids": ["old-point-1"],
            }
        },
    }

    merged = _merge_repair_document_metadata(
        {"pending_qdrant_cleanup": pending_cleanup, "source_key": "source"},
        {"pending_qdrant_cleanup": None, "document_format": "pdf"},
    )

    assert merged["pending_qdrant_cleanup"] == pending_cleanup
    assert merged["document_format"] == "pdf"
    assert merged["source_key"] == "source"


def test_repair_metadata_source_clears_stale_parsed_cleanup_state():
    merged = _merge_repair_document_metadata(
        {"pending_qdrant_cleanup": None, "source_key": "source"},
        {
            "pending_qdrant_cleanup": {
                "status": "deferred",
                "collections": {"openshift_docs": {"point_ids": ["old-point-1"]}},
            },
            "document_format": "pdf",
        },
    )

    assert merged["pending_qdrant_cleanup"] is None
    assert merged["document_format"] == "pdf"
    assert merged["source_key"] == "source"


def test_repair_metadata_ignores_parsed_cleanup_without_source_state():
    merged = _merge_repair_document_metadata(
        {"source_key": "source"},
        {
            "pending_qdrant_cleanup": {
                "status": "deferred",
                "collections": {"openshift_docs": {"point_ids": ["old-point-1"]}},
            },
            "document_format": "pdf",
        },
    )

    assert "pending_qdrant_cleanup" not in merged
    assert merged["document_format"] == "pdf"
    assert merged["source_key"] == "source"


def _parsed_document() -> ParsedUploadDocument:
    asset = DocumentAsset(
        asset_id="11111111-1111-1111-1111-111111111111",
        asset_type="image",
        filename="image1.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/image1.png",
        description="Architecture diagram",
        metadata={"qwen_model": "Qwen2.5-VL"},
    )
    blocks = (
        DocumentBlock(
            block_id="22222222-2222-2222-2222-222222222222",
            ordinal=0,
            block_type="heading",
            markdown="# Architecture",
            text="Architecture",
            heading_level=1,
            section_path=("Architecture",),
            heading_title="Architecture",
            source_anchor="architecture",
            toc_path=("Architecture",),
        ),
        DocumentBlock(
            block_id="33333333-3333-3333-3333-333333333333",
            ordinal=1,
            block_type="paragraph",
            markdown="Router sends traffic to services.",
            text="Router sends traffic to services.",
            section_path=("Architecture",),
            heading_title="Architecture",
            source_anchor="architecture",
            toc_path=("Architecture",),
        ),
        DocumentBlock(
            block_id="44444444-4444-4444-4444-444444444444",
            ordinal=2,
            block_type="image",
            markdown="![image1.png](asset://11111111-1111-1111-1111-111111111111)",
            text="image1.png",
            section_path=("Architecture",),
            heading_title="Architecture",
            source_anchor="architecture",
            toc_path=("Architecture",),
            asset_ids=(asset.asset_id,),
        ),
    )
    return ParsedUploadDocument(
        document_id="55555555-5555-5555-5555-555555555555",
        filename="deck.pptx",
        document_format="pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        sha256="source-sha",
        markdown="# Architecture\n\nRouter sends traffic to services.",
        blocks=blocks,
        assets=(asset,),
        metadata={"byte_size": 1234, "source_path": str(Path("deck.pptx"))},
    )


def test_build_parsed_document_rows_maps_parser_output_to_schema_rows():
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    rows = build_parsed_document_rows(parsed, chunks, created_by="tester")

    assert rows.source["filename"] == "deck.pptx"
    assert rows.source["byte_size"] == 1234
    assert rows.source["visibility"] == "private_user"
    assert rows.source["owner_user_id"] == "tester"
    assert rows.source["source_scope"] == "user_upload"
    assert rows.source["metadata"]["document_format"] == "pptx"
    assert rows.parsed_document["title"] == "Architecture"
    assert rows.parsed_document["metadata"]["byte_size"] == 1234
    assert rows.parsed_document["outline"][0]["text"] == "Architecture"
    assert rows.parsed_document["outline"][0]["heading_title"] == "Architecture"
    assert rows.blocks[2]["metadata"]["asset_ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert rows.blocks[2]["source_anchor"] == "architecture"
    assert rows.assets[0]["block_id"] == "44444444-4444-4444-4444-444444444444"
    assert rows.assets[0]["qwen_description"] == "Architecture diagram"
    assert rows.assets[0]["qwen_model"] == "Qwen2.5-VL"
    assert rows.chunks[0]["section_path"] == ["Architecture"]
    assert rows.chunks[0]["heading_title"] == "Architecture"
    assert rows.chunks[0]["source_anchor"] == "architecture"
    assert rows.chunks[0]["token_count"] > 0


def test_build_parsed_document_rows_strips_nul_before_postgres_boundary():
    parsed = _parsed_document()
    parsed = replace(
        parsed,
        markdown="# Architecture\x00\n\nRouter sends traffic to services.",
        metadata={**parsed.metadata, "source_path": "deck\x00.pptx"},
        blocks=tuple(
            replace(block, text=f"{block.text}\x00", markdown=f"{block.markdown}\x00")
            for block in parsed.blocks
        ),
    )
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    rows = build_parsed_document_rows(parsed, chunks, created_by="tester")

    serialized = str(rows.source) + str(rows.parsed_document) + str(rows.blocks) + str(rows.chunks)
    assert "\x00" not in serialized
    assert rows.parsed_document["markdown"].startswith("# Architecture")


def test_build_parsed_document_rows_scopes_upload_sha_by_owner():
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    owner_a_rows = build_parsed_document_rows(parsed, chunks, created_by="owner-a")
    owner_b_rows = build_parsed_document_rows(parsed, chunks, created_by="owner-b")
    shared_rows = build_parsed_document_rows(
        parsed,
        chunks,
        visibility="global_shared",
        source_scope="official_docs",
    )

    assert owner_a_rows.source["sha256"] != parsed.sha256
    assert owner_a_rows.source["sha256"] != owner_b_rows.source["sha256"]
    assert owner_a_rows.source["metadata"]["content_sha256"] == parsed.sha256
    assert shared_rows.source["sha256"] == parsed.sha256


def test_build_document_chunks_keeps_section_context_in_embedding_text_after_split():
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=45, overlap_blocks=0)

    assert len(chunks) >= 2
    assert all(chunk.section_path == ("Architecture",) for chunk in chunks)
    assert all(chunk.embedding_text.startswith("Architecture") for chunk in chunks)
    assert all(chunk.metadata["chunk_char_count"] > 0 for chunk in chunks)


def test_upload_pipeline_event_helpers_write_bind_and_replay_rows():
    connection = FakeConnection()

    inserted = insert_upload_pipeline_event(
        connection,
        run_id="run-1",
        event_id="0001-received",
        document_source_id="11111111-1111-1111-1111-111111111111",
        parsed_document_id="22222222-2222-2222-2222-222222222222",
        stage="bronze",
        event="received",
        status="running",
        payload={"filename": "ops.md"},
        evidence={"source": "unit"},
    )
    bind_upload_pipeline_events(
        connection,
        run_id="run-1",
        document_source_id="11111111-1111-1111-1111-111111111111",
        parsed_document_id="22222222-2222-2222-2222-222222222222",
    )
    events = list_upload_pipeline_events(connection, run_id="run-1")

    executed_sql = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "INSERT INTO upload_pipeline_events" in executed_sql
    assert "UPDATE upload_pipeline_events" in executed_sql
    assert "FROM upload_pipeline_events" in executed_sql
    assert inserted["occurred_at"] == "2026-05-14T02:30:00+00:00"
    assert events == [
        {
            "run_id": "run-1",
            "event_id": "0001-received",
            "document_source_id": "11111111-1111-1111-1111-111111111111",
            "parsed_document_id": "22222222-2222-2222-2222-222222222222",
            "stage": "bronze",
            "event": "received",
            "status": "running",
            "occurred_at": "2026-05-14T02:30:00+00:00",
            "payload": {"filename": "ops.md"},
            "evidence": {"source": "unit"},
        }
    ]


def test_build_parsed_document_rows_supports_shared_official_scope():
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    rows = build_parsed_document_rows(
        parsed,
        chunks,
        visibility="global_shared",
        source_scope="official_docs",
    )

    assert rows.source["visibility"] == "global_shared"
    assert rows.source["source_scope"] == "official_docs"
    assert rows.source["owner_user_id"] == ""


def test_persist_parsed_upload_document_executes_expected_insert_sequence():
    connection = FakeConnection()
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    stored = persist_parsed_upload_document(
        connection,
        parsed,
        chunks,
        tenant_slug="ocp",
        tenant_name="OCP",
        workspace_slug="ops",
        workspace_name="Ops",
        created_by="tester",
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)

    assert "INSERT INTO tenants" in sql_text
    assert "INSERT INTO workspaces" in sql_text
    assert "INSERT INTO repositories" in sql_text
    assert "INSERT INTO document_sources" in sql_text
    assert "INSERT INTO document_versions" in sql_text
    assert "INSERT INTO parse_jobs" in sql_text
    assert "INSERT INTO parsed_documents" in sql_text
    assert "INSERT INTO document_blocks" in sql_text
    assert "INSERT INTO document_assets" in sql_text
    assert "INSERT INTO document_chunks" in sql_text
    assert stored.repository_id.endswith("000000000003")
    assert stored.document_source_id.endswith("000000000004")
    assert len(stored.block_ids) == 3
    assert len(stored.asset_ids) == 1
    assert len(stored.chunk_ids) == 1


def test_persist_parsed_upload_document_can_create_shared_study_repository():
    connection = FakeConnection()
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    persist_parsed_upload_document(
        connection,
        parsed,
        chunks,
        repository_slug="study-docs",
        repository_title="Study Docs",
        repository_kind="study",
        visibility="workspace_shared",
        source_scope="study_docs",
    )

    repository_call = next(call for call in connection.cursor_obj.calls if "INSERT INTO repositories" in call[0])
    assert repository_call[1][5] == "study"
    assert repository_call[1][6] == "workspace_shared"
    source_call = next(call for call in connection.cursor_obj.calls if "INSERT INTO document_sources" in call[0])
    assert source_call[1][13] == "workspace_shared"
    assert source_call[1][14] == "study_docs"


def test_persist_parsed_upload_document_strips_nul_scalar_inputs():
    connection = FakeConnection()
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    persist_parsed_upload_document(
        connection,
        parsed,
        chunks,
        tenant_slug="pub\x00lic",
        tenant_name="Pub\x00lic",
        workspace_slug="def\x00ault",
        workspace_name="Def\x00ault",
        created_by="tes\x00ter",
        repository_slug="my\x00-uploads",
        repository_title="My\x00 Uploads",
        repository_kind="per\x00sonal",
        visibility="private\x00_user",
        source_scope="user\x00_upload",
    )

    serialized_params = "".join(str(params) for _sql, params in connection.cursor_obj.calls)
    assert "\x00" not in serialized_params


def test_user_upload_ignores_shared_repository_id_and_uses_personal_repository():
    connection = FakeConnection()
    parsed = _parsed_document()
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)

    persist_parsed_upload_document(
        connection,
        parsed,
        chunks,
        created_by="tester",
        repository_id="11111111-1111-1111-1111-111111111111",
        visibility="private_user",
        source_scope="user_upload",
    )

    repository_call = next(call for call in connection.cursor_obj.calls if "INSERT INTO repositories" in call[0])
    source_call = next(call for call in connection.cursor_obj.calls if "INSERT INTO document_sources" in call[0])
    assert repository_call[1][5] == "personal"
    assert repository_call[1][6] == "private_user"
    assert source_call[1][11] != "11111111-1111-1111-1111-111111111111"


def test_list_document_repositories_filters_by_owner_scope():
    connection = FakeConnection()

    repositories = list_document_repositories(
        connection,
        tenant_slug="public",
        workspace_slug="default",
        owner_user_id="tester",
        collection="openshift_docs",
    )

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "FROM repositories r" in sql_text
    assert "r.visibility IN ('workspace_shared', 'global_shared') OR r.owner_user_id = %s" in sql_text
    assert "uds.source_scope = 'user_upload'" not in sql_text
    indexed_call = next(call for call in connection.cursor_obj.calls if "LEFT JOIN qdrant_index_entries qie" in call[0])
    assert connection.cursor_obj.calls[0][1] == ("public", "default", "tester")
    assert indexed_call[1] == ("openshift_docs", "openshift_docs", ["99999999-9999-9999-9999-999999999999"])
    assert repositories[0]["repository_id"] == "99999999-9999-9999-9999-999999999999"
    assert repositories[0]["document_count"] == 2


def test_load_document_reader_does_not_bypass_owner_for_user_uploads():
    from play_book_studio.db.document_repository import load_document_reader

    connection = FakeConnection()

    try:
        load_document_reader(
            connection,
            tenant_slug="public",
            workspace_slug="default",
            owner_user_id="tester",
            document_source_id="99999999-9999-9999-9999-999999999999",
        )
    except (IndexError, TypeError, RuntimeError):
        pass

    sql_text = "\n".join(sql for sql, _params in connection.cursor_obj.calls)
    assert "ds.source_scope = 'user_upload'" not in sql_text
    assert "r.visibility IN ('workspace_shared', 'global_shared') OR r.owner_user_id = %s" in sql_text


def test_load_document_reader_returns_assets_for_reader():
    from play_book_studio.db.document_repository import load_document_reader

    class ReaderCursor:
        def __init__(self):
            self.calls = []
            self.fetchone_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            self.calls.append((str(sql), params))

        def fetchone(self):
            self.fetchone_count += 1
            if self.fetchone_count == 1:
                now = datetime(2026, 1, 1, tzinfo=UTC)
                return (
                    "99999999-9999-9999-9999-999999999999",
                    "88888888-8888-8888-8888-888888888888",
                    "Visual guide",
                    "visual.pdf",
                    "upload",
                    "application/pdf",
                    "user_upload",
                    "private_user",
                    {"document_format": "pdf"},
                    "# Visual guide",
                    {"pdf_image_count": 1},
                    [{"text": "Visual guide"}],
                    now,
                    now,
                    14,
                    False,
                )
            return (0,)

        def fetchall(self):
            last_sql = self.calls[-1][0]
            if "FROM document_assets" in last_sql:
                return [
                    (
                        "77777777-7777-7777-7777-777777777777",
                        "image",
                        "image/png",
                        "uploads/assets/page-001.png",
                        "asset-sha",
                        640,
                        480,
                        1,
                        "아키텍처 이미지",
                        "",
                        "",
                        "",
                        {"filename": "page-001.png"},
                    )
                ]
            return []

    class ReaderConnection:
        def __init__(self):
            self.cursor_obj = ReaderCursor()

        def cursor(self):
            return self.cursor_obj

    connection = ReaderConnection()

    document = load_document_reader(
        connection,
        tenant_slug="public",
        workspace_slug="default",
        owner_user_id="tester",
        document_source_id="99999999-9999-9999-9999-999999999999",
    )

    assert document is not None
    assert document["assets"] == [
        {
            "asset_id": "77777777-7777-7777-7777-777777777777",
            "asset_type": "image",
            "mime_type": "image/png",
            "storage_key": "uploads/assets/page-001.png",
            "sha256": "asset-sha",
            "width": 640,
            "height": 480,
            "page_number": 1,
            "caption_text": "아키텍처 이미지",
            "ocr_text": "",
            "qwen_description": "",
            "qwen_model": "",
            "filename": "page-001.png",
            "metadata": {"filename": "page-001.png"},
        }
    ]


def test_update_document_source_gold_build_run_only_updates_metadata():
    connection = FakeConnection()

    update_document_source_gold_build_run(
        connection,
        document_source_id="99999999-9999-9999-9999-999999999999",
        gold_build_run={"status": "repairing"},
    )

    sql_text = connection.cursor_obj.calls[-1][0]
    assert "UPDATE document_sources" in sql_text
    assert "metadata =" in sql_text
    assert "updated_at" not in sql_text
