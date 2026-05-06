from __future__ import annotations

from dataclasses import dataclass

from play_book_studio.retrieval.chunk_hydration import hydrate_retrieval_hits
from play_book_studio.retrieval.models import RetrievalHit


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


def _hit(chunk_id: str, *, text: str = "stale payload") -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug="uploaded-documents",
        chapter="old",
        section="old",
        anchor="old",
        source_url="old",
        viewer_path="old",
        text=text,
        source="vector",
        raw_score=0.75,
        fused_score=0.42,
        repository_id="old-repo",
        owner_user_id="old-owner",
        visibility="private_user",
        source_scope="user_upload",
        component_scores={"vector": 0.42},
    )


def _row_dict():
    return {
        "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "chunk_key": "doc:0",
        "ordinal": 0,
        "chunk_type": "document",
        "markdown": "# Canonical\n\nFresh DB body.",
        "embedding_text": "Canonical\nFresh DB body.",
        "section_path": ["Canonical"],
        "section_number": "1.1",
        "heading_title": "Canonical",
        "source_anchor": "canonical",
        "toc_path": ["1.1 Canonical"],
        "asset_ids": ["asset-1"],
        "repository_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "owner_user_id": "owner-a",
        "visibility": "workspace_shared",
        "source_scope": "study_docs",
        "chunk_metadata": {"block_ordinals": [0]},
        "parsed_document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "document_title": "Canonical Doc",
        "parsed_metadata": {"document_format": "pdf"},
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "filename": "guide.pdf",
        "storage_key": "corpus/sources/kmsc/raw/guide.pdf",
        "source_kind": "study_docs",
        "source_metadata": {"document_format": "pdf"},
        "created_by": "seed",
    }


def test_hydrate_retrieval_hits_rebuilds_hits_from_canonical_db_rows():
    row = _row_dict()
    columns = list(row)
    connection = FakeConnection(
        [tuple(row[column] for column in columns)],
        columns,
    )

    hydrated = hydrate_retrieval_hits(
        connection,
        [_hit("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
    )

    assert hydrated[0].text == "Canonical\nFresh DB body."
    assert hydrated[0].chapter == "Canonical"
    assert hydrated[0].section == "Canonical"
    assert hydrated[0].anchor == "canonical"
    assert hydrated[0].source_url == "corpus/sources/kmsc/raw/guide.pdf"
    assert hydrated[0].section_number == "1.1"
    assert hydrated[0].heading_title == "Canonical"
    assert hydrated[0].source_anchor == "canonical"
    assert hydrated[0].toc_path == ("1.1 Canonical",)
    assert hydrated[0].repository_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert hydrated[0].owner_user_id == "owner-a"
    assert hydrated[0].visibility == "workspace_shared"
    assert hydrated[0].source_scope == "study_docs"
    assert hydrated[0].asset_ids == ("asset-1",)
    assert hydrated[0].source == "vector"
    assert hydrated[0].raw_score == 0.75
    assert hydrated[0].fused_score == 0.42
    assert hydrated[0].component_scores == {"vector": 0.42}


def test_hydrate_retrieval_hits_keeps_missing_chunks_as_original_hits():
    row = _row_dict()
    columns = list(row)
    connection = FakeConnection(
        [tuple(row[column] for column in columns)],
        columns,
    )
    missing = _hit("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

    hydrated = hydrate_retrieval_hits(connection, [missing])

    assert hydrated == [missing]
