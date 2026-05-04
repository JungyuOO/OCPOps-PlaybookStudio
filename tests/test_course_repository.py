from __future__ import annotations

import json
from typing import Any

from play_book_studio.db.course_repository import (
    build_course_asset_record,
    build_course_chunk_record,
    import_course_assets,
    import_course_chunks,
    load_course_asset_by_path,
    load_course_chunk,
    load_course_chunks,
)


class FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.cursor_instance = FakeCursor(rows)

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


def test_build_course_chunk_record_preserves_payload_and_search_metadata() -> None:
    payload = {
        "chunk_id": "perf-001",
        "stage_id": "performance",
        "title": "Performance baseline",
        "body_md": "Check response time and worker thread saturation.",
    }

    record = build_course_chunk_record(payload, course_slug="ops-guide", source_ref="data/course_pbs")

    assert record.course_slug == "ops-guide"
    assert record.chunk_key == "perf-001"
    assert record.stage_id == "performance"
    assert record.search_text == "Check response time and worker thread saturation."
    assert record.payload == payload
    assert len(record.checksum) == 64


def test_import_course_chunks_upserts_valid_payloads() -> None:
    connection = FakeConnection()

    result = import_course_chunks(
        connection,
        [
            {"chunk_id": "a", "stage_id": "stage-a", "title": "A", "search_text": "alpha"},
            {"title": "missing id"},
        ],
        course_slug="project-playbook",
        source_ref="data/course_pbs",
    )

    assert result["scanned_count"] == 2
    assert result["imported_count"] == 1
    assert result["skipped_count"] == 1
    sql, params = connection.cursor_instance.statements[0]
    assert "ON CONFLICT (course_slug, chunk_key) DO UPDATE" in sql
    assert params[:4] == ("project-playbook", "a", "stage-a", "A")
    assert json.loads(params[4])["chunk_id"] == "a"


def test_load_course_chunks_returns_payload_rows() -> None:
    rows = [({"chunk_id": "b", "title": "B"},), (None,)]
    connection = FakeConnection(rows)

    chunks = load_course_chunks(connection, course_slug="project-playbook")

    assert chunks == [{"chunk_id": "b", "title": "B"}]


def test_load_course_chunk_returns_single_payload() -> None:
    connection = FakeConnection([({"chunk_id": "c", "title": "C"},)])

    chunk = load_course_chunk(connection, "c", course_slug="project-playbook")

    assert chunk == {"chunk_id": "c", "title": "C"}


def test_build_course_asset_record_hashes_content_and_normalizes_path() -> None:
    record = build_course_asset_record(
        asset_key="data/course_pbs/assets/a.png",
        asset_path="data\\course_pbs\\assets\\a.png",
        content=b"image-bytes",
        payload={"asset_id": "a"},
        course_slug="project-playbook",
        source_ref="data/course_pbs",
    )

    assert record.asset_key == "data/course_pbs/assets/a.png"
    assert record.asset_path == "data/course_pbs/assets/a.png"
    assert record.content_type == "image/png"
    assert record.byte_size == len(b"image-bytes")
    assert record.payload["asset_id"] == "a"
    assert len(record.checksum) == 64


def test_import_course_assets_upserts_binary_payloads() -> None:
    connection = FakeConnection()
    record = build_course_asset_record(
        asset_key="data/course_pbs/assets/a.png",
        asset_path="data/course_pbs/assets/a.png",
        content=b"image-bytes",
        payload={"asset_id": "a"},
        course_slug="project-playbook",
        source_ref="data/course_pbs",
    )

    result = import_course_assets(connection, [record], course_slug="project-playbook", source_ref="data/course_pbs")

    assert result["imported_count"] == 1
    sql, params = connection.cursor_instance.statements[0]
    assert "ON CONFLICT (course_slug, asset_key) DO UPDATE" in sql
    assert params[1:4] == ("data/course_pbs/assets/a.png", "data/course_pbs/assets/a.png", "image/png")
    assert params[7] == b"image-bytes"


def test_load_course_asset_by_path_returns_binary_content() -> None:
    connection = FakeConnection(
        [
            (
                "data/course_pbs/assets/a.png",
                "data/course_pbs/assets/a.png",
                "image/png",
                memoryview(b"image-bytes"),
                {"asset_id": "a"},
                "abc",
            )
        ]
    )

    asset = load_course_asset_by_path(connection, "data/course_pbs/assets/a.png", course_slug="project-playbook")

    assert asset == {
        "asset_key": "data/course_pbs/assets/a.png",
        "asset_path": "data/course_pbs/assets/a.png",
        "content_type": "image/png",
        "content": b"image-bytes",
        "payload": {"asset_id": "a"},
        "checksum": "abc",
    }
