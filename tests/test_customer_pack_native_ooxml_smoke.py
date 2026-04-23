from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from docx import Document
from openpyxl import Workbook
from pptx import Presentation

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


def _create_docx(path: Path) -> None:
    document = Document()
    document.add_heading("백업 절차", level=1)
    document.add_paragraph("oc get pods -A")
    document.add_paragraph("확인: Pod 상태를 점검한다.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "항목"
    table.cell(0, 1).text = "값"
    table.cell(1, 0).text = "모드"
    table.cell(1, 1).text = "active"
    document.save(path)


def _create_pptx(path: Path) -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "운영 점검"
    slide.placeholders[1].text = "oc get nodes\n확인: Node 상태를 점검한다."
    presentation.save(path)


def _create_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "정책 매트릭스"
    sheet.append(["항목", "값"])
    sheet.append(["지원", "enabled"])
    sheet.append(["제한", "local_only"])
    workbook.save(path)


class CustomerPackNativeOoxmlSmokeTests(unittest.TestCase):
    def test_native_ooxml_files_ingest_and_render_end_to_end(self) -> None:
        cases = (
            ("docx", _create_docx, "docx_native_structure", "procedure"),
            ("pptx", _create_pptx, "pptx_native_slide_extract", "procedure"),
            ("xlsx", _create_xlsx, "xlsx_native_sheet_extract", "reference"),
        )
        for source_type, create_fixture, expected_backend, expected_role in cases:
            with self.subTest(source_type=source_type):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    source_path = root / f"sample.{source_type}"
                    create_fixture(source_path)

                    with (
                        patch(
                            "play_book_studio.intake.private_corpus.load_sentence_model",
                            return_value=_FakeEmbeddingModel(),
                        ),
                        patch(
                            "play_book_studio.ingestion.chunking.load_sentence_model",
                            return_value=_FakeChunkingModel(),
                        ),
                    ):
                        result = ingest_customer_pack(
                            root,
                            {
                                "source_type": source_type,
                                "uri": str(source_path),
                                "title": f"{source_type.upper()} 샘플",
                                "approval_state": "approved",
                            },
                        )

                    book = dict(result.get("book") or {})
                    evidence = dict(book.get("customer_pack_evidence") or {})
                    sections = [
                        dict(section)
                        for section in (book.get("sections") or [])
                        if isinstance(section, dict)
                    ]

                    self.assertEqual("normalized", result["status"])
                    self.assertTrue(sections)
                    self.assertEqual("native_ooxml_first", evidence["primary_parse_strategy"])
                    self.assertEqual(expected_backend, evidence["parser_backend"])
                    self.assertTrue(any(str(section.get("semantic_role") or "") == expected_role for section in sections))
                    self.assertTrue(any(section.get("block_kinds") for section in sections))

                    with _test_server(root) as (base_url, _store, _answerer):
                        response = requests.get(
                            f"{base_url}/playbooks/customer-packs/{result['draft_id']}/index.html",
                            timeout=10,
                        )

                    self.assertEqual(200, response.status_code)
                    self.assertIn(f"{source_type.upper()} 샘플", response.text)


if __name__ == "__main__":
    unittest.main()
