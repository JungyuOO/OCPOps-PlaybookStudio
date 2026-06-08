from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from play_book_studio.retrieval.models import SessionContext

from .lightspeed_provider import is_private_pbs_citation
from .models import AnswerResult, Citation


PRIMARY_ROUTES = {
    "official_docs",
    "private_docs",
    "live_cluster_read",
    "aiops_review",
    "action_request",
}
CONTEXT_LANES = {
    "official_docs",
    "private_docs",
    "live_cluster",
    "terminal_events",
    "yaml_diff",
    "uploaded_files",
}
RELEVANCE_LEVELS = {"none", "weak", "strong"}
RISK_LEVELS = {"none", "read", "write"}

WRITE_ACTION_RE = re.compile(
    r"\b(oc\s+apply|oc\s+patch|oc\s+delete|oc\s+scale|rollout\s+restart|kubectl\s+apply|"
    r"apply\s+-f|patch|delete|scale|restart|install|uninstall)\b|"
    r"(\uc801\uc6a9|\ubc18\uc601|\uc0ad\uc81c|\uc2a4\ucf00\uc77c|\uc7ac\uc2dc\uc791|\uc124\uce58|\uc81c\uac70|\uc218\uc815\ud574|\ubcc0\uacbd\ud574)",
    re.IGNORECASE,
)
LIVE_CLUSTER_RE = re.compile(
    r"\b(current|this|now|live|cluster|namespace|pod|deployment|service|route|event|log|yaml)\b|"
    r"(\ud604\uc7ac|\uc9c0\uae08|\uc774\s*\ud074\ub7ec\uc2a4\ud130|\ub124\uc784\uc2a4\ud398\uc774\uc2a4|\uc774\ubca4\ud2b8|\ub85c\uadf8|\uc0c1\ud0dc|\uc2e4\ud328|\uc6d0\uc778|yaml)",
    re.IGNORECASE,
)
TERMINAL_RE = re.compile(
    r"\b(terminal|stdout|stderr|exit code|command|cli|oc\s+get|oc\s+describe)\b|"
    r"(\ud130\ubbf8\ub110|\uba85\ub839|\ucd9c\ub825|\uc5d0\ub7ec|\uc624\ub958|\ubc29\uae08|\ucd5c\uadfc)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class RouteProbe:
    private_docs: list[dict[str, Any]] = field(default_factory=list)
    selected_hits: list[dict[str, Any]] = field(default_factory=list)
    retrieval_warnings: list[str] = field(default_factory=list)
    private_doc_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RouteDecision:
    primary_route: str = "official_docs"
    context_lanes: list[str] = field(default_factory=lambda: ["official_docs"])
    private_docs_relevance: str = "none"
    live_cluster_relevance: str = "none"
    terminal_event_relevance: str = "none"
    risk_level: str = "none"
    confidence: float = 0.5
    reason: str = "deterministic fallback"
    classifier: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_route_probe(rag_result: AnswerResult) -> RouteProbe:
    private_docs = [
        _citation_probe(citation)
        for citation in rag_result.citations
        if is_private_pbs_citation(citation)
    ]
    return RouteProbe(
        private_docs=private_docs[:5],
        selected_hits=_selected_hits(rag_result)[:5],
        retrieval_warnings=list(rag_result.warnings),
        private_doc_count=len(private_docs),
    )


def should_include_private_context(decision: RouteDecision, probe: RouteProbe) -> bool:
    if probe.private_doc_count < 1:
        return False
    if "private_docs" in decision.context_lanes:
        return True
    return decision.private_docs_relevance == "strong"


def classify_route(
    query: str,
    *,
    probe: RouteProbe,
    context: SessionContext | None = None,
    llm_client: Any | None = None,
    trace_callback=None,
) -> RouteDecision:
    fallback = _deterministic_decision(query, probe=probe, context=context)
    if llm_client is None or not hasattr(llm_client, "generate"):
        return fallback
    try:
        raw = llm_client.generate(
            _classifier_messages(query, probe=probe, context=context, fallback=fallback),
            trace_callback=trace_callback,
            max_tokens=450,
        )
        parsed = _extract_json_object(raw)
        return _normalize_decision(parsed, fallback=fallback, classifier="llm")
    except Exception as exc:  # noqa: BLE001
        fallback.reason = f"{fallback.reason}; classifier fallback after LLM error: {exc}"
        return fallback


def _citation_probe(citation: Citation) -> dict[str, Any]:
    return {
        "index": citation.index,
        "book_slug": citation.book_slug,
        "section": citation.section,
        "source_collection": citation.source_collection,
        "source_url": citation.source_url,
        "viewer_path": citation.viewer_path,
        "excerpt": citation.excerpt[:500],
        "cli_commands": list(citation.cli_commands[:5]),
        "k8s_objects": list(citation.k8s_objects[:5]),
    }


def _selected_hits(rag_result: AnswerResult) -> list[dict[str, Any]]:
    selection = (
        rag_result.pipeline_trace.get("selection")
        if isinstance(rag_result.pipeline_trace, dict)
        else {}
    )
    selected = selection.get("selected_hits") if isinstance(selection, dict) else []
    return [item for item in selected if isinstance(item, dict)] if isinstance(selected, list) else []


def _deterministic_decision(
    query: str,
    *,
    probe: RouteProbe,
    context: SessionContext | None,
) -> RouteDecision:
    normalized = str(query or "").strip()
    lanes = ["official_docs"]
    primary = "official_docs"
    private_relevance = "none"
    live_relevance = "none"
    terminal_relevance = "none"
    risk = "none"
    reason_parts: list[str] = []

    if probe.private_doc_count > 0:
        private_relevance = "strong"
        lanes.append("private_docs")
        primary = "private_docs"
        reason_parts.append("private PBS retrieval evidence is available")
    if LIVE_CLUSTER_RE.search(normalized):
        live_relevance = "weak"
        reason_parts.append("query contains live cluster terms")
    if TERMINAL_RE.search(normalized):
        terminal_relevance = "weak"
        lanes.append("terminal_events")
        primary = "aiops_review" if primary != "private_docs" else primary
        reason_parts.append("query references terminal or command evidence")
    if WRITE_ACTION_RE.search(normalized):
        risk = "write"
        primary = "action_request"
        lanes.extend(["live_cluster", "yaml_diff"])
        reason_parts.append("query appears to request a live mutation")
    elif live_relevance != "none" and primary == "official_docs":
        primary = "live_cluster_read"
        lanes.append("live_cluster")
        risk = "read"

    if context and (context.active_document_id or context.active_repository_id):
        lanes.append("uploaded_files")

    return RouteDecision(
        primary_route=primary,
        context_lanes=_dedupe_lanes(lanes),
        private_docs_relevance=private_relevance,
        live_cluster_relevance=live_relevance,
        terminal_event_relevance=terminal_relevance,
        risk_level=risk,
        confidence=0.72 if reason_parts else 0.55,
        reason="; ".join(reason_parts) or "default to official OpenShift guidance",
    )


def _classifier_messages(
    query: str,
    *,
    probe: RouteProbe,
    context: SessionContext | None,
    fallback: RouteDecision,
) -> list[dict[str, str]]:
    context_payload = {
        "query": query,
        "probe": probe.to_dict(),
        "session_context": context.to_dict() if context else {},
        "deterministic_hint": fallback.to_dict(),
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a routing classifier for an OpenShift AIOps assistant. "
                "Do not answer the user. Return only valid JSON. "
                "Classify the query into primary_route and context_lanes. "
                "primary_route must be one of official_docs, private_docs, live_cluster_read, "
                "aiops_review, action_request. context_lanes may include official_docs, "
                "private_docs, live_cluster, terminal_events, yaml_diff, uploaded_files. "
                "Use semantic overlap, not only explicit words. If uploaded/private document "
                "probe excerpts are relevant to the user question, include private_docs even "
                "when the user did not say uploaded docs, private docs, or customer docs. "
                "Keep official_docs for general OpenShift documentation, command help, and "
                "concept questions. Include live_cluster or terminal_events only when the "
                "question depends on current cluster state, selected resources, events, logs, "
                "terminal output, or YAML shown in the UI. If the query asks to mutate live "
                "resources, set primary_route=action_request and risk_level=write. Never "
                "classify a pure explanation or command-help question as action_request."
            ),
        },
        {
            "role": "user",
            "content": (
                "Return JSON with keys: primary_route, context_lanes, private_docs_relevance, "
                "live_cluster_relevance, terminal_event_relevance, risk_level, confidence, reason.\n\n"
                f"{json.dumps(context_payload, ensure_ascii=False, sort_keys=True)}"
            ),
        },
    ]


