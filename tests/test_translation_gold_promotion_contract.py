from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.ingestion.translation_gold_promotion import _bm25_row


class TranslationGoldPromotionContractTests(unittest.TestCase):
    def test_incremental_bm25_row_preserves_required_runtime_metadata(self) -> None:
        chunk = {
            "chunk_id": "demo::1",
            "book_slug": "demo",
            "chapter": "Demo",
            "section": "Demo section",
            "section_id": "demo:demo-section",
            "anchor": "demo-section",
            "source_url": "https://docs.redhat.com/demo",
            "viewer_path": "/docs/ocp/4.20/ko/demo/index.html#demo-section",
            "text": "Demo text",
            "section_path": ["Demo", "Demo section"],
            "chunk_type": "procedure",
            "source_id": "demo",
            "source_lane": "official_ko",
            "source_type": "official_doc",
            "source_collection": "core",
            "product": "openshift",
            "version": "4.20",
            "locale": "ko",
            "translation_status": "approved_ko",
            "review_status": "approved",
            "trust_score": 1.0,
            "surface_kind": "document",
            "source_unit_kind": "section",
            "source_unit_id": "demo:demo-section",
            "source_unit_anchor": "demo-section",
            "origin_method": "native",
            "ocr_status": "not_run",
            "block_kinds": ["paragraph"],
            "citation_eligible": True,
            "citation_block_reason": "",
            "cli_commands": [],
            "error_strings": [],
            "k8s_objects": [],
            "operator_names": [],
            "verification_hints": [],
        }

        row = _bm25_row(chunk)

        for field in (
            "section_id",
            "surface_kind",
            "source_unit_kind",
            "source_unit_id",
            "source_unit_anchor",
            "origin_method",
            "ocr_status",
            "block_kinds",
            "citation_eligible",
        ):
            self.assertNotIn(row.get(field), (None, "", []), field)


if __name__ == "__main__":
    unittest.main()
