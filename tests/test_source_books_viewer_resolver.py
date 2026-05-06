from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.source_books_viewer_resolver as resolver


def test_playbook_book_is_built_from_postgres_records() -> None:
    payload = resolver._playbook_book_from_database_records(
        [
            {
                "storage_key": "corpus/official_docs/gold_corpus_ko/chunks.jsonl#architecture",
                "source_metadata": {"book_slug": "architecture", "source_id": "openshift:architecture"},
                "document_title": "Architecture",
                "parsed_metadata": {"document_format": "official_gold_jsonl"},
                "chunk_id": "chunk-a",
                "ordinal": 1,
                "markdown": "Control plane overview.",
                "section_path": ["Architecture", "Control plane"],
                "section_number": "1.1",
                "heading_title": "Control plane",
                "source_anchor": "control-plane",
            }
        ],
        "architecture",
    )

    assert payload is not None
    assert payload["book_slug"] == "architecture"
    assert payload["metadata"]["source"] == "postgres.document_chunks"
    assert payload["sections"][0]["blocks"][0]["text"] == "Control plane overview."
    assert payload["sections"][0]["viewer_path"].endswith("#control-plane")


def test_playbook_book_does_not_fallback_to_files_when_database_is_configured(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        playbook_dir = root / "data" / "gold_manualbook_ko" / "playbooks"
        playbook_dir.mkdir(parents=True, exist_ok=True)
        (playbook_dir / "architecture.json").write_text(
            json.dumps({"title": "File fallback", "sections": [{"heading": "File section"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            resolver,
            "load_settings",
            lambda _root: SimpleNamespace(
                database_url="postgresql://unit-test",
                playbook_book_dirs=(playbook_dir,),
                playbook_books_dir=playbook_dir,
                normalized_docs_candidates=(),
            ),
        )
        monkeypatch.setitem(sys.modules, "psycopg", None)

        assert resolver._load_playbook_book(root, "architecture") is None
        assert resolver._load_normalized_book_sections(root, "architecture") == []
