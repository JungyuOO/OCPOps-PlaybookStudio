"""Chat answer feedback endpoints for corpus/retrieval remediation."""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.answering.llm import LLMClient
from play_book_studio.config.settings import load_settings


ISSUE_LABELS = {
    "wrong_answer": "잘못된 답변",
    "missing_grounding": "근거 없음",
    "wrong_citation": "엉뚱한 문서 참조",
    "hallucination": "할루시네이션",
    "version_mismatch": "버전/환경 불일치",
    "incomplete_answer": "답변 부족",
}


def _limit_from_query(query: str, *, default: int = 50, maximum: int = 200) -> int:
    params = parse_qs(query or "")
    raw = params.get("limit", [str(default)])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _status_from_query(query: str) -> str:
    params = parse_qs(query or "")
    return str(params.get("status", [""])[0] or "").strip()


def _json_object_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.removeprefix("json").strip()
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fallback_remediation(issue: dict[str, Any]) -> dict[str, Any]:
    gap_type = str(issue.get("gap_type") or "unclassified")
    cited = list(issue.get("cited_chunk_ids") or [])
    if gap_type == "corpus_gap":
        corpus_action = "질문에 답할 chunk/문서가 코퍼스에 있는지 확인하고 없으면 source request 또는 문서 업로드로 보강"
        j_action = "no-answer/low-confidence 처리와 source request 생성 흐름 확인"
    elif gap_type == "retrieval_gap":
        corpus_action = "관련 chunk의 topic/object/command/error metadata coverage와 answerable_questions 보강"
        j_action = "query understanding, metadata boost, reranker top-k trace 확인"
    elif gap_type == "citation_gap":
        corpus_action = "citation 가능한 chunk의 source_anchor, section_path, evidence 연결 확인"
        j_action = "selected citation과 최종 답변 citation 매핑 로직 확인"
    else:
        corpus_action = "선택된 chunk가 질문을 충분히 답하는지 Reader에서 원문 대조"
        j_action = "선택 chunk를 사용한 answer synthesis와 hallucination guard 확인"
    return {
        "schema": "chat_feedback_remediation_draft_v1",
        "source": "deterministic_fallback",
        "root_cause_hypothesis": f"{gap_type} 가능성이 큽니다.",
        "corpus_actions": [corpus_action],
        "chatbot_actions": [j_action],
        "recommended_golden_question": {
            "question": str(issue.get("user_query") or ""),
            "expected_chunk_ids": cited,
            "expected_answer_shape": "근거 citation을 포함하고 환경/버전 전제를 분리해 답변",
        },
        "verification": [
            "동일 질문으로 retrieval selected_chunk_ids 확인",
            "Reader에서 expected chunk 원문 확인",
            "답변 citation precision 재검증",
        ],
        "auto_apply": False,
    }


