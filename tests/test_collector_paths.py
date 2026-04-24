from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.collector import collect_entry, raw_html_metadata_path, raw_html_path
from play_book_studio.ingestion.models import SourceManifestEntry


class _FakeResponse:
    def __init__(self) -> None:
        self.url = "https://docs.example/architecture"
        self.headers = {"Last-Modified": "Fri, 24 Apr 2026 00:00:00 GMT"}


class CollectorPathTests(unittest.TestCase):
    def test_collect_entry_creates_raw_html_and_metadata_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            entry = SourceManifestEntry(
                book_slug="architecture",
                title="Architecture",
                source_url="https://docs.example/architecture",
                source_kind="html-single",
                docs_language="ko",
                ocp_version="4.20",
            )

            with (
                patch(
                    "play_book_studio.ingestion.collector.fetch_html_response",
                    return_value=_FakeResponse(),
                ),
                patch(
                    "play_book_studio.ingestion.collector._decode_response_text",
                    return_value="<html><body><a href='/legal-notice'>Legal notice</a></body></html>",
                ),
            ):
                path = collect_entry(entry, settings, force=False)

            self.assertEqual(raw_html_path(settings, "architecture"), path)
            self.assertTrue(path.exists())
            self.assertTrue(raw_html_metadata_path(settings, "architecture").exists())


if __name__ == "__main__":
    unittest.main()
