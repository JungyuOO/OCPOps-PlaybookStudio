"""HTTP server support helpers split out of server.py."""
from __future__ import annotations

import json
import threading
import time
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.answering.models import AnswerResult
from play_book_studio.app.presenters import (
    _build_citation_presentation_context,
    _serialize_citation,
)
from play_book_studio.app.source_books import (
    build_chat_navigation_links as _build_chat_navigation_links,
    build_chat_section_links as _build_chat_section_links,
)
from play_book_studio.app.session_flow import suggest_follow_up_questions as _suggest_follow_up_questions
from play_book_studio.app.sessions import ChatSession

FRONTEND_DIST_DIRNAME = "presentation-ui/dist"
DATA_CONTROL_ROOM_CACHE_TTL_SECONDS = 30.0


def _frontend_dist_dir(root_dir: Path) -> Path:
    return (root_dir / FRONTEND_DIST_DIRNAME).resolve()


def _resolve_frontend_asset(root_dir: Path, request_path: str) -> Path | None:
    dist_dir = _frontend_dist_dir(root_dir)
    if not dist_dir.exists():
        return None
    relative = unquote((request_path or "").lstrip("/"))
    if not relative:
        relative = "index.html"
    candidate = (dist_dir / relative).resolve()
    if candidate.is_file() and (candidate == dist_dir or dist_dir in candidate.parents):
        return candidate
    return None


def _decode_multipart_text(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _parse_multipart_form_data(raw_body: bytes, content_type: str) -> dict[str, Any]:
    if not raw_body:
        return {}
    envelope = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8")
    message = BytesParser(policy=default_email_policy).parsebytes(envelope + raw_body)
    if not message.is_multipart():
        return {}

    payload: dict[str, Any] = {}
    uploaded_file_name = ""
    for part in message.iter_parts():
        field_name = str(part.get_param("name", header="content-disposition") or "").strip()
        if not field_name:
            continue
        filename = part.get_filename()
        if filename:
            payload[field_name] = part.get_payload(decode=True) or b""
            payload[f"{field_name}_name"] = str(filename)
            if field_name == "file":
                uploaded_file_name = str(filename)
            continue
        payload[field_name] = _decode_multipart_text(part)

    if "file" in payload:
        payload["file_bytes"] = payload.pop("file")
    if "file_name" not in payload and "file_name_name" in payload:
        payload["file_name"] = str(payload.pop("file_name_name") or "")
    elif "file_name" in payload:
        payload["file_name"] = str(payload["file_name"] or "")
    elif "file_bytes" in payload:
        payload["file_name"] = uploaded_file_name
    return payload


class _TimedValueCache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if cached is None:
                return None
            created_at, value = cached
            if now - created_at > self.ttl_seconds:
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> Any:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
        return value


def _build_chat_payload(
    *,
    root_dir: Path,
    answerer: ChatAnswerer | None = None,
    session: ChatSession,
    result: AnswerResult,
    timings_sink: dict[str, float] | None = None,
) -> dict[str, Any]:
    # UI 응답과 재현성 로그에 쓰는 chat payload serialization helper.
    presentation_context = _build_citation_presentation_context(root_dir)
    citation_started_at = time.perf_counter()
    serialized_citations = [
        _serialize_citation(
            root_dir,
            citation,
            presentation_context=presentation_context,
        )
        for citation in result.citations
    ]
    if timings_sink is not None:
        timings_sink["payload_citation_serialize"] = (time.perf_counter() - citation_started_at) * 1000
    related_links_started_at = time.perf_counter()
    related_links = _build_chat_navigation_links(
        root_dir,
        serialized_citations,
        user_id=session.context.user_id,
    )
    if timings_sink is not None:
        timings_sink["payload_related_links"] = (time.perf_counter() - related_links_started_at) * 1000
    related_sections_started_at = time.perf_counter()
    related_sections = _build_chat_section_links(
        root_dir,
        serialized_citations,
        user_id=session.context.user_id,
    )
    if timings_sink is not None:
        timings_sink["payload_related_sections"] = (time.perf_counter() - related_sections_started_at) * 1000
    suggested_queries_started_at = time.perf_counter()
    suggested_queries = _suggest_follow_up_questions(session=session, result=result)
    if timings_sink is not None:
        timings_sink["payload_suggested_queries"] = (time.perf_counter() - suggested_queries_started_at) * 1000
    payload = {
        "session_id": session.session_id,
        "mode": session.mode,
        "answer": result.answer,
        "rewritten_query": result.rewritten_query,
        "response_kind": result.response_kind,
        "warnings": list(result.warnings),
        "cited_indices": list(result.cited_indices),
        "citations": serialized_citations,
        "related_links": related_links,
        "related_sections": related_sections,
        "suggested_queries": suggested_queries,
        "context": session.context.to_dict(),
        "history_size": len(session.history),
        "retrieval_trace": dict(result.retrieval_trace),
        "pipeline_trace": dict(result.pipeline_trace),
    }
    if result.response_kind == "no_answer":
        payload["acquisition"] = {
            "kind": "repository_search",
            "title": "현재 Playbook Library에 해당 자료가 없습니다.",
            "body": "자료 추가를 원하시면 체크 후 확인을 눌러주세요.",
            "checkbox_label": "Repository에서 우선순위로 필요한 데이터 찾기",
            "confirm_label": "확인",
            "repository_query": (result.rewritten_query or result.query or "").strip(),
        }
    return payload


__all__ = [
    "DATA_CONTROL_ROOM_CACHE_TTL_SECONDS",
    "FRONTEND_DIST_DIRNAME",
    "_TimedValueCache",
    "_build_chat_payload",
    "_decode_multipart_text",
    "_frontend_dist_dir",
    "_parse_multipart_form_data",
    "_resolve_frontend_asset",
]
