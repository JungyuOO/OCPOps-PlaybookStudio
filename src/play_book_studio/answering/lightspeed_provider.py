from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import request

from play_book_studio.config.settings import Settings

from .models import AnswerResult


LightspeedTransport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class LightspeedChatContext:
    conversation_id: str = ""
    library_scope: str = ""
    cluster_context: dict[str, Any] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)


def lightspeed_enabled(settings: Settings) -> bool:
    return str(settings.chat_provider or "").strip().lower() == "lightspeed"


def build_lightspeed_payload(query: str, context: LightspeedChatContext | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": str(query or "").strip()}
    if context is None:
        return payload
    if context.conversation_id:
        payload["conversation_id"] = context.conversation_id
    if context.attachments:
        payload["attachments"] = list(context.attachments)
    pbs_context: dict[str, Any] = {}
    if context.library_scope:
        pbs_context["library_scope"] = context.library_scope
    if context.cluster_context:
        pbs_context["cluster_context"] = dict(context.cluster_context)
    if context.recent_events:
        pbs_context["recent_events"] = list(context.recent_events)
    if pbs_context:
        payload["pbs_context"] = pbs_context
    return payload


def build_lightspeed_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if settings.ols_auth_token:
        headers["Authorization"] = f"Bearer {settings.ols_auth_token}"
    return headers


def default_lightspeed_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured endpoint
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw) if raw else {}
    return parsed if isinstance(parsed, dict) else {}


def _answer_text_from_response(payload: dict[str, Any]) -> str:
    for key in ("response", "answer", "message", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _answer_text_from_response(nested)
    return ""


def _conversation_id_from_response(payload: dict[str, Any]) -> str:
    for key in ("conversation_id", "conversationId", "conversation"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def query_lightspeed(
    settings: Settings,
    query: str,
    *,
    context: LightspeedChatContext | None = None,
    transport: LightspeedTransport | None = None,
) -> AnswerResult:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query is required")
    if not settings.ols_base_url:
        return AnswerResult(
            query=normalized_query,
            mode="runtime",
            answer="OpenShift Lightspeed endpoint is not configured.",
            rewritten_query=normalized_query,
            response_kind="configuration_error",
            citations=[],
            warnings=["lightspeed endpoint is not configured"],
            retrieval_trace={"provider": "lightspeed", "configured": False},
            pipeline_trace={"provider": "lightspeed", "status": "configuration_error"},
        )

    started_at = time.perf_counter()
    endpoint = f"{settings.ols_base_url.rstrip('/')}/v1/query"
    request_payload = build_lightspeed_payload(normalized_query, context)
    headers = build_lightspeed_headers(settings)
    active_transport = transport or default_lightspeed_transport
    response_payload = active_transport(
        endpoint,
        request_payload,
        headers,
        float(settings.ols_timeout_seconds),
    )
    answer = _answer_text_from_response(response_payload)
    if not answer:
        answer = "OpenShift Lightspeed returned an empty response."
    conversation_id = _conversation_id_from_response(response_payload)
    return AnswerResult(
        query=normalized_query,
        mode="runtime",
        answer=answer,
        rewritten_query=normalized_query,
        response_kind="lightspeed",
        citations=[],
        warnings=[] if answer else ["lightspeed returned an empty response"],
        retrieval_trace={
            "provider": "lightspeed",
            "configured": True,
            "endpoint": endpoint,
            "conversation_id": conversation_id,
            "request_context_keys": sorted(request_payload.keys()),
        },
        pipeline_trace={
            "provider": "lightspeed",
            "status": "answered",
            "timings_ms": {
                "lightspeed_round_trip": round((time.perf_counter() - started_at) * 1000, 1),
            },
        },
    )


__all__ = [
    "LightspeedChatContext",
    "LightspeedTransport",
    "build_lightspeed_headers",
    "build_lightspeed_payload",
    "default_lightspeed_transport",
    "lightspeed_enabled",
    "query_lightspeed",
]
