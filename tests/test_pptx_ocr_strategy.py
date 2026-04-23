from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import Settings
from play_book_studio.intake.pptx_ocr_augment import _ocr_markdown_text, _preferred_ppt_ocr_backends


class PptxOcrStrategyTests(unittest.TestCase):
    def test_slide_preview_prefers_qwen_first_for_table_heavy_slide(self) -> None:
        settings = Settings(
            root_dir=Path("."),
            llm_endpoint="http://qwen.test/v1",
            llm_model="Qwen/Qwen3.5-9B",
            surya_ocr_endpoint="http://surya.test/ocr",
        )

        backends = _preferred_ppt_ocr_backends(
            settings,
            target_kind="slide_preview",
            slide={
                "slide_role": "table_heavy",
                "table_blocks": [{"rows": [["NO", "Owner"]]}],
            },
        )

        self.assertEqual(["qwen", "surya"], backends)

    def test_slide_preview_prefers_surya_first_for_general_diagram_slide(self) -> None:
        settings = Settings(
            root_dir=Path("."),
            llm_endpoint="http://qwen.test/v1",
            llm_model="Qwen/Qwen3.5-9B",
            surya_ocr_endpoint="http://surya.test/ocr",
        )

        backends = _preferred_ppt_ocr_backends(
            settings,
            target_kind="slide_preview",
            slide={
                "slide_role": "content",
                "table_blocks": [],
            },
        )

        self.assertEqual(["surya", "qwen"], backends)

    def test_embedded_image_prefers_qwen_then_surya(self) -> None:
        settings = Settings(
            root_dir=Path("."),
            qwen_ocr_endpoint="http://qwen.test/v1",
            qwen_ocr_model="qwen2.5-vl",
            surya_ocr_endpoint="http://surya.test/ocr",
        )

        backends = _preferred_ppt_ocr_backends(settings, target_kind="embedded_image")

        self.assertEqual(["qwen", "surya"], backends)

    def test_explicit_backend_override_disables_hybrid_chain(self) -> None:
        settings = Settings(
            root_dir=Path("."),
            customer_pack_pdf_fallback_backend="surya",
            qwen_ocr_endpoint="http://qwen.test/v1",
            qwen_ocr_model="qwen2.5-vl",
            surya_ocr_endpoint="http://surya.test/ocr",
        )

        self.assertEqual(
            ["surya"],
            _preferred_ppt_ocr_backends(settings, target_kind="slide_preview", slide={"slide_role": "table_heavy"}),
        )

    def test_ocr_markdown_text_strips_code_fences_and_html_breaks(self) -> None:
        markdown = "```markdown\nTitle<br>Line 1<br/>Line 2\n```"

        cleaned = _ocr_markdown_text(markdown)

        self.assertEqual("Title\nLine 1\nLine 2", cleaned)


if __name__ == "__main__":
    unittest.main()
