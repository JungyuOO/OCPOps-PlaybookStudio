# chat / chat-stream 처리 흐름을 server.py 밖으로 분리한다.
from __future__ import annotations

import uuid
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from datetime import datetime
import time

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.chat_modes import normalize_chat_mode
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.app.sessions import RUNTIME_CHAT_MODE, Turn


_SESSION_SYNTHESIS_RE = re.compile(
    r"(지금까지|앞에서|위 내용|배운 내용|대화 내용|so far).*(정리|요약|플랜|계획|체크리스트|로드맵|summary|plan)|"
    r"(정리|요약|플랜|계획|체크리스트|로드맵|summary|plan).*(지금까지|앞에서|위 내용|배운 내용|대화 내용|so far)|"
    r"(보고|증거|evidence).*(정리|압축|핵심|요약)|"
    r"(정리|압축|핵심|요약).*(보고|증거|evidence)",
    re.IGNORECASE,
)


def _is_session_synthesis_query(query: str) -> bool:
    return bool(_SESSION_SYNTHESIS_RE.search(query or ""))


def _citation_from_payload(payload: dict[str, Any], *, index: int) -> Citation | None:
    try:
        return Citation(
            index=index,
            chunk_id=str(payload.get("chunk_id") or payload.get("id") or f"session-citation-{index}"),
            book_slug=str(payload.get("book_slug") or ""),
            section=str(payload.get("section") or payload.get("section_path_label") or ""),
            anchor=str(payload.get("anchor") or ""),
            source_url=str(payload.get("source_url") or ""),
            viewer_path=str(payload.get("viewer_path") or ""),
            excerpt=str(payload.get("excerpt") or payload.get("snippet") or ""),
            section_path=tuple(str(item) for item in (payload.get("section_path") or ()) if str(item).strip()),
            section_path_label=str(payload.get("section_path_label") or payload.get("section") or ""),
            chunk_type=str(payload.get("chunk_type") or "reference"),
            semantic_role=str(payload.get("semantic_role") or "unknown"),
            source_collection=str(payload.get("source_collection") or "core"),
            source_lane=str(payload.get("source_lane") or "official_ko"),
            source_type=str(payload.get("source_type") or "official_doc"),
            boundary_truth=str(payload.get("boundary_truth") or ""),
            runtime_truth_label=str(payload.get("runtime_truth_label") or ""),
            boundary_badge=str(payload.get("boundary_badge") or ""),
            approval_state=str(payload.get("approval_state") or ""),
            publication_state=str(payload.get("publication_state") or ""),
            provider_egress_policy=str(payload.get("provider_egress_policy") or ""),
            retrieval_ready=bool(payload.get("retrieval_ready")),
            read_ready=bool(payload.get("read_ready")),
            block_kinds=tuple(str(item) for item in (payload.get("block_kinds") or ()) if str(item).strip()),
            cli_commands=tuple(str(item) for item in (payload.get("cli_commands") or ()) if str(item).strip()),
            error_strings=tuple(str(item) for item in (payload.get("error_strings") or ()) if str(item).strip()),
            k8s_objects=tuple(str(item) for item in (payload.get("k8s_objects") or ()) if str(item).strip()),
            operator_names=tuple(str(item) for item in (payload.get("operator_names") or ()) if str(item).strip()),
            verification_hints=tuple(str(item) for item in (payload.get("verification_hints") or ()) if str(item).strip()),
        )
    except Exception:
        return None


