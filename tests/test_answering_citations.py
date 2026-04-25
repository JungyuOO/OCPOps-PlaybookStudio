from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.citations import preserve_explicit_mixed_runtime_citations
from play_book_studio.answering.answer_text_commands import build_grounded_command_guide_answer
from play_book_studio.answering.answerer import (
    _finalize_deterministic_runtime_answer,
    _polish_blended_runtime_answer_citations,
)
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
    def test_buildconfig_command_guide_cites_uploaded_and_official_sources(self) -> None:
        citations = [
            _citation(
                index=1,
                chunk_id="private-cicd",
                book_slug="customer-master-kmsc-ocp-operations-playbook",
                section="CI/CD 운영 구조",
                viewer_path="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#cicd",
                source_collection="uploaded",
            ),
            _citation(
                index=2,
                chunk_id="buildconfig-overview",
                book_slug="builds_using_buildconfig",
                section="BuildConfig",
                viewer_path="/docs/ocp/4.20/ko/builds_using_buildconfig/index.html#buildconfig",
                source_collection="core",
            ),
        ]

        answer = build_grounded_command_guide_answer(
            query="고객 CI/CD 운영 자료와 OCP 4.20 BuildConfig 공식문서를 같이 참고해서 점검 순서를 알려줘",
            citations=citations,
        )

        self.assertIsNotNone(answer)
        self.assertIn("[1]", answer or "")
        self.assertIn("[2]", answer or "")
        self.assertIn("BuildConfig", answer or "")
        self.assertIn("```bash", answer or "")
        self.assertIn("oc describe buildconfig", answer or "")

    def test_deterministic_runtime_finalizer_keeps_explicit_mixed_citations(self) -> None:
        citations = [
            _citation(
                index=1,
                chunk_id="private-cicd",
                book_slug="customer-master-kmsc-ocp-operations-playbook",
                section="CI/CD 운영 구조",
                viewer_path="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#cicd",
                source_collection="uploaded",
            ),
            _citation(
                index=2,
                chunk_id="buildconfig-overview",
                book_slug="builds_using_buildconfig",
                section="BuildConfig",
                viewer_path="/docs/ocp/4.20/ko/builds_using_buildconfig/index.html#buildconfig",
                source_collection="core",
            ),
        ]

        answer, final_citations, cited_indices = _finalize_deterministic_runtime_answer(
            query="고객 CI/CD 운영 자료와 OCP 4.20 BuildConfig 공식문서를 같이 참고해줘",
            answer_text="답변: 고객 근거는 [1], 공식 BuildConfig 근거는 [2]입니다.",
            citations=citations,
        )

        self.assertIn("[1]", answer)
        self.assertIn("[2]", answer)
        self.assertEqual([1, 2], cited_indices)
        self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in final_citations})

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

    def test_blended_runtime_polish_cites_private_and_official_even_when_llm_uses_one_source(self) -> None:
        selected_citations = [
            _citation(
                index=1,
                chunk_id="private-router",
                book_slug="customer-master-kmsc-ocp-operations-playbook",
                section="사업/시스템 개요",
                viewer_path="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#overview",
                source_collection="uploaded",
            ),
            _citation(
                index=2,
                chunk_id="official-architecture",
                book_slug="architecture",
                section="OpenShift Container Platform의 아키텍처 개요",
                viewer_path="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
                source_collection="core",
            ),
        ]

        answer, final_citations, cited_indices = _polish_blended_runtime_answer_citations(
            query="고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘",
            answer_text="답변: 제공된 근거에는 Router 구성 세부 절차가 포함되어 있지 않습니다. [1]",
            selected_citations=selected_citations,
            final_citations=[selected_citations[0]],
            cited_indices=[1],
        )

        self.assertIn("고객 업로드 문서 기준", answer)
        self.assertIn("[1]", answer)
        self.assertIn("[2]", answer)
        self.assertEqual([1, 2], cited_indices)
        self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in final_citations})


if __name__ == "__main__":
    unittest.main()
