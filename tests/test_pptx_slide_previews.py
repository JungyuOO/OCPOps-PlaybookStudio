from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.intake.pptx_slide_previews import (  # noqa: E402
    _slide_number_from_exported_preview,
    render_pptx_slide_preview_assets,
)


class PptxSlidePreviewTests(unittest.TestCase):
    def test_slide_number_from_powerpoint_export_name_accepts_localized_names(self) -> None:
        self.assertEqual(0, _slide_number_from_exported_preview(Path("슬라이드0.PNG")))
        self.assertEqual(1, _slide_number_from_exported_preview(Path("Slide1.PNG")))
        self.assertEqual(12, _slide_number_from_exported_preview(Path("슬라이드12.PNG")))
        self.assertEqual(0, _slide_number_from_exported_preview(Path("notes.PNG")))

    def test_powerpoint_fallback_fills_missing_previews_after_partial_renderer_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            capture_path = root / "source.pptx"
            capture_path.write_bytes(b"fake-pptx")
            books_dir = root / "books"
            output_dir = books_dir / "draft.slide-assets"

            def fake_renderer_workspace(runtime_dir: Path, _node_modules_dir: Path) -> Path:
                runtime_dir.mkdir(parents=True, exist_ok=True)
                script_path = runtime_dir / "render_previews.mjs"
                script_path.write_text("// fake", encoding="utf-8")
                return script_path

            def fake_powerpoint_fallback(**kwargs: object) -> bool:
                target_dir = Path(kwargs["output_dir"])
                for ordinal in range(1, 4):
                    (target_dir / f"slide-{ordinal:03d}-preview.png").write_bytes(b"\x89PNG\r\n")
                return True

            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "slide-001-preview.png").write_bytes(b"partial")

            with (
                patch("play_book_studio.intake.pptx_slide_previews._resolve_node_bin", return_value=sys.executable),
                patch("play_book_studio.intake.pptx_slide_previews._resolve_node_modules_dir", return_value=root),
                patch(
                    "play_book_studio.intake.pptx_slide_previews._ensure_renderer_workspace",
                    side_effect=fake_renderer_workspace,
                ),
                patch(
                    "play_book_studio.intake.pptx_slide_previews.subprocess.run",
                    return_value=SimpleNamespace(stdout='{"preview_count": 1}'),
                ),
                patch(
                    "play_book_studio.intake.pptx_slide_previews._render_pptx_slide_previews_with_powerpoint",
                    side_effect=fake_powerpoint_fallback,
                ),
            ):
                assets = render_pptx_slide_preview_assets(
                    capture_path=capture_path,
                    books_dir=books_dir,
                    asset_slug="draft",
                    slide_width=1280,
                    slide_height=720,
                    slide_count=3,
                )

            self.assertEqual(3, len(assets))
            self.assertTrue((output_dir / "slide-003-preview.png").exists())


if __name__ == "__main__":
    unittest.main()
