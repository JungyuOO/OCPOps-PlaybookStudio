from __future__ import annotations

import uuid

from play_book_studio.ingestion.kmsc_course_import import _chunk_uuid, _parent_chunk_uuid, _with_parent_rows


def test_kmsc_chunk_uuid_accepts_existing_uuid() -> None:
    raw = str(uuid.uuid4())

    assert _chunk_uuid({"chunk_id": raw}) == raw


def test_kmsc_chunk_uuid_normalizes_slug_ids_stably() -> None:
    row = {"chunk_id": "completion--CH-02--default--none--chapter-summary--summary--54364cf6"}

    first = _chunk_uuid(row)
    second = _chunk_uuid(row)

    assert first == second
    assert str(uuid.UUID(first)) == first


def test_kmsc_parent_chunk_uuid_normalizes_slug_parent_ids() -> None:
    parent_id = _parent_chunk_uuid(
        {"parent_chunk_id": "architecture--parent--summary"},
        {},
    )

    assert str(uuid.UUID(parent_id)) == parent_id


def test_kmsc_parent_rows_are_derived_before_children() -> None:
    rows = _with_parent_rows(
        [
            {
                "chunk_id": "child-a",
                "parent_chunk_id": "parent-a",
                "source_pptx": "ops.pptx",
                "title": "성능 목표",
                "body_md": "TPS 목표를 먼저 확인합니다.",
            },
            {
                "chunk_id": "child-b",
                "parent_chunk_id": "parent-a",
                "source_pptx": "ops.pptx",
                "title": "성능 목표",
                "body_md": "Staging과 운영 환경 차이를 확인합니다.",
            },
        ]
    )

    assert rows[0]["chunk_id"] == "ops.pptx#parent-a"
    assert rows[0]["chunk_role"] == "parent"
    assert rows[0]["child_chunk_ids"] == ["child-a", "child-b"]
    assert rows[1]["parent_chunk_id"] == "parent-a"
