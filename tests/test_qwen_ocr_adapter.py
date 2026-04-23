from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import Settings
from play_book_studio.intake.normalization.degraded_pdf import requested_pdf_fallback_backend
from play_book_studio.intake.normalization.qwen_ocr_adapter import extract_image_markdown_with_qwen
from play_book_studio.intake.private_boundary import summarize_private_remote_ocr_boundary


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO9WcXQAAAAASUVORK5CYII="
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return dict(self._payload)


class QwenOcrAdapterTests(unittest.TestCase):
    def test_requested_backend_prefers_qwen_when_explicitly_configured(self) -> None:
        settings = Settings(
            root_dir=Path("."),
            customer_pack_pdf_fallback_backend="qwen",
            qwen_ocr_endpoint="http://qwen.test/v1",
            qwen_ocr_model="qwen2.5-vl",
            surya_ocr_endpoint="http://surya.test/ocr",
        )

        self.assertEqual("qwen", requested_pdf_fallback_backend(settings=settings))

    def test_extract_image_markdown_with_qwen_uses_qwen_endpoint_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.png"
            image_path.write_bytes(_ONE_PIXEL_PNG)
            settings = Settings(
                root_dir=Path(tmpdir),
                qwen_ocr_endpoint="http://qwen.test/v1",
                qwen_ocr_model="qwen2.5-vl",
                qwen_ocr_api_key="secret-token",
            )
            calls: list[dict[str, object]] = []

            def _fake_post(url: str, **kwargs):
                calls.append({"url": url, **kwargs})
                return _FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "OCR 결과 텍스트\nArgoCD",
                                }
                            }
                        ]
                    }
                )

            with patch("play_book_studio.intake.normalization.qwen_ocr_adapter.requests.post", side_effect=_fake_post):
                markdown = extract_image_markdown_with_qwen(image_path, settings=settings)

            self.assertIn("## OCR", markdown)
            self.assertIn("OCR 결과 텍스트", markdown)
            self.assertEqual("http://qwen.test/v1/chat/completions", calls[0]["url"])
            self.assertEqual("Bearer secret-token", calls[0]["headers"]["Authorization"])
            payload = dict(calls[0]["json"])
            self.assertEqual("qwen2.5-vl", payload["model"])
            content = list(payload["messages"][1]["content"])
            self.assertEqual("text", content[0]["type"])
            self.assertEqual("image_url", content[1]["type"])
            self.assertTrue(str(content[1]["image_url"]["url"]).startswith("data:image/png;base64,"))

    def test_extract_image_markdown_with_qwen_falls_back_to_llm_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.png"
            image_path.write_bytes(_ONE_PIXEL_PNG)
            settings = Settings(
                root_dir=Path(tmpdir),
                llm_endpoint="http://llm.test/v1",
                llm_model="qwen3.5-vl",
                llm_api_key="Bearer shared-token",
            )
            calls: list[dict[str, object]] = []

            def _fake_post(url: str, **kwargs):
                calls.append({"url": url, **kwargs})
                return _FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": [{"text": "화면 OCR 텍스트"}],
                                }
                            }
                        ]
                    }
                )

            with patch("play_book_studio.intake.normalization.qwen_ocr_adapter.requests.post", side_effect=_fake_post):
                markdown = extract_image_markdown_with_qwen(image_path, settings=settings)

            self.assertIn("화면 OCR 텍스트", markdown)
            self.assertEqual("http://llm.test/v1/chat/completions", calls[0]["url"])
            self.assertEqual("Bearer shared-token", calls[0]["headers"]["Authorization"])
            self.assertEqual("qwen3.5-vl", calls[0]["json"]["model"])

    def test_private_remote_boundary_accepts_qwen_provider_policy(self) -> None:
        summary = summarize_private_remote_ocr_boundary(
            {
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "pack_id": "customer-pack:draft-1",
                "pack_version": "draft-1",
                "classification": "private",
                "access_groups": ["workspace-a", "tenant-a"],
                "provider_egress_policy": "qwen_remote_ocr",
                "approval_state": "approved",
                "publication_state": "draft",
                "redaction_state": "masked",
            }
        )

        self.assertTrue(summary["remote_ocr_allowed"])
        self.assertTrue(summary["provider_policy_ok"])

    def test_extract_image_markdown_with_qwen_rejects_non_transcription_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.png"
            image_path.write_bytes(_ONE_PIXEL_PNG)
            settings = Settings(
                root_dir=Path(tmpdir),
                llm_endpoint="http://llm.test/v1",
                llm_model="qwen3.5-vl",
            )

            with (
                patch(
                    "play_book_studio.intake.normalization.qwen_ocr_adapter.requests.post",
                    return_value=_FakeResponse(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": "The image provided is completely blank and contains no visible text.",
                                    }
                                }
                            ]
                        }
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "non-transcription OCR text"),
            ):
                extract_image_markdown_with_qwen(image_path, settings=settings)


if __name__ == "__main__":
    unittest.main()
