from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.db.qdrant_indexer import (
    QdrantChunkCandidate,
    qdrant_candidate_from_row,
    qdrant_payload_from_row,
    record_qdrant_index_entries,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj


def _chunk_row():
    return {
        "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "chunk_key": "doc:0",
        "ordinal": 0,
        "chunk_type": "document",
        "markdown": "# Architecture\n\nRouter sends traffic.",
        "embedding_text": "Architecture\nRouter sends traffic.",
        "section_path": ["Architecture"],
        "asset_ids": ["asset-1"],
        "chunk_metadata": {"block_ordinals": [0, 1]},
        "parsed_document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "document_title": "Architecture",
        "parsed_metadata": {"document_format": "pptx"},
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "filename": "deck.pptx",
        "storage_key": "uploads/sources/deck.pptx",
        "source_kind": "upload",
        "source_metadata": {"document_format": "pptx"},
        "created_by": "admin",
    }


def test_qdrant_payload_from_row_matches_vector_retriever_contract():
    payload = qdrant_payload_from_row(_chunk_row())

    assert payload["chunk_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert payload["book_slug"] == "uploaded-documents"
    assert payload["chapter"] == "Architecture"
    assert payload["section"] == "Architecture"
    assert payload["viewer_path"] == (
        "/uploads/documents/cccccccc-cccc-cccc-cccc-cccccccccccc/chunks/"
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    assert payload["text"] == "Architecture\nRouter sends traffic."
    assert payload["source_type"] == "uploaded_document"
    assert payload["source_collection"] == "uploads"
    assert payload["section_path"] == ["Architecture"]
    assert payload["asset_ids"] == ["asset-1"]


def test_qdrant_candidate_from_row_hashes_stable_payload():
    candidate = qdrant_candidate_from_row(_chunk_row())

    assert candidate.chunk_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert candidate.point_id == candidate.chunk_id
    assert candidate.embedding_text == "Architecture\nRouter sends traffic."
    assert len(candidate.payload_hash) == 64


def test_record_qdrant_index_entries_upserts_payload_hashes():
    connection = FakeConnection()
    candidate = QdrantChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        point_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        payload={"chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        payload_hash="hash",
    )

    record_qdrant_index_entries(
        connection,
        collection="openshift_docs",
        vector_model="bge",
        candidates=(candidate,),
    )

    sql, params = connection.cursor_obj.calls[0]
    assert "INSERT INTO qdrant_index_entries" in sql
    assert "ON CONFLICT" in sql
    assert params == (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "openshift_docs",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bge",
        "hash",
    )


def test_db_qdrant_index_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-qdrant-index",
            "--root-dir",
            str(REPO_ROOT),
            "--collection",
            "uploads",
            "--limit",
            "10",
        ]
    )

    assert args.command == "db-qdrant-index"
    assert args.collection == "uploads"
    assert args.limit == 10
