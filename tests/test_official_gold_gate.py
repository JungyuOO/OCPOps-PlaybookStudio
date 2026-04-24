from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.server_routes_viewer import resolve_viewer_html
from play_book_studio.canonical.asciidoc import build_source_repo_document_ast
from play_book_studio.canonical.html import _blocks_from_text
from play_book_studio.canonical.models import FigureBlock
from play_book_studio.ingestion.models import SourceManifestEntry
from play_book_studio.ingestion.official_gold_gate import (
    _portable_path_findings,
    repair_portable_json_paths,
)


class OfficialGoldGateTests(unittest.TestCase):
    def test_canonical_text_parser_preserves_figure_blocks(self) -> None:
        blocks = _blocks_from_text(
            '[FIGURE src="/playbooks/wiki-assets/full_rebuild/demo/diagram.png" '
            'asset_ref="diagram.png" alt="Demo"]\nDemo caption\n[/FIGURE]'
        )

        self.assertEqual(1, len(blocks))
        self.assertIsInstance(blocks[0], FigureBlock)
        self.assertEqual("figure", blocks[0].kind)
        self.assertEqual("Demo caption", blocks[0].caption)
        self.assertEqual("/playbooks/wiki-assets/full_rebuild/demo/diagram.png", blocks[0].src)

    def test_source_repo_asciidoc_preserves_image_as_figure_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            mirror_root = root / "tmp_source" / "openshift-docs-enterprise-4.20"
            source_path = mirror_root / "demo" / "index.adoc"
            image_path = mirror_root / "images" / "demo.png"
            source_path.parent.mkdir(parents=True)
            image_path.parent.mkdir(parents=True)
            source_path.write_text(
                "= Demo Book\n\n"
                "== Overview\n\n"
                "image::demo.png[Demo figure]\n\n"
                "본문\n",
                encoding="utf-8",
            )
            image_path.write_bytes(b"png-bytes")
            (mirror_root / "_attributes").mkdir()
            entry = SourceManifestEntry(
                book_slug="demo",
                title="Demo Book",
                source_kind="source-first",
                viewer_path="/docs/ocp/4.20/ko/demo/index.html",
            )

            document = build_source_repo_document_ast(
                entry=entry,
                source_paths=[source_path],
                fallback_title="Demo Book",
            )

            figures = [
                block
                for section in document.sections
                for block in section.blocks
                if isinstance(block, FigureBlock)
            ]
            self.assertEqual(1, len(figures))
            self.assertEqual("Demo figure", figures[0].caption)
            self.assertEqual("/playbooks/wiki-assets/full_rebuild/demo/demo.png", figures[0].src)
            self.assertTrue((root / "data" / "wiki_assets" / "full_rebuild" / "demo" / "demo.png").exists())

    def test_direct_viewer_url_query_controls_page_mode(self) -> None:
        html = resolve_viewer_html(
            ROOT,
            "/playbooks/wiki-runtime/active/advanced_networking/index.html?page_mode=multi",
        )

        self.assertIsNotNone(html)
        self.assertGreater(str(html).count("section-card"), 1)

    def test_portable_path_repair_rewrites_known_old_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            active_path = root / "data" / "wiki_runtime_books" / "active_manifest.json"
            full_path = root / "data" / "wiki_runtime_books" / "full_rebuild_manifest.json"
            source_path = root / "manifests" / "ocp420_source_first_full_rebuild_manifest.json"
            figure_path = root / "data" / "wiki_relations" / "figure_assets.json"
            for path in (active_path, full_path, source_path, figure_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "source_manifest_path": (
                                "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                "data\\wiki_runtime_books\\full_rebuild_manifest.json"
                            ),
                            "entries": [
                                {
                                    "runtime_path": (
                                        "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                        "data\\wiki_runtime_books\\full_rebuild\\demo.md"
                                    ),
                                    "source_file": (
                                        "C:\\Users\\soulu\\cywell\\ocp-play-studio\\ocp-play-studio\\"
                                        "tmp_source\\openshift-docs-enterprise-4.20\\modules\\demo.adoc"
                                    ),
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            repair_portable_json_paths(root)
            findings = _portable_path_findings(root)

            self.assertEqual("ok", findings["status"])
            repaired = json.loads(active_path.read_text(encoding="utf-8"))
            self.assertEqual("data/wiki_runtime_books/full_rebuild_manifest.json", repaired["source_manifest_path"])
            self.assertEqual("data/wiki_runtime_books/full_rebuild/demo.md", repaired["entries"][0]["runtime_path"])
            self.assertEqual(
                "tmp_source/openshift-docs-enterprise-4.20/modules/demo.adoc",
                repaired["entries"][0]["source_file"],
            )


if __name__ == "__main__":
    unittest.main()
