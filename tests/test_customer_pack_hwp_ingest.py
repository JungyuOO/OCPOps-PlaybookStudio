from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.intake_api import ingest_customer_pack
from tests.test_customer_pack_read_boundary import (
    _FakeChunkingModel,
    _FakeEmbeddingModel,
    _test_server,
)


def _fake_hwp_rows(source_path, *, book_slug, book_title, source_url, viewer_path_base, settings=None):
    del source_path, settings
    return [
        {
            "book_slug": book_slug,
            "book_title": book_title,
            "heading": "1. 개요",
            "section_level": 1,
            "section_path": ["1. 개요"],
            "anchor": "1-개요",
            "source_url": source_url,
            "viewer_path": f"{viewer_path_base}#1-개요",
            "text": "첫 번째 설명\n\n[TABLE]\n항목 | 값\n모드 | active\n[/TABLE]",
        }
    ]


class CustomerPackHwpIngestTests(unittest.TestCase):
    def test_hwp_and_hwpx_ingest_use_structured_rows_lane_and_render_viewer(self) -> None:
        for source_type in ("hwp", "hwpx"):
            with self.subTest(source_type=source_type):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    with (
                        patch(
                            "play_book_studio.intake.private_corpus.load_sentence_model",
                            return_value=_FakeEmbeddingModel(),
                        ),
                        patch(
                            "play_book_studio.ingestion.chunking.load_sentence_model",
                            return_value=_FakeChunkingModel(),
                        ),
                        patch(
                            "play_book_studio.intake.normalization.builders.extract_hwp_rows_with_unhwp",
                            side_effect=_fake_hwp_rows,
                        ),
                    ):
                        result = ingest_customer_pack(
                            root,
                            {
                                "source_type": source_type,
                                "file_name": f"sample.{source_type}",
                                "file_bytes": f"fake-{source_type}".encode("utf-8"),
                                "title": "한글 샘플",
                                "approval_state": "approved",
                            },
                        )

                    book = dict(result.get("book") or {})
                    evidence = dict(book.get("customer_pack_evidence") or {})
                    sections = [dict(section) for section in (book.get("sections") or []) if isinstance(section, dict)]

                    self.assertEqual("normalized", result["status"])
                    self.assertTrue(sections)
                    self.assertEqual("1. 개요", sections[0]["heading"])
                    self.assertIn("첫 번째 설명", str(sections[0]["text"]))
                    self.assertIn("[TABLE]", str(sections[0]["text"]))
                    self.assertEqual("structured_hwp_first", evidence["primary_parse_strategy"])
                    self.assertEqual("unhwp_structured_rows", evidence["parser_backend"])
                    self.assertEqual(f"{source_type}_customer_pack_normalize_v1", evidence["parser_route"])

                    with _test_server(root) as (base_url, _store, _answerer):
                        response = requests.get(
                            f"{base_url}/playbooks/customer-packs/{result['draft_id']}/index.html",
                            timeout=10,
                        )

                    self.assertEqual(200, response.status_code)
                    self.assertIn("한글 샘플", response.text)
                    self.assertIn("첫 번째 설명", response.text)

    def test_hwp_ingest_uses_markdown_bridge_when_structured_rows_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch(
                    "play_book_studio.intake.private_corpus.load_sentence_model",
                    return_value=_FakeEmbeddingModel(),
                ),
                patch(
                    "play_book_studio.ingestion.chunking.load_sentence_model",
                    return_value=_FakeChunkingModel(),
                ),
                patch(
                    "play_book_studio.intake.normalization.builders.extract_hwp_rows_with_unhwp",
                    return_value=[],
                ),
                patch(
                    "play_book_studio.intake.normalization.builders.extract_hwp_markdown_with_unhwp",
                    return_value="# 1. 개요\n\noc get pods -A\n확인: Pod 상태를 점검한다.",
                ),
            ):
                result = ingest_customer_pack(
                    root,
                    {
                        "source_type": "hwp",
                        "file_name": "sample.hwp",
                        "file_bytes": b"fake-hwp",
                        "title": "한글 브리지",
                        "approval_state": "approved",
                    },
                )

        book = dict(result.get("book") or {})
        evidence = dict(book.get("customer_pack_evidence") or {})
        sections = [dict(section) for section in (book.get("sections") or []) if isinstance(section, dict)]

        self.assertEqual("normalized", result["status"])
        self.assertTrue(sections)
        self.assertEqual("1. 개요", sections[0]["heading"])
        self.assertEqual("procedure", sections[0]["semantic_role"])
        self.assertIn("oc get pods -A", sections[0]["cli_commands"])
        self.assertTrue(any("확인:" in item for item in sections[0]["verification_hints"]))
        self.assertEqual("structured_hwp_first", evidence["primary_parse_strategy"])
        self.assertEqual("unhwp_markdown_bridge", evidence["parser_backend"])
        self.assertTrue(
            any("markdown bridge" in str(note).lower() for note in evidence.get("normalization_notes") or [])
        )


if __name__ == "__main__":
    unittest.main()
