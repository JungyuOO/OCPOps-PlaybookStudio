# chat / chat-stream 처리 흐름을 server.py 밖으로 분리한다.
from __future__ import annotations

import json
import uuid
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from datetime import datetime
import time

from play_book_studio.config.settings import load_settings
from play_book_studio.db.chat_repository import persist_chat_turn
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.http.sessions import RUNTIME_CHAT_MODE, Turn


def _summarize_citation_truth(response_payload: dict[str, Any]) -> dict[str, str]:
    citations = response_payload.get("citations")
    if not isinstance(citations, list) or not citations:
        return {}
    payloads = [item for item in citations if isinstance(item, dict)]
    if not payloads:
        return {}
    boundary_truths = {str(item.get("boundary_truth") or "").strip() for item in payloads if str(item.get("boundary_truth") or "").strip()}
    has_private = "private_customer_pack_runtime" in boundary_truths
    has_official = any(
        truth in {"official_validated_runtime", "official_candidate_runtime"}
        for truth in boundary_truths
    )
    if has_private and has_official:
        official_label = next(
            (
                str(item.get("runtime_truth_label") or "").strip()
                for item in payloads
                if str(item.get("boundary_truth") or "").strip() in {"official_validated_runtime", "official_candidate_runtime"}
                and str(item.get("runtime_truth_label") or "").strip()
            ),
            "Official Runtime",
        )
        private_label = next(
            (
                str(item.get("runtime_truth_label") or "").strip()
                for item in payloads
                if str(item.get("boundary_truth") or "").strip() == "private_customer_pack_runtime"
                and str(item.get("runtime_truth_label") or "").strip()
            ),
            "Private Runtime",
        )
        return {
            "source_lane": "mixed_runtime_bridge",
            "boundary_truth": "mixed_runtime_bridge",
            "runtime_truth_label": f"{official_label} + {private_label}",
            "boundary_badge": "Mixed Runtime",
            "publication_state": "mixed",
            "approval_state": "mixed",
        }
    primary = payloads[0]
    return {
        "source_lane": str(primary.get("source_lane") or ""),
        "boundary_truth": str(primary.get("boundary_truth") or ""),
        "runtime_truth_label": str(primary.get("runtime_truth_label") or ""),
        "boundary_badge": str(primary.get("boundary_badge") or ""),
        "publication_state": str(primary.get("publication_state") or ""),
        "approval_state": str(primary.get("approval_state") or ""),
    }


def _apply_primary_citation_truth(turn: Turn, response_payload: dict[str, Any]) -> None:
    summary = _summarize_citation_truth(response_payload)
    if not summary:
        return
    turn.primary_source_lane = str(summary.get("source_lane") or "")
    turn.primary_boundary_truth = str(summary.get("boundary_truth") or "")
    turn.primary_runtime_truth_label = str(summary.get("runtime_truth_label") or "")
    turn.primary_boundary_badge = str(summary.get("boundary_badge") or "")
    turn.primary_publication_state = str(summary.get("publication_state") or "")
    turn.primary_approval_state = str(summary.get("approval_state") or "")


def _attach_server_timings(
    response_payload: dict[str, Any],
    *,
    server_timings_ms: dict[str, float],
) -> None:
    rounded = {
        key: round(float(value), 1)
        for key, value in server_timings_ms.items()
    }
    response_payload["server_timings_ms"] = rounded
    pipeline_trace = response_payload.get("pipeline_trace")
    if isinstance(pipeline_trace, dict):
        pipeline_trace["server_timings_ms"] = rounded


def _round_ms(value: Any) -> float:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0


def _sum_ms(*values: Any) -> float:
    return round(sum(float(value or 0.0) for value in values), 1)


def _selected_source_scopes(response_payload: dict[str, Any]) -> list[str]:
    citations = response_payload.get("citations")
    if not isinstance(citations, list):
        return []
    scopes: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        scope = str(citation.get("source_scope") or "").strip()
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def _vector_runtime_ms(vector_runtime: dict[str, Any], key: str) -> float:
    if vector_runtime.get(key) is not None:
        return _round_ms(vector_runtime.get(key))
    subqueries = vector_runtime.get("subqueries")
    if not isinstance(subqueries, list):
        return 0.0
    return round(
        sum(
            float(item.get(key, 0.0) or 0.0)
            for item in subqueries
            if isinstance(item, dict)
        ),
        1,
    )