def _session_synthesis_citations(session: Any, *, limit: int = 4) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for turn in reversed(getattr(session, "history", []) or []):
        for payload in getattr(turn, "citations", []) or []:
            if not isinstance(payload, dict):
                continue
            key = "|".join(
                [
                    str(payload.get("chunk_id") or payload.get("id") or ""),
                    str(payload.get("viewer_path") or ""),
                    str(payload.get("section") or ""),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            citation = _citation_from_payload(payload, index=len(citations) + 1)
            if citation is not None:
                citations.append(citation)
            if len(citations) >= limit:
                return citations
    return citations


def _build_session_synthesis_result(
    *,
    query: str,
    mode: str,
    session: Any,
) -> AnswerResult | None:
    if not _is_session_synthesis_query(query):
        return None
    citations = _session_synthesis_citations(session)
    if not citations:
        return None
    cited_indices = list(range(1, min(len(citations), 4) + 1))
    recent_turns = [
        str(turn.query or "").strip()
        for turn in (getattr(session, "history", []) or [])[-8:]
        if str(getattr(turn, "query", "") or "").strip()
    ]
    topic_lines = "\n".join(f"- {item}" for item in recent_turns[-5:])
    if normalize_chat_mode(mode) == "ops":
        answer = (
            "답변: 지금까지의 운영 흐름은 `대상 식별 -> 상태/이벤트 확인 -> 원인 분기 -> 조치 -> 정상화 검증`으로 압축할 수 있습니다 [1][2].\n\n"
            "1. 먼저 문제가 난 리소스와 namespace를 고정하고, 관련 Operator/워크로드의 condition과 phase를 확인합니다 [1].\n"
            "2. 이벤트, Pod 로그, 권한/설치 리소스 상태를 나눠 원인을 좁힙니다 [2].\n"
            "3. 조치 뒤에는 Ready/Available 조건, 반복 이벤트 소거, 알림 해소를 증거로 남깁니다 [3].\n\n"
            f"이번 세션에서 이어진 질문은 아래 흐름이었습니다.\n{topic_lines}\n\n"
            "운영 체크리스트로 넘길 때는 각 단계마다 `관찰한 신호`, `실행한 명령`, `정상화 판정`을 한 줄씩 남기면 됩니다 [1][2][3]."
        )
    else:
        answer = (
            "답변: 지금까지 배운 내용은 `기본 구조 -> 핵심 개념 -> 운영 리소스 관계 -> Day-2 관찰/검증` 순서로 묶는 것이 좋습니다 [1][2].\n\n"
            "1. 1일차에는 OpenShift와 Kubernetes의 차이, 클러스터 구성, Route/Ingress 같은 입문 개념을 정리합니다 [1].\n"
            "2. 2-3일차에는 Operator, OLM, Subscription, CSV, InstallPlan의 관계를 그림처럼 연결해서 봅니다 [2].\n"
            "3. 4-5일차에는 Storage, Observability, 권한/RBAC처럼 운영 중 자주 만나는 주제를 실제 증상과 묶어 봅니다 [3].\n"
            "4. 6-7일차에는 공식 문서 기준선과 고객 운영 자료의 현장 기준을 대조해서 자기 체크리스트를 만듭니다 [4].\n\n"
            f"이번 세션에서 이어진 질문은 아래 흐름이었습니다.\n{topic_lines}\n\n"
            "이 플랜은 문서 요약이 아니라, 다음 질문으로 바로 이어질 수 있는 학습 경로입니다 [1][2][3][4]."
        )
    return AnswerResult(
        query=query,
        mode=mode,
        answer=answer,
        rewritten_query=query,
        citations=citations,
        response_kind="rag",
        cited_indices=cited_indices,
        warnings=[],
        retrieval_trace={"route": "session_synthesis", "source_turns": len(getattr(session, "history", []) or [])},
        pipeline_trace={"events": [], "timings_ms": {"session_synthesis": 0.0}},
    )


def _summarize_citation_truth(response_payload: dict[str, Any]) -> dict[str, str]:
    citations = response_payload.get("citations")
    if not isinstance(citations, list) or not citations:
        return {}
    payloads = [item for item in citations if isinstance(item, dict)]
    if not payloads:
        return {}
    boundary_truths = {str(item.get("boundary_truth") or "").strip() for item in payloads if str(item.get("boundary_truth") or "").strip()}
    has_private = "private_customer_pack_runtime" in boundary_truths
    official_truths = {
        "official_gold_playbook_runtime",
        "official_validated_runtime",
        "official_candidate_runtime",
    }
    has_official = any(truth in official_truths for truth in boundary_truths)
    if has_private and has_official:
        official_label = next(
            (
                str(item.get("runtime_truth_label") or "").strip()
                for item in payloads
                if str(item.get("boundary_truth") or "").strip() in official_truths
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
    response_payload["primary_source_lane"] = str(summary.get("source_lane") or "")
    response_payload["primary_boundary_truth"] = str(summary.get("boundary_truth") or "")
    response_payload["primary_runtime_truth_label"] = str(summary.get("runtime_truth_label") or "")
    response_payload["primary_boundary_badge"] = str(summary.get("boundary_badge") or "")
    response_payload["primary_publication_state"] = str(summary.get("publication_state") or "")
    response_payload["primary_approval_state"] = str(summary.get("approval_state") or "")
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
) -> None:
    request_started_at = time.perf_counter()
    active_answerer = current_answerer()
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    session = store.get(session_id)
    mode = normalize_chat_mode(payload.get("mode") or session.mode or RUNTIME_CHAT_MODE)
    regenerate = bool(payload.get("regenerate", False))
    query = str(payload.get("query") or "").strip()
    request_context = context_with_request_overrides(
        session.context,
        payload=payload,
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
        synthesis_result = _build_session_synthesis_result(
            query=query,
            mode=mode,
            session=session,
        )
        if synthesis_result is not None:
            result = synthesis_result
        else:
            result = active_answerer.answer(
                query,
                mode=mode,
                context=request_context,
                top_k=8,
                candidate_k=20,
                max_context_chunks=6,
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

    session.mode = mode
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
    turn.suggested_queries = [str(item) for item in response_payload.get("suggested_queries") or [] if str(item).strip()]
    turn.suggested_followups = [item for item in response_payload.get("suggested_followups") or [] if isinstance(item, dict)]
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
) -> None:
    request_started_at = time.perf_counter()
    active_answerer = current_answerer()
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    session = store.get(session_id)
    mode = normalize_chat_mode(payload.get("mode") or session.mode or RUNTIME_CHAT_MODE)
    regenerate = bool(payload.get("regenerate", False))
    query = str(payload.get("query") or "").strip()
    request_context = context_with_request_overrides(
        session.context,
        payload=payload,
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
        synthesis_result = _build_session_synthesis_result(
            query=query,
            mode=mode,
            session=session,
        )
        if synthesis_result is not None:
            result = synthesis_result
            handler._stream_event(
                {
                    "type": "trace",
                    "step": "session_synthesis",
                    "label": "세션 요약 답변 생성",
                    "status": "done",
                    "detail": f"이전 turn {len(session.history)}개 기준",
                }
            )
        else:
            result = active_answerer.answer(
                query,
                mode=mode,
                context=request_context,
                top_k=8,
                candidate_k=20,
                max_context_chunks=6,
                trace_callback=emit_trace,
            )
        server_timings_ms["answerer_runtime"] = (time.perf_counter() - answer_started_at) * 1000
        answer_log_started_at = time.perf_counter()
        active_answerer.append_log(result)
        server_timings_ms["answer_log_persist"] = (time.perf_counter() - answer_log_started_at) * 1000
    except Exception as exc:  # noqa: BLE001
        handler._stream_event({"type": "error", "error": f"답변 생성 중 오류가 발생했습니다: {exc}"})
        return

    session.mode = mode
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
    turn.suggested_queries = [str(item) for item in response_payload.get("suggested_queries") or [] if str(item).strip()]
    turn.suggested_followups = [item for item in response_payload.get("suggested_followups") or [] if isinstance(item, dict)]
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
    )
