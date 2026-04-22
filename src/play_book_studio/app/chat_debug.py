"""채팅 turn 디버그/로그/snapshot 보조 로직."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.answering.models import AnswerResult
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.models import SessionContext

from .presenters import _build_citation_presentation_context, _build_health_payload, _serialize_citation
from .sessions import ChatSession, Turn, serialize_session_snapshot, serialize_turn


def session_display_name(session: ChatSession) -> str:
    short_id = (session.session_id or "").strip()[:8] or "unknown"
    return f"세션 {short_id}"


def build_session_debug_payload(session: ChatSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "mode": session.mode,
        "context": session.context.to_dict(),
        "revision": session.revision,
        "updated_at": session.updated_at,
        "history_size": len(session.history),
        "last_query": session.last_query,
        "history": [serialize_turn(turn) for turn in session.history],
    }


def compact_stage_hits(items: Any, *, score_key: str = "score", limit: int = 3) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return compact
    for row in items[:limit]:
        if not isinstance(row, dict):
            continue
        payload: dict[str, Any] = {
            "book_slug": row.get("book_slug", ""),
            "section": row.get("section", ""),
        }
        if score_key in row:
            payload["score"] = row.get(score_key)
        elif "fused_score" in row:
            payload["score"] = row.get("fused_score")
        compact.append(payload)
    return compact


def build_turn_stages(result: AnswerResult) -> list[dict[str, Any]]:
    retrieval_trace = result.retrieval_trace or {}
    pipeline_trace = result.pipeline_trace or {}
    metrics = retrieval_trace.get("metrics") or {}
    reranker = retrieval_trace.get("reranker") or {}
    selection = (pipeline_trace.get("selection") or {}).get("selected_hits") or []
    llm_runtime = pipeline_trace.get("llm") or {}
    hybrid_metrics = metrics.get("hybrid") or {}

    hybrid_value = (
        f"후보 {hybrid_metrics.get('count', 0)}개"
        if hybrid_metrics
        else "기록 없음"
    )
    reranker_value = "미적용"
    if reranker.get("enabled"):
        reranker_value = "적용됨" if reranker.get("applied") else "활성 상태지만 미적용"

    return [
        {
            "step": "user_input",
            "label": "사용자 입력",
            "value": result.query,
        },
        {
            "step": "rewritten_query",
            "label": "쿼리 재생성",
            "value": result.rewritten_query or result.query,
        },
        {
            "step": "hybrid_search",
            "label": "하이브리드 서치",
            "value": hybrid_value,
            "top_hits": compact_stage_hits(hybrid_metrics.get("top_hits")),
        },
        {
            "step": "query_reranking",
            "label": "쿼리 리랭킹",
            "value": reranker_value,
            "enabled": bool(reranker.get("enabled", False)),
            "applied": bool(reranker.get("applied", False)),
            "model": reranker.get("model", ""),
            "top_n": reranker.get("top_n", 0),
        },
        {
            "step": "citation_selection",
            "label": "근거 선택",
            "value": f"최종 {len(result.citations)}개",
            "selected": compact_stage_hits(selection, score_key="fused_score"),
        },
        {
            "step": "answer_generation",
            "label": "답변 생성",
            "value": result.response_kind or "rag",
            "provider": llm_runtime.get("last_provider") or llm_runtime.get("preferred_provider") or "",
            "fallback_used": bool(llm_runtime.get("last_fallback_used", False)),
        },
    ]


def build_turn_diagnosis(result: AnswerResult) -> dict[str, Any]:
    retrieval_trace = result.retrieval_trace or {}
    pipeline_trace = result.pipeline_trace or {}
    metrics = retrieval_trace.get("metrics") or {}
    reranker = retrieval_trace.get("reranker") or {}
    llm_runtime = pipeline_trace.get("llm") or {}

    severity = "ok"
    summary = "정상: 답변과 근거가 함께 생성됐습니다."
    signals: list[str] = []

    if result.response_kind in {"clarification", "no_answer", "smalltalk"}:
        severity = "watch"
        summary = f"주의: 현재 응답 종류는 `{result.response_kind}` 입니다."
        signals.append(f"response_kind={result.response_kind}")

    if not result.citations:
        severity = "risk"
        summary = "위험: 최종 citation이 없어 근거 연결이 비어 있습니다."
        signals.append("citation 없음")
    elif len(result.citations) == 1:
        if severity == "ok":
            severity = "watch"
            summary = "주의: 최종 citation이 1개뿐이라 근거 다양성이 낮습니다."
        signals.append("citation 1개")

    warnings = [str(item) for item in (result.warnings or []) if str(item).strip()]
    if warnings:
        if severity == "ok":
            severity = "watch"
            summary = "주의: 파이프라인 warning이 남았습니다."
        signals.extend(warnings[:4])

    hybrid = metrics.get("hybrid") or {}
    hybrid_count = int(hybrid.get("count", 0) or 0)
    if hybrid_count == 0:
        severity = "risk"
        summary = "위험: 하이브리드 검색 후보가 없어 retrieval 단계부터 비어 있습니다."
        signals.append("hybrid 후보 없음")
    elif hybrid_count < 3:
        if severity == "ok":
            severity = "watch"
            summary = "주의: 하이브리드 검색 후보가 적어 검색 폭이 좁습니다."
        signals.append(f"hybrid 후보 {hybrid_count}개")

    if bool(reranker.get("enabled", False)) and not bool(reranker.get("applied", False)):
        if severity == "ok":
            severity = "watch"
            summary = "주의: reranker는 켜져 있지만 이번 턴에는 적용되지 않았습니다."
        signals.append("reranker 미적용")

    if bool(llm_runtime.get("last_fallback_used", False)):
        if severity != "risk":
            severity = "watch"
            summary = "주의: LLM fallback이 사용되어 기준 런타임과 다를 수 있습니다."
        signals.append("LLM fallback 사용")

    if not signals:
        signals.append("문제 신호 없음")

    return {
        "severity": severity,
        "summary": summary,
        "signals": signals[:6],
    }


def _format_markdown_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items if str(item).strip()]


def _format_turn_markdown(payload: dict[str, Any], diagnosis: dict[str, Any]) -> str:
    envelope = payload.get("audit_envelope") or {}
    citations = payload.get("citations") or []
    warnings = [str(item) for item in (payload.get("warnings") or []) if str(item).strip()]
    suggested_queries = [str(item) for item in (payload.get("suggested_queries") or []) if str(item).strip()]
    runtime = payload.get("runtime") or {}
    retrieval_trace = payload.get("retrieval_trace") or {}
    pipeline_trace = payload.get("pipeline_trace") or {}
    timings = (pipeline_trace.get("timings_ms") or {})
    selection = ((pipeline_trace.get("selection") or {}).get("selected_hits") or [])
    llm_runtime = pipeline_trace.get("llm") or {}
    metrics = (retrieval_trace.get("metrics") or {})
    hybrid = metrics.get("hybrid") or {}
    reranker = retrieval_trace.get("reranker") or {}

    lines = [
        f"## {envelope.get('created_at') or payload.get('timestamp') or ''} | {payload.get('session_id') or ''} | turn {envelope.get('turn_index') or ''}",
        "",
        f"- query: {payload.get('query') or ''}",
        f"- rewritten_query: {payload.get('rewritten_query') or payload.get('query') or ''}",
        f"- response_kind: {payload.get('response_kind') or ''}",
        f"- diagnosis: {diagnosis.get('severity') or 'ok'}",
        f"- diagnosis_summary: {diagnosis.get('summary') or ''}",
        f"- total_ms: {timings.get('total', '')}",
        f"- retrieval_candidates: {hybrid.get('count', 0) if isinstance(hybrid, dict) else 0}",
        f"- reranker_applied: {bool(reranker.get('applied', False))}",
        f"- llm_provider: {llm_runtime.get('last_provider') or llm_runtime.get('preferred_provider') or 'skipped'}",
        f"- llm_fallback_used: {bool(llm_runtime.get('last_fallback_used', False))}",
        f"- citation_count: {len(citations)}",
        "",
        "### Answer",
        "",
        payload.get("answer") or "",
        "",
        "### Audit",
        "",
    ]

    audit_lines = [
        f"record_id: {envelope.get('record_id') or ''}",
        f"turn_id: {envelope.get('turn_id') or ''}",
        f"parent_turn_id: {envelope.get('parent_turn_id') or ''}",
        f"snapshot_path: {envelope.get('snapshot_path') or ''}",
        f"recent_session_path: {envelope.get('recent_session_path') or ''}",
        f"runtime_llm_endpoint: {runtime.get('llm_endpoint') or ''}",
        f"runtime_embedding_base_url: {runtime.get('embedding_base_url') or ''}",
        f"runtime_qdrant_collection: {runtime.get('qdrant_collection') or ''}",
    ]
    lines.extend(_format_markdown_list(audit_lines))

    if selection:
        lines.extend(["", "### Selected Evidence", ""])
        lines.extend(
            _format_markdown_list(
                [
                    f"{row.get('book_slug') or ''} :: {row.get('section') or ''} :: score={row.get('fused_score', row.get('score', ''))}"
                    for row in selection
                    if isinstance(row, dict)
                ]
            )
        )

    if citations:
        lines.extend(["", "### Citations", ""])
        lines.extend(
            _format_markdown_list(
                [
                    f"[{index}] {citation.get('book_slug') or ''} :: {citation.get('section') or ''} :: {citation.get('source_label') or citation.get('book_title') or ''}"
                    for index, citation in enumerate(citations, start=1)
                    if isinstance(citation, dict)
                ]
            )
        )

    if warnings:
        lines.extend(["", "### Warnings", ""])
        lines.extend(_format_markdown_list(warnings))

    diagnosis_signals = [str(item) for item in (diagnosis.get("signals") or []) if str(item).strip()]
    if diagnosis_signals:
        lines.extend(["", "### Signals", ""])
        lines.extend(_format_markdown_list(diagnosis_signals))

    if suggested_queries:
        lines.extend(["", "### Suggested Queries", ""])
        lines.extend(_format_markdown_list(suggested_queries))

    lines.extend(["", "---", ""])
    return "\n".join(lines)


def append_chat_turn_log(
    root_dir: Path,
    *,
    answerer: ChatAnswerer | None = None,
    session: ChatSession,
    query: str,
    result: AnswerResult,
    context_before: SessionContext | None,
    context_after: SessionContext | None,
    suggested_queries: list[str] | None = None,
    related_links: list[dict[str, Any]] | None = None,
    related_sections: list[dict[str, Any]] | None = None,
) -> Path:
    settings = load_settings(root_dir)
    target = settings.chat_log_path
    markdown_target = settings.chat_markdown_log_path
    target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    turn_index = len(session.history)
    latest_turn = session.history[-1] if session.history else None
    diagnosis = build_turn_diagnosis(result)
    presentation_context = _build_citation_presentation_context(root_dir)
    payload = {
        "record_kind": "chat_turn_audit",
        "audit_envelope": {
            "record_id": uuid4().hex,
            "session_id": session.session_id,
            "session_revision": session.revision,
            "turn_index": turn_index,
            "turn_id": getattr(latest_turn, "turn_id", "") or "",
            "parent_turn_id": getattr(latest_turn, "parent_turn_id", "") or "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "snapshot_path": str(settings.session_snapshot_path(session.session_id)),
            "recent_session_path": str(settings.recent_chat_session_path),
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session.session_id,
        "mode": session.mode,
        "query": query,
        "rewritten_query": result.rewritten_query,
        "answer": result.answer,
        "response_kind": result.response_kind,
        "warnings": list(result.warnings),
        "cited_indices": list(result.cited_indices),
        "citations": [
            _serialize_citation(
                root_dir,
                citation,
                presentation_context=presentation_context,
            )
            for citation in result.citations
        ],
        "context_before": context_before.to_dict() if context_before else {},
        "context_after": context_after.to_dict() if context_after else {},
        "history_size": len(session.history),
        "history": [serialize_turn(turn) for turn in session.history],
        "retrieval_trace": dict(result.retrieval_trace),
        "pipeline_trace": dict(result.pipeline_trace),
        "suggested_queries": list(suggested_queries or []),
        "related_links": list(related_links or []),
        "related_sections": list(related_sections or []),
    }
    if answerer is not None:
        payload["runtime"] = _build_health_payload(answerer)["runtime"]
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    with markdown_target.open("a", encoding="utf-8") as handle:
        handle.write(_format_turn_markdown(payload, diagnosis))
    return target


def append_unanswered_question_log(
    root_dir: Path,
    *,
    session: ChatSession,
    query: str,
    result: AnswerResult,
) -> Path:
    settings = load_settings(root_dir)
    target = settings.unanswered_questions_path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "record_kind": "unanswered_question",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session.session_id,
        "query": query,
        "rewritten_query": result.rewritten_query,
        "response_kind": result.response_kind,
        "warnings": list(result.warnings),
        "retrieval_trace": dict(result.retrieval_trace),
        "pipeline_trace": dict(result.pipeline_trace),
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def write_recent_chat_session_snapshot(
    root_dir: Path,
    *,
    session: ChatSession,
) -> Path:
    settings = load_settings(root_dir)
    target = settings.recent_chat_session_path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_session_snapshot(session)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    target.write_text(serialized, encoding="utf-8")
    snapshot_path = settings.session_snapshot_path(session.session_id)
    for snapshot_alias_path in settings.runtime_sessions_dir.glob(
        f"{settings.session_snapshot_stem(session.session_id)}-*.json"
    ):
        snapshot_alias_path.unlink(missing_ok=True)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(serialized, encoding="utf-8")
    return target


__all__ = [
    "append_chat_turn_log",
    "append_unanswered_question_log",
    "build_session_debug_payload",
    "build_turn_diagnosis",
    "build_turn_stages",
    "serialize_turn",
    "session_display_name",
    "write_recent_chat_session_snapshot",
]
