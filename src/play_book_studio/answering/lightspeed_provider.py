from __future__ import annotations

import hashlib
import json
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import request

from play_book_studio.config.settings import Settings

from .models import AnswerResult, Citation


LightspeedTransport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class LightspeedChatContext:
    conversation_id: str = ""
    library_scope: str = ""
    cluster_context: dict[str, Any] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    pbs_rag: dict[str, Any] = field(default_factory=dict)


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
    if context.pbs_rag:
        pbs_context["rag"] = dict(context.pbs_rag)
    if pbs_context:
        payload["pbs_context"] = pbs_context
    return payload


def is_private_pbs_citation(citation: Citation) -> bool:
    """Return true when a citation represents PBS user/customer uploaded knowledge."""

    source_collection = (citation.source_collection or "").lower()
    book_slug = (citation.book_slug or "").lower()
    viewer_path = citation.viewer_path or ""
    source_url = citation.source_url or ""
    return (
        source_collection
        in {"uploaded", "uploads", "customer", "customer_docs", "customer-pack", "customer_pack"}
        or book_slug == "uploaded-documents"
        or viewer_path.startswith("/uploads/")
        or "uploads/" in source_url
        or source_url.startswith("internal://customer")
        or source_url.startswith("customer_pack")
    )


def build_pbs_rag_context(result: AnswerResult, *, max_citations: int = 5, max_excerpt_chars: int = 900) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    private_citations = [citation for citation in result.citations if is_private_pbs_citation(citation)]
    for citation in private_citations[: max(0, max_citations)]:
        citations.append(
            {
                "index": citation.index,
                "source_collection": citation.source_collection,
                "book_slug": citation.book_slug,
                "section": citation.section,
                "source_url": citation.source_url,
                "viewer_path": citation.viewer_path,
                "excerpt": citation.excerpt[:max_excerpt_chars],
                "cli_commands": list(citation.cli_commands),
                "k8s_objects": list(citation.k8s_objects),
                "operator_names": list(citation.operator_names),
            }
        )
    return {
        "mode": "lightspeed-rag-with-pbs-private-context",
        "private_context_available": bool(citations),
        "pbs_retrieval_mode": result.mode,
        "response_kind": result.response_kind,
        "rewritten_query": result.rewritten_query,
        "answer_preview": str(result.answer or "")[:1200],
        "citations": citations,
        "warnings": list(result.warnings),
        "retrieval_trace": dict(result.retrieval_trace),
        "instruction": (
            "Use OpenShift Lightspeed's built-in knowledge and cluster analysis as the primary "
            "source for official OpenShift guidance. Treat this PBS context only as supplemental "
            "private/customer-uploaded evidence for this environment."
        ),
    }


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
    *,
    insecure_skip_tls_verify: bool = False,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    context = ssl._create_unverified_context() if insecure_skip_tls_verify else None
    with request.urlopen(req, timeout=timeout_seconds, context=context) as response:  # noqa: S310 - configured endpoint
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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _lightspeed_referenced_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("referenced_documents", "references", "documents", "sources", "citations"):
        values = _list_of_dicts(payload.get(key))
        if values:
            return values
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _lightspeed_referenced_documents(nested)
    return []


def _lightspeed_document_citation(doc: dict[str, Any], *, index: int) -> Citation:
    title = _first_string(doc, ("title", "name", "document_title", "doc_title")) or "OpenShift Lightspeed source"
    section = _first_string(doc, ("section", "heading", "chunk_title", "source_title")) or title
    url = _first_string(doc, ("url", "source_url", "doc_url", "uri", "href", "link"))
    viewer_path = _first_string(doc, ("viewer_path", "viewerPath"))
    excerpt = _first_string(doc, ("excerpt", "text", "content", "snippet", "summary")) or title
    anchor = _first_string(doc, ("anchor", "fragment"))
    doc_id = _first_string(doc, ("id", "document_id", "doc_id", "source_id"))
    digest = hashlib.sha256(
        json.dumps(
            {
                "index": index,
                "title": title,
                "section": section,
                "url": url,
                "viewer_path": viewer_path,
                "doc_id": doc_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return Citation(
        index=index,
        chunk_id=doc_id or f"lightspeed-{digest}",
        book_slug="openshift-lightspeed",
        section=section,
        anchor=anchor,
        source_url=url,
        viewer_path=viewer_path or url,
        excerpt=excerpt,
        section_path=(title,) if title != section else (),
        section_path_label=title,
        heading_title=section,
        source_collection="openshift_lightspeed",
    )


def build_lightspeed_citations(payload: dict[str, Any], *, start_index: int = 1) -> list[Citation]:
    """Normalize OLS reference metadata into PBS citations for source view rendering."""

    citations: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for offset, doc in enumerate(_lightspeed_referenced_documents(payload), start=start_index):
        citation = _lightspeed_document_citation(doc, index=offset)
        dedupe_key = (citation.source_url, citation.viewer_path, citation.section)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        citations.append(citation)
    return citations


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
    if settings.ols_provider:
        request_payload["provider"] = settings.ols_provider
    if settings.ols_model:
        request_payload["model"] = settings.ols_model
    if settings.ols_system_prompt:
        request_payload["system_prompt"] = settings.ols_system_prompt
    headers = build_lightspeed_headers(settings)
    if transport is None:
        response_payload = default_lightspeed_transport(
            endpoint,
            request_payload,
            headers,
            float(settings.ols_timeout_seconds),
            insecure_skip_tls_verify=settings.ols_insecure_skip_tls_verify,
        )
    else:
        response_payload = transport(
            endpoint,
            request_payload,
            headers,
            float(settings.ols_timeout_seconds),
        )
    answer = _answer_text_from_response(response_payload)
    if not answer:
        answer = "OpenShift Lightspeed returned an empty response."
    conversation_id = _conversation_id_from_response(response_payload)
    citations = build_lightspeed_citations(response_payload)
    return AnswerResult(
        query=normalized_query,
        mode="runtime",
        answer=answer,
        rewritten_query=normalized_query,
        response_kind="lightspeed",
        citations=citations,
        cited_indices=[citation.index for citation in citations],
        warnings=[] if answer else ["lightspeed returned an empty response"],
        retrieval_trace={
            "provider": "lightspeed",
            "configured": True,
            "endpoint": endpoint,
            "conversation_id": conversation_id,
            "request_context_keys": sorted(request_payload.keys()),
            "referenced_documents": len(citations),
            "insecure_skip_tls_verify": settings.ols_insecure_skip_tls_verify,
        },
        pipeline_trace={
            "provider": "lightspeed",
            "status": "answered",
            "referenced_documents": _lightspeed_referenced_documents(response_payload),
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
    "build_lightspeed_citations",
    "build_pbs_rag_context",
    "is_private_pbs_citation",
    "default_lightspeed_transport",
    "lightspeed_enabled",
    "query_lightspeed",
]
