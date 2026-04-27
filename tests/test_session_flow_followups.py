from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.app.session_flow import suggest_follow_up_items, suggest_follow_up_questions
from play_book_studio.app.sessions import ChatSession
from play_book_studio.retrieval.models import SessionContext


def _citation(
    index: int,
    *,
    book_slug: str,
    section: str,
    source_collection: str = "core",
    viewer_path: str = "/docs/ocp/4.20/ko/builds_using_buildconfig/index.html",
) -> Citation:
    return Citation(
        index=index,
        chunk_id=f"chunk-{index}",
        book_slug=book_slug,
        section=section,
        anchor="overview",
        source_url="https://example.com",
        viewer_path=viewer_path,
        excerpt="grounded excerpt",
        source_collection=source_collection,
    )


class SessionFlowFollowupTests(unittest.TestCase):
    def test_blended_customer_buildconfig_followups_are_structured_and_specific(self) -> None:
        session = ChatSession(
            session_id="followup-blended",
            context=SessionContext(mode="ops", ocp_version="4.20"),
        )
        result = AnswerResult(
            query="고객 CI/CD 운영 자료와 OCP 4.20 BuildConfig 공식문서를 같이 참고해서 점검 순서를 알려줘",
            mode="ops",
            answer="답변: 고객 운영북과 공식 문서를 함께 봅니다 [1][2].",
            rewritten_query="고객 CI/CD BuildConfig 점검",
            citations=[
                _citation(
                    1,
                    book_slug="customer-master-kmsc-ocp-operations-playbook",
                    section="CI/CD 운영 구조",
                    source_collection="uploaded",
                    viewer_path="/playbooks/customer-packs/customer-master/index.html",
                ),
                _citation(
                    2,
                    book_slug="builds_using_buildconfig",
                    section="BuildConfig를 사용한 빌드",
                ),
            ],
            cited_indices=[1, 2],
        )

        items = suggest_follow_up_items(session=session, result=result)
        queries = [item["query"] for item in items]
        dimensions = {item["dimension"] for item in items}

        self.assertEqual(["next_action", "verify", "branch"], [item["dimension"] for item in items])
        self.assertIn("고객 CI/CD 운영 구조", queries[0])
        self.assertIn("BuildConfig 공식문서", queries[0])
        self.assertNotIn("이 문서 기준", " ".join(queries))
        self.assertEqual({"next_action", "verify", "branch"}, dimensions)

    def test_legacy_suggested_queries_follow_structured_items(self) -> None:
        session = ChatSession(
            session_id="followup-official",
            context=SessionContext(mode="ops", ocp_version="4.20"),
        )
        result = AnswerResult(
            query="OCP 4.20에서 BuildConfig 운영자가 먼저 확인할 점과 예시 명령을 알려줘",
            mode="ops",
            answer="답변: BuildConfig 상태를 확인합니다 [1].",
            rewritten_query="BuildConfig 확인",
            citations=[
                _citation(
                    1,
                    book_slug="builds_using_buildconfig",
                    section="OpenShift Container Platform 파이프라인 이해",
                )
            ],
            cited_indices=[1],
        )

        items = suggest_follow_up_items(session=session, result=result)
        self.assertEqual([item["query"] for item in items], suggest_follow_up_questions(session=session, result=result))
        self.assertEqual("BuildConfig 상태 확인 명령만 모아서 다시 보여줘", items[0]["query"])
        self.assertEqual("verify", items[1]["dimension"])
        self.assertEqual("branch", items[2]["dimension"])

    def test_buildconfig_followup_chain_keeps_verification_lane(self) -> None:
        session = ChatSession(
            session_id="followup-chain",
            context=SessionContext(mode="ops", ocp_version="4.20"),
        )
        result = AnswerResult(
            query="BuildConfig 적용 후 build와 pod 상태를 검증하는 순서를 알려줘",
            mode="ops",
            answer="답변: BuildConfig 상태를 검증합니다 [1].",
            rewritten_query="BuildConfig 검증 순서",
            citations=[
                _citation(
                    1,
                    book_slug="builds_using_buildconfig",
                    section="Editing a BuildConfig",
                )
            ],
            cited_indices=[1],
        )

        items = suggest_follow_up_items(session=session, result=result)

        self.assertEqual(["next_action", "verify", "branch"], [item["dimension"] for item in items])
        self.assertNotIn(result.query, [item["query"] for item in items])
        self.assertIn("검증 증거", items[1]["query"])
        self.assertIn("oc describe bc", items[1]["query"])
        self.assertIn("oc get builds", items[1]["query"])

    def test_buildconfig_verification_evidence_followup_keeps_verification_lane(self) -> None:
        session = ChatSession(
            session_id="followup-evidence-chain",
            context=SessionContext(mode="ops", ocp_version="4.20"),
        )
        result = AnswerResult(
            query="BuildConfig 적용 후 oc describe bc와 oc get builds 결과를 검증 증거로 어떻게 남겨야 해?",
            mode="ops",
            answer="답변: BuildConfig 검증 증거를 확인합니다 [1].",
            rewritten_query="BuildConfig 검증 증거",
            citations=[
                _citation(
                    1,
                    book_slug="builds_using_buildconfig",
                    section="웹훅 URL 표시",
                )
            ],
            cited_indices=[1],
        )

        items = suggest_follow_up_items(session=session, result=result)

        self.assertEqual({"next_action", "verify", "branch"}, {item["dimension"] for item in items})
        self.assertNotIn(result.query, [item["query"] for item in items])
        self.assertIn("build 이벤트와 로그", " ".join(item["query"] for item in items))


if __name__ == "__main__":
    unittest.main()
