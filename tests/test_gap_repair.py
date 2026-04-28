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

from play_book_studio.answering.models import AnswerResult
from play_book_studio.app.gap_repair import build_gap_repair_plan
from play_book_studio.app.server_support import _build_chat_payload
from play_book_studio.app.sessions import ChatSession
from play_book_studio.retrieval.models import SessionContext


class GapRepairTests(unittest.TestCase):
    def test_gap_repair_plan_prefers_official_materialization_when_candidate_exists(self) -> None:
        fake_candidate = {
            "book_slug": "networking",
            "title": "Networking",
            "source_options": [
                {"key": "official_homepage", "availability": "available"},
                {"key": "official_repo", "availability": "available"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "play_book_studio.app.server_routes_ops._search_official_source_candidates",
                return_value=[fake_candidate],
            ):
                plan = build_gap_repair_plan(Path(tmp), query="Route wildcard TLS troubleshooting")

        self.assertEqual("ready_to_materialize_official", plan["state"])
        self.assertEqual("official_source_candidate", plan["official_candidates"][0]["candidate_kind"])
        self.assertEqual("/api/repositories/official-materialize", plan["official_candidates"][0]["materialize_endpoint"])
        self.assertIn("same_chat_query_rerun", plan["closed_loop_acceptance"])

    def test_gap_repair_plan_marks_community_selection_when_no_official_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "play_book_studio.app.server_routes_ops._search_official_source_candidates",
                return_value=[],
            ):
                plan = build_gap_repair_plan(Path(tmp), query="custom operator incident workaround")

        self.assertEqual("needs_community_source_selection", plan["state"])
        self.assertEqual("community", plan["community_search"]["authority_after_selection"]["source_authority"])
        self.assertTrue(plan["community_search"]["authority_after_selection"]["source_requires_review"])
        community_route = next(
            route for route in plan["materialization_routes"] if route["authority"] == "community"
        )
        self.assertIn("uri", community_route["required_fields"])
        self.assertEqual(["source_url"], community_route["accepted_aliases"]["uri"])

    def test_no_answer_payload_includes_gap_repair_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "play_book_studio.app.server_routes_ops._search_official_source_candidates",
                return_value=[],
            ):
                payload = _build_chat_payload(
                    root_dir=Path(tmp),
                    session=ChatSession(
                        session_id="session-1",
                        mode="ops",
                        context=SessionContext(mode="ops", ocp_version="4.20"),
                    ),
                    result=AnswerResult(
                        query="unknown router certificate edge case",
                        mode="ops",
                        answer="답변할 근거가 없습니다.",
                        rewritten_query="unknown router certificate edge case",
                        citations=[],
                        response_kind="no_answer",
                    ),
                )

        acquisition = payload["acquisition"]
        self.assertEqual("repository_search", acquisition["kind"])
        self.assertEqual("unknown router certificate edge case", acquisition["repository_query"])
        self.assertEqual("needs_community_source_selection", acquisition["repair_plan"]["state"])
        self.assertIn("selected_source_materialized_to_library", acquisition["repair_plan"]["closed_loop_acceptance"])


if __name__ == "__main__":
    unittest.main()
