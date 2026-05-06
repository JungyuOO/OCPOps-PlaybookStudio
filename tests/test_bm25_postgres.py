from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from play_book_studio.retrieval.bm25 import BM25Index, load_bm25_rows_from_connection
from play_book_studio.retrieval import retriever

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Column:
    name: str


class FakeCursor:
    def __init__(self, rows, columns):
        self.rows = rows
        self.description = [Column(name) for name in columns]
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows, columns):
        self.cursor_obj = FakeCursor(rows, columns)

    def cursor(self):
        return self.cursor_obj


def _row_dict() -> dict:
    return {
        "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "chunk_key": "doc:0",
        "ordinal": 0,
        "chunk_type": "procedure",
        "markdown": "oc get pods 명령으로 Pod 상태를 확인한다.",
        "embedding_text": "oc get pods 명령으로 Pod 상태를 확인한다.",
        "section_path": ["Workloads", "Pods"],
        "section_number": "1.2",
        "heading_title": "Pods",
        "source_anchor": "pods",
        "toc_path": ["1 Workloads", "1.2 Pods"],
        "asset_ids": [],
        "repository_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "owner_user_id": "",
        "visibility": "workspace_shared",
        "source_scope": "study_docs",
        "chunk_metadata": {
            "book_slug": "study-pods",
            "source_lane": "study_docs",
            "source_type": "study_doc",
            "cli_commands": ["oc get pods"],
        },
        "parsed_document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "document_title": "Pod Guide",
        "parsed_metadata": {"document_format": "pdf"},
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "filename": "pod-guide.pdf",
        "storage_key": "corpus/sources/kmsc/raw/pod-guide.pdf",
        "source_kind": "study_docs",
        "source_metadata": {"document_format": "pdf"},
        "created_by": "seed",
    }


def test_load_bm25_rows_from_connection_builds_runtime_payload_rows():
    row = _row_dict()
    columns = list(row)
    connection = FakeConnection(
        [tuple(row[column] for column in columns)],
        columns,
    )

    rows = load_bm25_rows_from_connection(connection)

    assert rows[0]["chunk_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert rows[0]["book_slug"] == "study-pods"
    assert rows[0]["text"] == "oc get pods 명령으로 Pod 상태를 확인한다."
    assert rows[0]["section_number"] == "1.2"
    assert rows[0]["heading_title"] == "Pods"
    assert rows[0]["source_scope"] == "study_docs"
    assert rows[0]["repository_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert rows[0]["cli_commands"] == ["oc get pods"]


def test_bm25_index_can_search_postgres_payload_rows():
    rows = load_bm25_rows_from_connection(
        FakeConnection(
            [tuple(_row_dict().values())],
            list(_row_dict()),
        )
    )

    hits = BM25Index.from_rows(rows).search("Pod 상태 확인 oc get pods", top_k=3)

    assert len(hits) == 1
    assert hits[0].chunk_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert hits[0].source == "bm25"
    assert hits[0].book_slug == "study-pods"
    assert hits[0].section_path == ("Workloads", "Pods")
    assert hits[0].cli_commands == ("oc get pods",)


def test_db_runtime_bm25_does_not_fall_back_to_missing_seed_file(monkeypatch):
    missing_seed_file = REPO_ROOT / "tmp" / "bm25_postgres_tests" / "missing" / "bm25_corpus.jsonl"
    monkeypatch.setattr(
        BM25Index,
        "from_postgres",
        classmethod(lambda cls, _database_url: (_ for _ in ()).throw(RuntimeError("db not ready"))),
    )
    settings = type(
        "Settings",
        (),
        {
            "database_url": "postgresql://unit-test",
            "retrieval_bm25_corpus_path": missing_seed_file,
        },
    )()

    index = retriever._load_bm25_index(settings)

    assert index.rows == []
    assert index.search("anything") == []
