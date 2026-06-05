from __future__ import annotations

from pathlib import Path

from play_book_studio.aiops.event_timeline import (
    append_timeline_event,
    read_timeline_events,
    timeline_event_path,
)


def test_append_and_read_timeline_events_roundtrip(tmp_path: Path) -> None:
    event = append_timeline_event(
        tmp_path,
        event_type="cli_command",
        source="terminal",
        summary="Command submitted: oc get pods",
        session_id="term-1",
        command_text="oc get pods",
        stdout="pod/api Running",
        exit_code=0,
        metadata={"executor_mode": "dry-run"},
    )

    assert timeline_event_path(tmp_path).is_file()
    rows = read_timeline_events(tmp_path)

    assert rows[0]["event_id"] == event.event_id
    assert rows[0]["event_type"] == "cli_command"
    assert rows[0]["source"] == "terminal"
    assert rows[0]["command_text"] == "oc get pods"
    assert rows[0]["stdout"] == "pod/api Running"
    assert rows[0]["exit_code"] == 0
    assert rows[0]["metadata"] == {"executor_mode": "dry-run"}


def test_read_timeline_events_returns_newest_first_and_honors_limit(tmp_path: Path) -> None:
    append_timeline_event(tmp_path, event_type="first", source="test", summary="first")
    append_timeline_event(tmp_path, event_type="second", source="test", summary="second")

    rows = read_timeline_events(tmp_path, limit=1)

    assert [row["event_type"] for row in rows] == ["second"]
