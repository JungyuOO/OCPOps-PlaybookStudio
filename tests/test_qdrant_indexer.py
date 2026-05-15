from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.db.qdrant_indexer import (
    QdrantChunkCandidate,
    backfill_existing_qdrant_index_entries,
    fetch_existing_qdrant_point_ids,
    overwrite_qdrant_payloads,
    qdrant_candidate_from_row,
    qdrant_payload_from_row,
    record_qdrant_index_entries,
    refresh_stale_qdrant_payloads,
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class SettingsStub:
    qdrant_url = "http://qdrant"
    qdrant_collection = "openshift_docs"
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
    assert payload["section_number"] == "1"
    assert payload["heading_title"] == "Architecture"
    assert payload["source_anchor"] == "1-architecture"
    assert payload["toc_path"] == ["1 Architecture"]
    assert payload["repository_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert payload["visibility"] == "private_user"
    assert payload["owner_user_id"] == "admin"
    assert payload["source_scope"] == "user_upload"
    assert payload["asset_ids"] == ["asset-1"]
    assert payload["chunk_role"] == "parent"
    assert payload["child_chunk_ids"] == ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]
    assert payload["navigation_only"] is False
    assert payload["beginner_narrative"] == "초보자는 Route와 Service 관계를 먼저 확인합니다."
    assert payload["starter_question_candidates"] == ["앱을 브라우저로 접속하려면 무엇을 확인해야 해?"]
    assert payload["question_candidates_version"] == 1


def test_qdrant_payload_from_row_preserves_official_gold_metadata():
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

    payload = qdrant_payload_from_row(row)

    assert payload["book_slug"] == "architecture"
    assert payload["chapter"] == "Architecture overview"
    assert payload["section"] == "Routes and services"
    assert payload["section_id"] == "architecture:routes"
    assert payload["anchor"] == "routes"
    assert payload["source_url"] == "https://docs.redhat.com/openshift/architecture"
    assert payload["viewer_path"] == "/docs/ocp/4.20/ko/architecture/index.html#routes"
    assert payload["source_id"] == "openshift:architecture"
    assert payload["source_lane"] == "official_ko"
    assert payload["source_type"] == "official_doc"
    assert payload["source_collection"] == "core"
    assert payload["review_status"] == "approved"
    assert payload["trust_score"] == 1.0
    assert payload["semantic_role"] == "concept"
    assert payload["cli_commands"] == ["oc get routes"]
    assert payload["k8s_objects"] == ["Route", "Service"]
    assert payload["visibility"] == "global_shared"
    assert payload["source_scope"] == "official_docs"
    assert payload["id"] == payload["chunk_id"]
    assert payload["document_id"] == payload["document_source_id"]
    assert payload["source"] == {
        "corpus_scope": "official_docs",
        "doc_type": "official_doc",
        "source_lane": "official_ko",
        "visibility": "global_shared",
        "review_status": "approved",
        "citation_eligible": True,
        "enabled_for_chat": True,
    }
    assert payload["classification"]["domain"] == "architecture"
    assert payload["classification"]["book_slug"] == "architecture"
    assert payload["classification"]["ocp_version"] == "4.20"
    assert payload["classification"]["locale"] == "ko"
    assert payload["chunk"]["chunk_type"] == "document"
    assert payload["chunk"]["title"] == "Architecture"
    assert payload["chunk"]["section_path"] == ["Architecture"]
    assert payload["chunk"]["viewer_path"] == "/docs/ocp/4.20/ko/architecture/index.html#routes"
    assert payload["search_signals"]["commands"] == ["oc get routes"]
    assert payload["search_signals"]["command_families"] == ["oc_get"]
    assert payload["search_signals"]["objects"] == ["Route", "Service"]
    assert payload["text"] == "Architecture\nRouter sends traffic."
    assert payload["text_fields"]["embedding_text"] == "Architecture\nRouter sends traffic."


def test_qdrant_payload_from_row_preserves_learning_metadata_refs():
    row = {
        **_chunk_row(),
        "chunk_metadata": {
            "learning": {
                "stage_id": "install-001",
                "next_refs": [{"ref_type": "document", "book_slug": "nodes", "reason": "다음 학습 단계"}],
            }
        },
        "source_metadata": {
            "learning": {
                "stage_id": "install-001",
                "prerequisite_refs": [{"ref_type": "document", "book_slug": "overview", "reason": "이전 학습 단계"}],
            }
        },
    }

    payload = qdrant_payload_from_row(row)

    assert payload["learning"]["document"]["stage_id"] == "install-001"
    assert payload["learning"]["chunk"]["next_refs"][0]["book_slug"] == "nodes"
    assert payload["learning"]["refs"]["prerequisite_refs"][0]["book_slug"] == "overview"
    assert payload["learning"]["refs"]["next_refs"][0]["book_slug"] == "nodes"


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
        1,
    )