def _draft_remediation_with_qwen(settings, issue: dict[str, Any]) -> dict[str, Any]:
    prompt = {
        "task": "Analyze a bad RAG/chatbot answer. Do not fix corpus automatically. Return JSON only.",
        "required_schema": {
            "root_cause_hypothesis": "short Korean summary",
            "corpus_actions": ["what S/data team should inspect or enrich"],
            "chatbot_actions": ["what J/chatbot team should inspect"],
            "recommended_golden_question": {
                "question": "original or refined user question",
                "expected_chunk_ids": ["chunk ids if available"],
                "expected_answer_shape": "short expected answer form",
            },
            "verification": ["concrete checks"],
            "auto_apply": False,
        },
        "issue": {
            "issue_type": issue.get("issue_type"),
            "gap_type": issue.get("gap_type"),
            "user_query": issue.get("user_query"),
            "assistant_answer": issue.get("assistant_answer"),
            "user_comment": issue.get("user_comment"),
            "expected_answer": issue.get("expected_answer"),
            "cited_chunk_ids": issue.get("cited_chunk_ids"),
            "citations": issue.get("citations"),
            "retrieval_trace": issue.get("retrieval_trace"),
            "pipeline_trace": issue.get("pipeline_trace"),
        },
    }
    client = LLMClient(settings)
    content = client.generate(
        [
            {
                "role": "system",
                "content": "너는 RAG 품질 이슈를 corpus gap, retrieval gap, answer gap, citation gap으로 분류하는 품질 분석가다. JSON만 출력한다.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        max_tokens=1200,
    )
    parsed = _json_object_from_text(content)
    if not parsed:
        parsed = _fallback_remediation(issue)
        parsed["source"] = "qwen_parse_failed_fallback"
        parsed["raw_qwen_output"] = content[:2000]
        return parsed
    parsed["schema"] = "chat_feedback_remediation_draft_v1"
    parsed["source"] = "qwen"
    parsed["auto_apply"] = False
    return parsed


def build_chat_feedback_save_response(
    root_dir: Path,
    payload: dict[str, Any],
    *,
    owner_user_id: str = "",
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    if not settings.database_url.strip():
        raise ValueError("DATABASE_URL is required for chat feedback")
    import psycopg

    citations = [item for item in (payload.get("citations") or []) if isinstance(item, dict)]
    cited_chunk_ids = [
        str(item.get("chunk_id") or "").strip()
        for item in citations
        if str(item.get("chunk_id") or "").strip()
    ]
    cited_asset_ids = [
        str(asset_id or "").strip()
        for item in citations
        for asset_id in (item.get("asset_ids") or [item.get("asset_id")])
        if str(asset_id or "").strip()
    ]
    from play_book_studio.db.chat_repository import save_chat_feedback_issue

    with psycopg.connect(settings.database_url) as connection:
        saved = save_chat_feedback_issue(
            connection,
            owner_user_id=owner_user_id,
            user_id=str(payload.get("user_id") or ""),
            client_session_id=str(payload.get("session_id") or payload.get("client_session_id") or ""),
            user_message_id=str(payload.get("user_message_id") or ""),
            assistant_message_id=str(payload.get("assistant_message_id") or ""),
            issue_type=str(payload.get("issue_type") or "wrong_answer"),
            severity=str(payload.get("severity") or "medium"),
            user_query=str(payload.get("user_query") or ""),
            assistant_answer=str(payload.get("assistant_answer") or ""),
            user_comment=str(payload.get("user_comment") or ""),
            expected_answer=str(payload.get("expected_answer") or ""),
            active_repository_id=str(payload.get("active_repository_id") or ""),
            active_document_id=str(payload.get("active_document_id") or ""),
            cited_chunk_ids=cited_chunk_ids,
            cited_asset_ids=cited_asset_ids,
            citations=citations,
            retrieval_trace=payload.get("retrieval_trace") if isinstance(payload.get("retrieval_trace"), dict) else {},
            pipeline_trace=payload.get("pipeline_trace") if isinstance(payload.get("pipeline_trace"), dict) else {},
            metadata={
                "source": "chat_feedback_api",
                "issue_label": ISSUE_LABELS.get(str(payload.get("issue_type") or ""), "잘못된 답변"),
                "response_kind": str(payload.get("response_kind") or ""),
                "route_kind": str(payload.get("route_kind") or ""),
            },
        )
    return {"saved": True, **saved}


def build_chat_feedback_queue_response(root_dir: Path, query: str, *, owner_user_id: str = "") -> dict[str, Any]:
    settings = load_settings(root_dir)
    if not settings.database_url.strip():
        return {"schema": "chat_feedback_queue_v1", "ready": False, "reason": "database_url_unconfigured", "issues": []}
    import psycopg

    from play_book_studio.db.chat_repository import list_chat_feedback_issues

    with psycopg.connect(settings.database_url) as connection:
        issues = list_chat_feedback_issues(
            connection,
            owner_user_id=owner_user_id,
            status=_status_from_query(query),
            limit=_limit_from_query(query),
        )
    return {
        "schema": "chat_feedback_queue_v1",
        "ready": True,
        "count": len(issues),
        "issues": issues,
    }


def build_chat_feedback_draft_response(root_dir: Path, feedback_id: str, *, owner_user_id: str = "") -> dict[str, Any]:
    settings = load_settings(root_dir)
    if not settings.database_url.strip():
        raise ValueError("DATABASE_URL is required for chat feedback remediation")
    import psycopg

    from play_book_studio.db.chat_repository import list_chat_feedback_issues, update_chat_feedback_remediation

    with psycopg.connect(settings.database_url) as connection:
        issues = [
            issue
            for issue in list_chat_feedback_issues(connection, owner_user_id=owner_user_id, limit=200)
            if issue["feedback_id"] == feedback_id
        ]
        if not issues:
            raise ValueError("feedback issue not found")
        issue = issues[0]
        try:
            draft = _draft_remediation_with_qwen(settings, issue)
        except Exception as exc:  # noqa: BLE001
            draft = _fallback_remediation(issue)
            draft["source"] = "qwen_unavailable_fallback"
            draft["error"] = str(exc)
        updated = update_chat_feedback_remediation(
            connection,
            feedback_id=feedback_id,
            qwen_draft=draft,
            owner_user_id=owner_user_id,
        )
        connection.commit()
    return {"drafted": True, **updated}


def handle_chat_feedback_save(handler: Any, payload: dict[str, Any], *, root_dir: Path, owner_user_id: str = "") -> None:
    try:
        handler._send_json(build_chat_feedback_save_response(root_dir, payload, owner_user_id=owner_user_id))
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"chat feedback save failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def handle_chat_feedback_queue(handler: Any, query: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    handler._send_json(build_chat_feedback_queue_response(root_dir, query, owner_user_id=owner_user_id))


def handle_chat_feedback_draft(handler: Any, feedback_id: str, *, root_dir: Path, owner_user_id: str = "") -> None:
    try:
        handler._send_json(build_chat_feedback_draft_response(root_dir, feedback_id, owner_user_id=owner_user_id))
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"chat feedback remediation draft failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


__all__ = [
    "build_chat_feedback_draft_response",
    "build_chat_feedback_queue_response",
    "build_chat_feedback_save_response",
    "handle_chat_feedback_draft",
    "handle_chat_feedback_queue",
    "handle_chat_feedback_save",
]