def _extract_json_object(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}


def _normalize_decision(
    payload: dict[str, Any],
    *,
    fallback: RouteDecision,
    classifier: str,
) -> RouteDecision:
    primary = str(payload.get("primary_route") or fallback.primary_route).strip()
    if primary not in PRIMARY_ROUTES:
        primary = fallback.primary_route

    lanes = [
        str(item).strip()
        for item in payload.get("context_lanes", [])
        if str(item).strip() in CONTEXT_LANES
    ]
    if not lanes:
        lanes = list(fallback.context_lanes)
    if primary == "private_docs" and "private_docs" not in lanes:
        lanes.append("private_docs")
    if primary == "official_docs" and "official_docs" not in lanes:
        lanes.insert(0, "official_docs")
    if primary in {"live_cluster_read", "aiops_review", "action_request"} and "live_cluster" not in lanes:
        lanes.append("live_cluster")
    if primary == "action_request" and "yaml_diff" not in lanes:
        lanes.append("yaml_diff")

    confidence = payload.get("confidence", fallback.confidence)
    try:
        confidence_value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_value = fallback.confidence

    return RouteDecision(
        primary_route=primary,
        context_lanes=_dedupe_lanes(lanes),
        private_docs_relevance=_enum_value(
            payload.get("private_docs_relevance"),
            RELEVANCE_LEVELS,
            fallback.private_docs_relevance,
        ),
        live_cluster_relevance=_enum_value(
            payload.get("live_cluster_relevance"),
            RELEVANCE_LEVELS,
            fallback.live_cluster_relevance,
        ),
        terminal_event_relevance=_enum_value(
            payload.get("terminal_event_relevance"),
            RELEVANCE_LEVELS,
            fallback.terminal_event_relevance,
        ),
        risk_level=_enum_value(payload.get("risk_level"), RISK_LEVELS, fallback.risk_level),
        confidence=confidence_value,
        reason=str(payload.get("reason") or fallback.reason)[:500],
        classifier=classifier,
    )


def _enum_value(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in allowed else fallback


def _dedupe_lanes(lanes: list[str]) -> list[str]:
    deduped: list[str] = []
    for lane in lanes:
        if lane in CONTEXT_LANES and lane not in deduped:
            deduped.append(lane)
    return deduped or ["official_docs"]


__all__ = [
    "RouteDecision",
    "RouteProbe",
    "build_route_probe",
    "classify_route",
    "should_include_private_context",
]
