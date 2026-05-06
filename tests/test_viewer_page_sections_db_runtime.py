from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.viewer_page_sections as viewer_page_sections


def test_playbook_anchor_index_does_not_read_files_when_database_is_configured(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        playbook_dir = root / "data" / "gold_manualbook_ko" / "playbooks"
        playbook_dir.mkdir(parents=True, exist_ok=True)
        (playbook_dir / "architecture.json").write_text(
            json.dumps({"anchor_map": {"file-anchor": "/docs/ocp/4.20/ko/architecture/index.html#file-anchor"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            viewer_page_sections,
            "load_settings",
            lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
        )
        monkeypatch.setitem(sys.modules, "psycopg", None)
        viewer_page_sections._playbook_anchor_index.cache_clear()

        assert viewer_page_sections._playbook_anchor_index(str(root)) == {}


def test_source_anchor_index_does_not_read_tmp_source_when_database_is_configured(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        module_dir = root / "tmp_source" / "openshift-docs-enterprise-4.20" / "modules"
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "architecture.adoc").write_text(
            '[id="file-anchor"]\n= File anchor\n\nFile body',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            viewer_page_sections,
            "load_settings",
            lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
        )
        monkeypatch.setitem(sys.modules, "psycopg", None)
        viewer_page_sections._source_anchor_file_index.cache_clear()
        viewer_page_sections._source_section_lines.cache_clear()

        assert viewer_page_sections._source_anchor_file_index(str(root)) == {}
        assert viewer_page_sections._source_section_lines(str(root), "file-anchor") == ()
