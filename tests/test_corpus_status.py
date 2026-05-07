from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.db.corpus_status import disabled_corpus_status, load_corpus_status

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

    def fetchall(self):
        return self.current

    def fetchone(self):
        return self.current[0] if self.current else None


class FakeConnection:
    def __init__(self, result_sets):
        self.cursor_obj = FakeCursor(result_sets)

    def cursor(self):
        return self.cursor_obj


def test_disabled_corpus_status_is_not_ready():
    payload = disabled_corpus_status()

    assert payload["database"] == "disabled"
    assert payload["ready"] is False
    assert payload["total_chunks"] == 0


def test_load_corpus_status_reports_ready_when_chunks_and_index_entries_match():
    connection = FakeConnection(
        [
            [("official_docs", 29), ("study_docs", 10)],
            [("official_docs", 27907), ("study_docs", 602)],
            [(28509,)],
            [(28509,)],
            [(0,)],
        ]
    )

    payload = load_corpus_status(connection, collection="openshift_docs")

    assert payload["database"] == "postgres"
    assert payload["collection"] == "openshift_docs"
    assert payload["source_counts"] == {"official_docs": 29, "study_docs": 10}
    assert payload["chunk_counts"] == {"official_docs": 27907, "study_docs": 602}
    assert payload["total_sources"] == 39
    assert payload["total_chunks"] == 28509
    assert payload["qdrant_index_entries"] == 28509
    assert payload["missing_qdrant_index_entries"] == 0
    assert payload["qdrant_index_parity"] is True
    assert payload["ready"] is True


def test_load_corpus_status_reports_not_ready_when_qdrant_entries_are_missing():
    connection = FakeConnection(
        [
            [("official_docs", 29), ("study_docs", 10)],
            [("official_docs", 27907), ("study_docs", 602)],
            [(28509,)],
            [(100,)],
            [(28409,)],
        ]
    )

    payload = load_corpus_status(connection, collection="openshift_docs")

    assert payload["qdrant_index_parity"] is False
    assert payload["ready"] is False
    assert payload["missing_qdrant_index_entries"] == 28409


def test_db_corpus_status_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-corpus-status",
            "--root-dir",
            str(REPO_ROOT),
            "--collection",
            "openshift_docs",
        ]
    )

    assert args.command == "db-corpus-status"
    assert args.collection == "openshift_docs"
