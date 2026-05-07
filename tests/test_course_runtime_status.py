from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.db.course_runtime_status import (
    disabled_course_runtime_status,
    load_course_runtime_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.current = []
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        self.current = self.result_sets.pop(0)

    def fetchone(self):
        return self.current[0] if self.current else None


class FakeConnection:
    def __init__(self, result_sets):
        self.cursor_obj = FakeCursor(result_sets)

    def cursor(self):
        return self.cursor_obj


def test_disabled_course_runtime_status_is_not_ready():
    payload = disabled_course_runtime_status(course_slug="project-playbook")

    assert payload["database"] == "disabled"
    assert payload["course_slug"] == "project-playbook"
    assert payload["ready"] is False
    assert payload["chunk_count"] == 0


def test_load_course_runtime_status_reports_ready_when_all_read_models_exist():
    connection = FakeConnection(
        [
            [(523,)],
            [(775, 48924505)],
            [(1, 5, 166)],
        ]
    )

    payload = load_course_runtime_status(connection, course_slug="project-playbook")

    assert payload["database"] == "postgres"
    assert payload["chunk_count"] == 523
    assert payload["asset_count"] == 775
    assert payload["asset_total_bytes"] == 48924505
    assert payload["manifest_count"] == 1
    assert payload["stage_count"] == 5
    assert payload["stop_count"] == 166
    assert payload["has_chunks"] is True
    assert payload["has_assets"] is True
    assert payload["has_manifest"] is True
    assert payload["ready"] is True


def test_load_course_runtime_status_reports_not_ready_without_manifest():
    connection = FakeConnection(
        [
            [(523,)],
            [(775, 48924505)],
            [(0, 0, 0)],
        ]
    )

    payload = load_course_runtime_status(connection, course_slug="project-playbook")

    assert payload["has_manifest"] is False
    assert payload["ready"] is False


def test_course_runtime_status_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "course-runtime-status",
            "--root-dir",
            str(REPO_ROOT),
            "--course-slug",
            "project-playbook",
        ]
    )

    assert args.command == "course-runtime-status"
    assert args.root_dir == REPO_ROOT
    assert args.course_slug == "project-playbook"
