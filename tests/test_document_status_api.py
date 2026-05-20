from __future__ import annotations

from datetime import datetime, timezone

from play_book_studio.http.document_status_api import _jsonable, _status_message, COMPLETED_PARSE_STATUSES


def test_jsonable_serializes_datetime_values() -> None:
    value = datetime(2026, 5, 8, 12, 30, tzinfo=timezone.utc)

    assert _jsonable(value) == "2026-05-08T12:30:00+00:00"


def test_jsonable_leaves_plain_values_unchanged() -> None:
    assert _jsonable("ready") == "ready"
    assert _jsonable(3) == 3


def test_parsed_status_is_basic_index_complete_vocabulary() -> None:
    assert "parsed" in COMPLETED_PARSE_STATUSES
    assert _status_message("parsed", indexed_count=3, chunk_count=3) == "기본 텍스트 인덱싱이 완료되었습니다. 답변 품질 검수는 별도입니다."
