from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.citations import preserve_explicit_mixed_runtime_citations
from play_book_studio.answering.models import Citation


def _citation(*, index: int, chunk_id: str, book_slug: str, section: str, viewer_path: str, source_collection: str) -> Citation:
    return Citation(
        index=index,
        chunk_id=chunk_id,
        book_slug=book_slug,
        section=section,
        anchor=section,
        source_url=viewer_path,
        viewer_path=viewer_path,
        excerpt=section,
        source_collection=source_collection,
    )


class AnsweringCitationTests(unittest.TestCase):
    def test_preserve_mixed_runtime_citations_for_blend_signal_query(self) -> None:
        selected_citations = [
            _citation(
                index=1,
                chunk_id="private-1",
                book_slug="customer-pack",
                section="Router Node 구성",
                viewer_path="/playbooks/customer-packs/dtb-3860785ca6b5/index.html#router-node-구성",
                source_collection="uploaded",
            ),
            _citation(
                index=2,
                chunk_id="official-1",
                book_slug="architecture",
                section="OpenShift Container Platform의 아키텍처 개요",
                viewer_path="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
                source_collection="core",
            ),
        ]
        final_citations = [selected_citations[0]]

        preserved = preserve_explicit_mixed_runtime_citations(
            "OCP 운영 설계서의 Router 구성과 OpenShift 아키텍처 개요 문서를 같이 참고해서 설명해줘",
            selected_citations=selected_citations,
            final_citations=final_citations,
        )

        self.assertEqual(2, len(preserved))
        self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in preserved})


if __name__ == "__main__":
    unittest.main()
