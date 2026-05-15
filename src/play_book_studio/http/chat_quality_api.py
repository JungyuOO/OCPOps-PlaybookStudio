"""Chat quality insight endpoints.

These endpoints analyze chat logs for review and evaluation work. They do not
feed user queries back into retrieval or starter-question generation directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings


def _limit_from_query(query: str, *, default: int = 20, maximum: int = 100) -> int:
    params = parse_qs(query or "")
    raw = params.get("limit", [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def build_chat_quality_query_insights(root_dir: Path, query: str = "") -> dict[str, Any]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return {
            "schema": "chat_quality_query_insights_v1",
            "source": "postgres.chat_messages",
            "ready": False,
            "reason": "database_url_unconfigured",
            "insights": [],
        }

    try:
        import psycopg

        from play_book_studio.db.chat_repository import list_chat_quality_question_candidates

        with psycopg.connect(database_url) as connection:
            rows = list_chat_quality_question_candidates(
                connection,
                limit=_limit_from_query(query),
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "chat_quality_query_insights_v1",
            "source": "postgres.chat_messages",
            "ready": False,
            "reason": type(exc).__name__,
            "insights": [],
        }

    insights: list[dict[str, Any]] = []
    for row in rows:
        response_kind = str(row.get("response_kind") or "")
        if response_kind == "rag":
            action = "review_answer_quality"
        elif response_kind == "clarification":
            action = "review_query_understanding_or_retrieval"
        elif response_kind == "no_answer":
            action = "review_source_coverage_or_chunking"
        else:
            action = "review_response_route"
        insights.append(
            {
                "query": str(row.get("query") or ""),
                "response_kind": response_kind,
                "rewritten_query": str(row.get("rewritten_query") or ""),
                "occurrence_count": int(row.get("occurrence_count") or 0),
                "last_seen_at": str(row.get("last_seen_at") or ""),
                "recommended_action": action,
            }
        )

    return {
        "schema": "chat_quality_query_insights_v1",
        "source": "postgres.chat_messages",
        "ready": True,
        "usage": "analysis_only_not_rag_input",
        "insights": insights,
    }


def build_corpus_handoff_report_response(root_dir: Path, query: str = "", *, owner_user_id: str = "") -> dict[str, Any]:
    del query
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return {
            "schema": "corpus_handoff_report_v1",
            "ready": False,
            "reason": "database_url_unconfigured",
            "scopes": {},
            "golden_questions": [],
            "known_blockers": [],
        }

    try:
        import psycopg

        from play_book_studio.db.corpus_handoff import build_corpus_handoff_report

        with psycopg.connect(database_url) as connection:
            report = build_corpus_handoff_report(connection, owner_user_id=owner_user_id)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "corpus_handoff_report_v1",
            "ready": False,
            "reason": type(exc).__name__,
            "scopes": {},
            "golden_questions": [],
            "known_blockers": [{"kind": "report_error", "summary": str(exc)}],
        }
    return {"ready": True, **report}


def handle_chat_quality_query_insights(handler: Any, query: str, *, root_dir: Path) -> None:
    handler._send_json(build_chat_quality_query_insights(root_dir, query))


def handle_corpus_handoff_report(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    handler._send_json(build_corpus_handoff_report_response(root_dir, query, owner_user_id=owner_user_id))


__all__ = [
    "build_chat_quality_query_insights",
    "build_corpus_handoff_report_response",
    "handle_chat_quality_query_insights",
    "handle_corpus_handoff_report",
]
