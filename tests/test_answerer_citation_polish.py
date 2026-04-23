from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.answering.models import Citation, ContextBundle
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.models import SessionContext


def _runtime_meta() -> dict[str, object]:
    return {
        "preferred_provider": "deterministic-test",
        "fallback_enabled": False,
        "last_provider": "deterministic-test",
        "last_fallback_used": False,
        "last_attempted_providers": ["deterministic-test"],
        "last_requested_max_tokens": 0,
    }


def _llm_phase_timings() -> dict[str, float]:
    return {
        "llm_provider_round_trip": 0.0,
        "llm_post_process": 0.0,
    }


def _uploaded_citation(draft_id: str) -> Citation:
    return Citation(
        index=1,
        chunk_id="customer-router",
        book_slug="customer-router-playbook",
        section="Router 구성",
        anchor="router-section",
        source_url=f"/playbooks/customer-packs/{draft_id}/index.html#router-section",
        viewer_path=f"/playbooks/customer-packs/{draft_id}/index.html#router-section",
        excerpt="고객 OCP 운영 설계서의 Router 구성",
        source_collection="uploaded",
    )


def _official_citation() -> Citation:
    return Citation(
        index=2,
        chunk_id="official-architecture",
        book_slug="architecture",
        section="OpenShift 아키텍처 개요",
        anchor="architecture-overview",
        source_url="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
        viewer_path="/docs/ocp/4.20/ko/architecture/index.html#architecture-overview",
        excerpt="OpenShift Router와 아키텍처 개요",
        source_collection="core",
    )


class AnswererCitationPolishTests(unittest.TestCase):
    def test_blended_answer_keeps_uploaded_and_official_citations_in_final_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            draft_id = "dtb-polish"
            query = "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘"
            selected_citations = [
                _uploaded_citation(draft_id),
                _official_citation(),
            ]
            retriever = Mock()
            retriever.retrieve.return_value = SimpleNamespace(
                hits=[],
                rewritten_query=query,
                trace={"warnings": []},
            )
            answerer = ChatAnswerer(
                settings=settings,
                retriever=retriever,
                llm_client=Mock(),
            )

            with (
                patch("play_book_studio.answering.answerer.route_non_rag", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.assemble_context",
                    return_value=ContextBundle(prompt_context="", citations=selected_citations),
                ),
                patch("play_book_studio.answering.answerer._build_doc_locator_answer", return_value=None),
                patch("play_book_studio.answering.answerer.build_deployment_scaling_answer", return_value=None),
                patch("play_book_studio.answering.answerer.build_grounded_command_guide_answer", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.generate_grounded_answer_text",
                    return_value=(
                        "답변: 고객 Router 구성은 사설 설계서 기준으로 먼저 확인하면 됩니다 [1].",
                        _runtime_meta(),
                        _llm_phase_timings(),
                    ),
                ),
            ):
                result = answerer.answer(
                    query,
                    context=SessionContext(
                        mode="chat",
                        ocp_version=settings.ocp_version,
                        selected_draft_ids=[draft_id],
                        restrict_uploaded_sources=False,
                    ),
                    top_k=5,
                    candidate_k=10,
                    max_context_chunks=4,
                )

            self.assertEqual("rag", result.response_kind)
            self.assertEqual([1, 2], result.cited_indices)
            self.assertEqual(2, len(result.citations))
            self.assertEqual("uploaded", result.citations[0].source_collection)
            self.assertEqual("core", result.citations[1].source_collection)
            self.assertIn(
                "고객 업로드 문서 기준은 [1], OpenShift 공식 근거는 [2]를 함께 참고했습니다.",
                result.answer,
            )

    def test_non_blended_answer_does_not_force_official_bridge_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            draft_id = "dtb-polish"
            query = "고객 OCP 운영 설계서 기준으로 Router 구성을 설명해줘"
            selected_citations = [
                _uploaded_citation(draft_id),
                _official_citation(),
            ]
            retriever = Mock()
            retriever.retrieve.return_value = SimpleNamespace(
                hits=[],
                rewritten_query=query,
                trace={"warnings": []},
            )
            answerer = ChatAnswerer(
                settings=settings,
                retriever=retriever,
                llm_client=Mock(),
            )

            with (
                patch("play_book_studio.answering.answerer.route_non_rag", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.assemble_context",
                    return_value=ContextBundle(prompt_context="", citations=selected_citations),
                ),
                patch("play_book_studio.answering.answerer._build_doc_locator_answer", return_value=None),
                patch("play_book_studio.answering.answerer.build_deployment_scaling_answer", return_value=None),
                patch("play_book_studio.answering.answerer.build_grounded_command_guide_answer", return_value=None),
                patch(
                    "play_book_studio.answering.answerer.generate_grounded_answer_text",
                    return_value=(
                        "답변: 고객 Router 구성은 사설 설계서 기준으로 먼저 확인하면 됩니다 [1].",
                        _runtime_meta(),
                        _llm_phase_timings(),
                    ),
                ),
            ):
                result = answerer.answer(
                    query,
                    context=SessionContext(
                        mode="chat",
                        ocp_version=settings.ocp_version,
                        selected_draft_ids=[draft_id],
                        restrict_uploaded_sources=False,
                    ),
                    top_k=5,
                    candidate_k=10,
                    max_context_chunks=4,
                )

            self.assertEqual([1], result.cited_indices)
            self.assertEqual(1, len(result.citations))
            self.assertNotIn("OpenShift 공식 근거는 [2]", result.answer)


if __name__ == "__main__":
    unittest.main()
