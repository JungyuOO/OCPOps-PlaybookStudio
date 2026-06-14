from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.runtime_catalog_registry import (
    _load_registry_cached,
    active_manifest_runtime_slugs,
    official_runtime_books,
)


def test_official_runtime_books_are_limited_to_active_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SOURCE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("PLAYBOOK_DOCUMENTS_PATH", raising=False)
    _load_registry_cached.cache_clear()

    source_manifest = tmp_path / "corpus" / "manifests" / "official" / "ocp_ko_4_20_approved_ko.json"
    source_manifest.parent.mkdir(parents=True)
    source_manifest.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "book_slug": "overview",
                        "title": "Overview",
                        "approval_state": "approved",
                        "source_url": "https://example.test/overview",
                    },
                    {
                        "book_slug": "ai_workloads",
                        "title": "AI Workloads",
                        "approval_state": "approved",
                        "source_url": "https://example.test/ai-workloads",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    active_manifest = tmp_path / "corpus" / "data" / "wiki_runtime_books" / "active_manifest.json"
    active_manifest.parent.mkdir(parents=True)
    active_manifest.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "book_slug": "overview",
                        "title": "Overview",
                        "runtime_path": str(tmp_path / "overview.md"),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert active_manifest_runtime_slugs(tmp_path) == ["overview"]
    assert [book["book_slug"] for book in official_runtime_books(tmp_path)] == ["overview"]
