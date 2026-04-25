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

from play_book_studio.ingestion.chunking import _split_blocks
from play_book_studio.ingestion.models import ChunkRecord
from play_book_studio.ingestion.official_figures import build_official_figure_relation_sidecars
from play_book_studio.ingestion.official_gold_gate import (
    _bm25_metadata_contract,
    _figure_relation_coverage,
)
from play_book_studio.ingestion.pipeline import _bm25_row_from_chunk
from play_book_studio.app.viewer_blocks_rich import _render_playbook_block_html
from play_book_studio.app.source_books_viewer_runtime import _sections_with_relation_figures


def _playbook_rows() -> list[dict[str, object]]:
    return [
        {
            "book_slug": "advanced_networking",
            "title": "고급 네트워킹",
            "sections": [
                {
                    "heading": "BGP 경로 알림",
                    "anchor": "bgp-route-advertisements",
                    "section_path": ["고급 네트워킹", "BGP 경로 알림"],
                    "blocks": [
                        {"kind": "paragraph", "text": "다음 다이어그램을 확인합니다."},
                        {
                            "kind": "figure",
                            "src": "https://example.test/images/bgp.png",
                            "asset_url": "https://example.test/images/bgp.png",
                            "asset_ref": "bgp.png",
                            "caption": "BGP 경로 알림 다이어그램",
                            "alt": "BGP 경로 알림 다이어그램",
                        },
                    ],
                }
            ],
        }
    ]


class OfficialFigureContractTests(unittest.TestCase):
    def test_builds_figure_assets_and_section_index_from_playbook_figure_blocks(self) -> None:
        payloads = build_official_figure_relation_sidecars(_playbook_rows())

        assets = payloads["figure_assets"]
        section_index = payloads["figure_section_index"]

        self.assertEqual(1, assets["figure_count"])
        self.assertEqual(1, section_index["matched_section_count"])
        self.assertEqual("bgp.png", assets["entries"]["advanced_networking"][0]["source_asset_ref"])
        self.assertEqual(
            "/wiki/figures/advanced_networking/bgp.png/index.html",
            section_index["by_slug"]["advanced_networking"][0]["viewer_path"],
        )

    def test_figure_relation_coverage_fails_closed_when_sidecar_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            relation_dir = root / "data" / "wiki_relations"
            relation_dir.mkdir(parents=True)
            (relation_dir / "figure_assets.json").write_text(
                json.dumps({"entries": {}}, ensure_ascii=False),
                encoding="utf-8",
            )
            (relation_dir / "figure_section_index.json").write_text(
                json.dumps({"by_slug": {}}, ensure_ascii=False),
                encoding="utf-8",
            )

            coverage = _figure_relation_coverage(root, _playbook_rows())

        self.assertEqual("fail", coverage["status"])
        self.assertEqual(1, coverage["missing_relation_count"])

    def test_chunking_treats_figure_markers_as_atomic_blocks(self) -> None:
        blocks = _split_blocks(
            "intro\n\n"
            "[FIGURE src=\"/playbooks/wiki-assets/full_rebuild/demo/diagram.png\"]\n"
            "Demo diagram\n"
            "[/FIGURE]\n\n"
            "outro"
        )

        self.assertEqual(3, len(blocks))
        self.assertTrue(blocks[1].startswith("[FIGURE"))
        self.assertTrue(blocks[1].endswith("[/FIGURE]"))

    def test_bm25_rows_keep_reader_metadata_contract(self) -> None:
        row = _bm25_row_from_chunk(
            ChunkRecord(
                chunk_id="chunk-1",
                book_slug="advanced_networking",
                book_title="고급 네트워킹",
                chapter="네트워킹",
                section="BGP 경로 알림",
                section_id="advanced_networking:bgp-route-advertisements",
                anchor="bgp-route-advertisements",
                source_url="https://docs.example.test",
                viewer_path="/docs/ocp/4.20/ko/advanced_networking/index.html#bgp-route-advertisements",
                text="고급 네트워킹\n\n[FIGURE]\nBGP 경로 알림 다이어그램\n[/FIGURE]",
                token_count=12,
                ordinal=0,
                section_path=("네트워킹", "BGP 경로 알림"),
                chunk_type="reference",
                surface_kind="document",
                source_unit_kind="section",
                source_unit_id="advanced_networking:bgp-route-advertisements",
                source_unit_anchor="bgp-route-advertisements",
                origin_method="native",
                ocr_status="not_run",
                block_kinds=("paragraph", "figure"),
                citation_eligible=True,
            )
        )

        contract = _bm25_metadata_contract([row])

        self.assertEqual("ok", contract["status"])
        self.assertEqual(["paragraph", "figure"], row["block_kinds"])
        self.assertEqual("section", row["source_unit_kind"])
        self.assertEqual(1, contract["figure_rows_with_block_kind"])

    def test_inline_figure_links_to_figure_viewer_when_sidecar_path_is_present(self) -> None:
        html = _render_playbook_block_html(
            {
                "kind": "figure",
                "src": "https://example.test/images/bgp.png",
                "caption": "BGP 경로 알림 다이어그램",
                "viewer_path": "/wiki/figures/advanced_networking/bgp.png/index.html",
            }
        )

        self.assertIn('href="/wiki/figures/advanced_networking/bgp.png/index.html"', html)
        self.assertNotIn('target="_blank"', html)

    def test_relation_sidecar_enriches_existing_inline_figure_with_viewer_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            relation_dir = root / "data" / "wiki_relations"
            relation_dir.mkdir(parents=True)
            payloads = build_official_figure_relation_sidecars(_playbook_rows())
            (relation_dir / "figure_assets.json").write_text(
                json.dumps(payloads["figure_assets"], ensure_ascii=False),
                encoding="utf-8",
            )
            (relation_dir / "figure_section_index.json").write_text(
                json.dumps(payloads["figure_section_index"], ensure_ascii=False),
                encoding="utf-8",
            )

            sections = [
                {
                    "anchor": "bgp-route-advertisements",
                    "blocks": [
                        {
                            "kind": "figure",
                            "src": "https://example.test/images/bgp.png",
                            "asset_url": "https://example.test/images/bgp.png",
                            "asset_ref": "bgp.png",
                            "caption": "BGP 경로 알림 다이어그램",
                        }
                    ],
                }
            ]
            enriched = _sections_with_relation_figures(root, "advanced_networking", sections)

        figure = enriched[0]["blocks"][0]
        self.assertEqual("/wiki/figures/advanced_networking/bgp.png/index.html", figure["viewer_path"])


if __name__ == "__main__":
    unittest.main()
