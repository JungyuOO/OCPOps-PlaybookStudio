from __future__ import annotations

from datetime import datetime, timezone

from play_book_studio.http.document_status_api import _jsonable


def test_jsonable_serializes_datetime_values() -> None:
    value = datetime(2026, 5, 8, 12, 30, tzinfo=timezone.utc)

    assert _jsonable(value) == "2026-05-08T12:30:00+00:00"


def test_jsonable_leaves_plain_values_unchanged() -> None:
    assert _jsonable("ready") == "ready"
    assert _jsonable(3) == 3
