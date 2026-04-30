from __future__ import annotations

from pathlib import Path

from play_book_studio.db.document_repository import (
    build_parsed_document_rows,
    persist_parsed_upload_document,
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
        return (self.return_ids.pop(0),)


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj


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
        ),
        DocumentBlock(
            block_id="33333333-3333-3333-3333-333333333333",
            ordinal=1,
            block_type="paragraph",
            markdown="Router sends traffic to services.",
            text="Router sends traffic to services.",
            section_path=("Architecture",),
        ),
        DocumentBlock(
            block_id="44444444-4444-4444-4444-444444444444",
            ordinal=2,
            block_type="image",
            markdown="![image1.png](asset://11111111-1111-1111-1111-111111111111)",
            text="image1.png",
            section_path=("Architecture",),
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
    assert rows.source["metadata"]["document_format"] == "pptx"
    assert rows.parsed_document["title"] == "Architecture"
    assert rows.parsed_document["outline"][0]["text"] == "Architecture"
    assert rows.blocks[2]["metadata"]["asset_ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert rows.assets[0]["block_id"] == "44444444-4444-4444-4444-444444444444"
    assert rows.assets[0]["qwen_description"] == "Architecture diagram"
    assert rows.assets[0]["qwen_model"] == "Qwen2.5-VL"
    assert rows.chunks[0]["section_path"] == ["Architecture"]
    assert rows.chunks[0]["token_count"] > 0


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
    assert "INSERT INTO document_sources" in sql_text
    assert "INSERT INTO document_versions" in sql_text
    assert "INSERT INTO parse_jobs" in sql_text
    assert "INSERT INTO parsed_documents" in sql_text
    assert "INSERT INTO document_blocks" in sql_text
    assert "INSERT INTO document_assets" in sql_text
    assert "INSERT INTO document_chunks" in sql_text
    assert stored.document_source_id.endswith("000000000003")
    assert len(stored.block_ids) == 3
    assert len(stored.asset_ids) == 1
    assert len(stored.chunk_ids) == 1
