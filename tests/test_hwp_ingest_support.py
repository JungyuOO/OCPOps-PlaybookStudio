from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ["ARTIFACTS_DIR"] = "artifacts"

from play_book_studio.app.intake_api import (
    build_customer_pack_support_matrix,
    customer_pack_request_from_payload,
)
from play_book_studio.intake.normalization.unhwp_adapter import (
    _run_unhwp_convert,
    extract_hwp_markdown_with_unhwp,
    extract_hwp_rows_with_unhwp,
    probe_unhwp,
)


class HwpIntakeSupportTests(unittest.TestCase):
    def test_customer_pack_request_accepts_hwp_and_hwpx(self) -> None:
        for source_type in ("hwp", "hwpx"):
            with self.subTest(source_type=source_type):
                request = customer_pack_request_from_payload(
                    {
                        "source_type": source_type,
                        "uri": f"C:/tmp/sample.{source_type}",
                        "title": "sample",
                    }
                )
                self.assertEqual(source_type, request.source_type)

    def test_customer_pack_upload_request_accepts_missing_uri_when_file_payload_exists(self) -> None:
        for source_type in ("hwp", "hwpx"):
            with self.subTest(source_type=source_type):
                request = customer_pack_request_from_payload(
                    {
                        "source_type": source_type,
                        "file_name": f"sample.{source_type}",
                        "file_bytes": f"fake-{source_type}".encode("utf-8"),
                        "title": "sample",
                    }
                )
                self.assertEqual(source_type, request.source_type)
                self.assertEqual(
                    f"upload://customer-pack/sample.{source_type}",
                    request.uri,
                )

    def test_support_matrix_includes_hwp_and_hwpx_entries(self) -> None:
        matrix = build_customer_pack_support_matrix()
        entries = {
            str(entry.get("format_id") or ""): entry
            for entry in (matrix.get("entries") or [])
            if isinstance(entry, dict)
        }

        self.assertEqual("hwp", entries["hwp"]["source_type"])
        self.assertEqual("staged", entries["hwp"]["support_status"])
        self.assertEqual("native", entries["hwp"]["lane_kind"])
        self.assertEqual("unhwp_structured_extract_v1", entries["hwp"]["normalization_strategy"])
        self.assertEqual(["bridge", "rescue"], sorted(entries["hwp"]["fallback_lanes"]))
        self.assertIn(".hwp", entries["hwp"]["accepted_extensions"])

        self.assertEqual("hwpx", entries["hwpx"]["source_type"])
        self.assertEqual("staged", entries["hwpx"]["support_status"])
        self.assertEqual("native", entries["hwpx"]["lane_kind"])
        self.assertEqual("unhwp_structured_extract_v1", entries["hwpx"]["normalization_strategy"])
        self.assertEqual(["bridge", "rescue"], sorted(entries["hwpx"]["fallback_lanes"]))
        self.assertIn(".hwpx", entries["hwpx"]["accepted_extensions"])

    def test_probe_unhwp_reports_not_configured_when_missing(self) -> None:
        with (
            patch("play_book_studio.intake.normalization.unhwp_adapter._resolve_unhwp_bin", return_value=""),
            patch("play_book_studio.intake.normalization.unhwp_adapter._load_unhwp_module", return_value=None),
        ):
            payload = probe_unhwp()

        self.assertFalse(payload["ready"])
        self.assertEqual("not_configured", payload["status"])

    def test_probe_unhwp_reports_python_runtime_when_module_is_available(self) -> None:
        class _FakeModule:
            @staticmethod
            def version() -> str:
                return "0.2.4"

            @staticmethod
            def supported_formats() -> str:
                return "HWP 5.0, HWPX"

        with (
            patch("play_book_studio.intake.normalization.unhwp_adapter._resolve_unhwp_bin", return_value=""),
            patch("play_book_studio.intake.normalization.unhwp_adapter._load_unhwp_module", return_value=_FakeModule()),
        ):
            payload = probe_unhwp()

        self.assertTrue(payload["ready"])
        self.assertEqual("ok", payload["status"])
        self.assertEqual("python", payload["runtime"])
        self.assertEqual("python:unhwp", payload["binary"])

    def test_extract_hwp_markdown_with_unhwp_reads_generated_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.hwp"
            source.write_bytes(b"fake-hwp")

            def _fake_run(path: Path, *, output_dir: Path, settings=None) -> None:
                del path, settings
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "extract.md").write_text("# 제목\n\n본문", encoding="utf-8")
                (output_dir / "extract.txt").write_text("본문", encoding="utf-8")
                (output_dir / "content.json").write_text(
                    json.dumps({"sections": []}),
                    encoding="utf-8",
                )

            with patch(
                "play_book_studio.intake.normalization.unhwp_adapter._run_unhwp_convert",
                side_effect=_fake_run,
            ):
                markdown = extract_hwp_markdown_with_unhwp(source)

        self.assertIn("# 제목", markdown)
        self.assertIn("본문", markdown)

    def test_extract_hwp_rows_with_unhwp_prefers_structured_content_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.hwpx"
            source.write_bytes(b"fake-hwpx")

            structured_payload = {
                "sections": [
                    {
                        "content": [
                            {
                                "Paragraph": {
                                    "style": {"heading_level": 0},
                                    "content": [{"Text": {"text": "1. 개요"}}],
                                }
                            },
                            {
                                "Paragraph": {
                                    "style": {"heading_level": 0},
                                    "content": [{"Text": {"text": "첫 번째 설명"}}],
                                }
                            },
                            {
                                "Table": {
                                    "rows": [
                                        {
                                            "cells": [
                                                {"content": [{"Text": {"text": "항목"}}]},
                                                {"content": [{"Text": {"text": "값"}}]},
                                            ]
                                        },
                                        {
                                            "cells": [
                                                {"content": [{"Text": {"text": "모드"}}]},
                                                {"content": [{"Text": {"text": "active"}}]},
                                            ]
                                        },
                                    ]
                                }
                            },
                        ]
                    }
                ]
            }

            def _fake_run(path: Path, *, output_dir: Path, settings=None) -> None:
                del path, settings
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "content.json").write_text(
                    json.dumps(structured_payload),
                    encoding="utf-8",
                )

            with patch(
                "play_book_studio.intake.normalization.unhwp_adapter._run_unhwp_convert",
                side_effect=_fake_run,
            ):
                rows = extract_hwp_rows_with_unhwp(
                    source,
                    book_slug="sample-book",
                    book_title="샘플 문서",
                    source_url="/tmp/sample.hwpx",
                    viewer_path_base="/playbooks/customer-packs/draft/index.html",
                )

        self.assertEqual(1, len(rows))
        self.assertEqual("1. 개요", rows[0]["heading"])
        self.assertIn("첫 번째 설명", str(rows[0]["text"]))
        self.assertIn("[TABLE]", str(rows[0]["text"]))

    def test_run_unhwp_convert_forces_utf8_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.hwpx"
            source.write_bytes(b"fake-hwpx")
            output_dir = Path(tmpdir) / "output"

            with (
                patch(
                    "play_book_studio.intake.normalization.unhwp_adapter._resolve_unhwp_bin",
                    return_value="C:/tools/unhwp.exe",
                ),
                patch("play_book_studio.intake.normalization.unhwp_adapter.subprocess.run") as run_mock,
            ):
                _run_unhwp_convert(source, output_dir=output_dir)

        _, kwargs = run_mock.call_args
        self.assertEqual("utf-8", kwargs["encoding"])
        self.assertEqual("replace", kwargs["errors"])

    def test_run_unhwp_convert_uses_python_runtime_when_cli_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.hwpx"
            source.write_bytes(b"fake-hwpx")
            output_dir = Path(tmpdir) / "output"

            class _FakeResult:
                markdown = "# 제목\n\n본문"
                plain_text = "본문"
                json = '{"sections": [{"content": []}]}'

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            class _FakeModule:
                @staticmethod
                def parse(path: Path):
                    del path

                    @contextmanager
                    def _ctx():
                        yield _FakeResult()

                    return _ctx()

            with (
                patch("play_book_studio.intake.normalization.unhwp_adapter._resolve_unhwp_bin", return_value=""),
                patch("play_book_studio.intake.normalization.unhwp_adapter._load_unhwp_module", return_value=_FakeModule()),
            ):
                _run_unhwp_convert(source, output_dir=output_dir)
                self.assertTrue((output_dir / "extract.md").exists())
                self.assertTrue((output_dir / "extract.txt").exists())
                self.assertTrue((output_dir / "content.json").exists())


if __name__ == "__main__":
    unittest.main()
