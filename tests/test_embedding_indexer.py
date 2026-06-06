from __future__ import annotations

from pathlib import Path

import pytest

from play_book_studio.cli import build_parser
from play_book_studio.db.embedding_indexer import (
    EmbeddingChunkCandidate,
    index_pending_document_chunks,
    load_embedding_chunk_candidates,
    upsert_chunk_embeddings,
)
from play_book_studio.retrieval.payload import retrieval_payload_from_row

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.description = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def transaction(self):
        return FakeTransaction()

    def cursor(self):
        return self.cursor_obj


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _text in texts]


class SettingsStub:
    request_timeout_seconds = 5
    embedding_model = "bge"


def _chunk_row():
    return {
        "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "chunk_key": "doc:0",
        "ordinal": 0,
        "chunk_type": "document",
        "markdown": "# Architecture\n\nRouter sends traffic.",
        "embedding_text": "Architecture\nRouter sends traffic.",
        "section_path": ["Architecture"],
        "section_number": "1",
        "heading_title": "Architecture",
        "source_anchor": "1-architecture",
        "toc_path": ["1 Architecture"],
        "asset_ids": ["asset-1"],
        "chunk_role": "parent",
        "parent_chunk_id": "",
        "child_chunk_ids": ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"],
        "navigation_only": False,
        "beginner_narrative": "초보자는 Route와 Service 관계를 먼저 확인합니다.",
        "starter_question_candidates": ["앱을 브라우저로 접속하려면 무엇을 확인해야 해?"],
        "followup_question_candidates": ["Service가 Route와 연결됐는지 확인하는 명령어가 뭐야?"],
        "question_candidates_version": 1,
        "repository_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "owner_user_id": "admin",
        "visibility": "private_user",
        "source_scope": "user_upload",
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


def test_retrieval_payload_from_row_matches_vector_retriever_contract():
    payload = retrieval_payload_from_row(_chunk_row())

    assert payload["chunk_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert payload["book_slug"] == "uploaded-documents"
    assert payload["viewer_path"] == (
        "/uploads/documents/cccccccc-cccc-cccc-cccc-cccccccccccc/index.html#"
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    assert payload["text"] == "Architecture\nRouter sends traffic."
    assert payload["source_type"] == "uploaded_document"
    assert payload["source_collection"] == "uploads"
    assert payload["repository_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert payload["visibility"] == "private_user"
    assert payload["owner_user_id"] == "admin"
    assert payload["source_scope"] == "user_upload"
    assert payload["asset_ids"] == ["asset-1"]
    assert payload["chunk_role"] == "parent"
    assert payload["child_chunk_ids"] == ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]
    assert payload["navigation_only"] is False
    assert payload["question_candidates_version"] == 1


def test_retrieval_payload_from_row_preserves_official_gold_metadata():
    row = {
        **_chunk_row(),
        "chunk_metadata": {
            "book_slug": "architecture",
            "chapter": "Architecture overview",
            "section": "Routes and services",
            "section_id": "architecture:routes",
            "anchor": "routes",
            "source_url": "https://docs.redhat.com/openshift/architecture",
            "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#routes",
            "source_id": "openshift:architecture",
            "source_lane": "official_ko",
            "source_type": "official_doc",
            "source_collection": "core",
            "review_status": "approved",
            "trust_score": 1.0,
            "semantic_role": "concept",
            "cli_commands": ["oc get routes"],
            "k8s_objects": ["Route", "Service"],
        },
        "source_kind": "official_gold",
        "source_scope": "official_docs",
        "visibility": "global_shared",
        "source_metadata": {
            "document_format": "official_gold_jsonl",
            "source_scope": "official_docs",
            "visibility": "global_shared",
        },
    }

    payload = retrieval_payload_from_row(row)

    assert payload["book_slug"] == "architecture"
    assert payload["section"] == "Routes and services"
    assert payload["viewer_path"] == "/docs/ocp/4.20/ko/architecture/index.html#routes"
    assert payload["source_type"] == "official_doc"
    assert payload["source_collection"] == "core"
    assert payload["review_status"] == "approved"
    assert payload["semantic_role"] == "concept"
    assert payload["cli_commands"] == ["oc get routes"]
    assert payload["k8s_objects"] == ["Route", "Service"]
    assert payload["source"]["corpus_scope"] == "official_docs"
    assert payload["classification"]["domain"] == "architecture"
    assert payload["search_signals"]["command_families"] == ["oc_get"]
    assert payload["text_fields"]["embedding_text"] == "Architecture\nRouter sends traffic."


def test_load_embedding_chunk_candidates_rejects_invalid_document_source_id():
    with pytest.raises(ValueError, match="document_source_id"):
        load_embedding_chunk_candidates(
            FakeConnection(),
            model="bge",
            document_source_id="not-a-uuid",
        )


def test_load_embedding_chunk_candidates_uses_chunk_embeddings_and_skips_empty_text():
    connection = FakeConnection()

    candidates = load_embedding_chunk_candidates(
        connection,
        model="bge",
    )

    assert candidates == ()
    sql = connection.cursor_obj.calls[0][0]
    assert "LEFT JOIN chunk_embeddings ce" in sql
    assert "length(btrim(COALESCE(c.embedding_text, ''))) > 0" in sql
    assert "c.source_scope <> 'user_upload'" in sql
    assert "latest_pd.document_source_id = ds.id" in sql
    assert "ce.embedding_text_hash" in sql


def test_upsert_chunk_embeddings_writes_pgvector_rows():
    connection = FakeConnection()
    candidate = EmbeddingChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        embedding_text_hash="text-hash",
        payload={"chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        payload_hash="payload-hash",
    )

    upsert_chunk_embeddings(
        connection,
        model="bge",
        candidates=(candidate,),
        vectors=[[0.1, 0.2, 0.3]],
    )

    sql, params = connection.cursor_obj.calls[0]
    assert "INSERT INTO chunk_embeddings" in sql
    assert "ON CONFLICT (chunk_id, model)" in sql
    assert params == (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bge",
        "[0.1,0.2,0.3]",
        "text-hash",
        "payload-hash",
    )


def test_upsert_chunk_embeddings_rejects_vector_count_mismatch():
    with pytest.raises(ValueError, match="candidate count"):
        upsert_chunk_embeddings(
            FakeConnection(),
            model="bge",
            candidates=(
                EmbeddingChunkCandidate(
                    chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    embedding_text="text",
                    embedding_text_hash="text-hash",
                    payload={},
                    payload_hash="payload-hash",
                ),
            ),
            vectors=[],
        )


def test_index_pending_document_chunks_scopes_to_document_source_id(monkeypatch):
    captured = {}
    candidate = EmbeddingChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        embedding_text_hash="text-hash",
        payload={},
        payload_hash="payload-hash",
    )

    def fake_load(connection, **kwargs):
        captured.update(kwargs)
        return (candidate,)

    monkeypatch.setattr("play_book_studio.db.embedding_indexer.load_embedding_chunk_candidates", fake_load)

    result = index_pending_document_chunks(
        SettingsStub(),
        FakeConnection(),
        source_scope="user_upload",
        document_source_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        limit=25,
        embedding_client=FakeEmbeddingClient(),
    )

    assert captured == {
        "model": "bge",
        "source_scope": "user_upload",
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "limit": 25,
    }
    assert result == {
        "backend": "pgvector",
        "model": "bge",
        "source_scope": "user_upload",
        "document_source_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "candidate_count": 1,
        "indexed_count": 1,
    }


def test_db_vector_index_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-vector-index",
            "--root-dir",
            str(REPO_ROOT),
            "--source-scope",
            "workspace_uploads",
            "--document-source-id",
            "11111111-1111-1111-1111-111111111111",
            "--limit",
            "10",
        ]
    )

    assert args.command == "db-vector-index"
    assert args.source_scope == "workspace_uploads"
    assert args.document_source_id == "11111111-1111-1111-1111-111111111111"
    assert args.limit == 10
