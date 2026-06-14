from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.data_control_room_library as library
from play_book_studio.http.data_control_room import _library_count_contract


def test_viewer_path_fallback_does_not_require_playbook_file_when_database_is_configured(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        playbook_dir = root / "data" / "gold_manualbook_ko" / "playbooks"
        monkeypatch.setattr(
            library,
            "load_settings",
            lambda _root: SimpleNamespace(
                database_url="postgresql://unit-test",
                playbook_books_dir=playbook_dir,
                viewer_path_template="/playbooks/wiki-runtime/active/{slug}/index.html",
            ),
        )

        rows = library._apply_viewer_path_fallback([{"book_slug": "architecture"}], root=root)

    assert rows[0]["viewer_path"] == "/playbooks/wiki-runtime/active/architecture/index.html"


def test_viewer_path_fallback_still_requires_file_without_database(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        playbook_dir = root / "data" / "gold_manualbook_ko" / "playbooks"
        monkeypatch.setattr(
            library,
            "load_settings",
            lambda _root: SimpleNamespace(
                database_url="",
                playbook_books_dir=playbook_dir,
                viewer_path_template="/playbooks/wiki-runtime/active/{slug}/index.html",
            ),
        )

        rows = library._apply_viewer_path_fallback([{"book_slug": "architecture"}], root=root)

    assert "viewer_path" not in rows[0]


def test_library_count_contract_treats_approved_runtime_books_as_authoritative() -> None:
    counts = _library_count_contract(
        known_books=[{"book_slug": "support"}],
        gold_books=[],
        core_manualbooks=[{"book_slug": "support"}, {"book_slug": "networking"}],
        approved_wiki_runtime_books={
            "books": [
                {"book_slug": "support", "grade": "Gold"},
                {"book_slug": "networking", "grade": "Gold"},
            ]
        },
    )

    assert counts["known_books_count"] == 1
    assert counts["gold_book_count"] == 0
    assert counts["manualbook_book_count"] == 2
    assert counts["approved_wiki_runtime_book_count"] == 2
    assert counts["authoritative_runtime_book_count"] == 2
    assert counts["library_authoritative_bucket"] == "approved_wiki_runtime_books"
