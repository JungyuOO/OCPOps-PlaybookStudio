from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.graph_sidecar import (
    GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
    build_graph_sidecar_compact_payload_from_chunk_rows,
)
from play_book_studio.retrieval.graph_runtime import RetrievalGraphRuntime

TEST_TMP = Path(__file__).resolve().parent / "_tmp_graph_sidecar_postgres"


def test_build_graph_sidecar_compact_payload_from_chunk_rows_groups_books_and_relations():
    payload = build_graph_sidecar_compact_payload_from_chunk_rows(
        [
            {
                "chunk_id": "chunk-a",
                "book_slug": "routes",
                "chapter": "Networking",
                "viewer_path": "/docs/routes",
                "source_url": "https://example.test/routes",
                "source_type": "official_doc",
                "source_lane": "official_docs",
                "source_collection": "core",
                "k8s_objects": ["Route"],
            },
            {
                "chunk_id": "chunk-b",
                "book_slug": "services",
                "chapter": "Networking",
                "viewer_path": "/docs/services",
                "source_url": "https://example.test/services",
                "source_type": "official_doc",
                "source_lane": "official_docs",
                "source_collection": "core",
                "k8s_objects": ["Route"],
            },
        ],
        graph_backend="local",
        app_id="play-book-studio",
        pack_id="openshift-4-20-core",
    )

    assert payload["schema_version"] == GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION
    assert payload["book_count"] == 2
    assert payload["relation_count"] == 1
    assert payload["summary"]["relation_group_counts"]["shared_k8s_objects"] == 1
    assert {book["book_slug"] for book in payload["books"]} == {"routes", "services"}
    assert payload["relations"][0]["relation_types"] == ["shared_k8s_objects"]
    assert payload["relations"][0]["signal_values"] == ["Route"]


def test_graph_runtime_prefers_compact_sidecar_books_before_playbook_document_fallback():
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        root_dir=TEST_TMP,
        graph_sidecar_path_override=str(TEST_TMP / "artifacts" / "retrieval" / "graph_sidecar.json"),
    )
    settings.graph_sidecar_compact_path.parent.mkdir(parents=True, exist_ok=True)
    settings.playbook_documents_path.parent.mkdir(parents=True, exist_ok=True)
    settings.playbook_documents_path.write_text(
        json.dumps(
            {
                "book_slug": "file-book",
                "title": "File Book",
                "source_metadata": {"source_type": "legacy_file"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    settings.graph_sidecar_compact_path.write_text(
        json.dumps(
            {
                "schema_version": GRAPH_SIDECAR_COMPACT_SCHEMA_VERSION,
                "book_count": 1,
                "relation_count": 0,
                "books": [
                    {
                        "book_slug": "db-book",
                        "title": "DB Book",
                        "source_type": "official_doc",
                        "source_lane": "official_docs",
                        "source_collection": "core",
                    }
                ],
                "relations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    book_index = RetrievalGraphRuntime(settings).local_sidecar._load_book_index()  # noqa: SLF001

    assert set(book_index) == {"db-book"}
    assert book_index["db-book"]["title"] == "DB Book"
