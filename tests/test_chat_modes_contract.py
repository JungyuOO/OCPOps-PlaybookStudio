from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.models import AnswerResult, ContextBundle
from play_book_studio.answering.prompt import build_messages
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


if __name__ == "__main__":
    unittest.main()