def _build_chat_latency_log(
    *,
    request_id: str,
    session_id: str,
    route: str,
    payload: dict[str, Any],
    query: str,
    request_context: SessionContext,
    result: Any,
    response_payload: dict[str, Any],
    server_timings_ms: dict[str, float],
) -> dict[str, Any]:
    retrieval_trace = getattr(result, "retrieval_trace", {}) or {}
    pipeline_trace = getattr(result, "pipeline_trace", {}) or {}
    retrieval_timings = retrieval_trace.get("timings_ms") or {}
    pipeline_timings = pipeline_trace.get("timings_ms") or {}
    vector_runtime = retrieval_trace.get("vector_runtime") or {}
    reranker_trace = retrieval_trace.get("reranker") or {}
    llm_runtime = pipeline_trace.get("llm") or {}
    ablation = retrieval_trace.get("ablation") or {}
    return {
        "event": "chat_latency",
        "request_id": request_id,
        "session_id": session_id,
        "route": route,
        "route_kind": str(payload.get("route_kind") or "").strip(),
        "preferred_source_scope": str(getattr(request_context, "preferred_source_scope", "") or ""),
        "query_len": len(query),
        "response_kind": str(getattr(result, "response_kind", "") or ""),
        "warnings": list(getattr(result, "warnings", []) or []),
        "total_ms": _round_ms(server_timings_ms.get("request_total")),
        "answerer_ms": _round_ms(server_timings_ms.get("answerer_runtime")),
        "retrieval_ms": _round_ms(pipeline_timings.get("retrieval_total")),
        "bm25_ms": _round_ms(retrieval_timings.get("bm25_search")),
        "vector_ms": _round_ms(retrieval_timings.get("vector_search")),
        "embedding_ms": _vector_runtime_ms(vector_runtime, "embedding_ms"),
        "qdrant_ms": _vector_runtime_ms(vector_runtime, "qdrant_ms"),
        "hydrate_ms": _vector_runtime_ms(vector_runtime, "hydrate_ms"),
        "rerank_ms": _round_ms(retrieval_timings.get("rerank")),
        "llm_ms": _round_ms(pipeline_timings.get("llm_generate_total")),
        "llm_provider_ms": _round_ms(pipeline_timings.get("llm_provider_round_trip")),
        "prompt_build_ms": _round_ms(pipeline_timings.get("prompt_build")),
        "context_ms": _round_ms(pipeline_timings.get("context_assembly")),
        "citation_finalize_ms": _round_ms(pipeline_timings.get("citation_finalize")),
        "payload_build_ms": _round_ms(server_timings_ms.get("payload_build")),
        "related_links_ms": _round_ms(server_timings_ms.get("payload_related_links")),
        "related_sections_ms": _round_ms(server_timings_ms.get("payload_related_sections")),
        "suggested_queries_ms": _round_ms(server_timings_ms.get("payload_suggested_queries")),
        "session_persist_ms": _sum_ms(
            server_timings_ms.get("session_persist_pre_payload"),
            server_timings_ms.get("session_persist_post_payload"),
        ),
        "answer_log_persist_ms": _round_ms(server_timings_ms.get("answer_log_persist")),
        "top_book_slugs": list(ablation.get("reranked_top_book_slugs") or [])[:5],
        "source_scopes": _selected_source_scopes(response_payload),
        "llm_model": str(llm_runtime.get("model") or ""),
        "reranker_model": str(reranker_trace.get("model") or ""),
    }


def _emit_chat_latency_log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _stream_answer_delta(handler: Any, answer: str, *, target_chars: int = 34) -> None:
    buffer = ""
    for token in re.split(r"(\s+)", answer):
        if not token:
            continue
        buffer += token
        if len(buffer) >= target_chars or "\n" in buffer:
            handler._stream_event({"type": "answer_delta", "delta": buffer})
            buffer = ""
            time.sleep(0.01)
    if buffer:
        handler._stream_event({"type": "answer_delta", "delta": buffer})


