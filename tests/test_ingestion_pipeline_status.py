from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.ingestion.models import NormalizedSection, SourceManifestEntry
from play_book_studio.ingestion.pipeline import _entry_with_inferred_runtime_status


def _section(text: str) -> NormalizedSection:
    return NormalizedSection(
        book_slug="demo",
        book_title="데모",
        heading="개요",
        section_level=2,
        section_path=["개요"],
        anchor="overview",
        source_url="https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/demo/index",
        viewer_path="/docs/ocp/4.20/ko/demo/index.html#overview",
        text=text,
    )


class IngestionPipelineStatusTests(unittest.TestCase):
    def test_inferred_approved_book_updates_approval_and_publication_state(self) -> None:
        entry = SourceManifestEntry(book_slug="demo", title="데모")

        inferred = _entry_with_inferred_runtime_status(
            entry,
            html="",
            sections=[_section("이 문서는 한국어 본문입니다.")],
        )

        self.assertEqual("approved_ko", inferred.content_status)
        self.assertEqual("approved", inferred.review_status)
        self.assertEqual("approved", inferred.approval_state)
        self.assertEqual("published", inferred.publication_state)
        self.assertTrue(inferred.citation_eligible)

    def test_inferred_english_only_book_sets_review_required_candidate_state(self) -> None:
        entry = SourceManifestEntry(book_slug="demo", title="Demo")

        inferred = _entry_with_inferred_runtime_status(
            entry,
            html="",
            sections=[_section("This document is written in English only.")],
        )

        self.assertEqual("en_only", inferred.content_status)
        self.assertEqual("needs_review", inferred.review_status)
        self.assertEqual("review_required", inferred.approval_state)
        self.assertEqual("candidate", inferred.publication_state)
        self.assertFalse(inferred.citation_eligible)


if __name__ == "__main__":
    unittest.main()
