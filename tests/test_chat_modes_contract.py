from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.answerer import (
    _allow_multi_citation_runtime_fallback,
    _build_blended_runtime_fallback_answer,
    _build_cross_source_learning_path_answer,
    _build_doc_locator_answer,
    _build_operator_learning_answer,
    _build_route_ingress_learning_answer,
)
from play_book_studio.answering.answer_text import (
    build_grounded_command_guide_answer,
    shape_actionable_ops_answer,
)
from play_book_studio.answering.models import AnswerResult, Citation, ContextBundle
from play_book_studio.answering.prompt import build_messages
from play_book_studio.answering.router import route_non_rag
from play_book_studio.app.session_flow import context_with_request_overrides, derive_next_context
from play_book_studio.chat_modes import normalize_chat_mode
from play_book_studio.retrieval.models import SessionContext


class ChatModesContractTests(unittest.TestCase):
    def test_normalize_chat_mode_preserves_two_modes_and_maps_legacy_values(self) -> None:
        self.assertEqual("ops", normalize_chat_mode("ops"))
        self.assertEqual("learn", normalize_chat_mode("learn"))
        self.assertEqual("ops", normalize_chat_mode("chat"))
        self.assertEqual("learn", normalize_chat_mode("guided_tour"))
        self.assertEqual("ops", normalize_chat_mode("unknown-mode"))

    def test_request_context_preserves_requested_learn_mode(self) -> None:
        context = context_with_request_overrides(
            SessionContext(mode="chat"),
            payload={"mode": "learn"},
            mode="ops",
            default_ocp_version="4.20",
        )

        self.assertEqual("learn", context.mode)
        self.assertEqual("4.20", context.ocp_version)

    def test_next_context_preserves_requested_ops_mode(self) -> None:
        result = AnswerResult(
            query="oc get pods 먼저 확인해?",
            mode="ops",
            answer="답변: 먼저 이벤트를 확인합니다.",
            rewritten_query="oc get pods 먼저 확인해?",
            citations=[],
            response_kind="rag",
        )

        context = derive_next_context(
            SessionContext(mode="learn", ocp_version="4.20"),
            query=result.query,
            mode="ops",
            result=result,
            default_ocp_version="4.20",
        )

        self.assertEqual("ops", context.mode)

    def test_prompt_contract_differs_between_learn_and_ops(self) -> None:
        bundle = ContextBundle(prompt_context="[1] OCP 근거", citations=[])

        learn_messages = build_messages(query="Operator가 뭐야?", mode="learn", context_bundle=bundle)
        ops_messages = build_messages(query="Pod Pending이면 먼저 뭘 봐?", mode="ops", context_bundle=bundle)

        learn_joined = "\n".join(message["content"] for message in learn_messages)
        ops_joined = "\n".join(message["content"] for message in ops_messages)
        self.assertIn("현재 챗봇 모드: learn", learn_joined)
        self.assertIn("개념 정의, 구성 요소", learn_joined)
        self.assertIn("현재 챗봇 모드: ops", ops_joined)
        self.assertIn("첫 확인 행동", ops_joined)

    def test_grounded_learning_path_questions_are_not_short_circuited_as_generic_guide(self) -> None:
        routed = route_non_rag(
            "OpenShift를 처음 배우는 사람에게 개요, 아키텍처, Operator를 어떤 순서로 설명하면 좋을까?"
        )

        self.assertIsNone(routed)

    def test_learn_mode_allows_runtime_blend_citation_fallback(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="official-1",
                book_slug="overview",
                section="개요",
                anchor="overview",
                source_url="https://docs.redhat.com/overview",
                viewer_path="/docs/ocp/4.20/ko/overview/index.html#overview",
                excerpt="OpenShift 공식 문서 근거",
                boundary_truth="official_runtime",
            ),
            Citation(
                index=2,
                chunk_id="customer-1",
                book_slug="dtb-001",
                section="고객 운영북",
                anchor="customer",
                source_url="customer.pptx",
                viewer_path="/playbooks/customer-packs/dtb-001/index.html#customer",
                excerpt="고객 PPT 근거",
                boundary_truth="private_customer_pack_runtime",
                source_collection="uploaded",
            ),
        ]

        self.assertTrue(
            _allow_multi_citation_runtime_fallback(
                query="공식 문서와 고객 PPT를 같이 참고해서 학습 경로를 설명해줘",
                mode="learn",
                citations=citations,
            )
        )
        self.assertTrue(
            _allow_multi_citation_runtime_fallback(
                query="공식 문서와 고객 운영 자료를 같이 공부할 때 어떤 순서가 좋아?",
                mode="learn",
                citations=citations,
            )
        )

    def test_learn_mode_blended_runtime_fallback_is_learning_copy(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="official-1",
                book_slug="overview",
                section="OpenShift Container Platform 소개",
                anchor="overview",
                source_url="https://docs.redhat.com/overview",
                viewer_path="/docs/ocp/4.20/ko/overview/index.html#overview",
                excerpt="OpenShift 공식 문서 근거",
                boundary_truth="official_runtime",
            ),
            Citation(
                index=2,
                chunk_id="customer-1",
                book_slug="dtb-001",
                section="고객 운영북",
                anchor="customer",
                source_url="customer.pptx",
                viewer_path="/playbooks/customer-packs/dtb-001/index.html#customer",
                excerpt="고객 PPT 근거",
                boundary_truth="private_customer_pack_runtime",
                source_collection="uploaded",
            ),
        ]

        result = _build_blended_runtime_fallback_answer(
            query="공식 문서와 고객 PPT를 같이 참고해서 학습 경로를 설명해줘",
            mode="learn",
            citations=citations,
        )

        self.assertIsNotNone(result)
        assert result is not None
        answer, final_citations = result
        self.assertIn("학습 경로", answer)
        self.assertIn("고객 맥락 -> 공식 개념 -> 차이점 정리", answer)
        self.assertNotIn("문서를 여는 것이 맞습니다", answer)
        self.assertEqual(2, len(final_citations))

    def test_learn_mode_cross_source_learning_path_has_customer_and_official_citations(self) -> None:
        result = _build_cross_source_learning_path_answer(
            "공식 문서와 고객 운영 자료를 같이 공부할 때 어떤 순서가 좋아?"
        )

        self.assertIsNotNone(result)
        assert result is not None
        answer, citations = result
        self.assertIn("고객 운영 자료 -> 공식 개념", answer)
        self.assertIn("학습모드", answer)
        self.assertEqual({"uploaded", "core"}, {citation.source_collection for citation in citations})
        self.assertEqual(
            ["customer-master-kmsc-ocp-operations-playbook", "overview", "operators"],
            [citation.book_slug for citation in citations],
        )

    def test_learn_mode_route_ingress_difference_has_citations(self) -> None:
        result = _build_route_ingress_learning_answer(
            "Route와 Ingress 차이를 실무자가 이해하기 쉽게 설명해줘"
        )

        self.assertIsNotNone(result)
        assert result is not None
        answer, citations = result
        self.assertIn("학습 관점", answer)
        self.assertIn("차이", answer)
        self.assertIn("구분", answer)
        self.assertGreaterEqual(len(citations), 2)

    def test_learn_mode_cluster_operator_difference_is_not_command_only(self) -> None:
        result = _build_operator_learning_answer(
            "ClusterOperator와 일반 Operator는 어떻게 구분해?"
        )

        self.assertIsNotNone(result)
        assert result is not None
        answer, citations = result
        self.assertIn("학습 관점", answer)
        self.assertIn("구분", answer)
        self.assertIn("구조", answer)
        self.assertNotIn("oc get", answer)
        self.assertGreaterEqual(len(citations), 2)

    def test_ops_mode_operator_first_contact_is_not_doc_locator_only(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="operator-1",
                book_slug="operators",
                section="Operator 문제 해결",
                anchor="operator-troubleshooting",
                source_url="https://docs.redhat.com/operators",
                viewer_path="/docs/ocp/4.20/ko/operators/index.html#operator-troubleshooting",
                excerpt="Operator 상태, 이벤트, 로그를 확인한다.",
                source_collection="core",
            )
        ]

        answer = shape_actionable_ops_answer(
            "답변: 먼저 `Operator 문제 해결` 문서를 여는 것이 맞습니다 [1].",
            query="OpenShift Operator 문제를 처음 만났을 때 무엇부터 봐야 하나?",
            mode="ops",
            citations=citations,
        )

        self.assertIn("상태", answer)
        self.assertIn("확인", answer)
        self.assertIn("검증", answer)
        self.assertNotIn("문서를 여는 것이 맞습니다", answer)

    def test_operator_first_contact_query_does_not_route_to_doc_locator(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="operator-1",
                book_slug="operators",
                section="Operator 문제 해결",
                anchor="operator-troubleshooting",
                source_url="https://docs.redhat.com/operators",
                viewer_path="/docs/ocp/4.20/ko/operators/index.html#operator-troubleshooting",
                excerpt="Operator 상태, 이벤트, 로그를 확인한다.",
                source_collection="core",
            )
        ]

        answer = _build_doc_locator_answer(
            query="OpenShift Operator 문제를 처음 만났을 때 무엇부터 봐야 하나?",
            citations=citations,
        )

        self.assertIsNone(answer)

    def test_command_guide_keeps_grounded_config_block_from_citation(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="community-wildcard-1",
                book_slug="community-ocp-wildcard-routes-troubleshooting-note",
                section="Community OCP wildcard routes troubleshooting note",
                anchor="wildcard",
                source_url="https://gist.githubusercontent.com/example/raw/ocp-wildcard-routes.md",
                viewer_path="/playbooks/customer-packs/dtb-community/index.html#wildcard",
                excerpt=(
                    "If wildcard routes are rejected, edit the default IngressController. "
                    "[CODE]\n"
                    "# oc -n openshift-ingress-operator edit ingresscontroller default\n"
                    "spec:\n"
                    "  routeAdmission:\n"
                    "    wildcardPolicy: WildcardsAllowed\n"
                    "[/CODE]"
                ),
                cli_commands=["oc -n openshift-ingress-operator edit ingresscontroller default"],
                source_authority="community",
                source_requires_review=True,
            )
        ]

        answer = build_grounded_command_guide_answer(
            query="wildcard route가 Rejected일 때 routeAdmission wildcardPolicy를 어디서 확인하고 조치해?",
            citations=citations,
        )

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("oc -n openshift-ingress-operator edit ingresscontroller default", answer)
        self.assertIn("spec.routeAdmission.wildcardPolicy", answer)
        self.assertIn("wildcardPolicy: WildcardsAllowed", answer)

    def test_command_guide_recovers_inline_compressed_config_from_excerpt(self) -> None:
        citations = [
            Citation(
                index=1,
                chunk_id="community-wildcard-1",
                book_slug="community-ocp-wildcard-routes-troubleshooting-note",
                section="Community OCP wildcard routes troubleshooting note",
                anchor="wildcard",
                source_url="https://gist.githubusercontent.com/example/raw/ocp-wildcard-routes.md",
                viewer_path="/playbooks/customer-packs/dtb-community/index.html#wildcard",
                excerpt=(
                    "To enable wildcard route, edit the IngressController. "
                    "[CODE] # oc -n openshift-ingress-operator edit ingresscontroller default "
                    "spec: ... routeAdmission: wildcardPolicy: WildcardsAllowed [/CODE]"
                ),
                cli_commands=["oc -n openshift-ingress-operator edit ingresscontroller default"],
                source_authority="community",
                source_requires_review=True,
            )
        ]

        answer = build_grounded_command_guide_answer(
            query="wildcard route가 Rejected일 때 routeAdmission wildcardPolicy를 어디서 확인하고 조치해?",
            citations=citations,
        )

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("spec.routeAdmission.wildcardPolicy", answer)
        self.assertIn("wildcardPolicy: WildcardsAllowed", answer)


if __name__ == "__main__":
    unittest.main()