def _uuid_or_empty(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return ""


def _persist_chat_audit_logs(
    *,
    root_dir: Path,
    answerer: Any,
    session: Turn | Any,
    query: str,
    result: Any,
    context_before: SessionContext,
    context_after: SessionContext,
    response_payload: dict[str, Any],
    append_chat_turn_log: Any,
    append_unanswered_question_log: Any,
    owner_user_id: str = "",
    active_repository_id: str = "",
) -> None:
    try:
        append_chat_turn_log(
            root_dir,
            answerer=answerer,
            session=session,
            query=query,
            result=result,
            context_before=context_before,
            context_after=context_after,
            suggested_queries=response_payload.get("suggested_queries"),
            related_links=response_payload.get("related_links"),
            related_sections=response_payload.get("related_sections"),
        )
        if result.response_kind == "no_answer":
            append_unanswered_question_log(
                root_dir,
                session=session,
                query=query,
                result=result,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[chat-audit] persist failed: {exc}")
    _persist_chat_turn_to_db(
        root_dir=root_dir,
        session=session,
        query=query,
        result=result,
        response_payload=response_payload,
        owner_user_id=owner_user_id,
        active_repository_id=active_repository_id,
    )


def _persist_chat_turn_to_db(
    *,
    root_dir: Path,
    session: Any,
    query: str,
    result: Any,
    response_payload: dict[str, Any],
    owner_user_id: str,
    active_repository_id: str,
) -> None:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return
    turn = session.history[-1] if getattr(session, "history", None) else None
    if turn is None:
        return
    import psycopg

    try:
        with psycopg.connect(database_url) as connection:
            persist_chat_turn(
                connection,
                client_session_id=str(getattr(session, "session_id", "") or ""),
                anonymous_user_id=owner_user_id,
                query=query,
                answer=str(getattr(result, "answer", "") or ""),
                active_repository_id=active_repository_id,
                turn_id=str(getattr(turn, "turn_id", "") or ""),
                parent_turn_id=str(getattr(turn, "parent_turn_id", "") or ""),
                mode=str(getattr(result, "mode", "") or RUNTIME_CHAT_MODE),
                response_kind=str(getattr(result, "response_kind", "") or ""),
                rewritten_query=str(getattr(result, "rewritten_query", "") or ""),
                citations=[item for item in response_payload.get("citations") or [] if isinstance(item, dict)],
                metadata={
                    "session_revision": int(getattr(session, "revision", 0) or 0),
                },
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[chat-db] persist failed: {exc}")


def handle_chat(
    handler: Any,
    payload: dict[str, Any],
    *,
    current_answerer: Any,
    store: Any,
    root_dir: Path,
    build_chat_payload: Any,
    context_with_request_overrides: Any,
    derive_next_context: Any,
    append_chat_turn_log: Any,
    append_unanswered_question_log: Any,
    write_recent_chat_session_snapshot: Any,
    build_turn_stages: Any,
    build_turn_diagnosis: Any,
    suggest_follow_up_questions: Any | None = None,
    owner_user_id: str = "",
) -> None:
    request_started_at = time.perf_counter()
    request_id = uuid.uuid4().hex
    active_answerer = current_answerer()
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    session = store.get(session_id)
    mode = RUNTIME_CHAT_MODE
    regenerate = bool(payload.get("regenerate", False))
    query = str(payload.get("query") or "").strip()
    active_repository_id = _uuid_or_empty(payload.get("active_repository_id") or payload.get("repository_id"))
    active_document_id = _uuid_or_empty(payload.get("active_document_id") or payload.get("document_source_id"))
    scoped_payload = dict(payload)
    if owner_user_id:
        scoped_payload["owner_user_id"] = owner_user_id
    if active_repository_id:
        scoped_payload["active_repository_id"] = active_repository_id
    if active_document_id:
        scoped_payload["active_document_id"] = active_document_id
    request_context = context_with_request_overrides(
        session.context,
        payload=scoped_payload,
        mode=mode,
        default_ocp_version=active_answerer.settings.ocp_version,
    )
    context_before = SessionContext.from_dict(request_context.to_dict())
    if regenerate and not query:
        query = session.last_query

    if not query:
        handler._send_json({"error": "Query is required."}, HTTPStatus.BAD_REQUEST)
        return

    server_timings_ms: dict[str, float] = {}
    try:
        answer_started_at = time.perf_counter()
        result = active_answerer.answer(
            query,
            mode=mode,
            context=request_context,
            top_k=5,
            candidate_k=10,
            max_context_chunks=5,
        )
        server_timings_ms["answerer_runtime"] = (time.perf_counter() - answer_started_at) * 1000
        answer_log_started_at = time.perf_counter()
        active_answerer.append_log(result)
        server_timings_ms["answer_log_persist"] = (time.perf_counter() - answer_log_started_at) * 1000
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"답변 생성 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return

    session.mode = RUNTIME_CHAT_MODE
    session.context = derive_next_context(
        request_context,
        query=query,
        mode=mode,
        result=result,
        default_ocp_version=active_answerer.settings.ocp_version,
    )
    now = datetime.now().isoformat(timespec="seconds")
    parent_turn_id = session.history[-1].turn_id if session.history else ""
    turn = Turn(
        turn_id=uuid.uuid4().hex,
        parent_turn_id=parent_turn_id,
        created_at=now,
        query=query,
        mode=mode,
        answer=result.answer,
        rewritten_query=result.rewritten_query,
        response_kind=result.response_kind,
        warnings=list(result.warnings),
        stages=build_turn_stages(result),
        diagnosis=build_turn_diagnosis(result),
    )
    session.history.append(
        turn
    )
    session.history = session.history[-20:]
    session.revision += 1
    session.updated_at = now
    first_session_persist_started_at = time.perf_counter()
    store.update(session)
    server_timings_ms["session_persist_pre_payload"] = (
        (time.perf_counter() - first_session_persist_started_at) * 1000
    )
    payload_build_started_at = time.perf_counter()
    payload_build_breakdown_ms: dict[str, float] = {}
    response_payload = build_chat_payload(
        root_dir=root_dir,
        answerer=active_answerer,
        session=session,
        result=result,
        timings_sink=payload_build_breakdown_ms,
    )
    server_timings_ms["payload_build"] = (time.perf_counter() - payload_build_started_at) * 1000
    server_timings_ms.update(payload_build_breakdown_ms)
    turn.citations = [item for item in response_payload.get("citations") or [] if isinstance(item, dict)]
    turn.related_links = [item for item in response_payload.get("related_links") or [] if isinstance(item, dict)]
    turn.related_sections = [item for item in response_payload.get("related_sections") or [] if isinstance(item, dict)]
    _apply_primary_citation_truth(turn, response_payload)
    second_session_persist_started_at = time.perf_counter()
    store.update(session)
    server_timings_ms["session_persist_post_payload"] = (
        (time.perf_counter() - second_session_persist_started_at) * 1000
    )
    server_timings_ms["post_answer_total"] = (
        (time.perf_counter() - request_started_at) * 1000
        - server_timings_ms.get("answerer_runtime", 0.0)
    )
    server_timings_ms["request_total"] = (time.perf_counter() - request_started_at) * 1000
    _attach_server_timings(response_payload, server_timings_ms=server_timings_ms)
    _emit_chat_latency_log(
        _build_chat_latency_log(
            request_id=request_id,
            session_id=session_id,
            route="/api/chat",
            payload=payload,
            query=query,
            request_context=request_context,
            result=result,
            response_payload=response_payload,
            server_timings_ms=server_timings_ms,
        )
    )
    handler._send_json(response_payload)
    _persist_chat_audit_logs(
        root_dir=root_dir,
        answerer=active_answerer,
        session=session,
        query=query,
        result=result,
        context_before=context_before,
        context_after=session.context,
        response_payload=response_payload,
        append_chat_turn_log=append_chat_turn_log,
        append_unanswered_question_log=append_unanswered_question_log,
        owner_user_id=owner_user_id,
        active_repository_id=active_repository_id,
    )


def handle_chat_stream(
    handler: Any,
    payload: dict[str, Any],
    *,
    current_answerer: Any,
    store: Any,
    root_dir: Path,
    build_chat_payload: Any,
    context_with_request_overrides: Any,
    derive_next_context: Any,
    append_chat_turn_log: Any,
    append_unanswered_question_log: Any,
    write_recent_chat_session_snapshot: Any,
    build_turn_stages: Any,
    build_turn_diagnosis: Any,
    owner_user_id: str = "",
) -> None:
    request_started_at = time.perf_counter()
    request_id = uuid.uuid4().hex
    active_answerer = current_answerer()
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    session = store.get(session_id)
    mode = RUNTIME_CHAT_MODE
    regenerate = bool(payload.get("regenerate", False))
    query = str(payload.get("query") or "").strip()
    active_repository_id = _uuid_or_empty(payload.get("active_repository_id") or payload.get("repository_id"))
    active_document_id = _uuid_or_empty(payload.get("active_document_id") or payload.get("document_source_id"))
    scoped_payload = dict(payload)
    if owner_user_id:
        scoped_payload["owner_user_id"] = owner_user_id
    if active_repository_id:
        scoped_payload["active_repository_id"] = active_repository_id
    if active_document_id:
        scoped_payload["active_document_id"] = active_document_id
    request_context = context_with_request_overrides(
        session.context,
        payload=scoped_payload,
        mode=mode,
        default_ocp_version=active_answerer.settings.ocp_version,
    )
    context_before = SessionContext.from_dict(request_context.to_dict())
    if regenerate and not query:
        query = session.last_query

    if not query:
        handler._send_json({"error": "Query is required."}, HTTPStatus.BAD_REQUEST)
        return

    handler._start_ndjson_stream()
    handler._stream_event(
        {
            "type": "trace",
            "step": "request_received",
            "label": "질문 접수 완료",
            "status": "done",
            "detail": query[:180],
        }
    )

    def emit_trace(event: dict[str, Any]) -> None:
        handler._stream_event(event)

    server_timings_ms: dict[str, float] = {}
    try:
        answer_started_at = time.perf_counter()
        result = active_answerer.answer(
            query,
            mode=mode,
            context=request_context,
            top_k=5,
            candidate_k=10,
            max_context_chunks=5,
            trace_callback=emit_trace,
        )
        server_timings_ms["answerer_runtime"] = (time.perf_counter() - answer_started_at) * 1000
        answer_log_started_at = time.perf_counter()
        active_answerer.append_log(result)
        server_timings_ms["answer_log_persist"] = (time.perf_counter() - answer_log_started_at) * 1000
    except Exception as exc:  # noqa: BLE001
        handler._stream_event({"type": "error", "error": f"답변 생성 중 오류가 발생했습니다: {exc}"})
        return

    session.mode = RUNTIME_CHAT_MODE
    session.context = derive_next_context(
        request_context,
        query=query,
        mode=mode,
        result=result,
        default_ocp_version=active_answerer.settings.ocp_version,
    )
    now = datetime.now().isoformat(timespec="seconds")
    parent_turn_id = session.history[-1].turn_id if session.history else ""
    turn = Turn(
        turn_id=uuid.uuid4().hex,
        parent_turn_id=parent_turn_id,
        created_at=now,
        query=query,
        mode=mode,
        answer=result.answer,
        rewritten_query=result.rewritten_query,
        response_kind=result.response_kind,
        warnings=list(result.warnings),
        stages=build_turn_stages(result),
        diagnosis=build_turn_diagnosis(result),
    )
    session.history.append(
        turn
    )
    session.history = session.history[-20:]
    session.revision += 1
    session.updated_at = now
    first_session_persist_started_at = time.perf_counter()
    store.update(session)
    server_timings_ms["session_persist_pre_payload"] = (
        (time.perf_counter() - first_session_persist_started_at) * 1000
    )
    payload_build_started_at = time.perf_counter()
    payload_build_breakdown_ms: dict[str, float] = {}
    response_payload = build_chat_payload(
        root_dir=root_dir,
        answerer=active_answerer,
        session=session,
        result=result,
        timings_sink=payload_build_breakdown_ms,
    )
    server_timings_ms["payload_build"] = (time.perf_counter() - payload_build_started_at) * 1000
    server_timings_ms.update(payload_build_breakdown_ms)
    turn.citations = [item for item in response_payload.get("citations") or [] if isinstance(item, dict)]
    turn.related_links = [item for item in response_payload.get("related_links") or [] if isinstance(item, dict)]
    turn.related_sections = [item for item in response_payload.get("related_sections") or [] if isinstance(item, dict)]
    _apply_primary_citation_truth(turn, response_payload)
    second_session_persist_started_at = time.perf_counter()
    store.update(session)
    server_timings_ms["session_persist_post_payload"] = (
        (time.perf_counter() - second_session_persist_started_at) * 1000
    )
    server_timings_ms["post_answer_total"] = (
        (time.perf_counter() - request_started_at) * 1000
        - server_timings_ms.get("answerer_runtime", 0.0)
    )
    server_timings_ms["request_total"] = (time.perf_counter() - request_started_at) * 1000
    _attach_server_timings(response_payload, server_timings_ms=server_timings_ms)
    _emit_chat_latency_log(
        _build_chat_latency_log(
            request_id=request_id,
            session_id=session_id,
            route="/api/chat/stream",
            payload=payload,
            query=query,
            request_context=request_context,
            result=result,
            response_payload=response_payload,
            server_timings_ms=server_timings_ms,
        )
    )
    _stream_answer_delta(handler, str(response_payload.get("answer") or ""))
    handler._stream_event(
        {
            "type": "result",
            "payload": response_payload,
        }
    )
    _persist_chat_audit_logs(
        root_dir=root_dir,
        answerer=active_answerer,
        session=session,
        query=query,
        result=result,
        context_before=context_before,
        context_after=session.context,
        response_payload=response_payload,
        append_chat_turn_log=append_chat_turn_log,
        append_unanswered_question_log=append_unanswered_question_log,
        owner_user_id=owner_user_id,
        active_repository_id=active_repository_id,
    )