def test_fetch_existing_qdrant_point_ids_reads_existing_points(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse(
            {
                "result": [
                    {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
                    {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
                ]
            }
        )

    monkeypatch.setattr("play_book_studio.db.qdrant_indexer.requests.post", fake_post)

    point_ids = fetch_existing_qdrant_point_ids(
        SettingsStub(),
        collection="openshift_docs",
        point_ids=[
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
        ],
    )

    assert point_ids == {
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }
    assert calls[0][0] == "http://qdrant/collections/openshift_docs/points"
    assert calls[0][1]["with_payload"] is False
    assert calls[0][1]["with_vector"] is False


def test_backfill_existing_qdrant_index_entries_records_existing_candidates(monkeypatch):
    existing = QdrantChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        point_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        payload={"chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        payload_hash="hash-a",
    )
    missing = QdrantChunkCandidate(
        chunk_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        point_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        embedding_text="text",
        payload={"chunk_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
        payload_hash="hash-b",
    )
    connection = FakeConnection()

    monkeypatch.setattr(
        "play_book_studio.db.qdrant_indexer.load_qdrant_chunk_candidates",
        lambda connection, collection, limit: (existing, missing),
    )
    monkeypatch.setattr(
        "play_book_studio.db.qdrant_indexer.fetch_existing_qdrant_point_ids",
        lambda settings, collection, point_ids: {existing.point_id},
    )

    result = backfill_existing_qdrant_index_entries(
        SettingsStub(),
        connection,
        collection="openshift_docs",
        limit=2,
    )

    assert result == {
        "collection": "openshift_docs",
        "candidate_count": 2,
        "existing_count": 1,
        "missing_count": 1,
        "recorded_count": 1,
    }
    assert len(connection.cursor_obj.calls) == 1
    assert connection.cursor_obj.calls[0][1][0] == existing.chunk_id


def test_overwrite_qdrant_payloads_batches_distinct_payload_operations(monkeypatch):
    calls = []
    candidate = QdrantChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        point_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        payload={"chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "section_number": "1.1"},
        payload_hash="hash-a",
    )

    def fake_post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse({"result": {"status": "ok"}})

    monkeypatch.setattr("play_book_studio.db.qdrant_indexer.requests.post", fake_post)

    overwrite_qdrant_payloads(SettingsStub(), "openshift_docs", (candidate,))

    assert calls == [
        (
            "http://qdrant/collections/openshift_docs/points/batch?wait=true",
            {
                "operations": [
                    {
                        "overwrite_payload": {
                            "points": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                            "payload": {
                                "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                                "section_number": "1.1",
                            },
                        }
                    }
                ]
            },
            120,
        )
    ]


def test_refresh_stale_qdrant_payloads_updates_existing_candidates(monkeypatch):
    stale = QdrantChunkCandidate(
        chunk_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        point_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        embedding_text="text",
        payload={"chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "section_number": "1.1"},
        payload_hash="hash-a",
    )
    missing = QdrantChunkCandidate(
        chunk_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        point_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        embedding_text="text",
        payload={"chunk_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},
        payload_hash="hash-b",
    )
    connection = FakeConnection()
    overwritten = []

    monkeypatch.setattr(
        "play_book_studio.db.qdrant_indexer.load_qdrant_payload_refresh_candidates",
        lambda connection, collection, source_scope, limit: (stale, missing),
    )
    monkeypatch.setattr(
        "play_book_studio.db.qdrant_indexer.fetch_existing_qdrant_point_ids",
        lambda settings, collection, point_ids: {stale.point_id},
    )
    monkeypatch.setattr(
        "play_book_studio.db.qdrant_indexer.overwrite_qdrant_payloads",
        lambda settings, collection, candidates, batch_size: overwritten.extend(candidates),
    )

    result = refresh_stale_qdrant_payloads(
        SettingsStub(),
        connection,
        collection="openshift_docs",
        source_scope="official_docs",
        limit=2,
    )

    assert result == {
        "collection": "openshift_docs",
        "source_scope": "official_docs",
        "candidate_count": 2,
        "existing_count": 1,
        "missing_count": 1,
        "refreshed_count": 1,
    }
    assert overwritten == [stale]
    assert len(connection.cursor_obj.calls) == 1
    assert connection.cursor_obj.calls[0][1][0] == stale.chunk_id


def test_db_qdrant_index_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-qdrant-index",
            "--root-dir",
            str(REPO_ROOT),
            "--collection",
            "uploads",
            "--source-scope",
            "workspace_uploads",
            "--limit",
            "10",
        ]
    )

    assert args.command == "db-qdrant-index"
    assert args.collection == "uploads"
    assert args.source_scope == "workspace_uploads"
    assert args.limit == 10


def test_db_qdrant_backfill_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-qdrant-backfill",
            "--root-dir",
            str(REPO_ROOT),
            "--collection",
            "openshift_docs",
            "--limit",
            "1000",
            "--batch-size",
            "128",
        ]
    )

    assert args.command == "db-qdrant-backfill"
    assert args.collection == "openshift_docs"
    assert args.limit == 1000
    assert args.batch_size == 128


def test_db_qdrant_refresh_payloads_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "db-qdrant-refresh-payloads",
            "--root-dir",
            str(REPO_ROOT),
            "--collection",
            "openshift_docs",
            "--source-scope",
            "official_docs",
            "--limit",
            "500",
            "--batch-size",
            "64",
        ]
    )

    assert args.command == "db-qdrant-refresh-payloads"
    assert args.collection == "openshift_docs"
    assert args.source_scope == "official_docs"
    assert args.limit == 500
    assert args.batch_size == 64
