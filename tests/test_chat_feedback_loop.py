from play_book_studio.db.chat_repository import _classify_gap_type
from play_book_studio.db.chat_repository import update_chat_feedback_remediation
from play_book_studio.http.chat_feedback_api import _fallback_remediation


def test_feedback_gap_classification_uses_citations_and_issue_type() -> None:
    assert _classify_gap_type(
        issue_type="hallucination",
        cited_chunk_ids=["chunk-1"],
        retrieval_trace={},
        pipeline_trace={},
    ) == "answer_gap"

    assert _classify_gap_type(
        issue_type="missing_grounding",
        cited_chunk_ids=[],
        retrieval_trace={},
        pipeline_trace={},
    ) == "retrieval_gap"

    assert _classify_gap_type(
        issue_type="version_mismatch",
        cited_chunk_ids=[],
        retrieval_trace={},
        pipeline_trace={},
    ) == "corpus_gap"

    assert _classify_gap_type(
        issue_type="wrong_answer",
        cited_chunk_ids=[],
        retrieval_trace={"hybrid": [{"chunk_id": "chunk-1"}]},
        pipeline_trace={},
    ) == "retrieval_gap"


def test_feedback_remediation_draft_is_never_auto_applied() -> None:
    draft = _fallback_remediation(
        {
            "gap_type": "retrieval_gap",
            "user_query": "Route가 안 열릴 때 뭐부터 봐야 돼?",
            "cited_chunk_ids": ["chunk-1"],
        }
    )

    assert draft["auto_apply"] is False
    assert draft["recommended_golden_question"]["expected_chunk_ids"] == ["chunk-1"]
    assert draft["corpus_actions"]
    assert draft["chatbot_actions"]


def test_feedback_remediation_update_is_owner_scoped() -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, sql, params) -> None:
            self.sql = sql
            self.params = params

        def fetchone(self):
            from datetime import datetime, timezone

            return ("feedback-1", "drafted", {"auto_apply": False}, datetime(2026, 5, 15, tzinfo=timezone.utc))

    class FakeConnection:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

    connection = FakeConnection()

    result = update_chat_feedback_remediation(
        connection,
        feedback_id="11111111-1111-1111-1111-111111111111",
        qwen_draft={"auto_apply": False},
        owner_user_id="owner-a",
    )

    assert result["status"] == "drafted"
    assert "AND owner_user_id = %s" in connection.cursor_obj.sql
    assert connection.cursor_obj.params[-1] == "owner-a"
