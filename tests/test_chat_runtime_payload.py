from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.models import AnswerResult
from play_book_studio.app.server_support import _build_chat_payload
from play_book_studio.app.sessions import ChatSession
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.models import SessionContext


class _FakeLlmClient:
    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
        }


class _FakeAnswerer:
    def __init__(self, root: Path) -> None:
        self.settings = load_settings(root)
        self.llm_client = _FakeLlmClient()
        self.retriever = SimpleNamespace(reranker=None)


class ChatRuntimePayloadTests(unittest.TestCase):
    def test_build_chat_payload_includes_runtime_compact_graph_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            answerer = _FakeAnswerer(root)
            session = ChatSession(
                session_id="session-runtime",
                context=SessionContext(mode="chat", ocp_version=answerer.settings.ocp_version),
            )
            result = AnswerResult(
                query="runtime probe",
                mode="chat",
                answer="ok",
                rewritten_query="runtime probe",
                citations=[],
                response_kind="rag",
            )

            payload = _build_chat_payload(
                root_dir=root,
                answerer=answerer,
                session=session,
                result=result,
            )

            runtime = payload.get("runtime")
            self.assertIsInstance(runtime, dict)
            self.assertIsInstance(runtime.get("graph_compact_artifact"), dict)
            self.assertTrue(str(runtime.get("config_fingerprint") or "").strip())
            self.assertIn("suggested_followups", payload)
            self.assertEqual([], payload["suggested_followups"])


if __name__ == "__main__":
    unittest.main()
