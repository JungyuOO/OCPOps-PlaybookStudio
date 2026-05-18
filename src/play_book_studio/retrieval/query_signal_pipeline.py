"""One-shot query signal planning for the RAG retrieval pipeline.

This layer turns a user question into retrieval-only signals. It does not
answer the user and it does not call a separate intent-agent service.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any

from .domain_lexicon import (
    DOMAIN_LEXICONS,
    query_matches_domain,
    query_matches_dynamic_variant,
    query_matches_static_variant,
)

from .query_understanding import StructuredQuerySignals, understand_query_signals


@dataclass(frozen=True, slots=True)
class QueryCorrection:
    type: str
    source: str
    replacement: str

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "from": self.source,
            "to": self.replacement,
        }


@dataclass(frozen=True, slots=True)
class QuerySignalPlan:
    raw_query: str
    normalized_query: str
    correction_notes: tuple[QueryCorrection, ...]
    classification: dict[str, Any]
    search_signals: dict[str, tuple[str, ...]]
    confidence: dict[str, float]
    embedding_queries: tuple[str, ...]
    metadata_filter: dict[str, Any]

    @property
    def vector_query(self) -> str:
        return self.embedding_queries[0] if self.embedding_queries else self.normalized_query

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "normalized_query": self.normalized_query,
            "correction_notes": [item.to_dict() for item in self.correction_notes],
            "classification": dict(self.classification),
            "search_signals": {key: list(value) for key, value in self.search_signals.items()},
            "confidence": dict(self.confidence),
            "embedding_queries": list(self.embedding_queries),
            "metadata_filter": self.metadata_filter,
            "vector_query": self.vector_query,
        }


_NORMALIZATION_RULES: tuple[tuple[str, str, str], ...] = (
    (r"피\s*브이\s*씨|피브이씨", "PVC", "object_alias"),
    (r"피\s*브이|피브이", "PV", "object_alias"),
    (r"파드", "Pod", "object_alias"),
    (r"라우트", "Route", "object_alias"),
    (r"시크릿", "Secret", "object_alias"),
    (r"노드", "Node", "object_alias"),
    (r"이미지\s*풀\s*백\s*오프|이미지풀백오프", "ImagePullBackOff", "error_alias"),
    (r"노트\s*레디|노트레디", "NotReady", "error_alias"),
    (r"\bnot\s+ready\b", "NotReady", "error_alias"),
    (r"\bimage\s+pull\s+back\s+off\b", "ImagePullBackOff", "error_alias"),
)

_ALLOWED_DOMAINS = {
    "install",
    "storage",
    "networking",
    "security",
    "monitoring",
    "troubleshooting",
    "upgrade",
    "operators",
    "logging",
    "registry",
    "ui_tooling",
    "architecture",
    "release_notes",
    "node_ops",
    "backup_restore",
    "etcd",
}
_ALLOWED_PLATFORMS = {"bare_metal", "agent_based", "any_platform", "none"}
_SEARCH_SIGNAL_KEYS = (
    "objects",
    "error_states",
    "intent_labels",
    "answer_shapes",
    "command_families",
    "primary_topics",
    "cluster_phase",
    "execution_target",
    "commands",
    "secondary_topics",
    "components",
)
_ALLOWED_INTENT_LABELS = {
    "explain_concept",
    "check_status",
    "verify_result",
    "troubleshoot",
    "configure_resource",
    "create_resource",
    "update_resource",
    "delete_resource",
    "backup",
    "restore",
    "install",
    "upgrade",
    "compare_options",
    "find_document",
    "command_lookup",
    "summarize",
    "list_prerequisites",
    "identify_execution_target",
    "explain_warning",
    "next_steps",
}
_ALLOWED_ANSWER_SHAPES = {
    "short_explanation",
    "step_by_step",
    "command",
    "checklist",
    "yaml_example",
    "decision_guide",
    "warning",
    "troubleshooting_flow",
    "document_link",
}
_ALLOWED_COMMAND_FAMILIES = {
    "oc_get",
    "oc_describe",
    "oc_logs",
    "oc_debug",
    "oc_apply",
    "oc_create",
    "oc_delete",
    "oc_adm",
    "oc_project",
    "oc_explain",
    "kubectl_get",
    "kubectl_describe",
    "etcdctl",
    "cluster_backup",
}


def build_query_signal_plan(
    query: str,
    *,
    ocp_version: str = "4.20",
    locale: str = "ko",
    llm_client: Any | None = None,
) -> QuerySignalPlan:
    fallback = _build_rule_based_query_signal_plan(query, ocp_version=ocp_version, locale=locale)
    if llm_client is None:
        return fallback
    try:
        return _build_llm_query_signal_plan(
            raw_query=fallback.raw_query,
            fallback=fallback,
            llm_client=llm_client,
            ocp_version=ocp_version,
            locale=locale,
        )
    except Exception:  # noqa: BLE001
        return fallback


def _build_rule_based_query_signal_plan(
    query: str,
    *,
    ocp_version: str = "4.20",
    locale: str = "ko",
) -> QuerySignalPlan:
    raw_query = " ".join(str(query or "").split())
    normalized_query, correction_notes = _normalize_query(raw_query)
    baseline = understand_query_signals(normalized_query, ocp_version=ocp_version, locale=locale)
    classification = dict(baseline.classification)
    classification.setdefault("platform", "any_platform")
    search_signals = {key: list(value) for key, value in baseline.search_signals.items()}
    confidence = dict(baseline.confidence)

    _apply_domain_specific_enrichment(
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )

    normalized_signals = {
        key: tuple(dict.fromkeys(item for item in values if str(item or "").strip()))
        for key, values in search_signals.items()
    }
    embedding_queries = _embedding_queries(
        raw_query=raw_query,
        normalized_query=normalized_query,
        baseline=baseline,
        search_signals=normalized_signals,
    )
    metadata_filter = _metadata_filter(
        classification=classification,
        confidence=confidence,
        ocp_version=ocp_version,
        locale=locale,
    )

    return QuerySignalPlan(
        raw_query=raw_query,
        normalized_query=normalized_query,
        correction_notes=correction_notes,
        classification=classification,
        search_signals=normalized_signals,
        confidence=confidence,
        embedding_queries=embedding_queries,
        metadata_filter=metadata_filter,
    )


def _build_llm_query_signal_plan(
    *,
    raw_query: str,
    fallback: QuerySignalPlan,
    llm_client: Any,
    ocp_version: str,
    locale: str,
) -> QuerySignalPlan:
    content = llm_client.generate(
        _query_signal_messages(raw_query=raw_query, ocp_version=ocp_version, locale=locale),
        max_tokens=900,
    )
    payload = _extract_json_object(content)
    return _validated_llm_plan(
        raw_query=raw_query,
        payload=payload,
        fallback=fallback,
        ocp_version=ocp_version,
        locale=locale,
    )


def _query_signal_messages(*, raw_query: str, ocp_version: str, locale: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You extract retrieval signals for an OpenShift RAG pipeline. "
                "Return only one JSON object. Do not answer the user. "
                "Normalize typos and aliases, classify the question, extract search signals, "
                "and create 2-3 embedding search queries. "
                "Use only allowed concise labels. Do not invent platform or commands when uncertain."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": raw_query,
                    "fixed_context": {"ocp_version": ocp_version, "locale": locale},
                    "domain_policy": (
                        "classification.domain is the document/search area for metadata filtering, "
                        "not the user's intent. If a troubleshooting question has a clear target object, "
                        "prefer the object-specific domain and put troubleshooting in intent_labels. "
                        "Examples: Node NotReady -> domain=node_ops with intent_labels=[troubleshoot, check_status]; "
                        "PVC Pending -> domain=storage with intent_labels=[troubleshoot, check_status]; "
                        "ImagePullBackOff -> domain=registry with intent_labels=[troubleshoot, check_status]."
                    ),
                    "allowed_domains": sorted(_ALLOWED_DOMAINS),
                    "allowed_platforms": sorted(_ALLOWED_PLATFORMS),
                    "allowed_intent_labels": sorted(_ALLOWED_INTENT_LABELS),
                    "allowed_answer_shapes": sorted(_ALLOWED_ANSWER_SHAPES),
                    "allowed_command_families": sorted(_ALLOWED_COMMAND_FAMILIES),
                    "required_json_shape": {
                        "normalized_query": "string",
                        "correction_notes": [{"type": "typo|alias|spacing|object_alias|error_alias", "from": "string", "to": "string"}],
                        "classification": {
                            "domain": "allowed domain or empty string",
                            "book_slug_candidates": ["string"],
                            "domain_filter_values": ["optional allowed domains when one query should scope multiple document areas"],
                            "platform": "allowed platform",
                            "ocp_version": ocp_version,
                            "locale": locale,
                        },
                        "search_signals": {key: ["string"] for key in _SEARCH_SIGNAL_KEYS},
                        "confidence": {"domain": 0.0, "objects": 0.0, "commands": 0.0},
                        "embedding_queries": ["2-3 short retrieval queries, max 300 chars each"],
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("query signal LLM response must be a JSON object")
    return payload


def _validated_llm_plan(
    *,
    raw_query: str,
    payload: dict[str, Any],
    fallback: QuerySignalPlan,
    ocp_version: str,
    locale: str,
) -> QuerySignalPlan:
    normalized_query = _clean_text(payload.get("normalized_query"), fallback.normalized_query, max_chars=500)
    correction_notes = _validated_corrections(payload.get("correction_notes"))
    classification = _validated_classification(
        payload.get("classification"),
        fallback=fallback.classification,
        ocp_version=ocp_version,
        locale=locale,
    )
    search_signals = _validated_search_signals(payload.get("search_signals"), fallback.search_signals)
    confidence = _validated_confidence(payload.get("confidence"), fallback.confidence)
    _apply_domain_specific_enrichment(
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )
    normalized_signals = {
        key: tuple(dict.fromkeys(item for item in values if str(item or "").strip()))
        for key, values in search_signals.items()
    }
    embedding_queries = _validated_embedding_queries(
        payload.get("embedding_queries"),
        fallback=fallback.embedding_queries,
        normalized_query=normalized_query,
    )
    metadata_filter = _metadata_filter(
        classification=classification,
        confidence=confidence,
        ocp_version=ocp_version,
        locale=locale,
    )
    return QuerySignalPlan(
        raw_query=raw_query,
        normalized_query=normalized_query,
        correction_notes=correction_notes,
        classification=classification,
        search_signals=normalized_signals,
        confidence=confidence,
        embedding_queries=embedding_queries,
        metadata_filter=metadata_filter,
    )


def _clean_text(value: Any, default: str = "", *, max_chars: int = 300) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        cleaned = default
    return cleaned[:max_chars].strip()


def _validated_corrections(value: Any) -> tuple[QueryCorrection, ...]:
    if not isinstance(value, list):
        return ()
    corrections: list[QueryCorrection] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        correction_type = _clean_text(item.get("type"), "normalization", max_chars=40)
        source = _clean_text(item.get("from") or item.get("source"), max_chars=160)
        replacement = _clean_text(item.get("to") or item.get("replacement"), max_chars=160)
        if source and replacement and source != replacement:
            corrections.append(QueryCorrection(correction_type, source, replacement))
    return tuple(corrections)


def _validated_classification(
    value: Any,
    *,
    fallback: dict[str, Any],
    ocp_version: str,
    locale: str,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    domain = _clean_text(source.get("domain"), str(fallback.get("domain") or ""), max_chars=40)
    if domain not in _ALLOWED_DOMAINS:
        domain = str(fallback.get("domain") or "") if str(fallback.get("domain") or "") in _ALLOWED_DOMAINS else ""
    platform = _clean_text(source.get("platform"), str(fallback.get("platform") or "any_platform"), max_chars=40)
    if platform not in _ALLOWED_PLATFORMS:
        platform = "any_platform"
    return {
        "domain": domain,
        "domain_filter_values": _domain_filter_values(
            source.get("domain_filter_values"),
            fallback.get("domain_filter_values"),
            domain=domain,
        ),
        "book_slug_candidates": _string_tuple(source.get("book_slug_candidates"), fallback.get("book_slug_candidates")),
        "ocp_version": ocp_version,
        "locale": locale,
        "platform": platform,
    }


def _domain_filter_values(value: Any, fallback: Any, *, domain: str) -> tuple[str, ...]:
    raw_values = _string_tuple(value, fallback, max_items=4, max_chars=40)
    values = tuple(item for item in raw_values if item in _ALLOWED_DOMAINS)
    if values:
        return values
    return (domain,) if domain in _ALLOWED_DOMAINS else ()


def _validated_search_signals(value: Any, fallback: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, list[str]] = {}
    for key in _SEARCH_SIGNAL_KEYS:
        values = list(_string_tuple(source.get(key), fallback.get(key, ()), max_items=12, max_chars=120))
        if key == "intent_labels":
            values = [item for item in values if item in _ALLOWED_INTENT_LABELS]
        elif key == "answer_shapes":
            values = [item for item in values if item in _ALLOWED_ANSWER_SHAPES]
        elif key == "command_families":
            values = [item for item in values if item in _ALLOWED_COMMAND_FAMILIES]
        result[key] = values
    return result


def _validated_confidence(value: Any, fallback: dict[str, float]) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    result = dict(fallback)
    for key, raw in source.items():
        if not isinstance(key, str):
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        result[key] = min(1.0, max(0.0, score))
    return result


def _validated_embedding_queries(
    value: Any,
    *,
    fallback: tuple[str, ...],
    normalized_query: str,
) -> tuple[str, ...]:
    queries = _string_tuple(value, (), max_items=3, max_chars=300)
    queries = tuple(
        dict.fromkeys(
            query
            for query in (normalized_query, *queries)
            if str(query or "").strip()
        )
    )
    if not queries:
        queries = fallback
    if not queries:
        queries = (normalized_query,)
    return tuple(dict.fromkeys(query for query in queries if query))[:3]


def _string_tuple(
    value: Any,
    default: Any = (),
    *,
    max_items: int = 8,
    max_chars: int = 80,
) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list | tuple) else default
    items: list[str] = []
    if isinstance(raw_items, list | tuple):
        for item in raw_items:
            cleaned = _clean_text(item, max_chars=max_chars)
            if cleaned:
                items.append(cleaned)
    return tuple(dict.fromkeys(items))[:max_items]


def _normalize_query(query: str) -> tuple[str, tuple[QueryCorrection, ...]]:
    normalized = " ".join(str(query or "").split())
    corrections: list[QueryCorrection] = []
    for pattern, replacement, correction_type in _NORMALIZATION_RULES:
        next_value = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        if next_value != normalized:
            corrections.append(QueryCorrection(correction_type, normalized, next_value))
            normalized = next_value
    return normalized, tuple(corrections)


def _append(values: list[str], *items: str) -> None:
    for item in items:
        cleaned = " ".join(str(item or "").split())
        if cleaned and cleaned not in values:
            values.append(cleaned)


def _apply_domain_specific_enrichment(
    *,
    normalized_query: str,
    classification: dict[str, Any],
    search_signals: dict[str, list[str]],
    confidence: dict[str, float],
) -> None:
    lowered = normalized_query.lower()
    route_http_headers = (
        any(token in lowered for token in ("route", "routes", "라우트", "경로"))
        and any(token in lowered for token in ("http", "header", "headers", "헤더", "요청", "응답"))
    )
    objects = search_signals.setdefault("objects", [])
    commands = search_signals.setdefault("commands", [])
    command_families = search_signals.setdefault("command_families", [])
    error_states = search_signals.setdefault("error_states", [])
    intent_labels = search_signals.setdefault("intent_labels", [])
    answer_shapes = search_signals.setdefault("answer_shapes", [])
    primary_topics = search_signals.setdefault("primary_topics", [])
    secondary_topics = search_signals.setdefault("secondary_topics", [])
    cluster_phase = search_signals.setdefault("cluster_phase", [])
    execution_target = search_signals.setdefault("execution_target", [])
    components = search_signals.setdefault("components", [])

    if route_http_headers:
        classification["domain"] = "networking"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "ingress_and_load_balancing",
        )
        _append(objects, "Route")
        _append(primary_topics, "Route HTTP header configuration", "HTTP request header", "HTTP response header")
        _append(secondary_topics, "nw-route-set-or-delete-http-headers")
        _append(intent_labels, "configure_resource", "command_lookup")
        _append(answer_shapes, "command", "step_by_step")
        _append(commands, "oc -n app-example create -f app-example-route.yaml")
        _append(command_families, "oc_create")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.93)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)

    storage_lexicon = DOMAIN_LEXICONS["storage"]
    if query_matches_domain(normalized_query, "storage"):
        classification["domain"] = classification.get("domain") or storage_lexicon.domain
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            *storage_lexicon.book_slugs,
        )
        _append(objects, *storage_lexicon.objects)
        _append(primary_topics, *storage_lexicon.primary_topics)
        _append(secondary_topics, *storage_lexicon.secondary_topics)
        _append(commands, *storage_lexicon.commands)
        _append(command_families, *storage_lexicon.command_families)
        if query_matches_static_variant(normalized_query, "storage"):
            _append(primary_topics, "static provisioning")
        if query_matches_dynamic_variant(normalized_query, "storage"):
            _append(primary_topics, "dynamic provisioning")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.9)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.86)

    has_vsphere_storage = (
        any(token in lowered for token in ("vsphere", "vmware"))
        and query_matches_domain(normalized_query, "storage")
    )
    if has_vsphere_storage:
        classification["domain"] = "storage"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "storage",
        )
        _append(objects, "PV", "PVC", "StorageClass")
        _append(
            primary_topics,
            "VMware vSphere",
            "vSphere volume provisioning",
            "VMware vSphere CSI Driver",
        )
        _append(secondary_topics, "VMDK", "thin-csi", "storage provisioning")
        _append(components, "vSphere CSI Driver", "CSI Driver", "StorageClass")
        _append(intent_labels, "configure_resource", "create_resource", "command_lookup")
        _append(answer_shapes, "step_by_step", "command")
        _append(command_families, "oc_create", "oc_get")
        if query_matches_dynamic_variant(normalized_query, "storage"):
            _append(primary_topics, "dynamic provisioning")
            _append(secondary_topics, "thin StorageClass", "PersistentVolumeClaim")
        elif query_matches_static_variant(normalized_query, "storage"):
            _append(primary_topics, "static provisioning")
            _append(secondary_topics, "PersistentVolume", "PersistentVolumeClaim")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.94)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.93)

    if "etcd" in lowered and ("백업" in normalized_query or "backup" in lowered):
        classification["domain"] = "etcd"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "etcd",
            "backup_and_restore",
        )
        _append(primary_topics, "etcd", "etcd backup")
        _append(intent_labels, "backup", "identify_execution_target")
        _append(answer_shapes, "step_by_step", "command")
        _append(cluster_phase, "day2", "recovery")
        _append(execution_target, "control_plane_node")
        _append(commands, "oc debug node/<control-plane-node>", "chroot /host", "cluster-backup.sh")
        _append(command_families, "oc_debug")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.92)
        confidence["execution_target"] = max(confidence.get("execution_target", 0.0), 0.9)

    if "imagepullbackoff" in lowered:
        if not classification.get("domain"):
            classification["domain"] = "registry"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "images",
            "registry",
        )
        _append(objects, "Pod", "Secret")
        _append(primary_topics, "ImagePullBackOff", "pull secret", "container image registry")
        _append(error_states, "ImagePullBackOff")
        _append(intent_labels, "troubleshoot", "check_status")
        _append(answer_shapes, "troubleshooting_flow", "checklist", "command")
        _append(cluster_phase, "incident", "day2")
        _append(commands, "oc describe pod", "oc get secret")
        _append(command_families, "oc_describe", "oc_get")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.88)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.92)
        confidence["error_states"] = max(confidence.get("error_states", 0.0), 0.97)

    if "notready" in lowered and "node" in lowered:
        classification["domain"] = "node_ops"
        classification["domain_filter_values"] = ("node_ops", "troubleshooting")
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "nodes",
        )
        _append(objects, "Node")
        _append(primary_topics, "Node", "node status")
        _append(error_states, "NotReady")
        _append(intent_labels, "troubleshoot", "check_status")
        _append(answer_shapes, "checklist", "command", "troubleshooting_flow")
        _append(cluster_phase, "incident", "day2")
        _append(execution_target, "cluster_admin_cli")
        _append(commands, "oc get nodes", "oc describe node")
        _append(command_families, "oc_get", "oc_describe")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.91)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.94)
        confidence["error_states"] = max(confidence.get("error_states", 0.0), 0.95)

    if classification.get("domain") == "troubleshooting" and "imagepullbackoff" in lowered:
        classification["domain"] = "registry"
        classification["domain_filter_values"] = ("registry", "troubleshooting")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.88)

    if classification.get("domain") == "install":
        classification["platform"] = "any_platform"
        _append(primary_topics, "UPI", "Agent-based Installer", "installation method")
        _append(answer_shapes, "decision_guide")
        _append(intent_labels, "install", "compare_options")
        confidence["platform"] = max(confidence.get("platform", 0.0), 0.72)

    if commands:
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.82)
    if intent_labels:
        confidence["intent_labels"] = max(confidence.get("intent_labels", 0.0), 0.88)
    if answer_shapes:
        confidence["answer_shapes"] = max(confidence.get("answer_shapes", 0.0), 0.84)
    if objects:
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
    if "csi driver" in " ".join(components).lower():
        return
    if query_matches_domain(normalized_query, "storage"):
        _append(components, "CSI Driver", "scheduler")


def _tuple_append(values: Any, *items: str) -> tuple[str, ...]:
    result = [str(value) for value in values if str(value or "").strip()] if isinstance(values, tuple | list) else []
    _append(result, *items)
    return tuple(result)


def _metadata_filter(
    *,
    classification: dict[str, Any],
    confidence: dict[str, float],
    ocp_version: str,
    locale: str,
) -> dict[str, Any]:
    must: list[dict[str, Any]] = [
        {"key": "source.enabled_for_chat", "match": {"value": True}},
        {"key": "source.review_status", "match": {"value": "approved"}},
        {"key": "source.citation_eligible", "match": {"value": True}},
        {"key": "classification.locale", "match": {"value": locale}},
        {"key": "classification.ocp_version", "match": {"value": ocp_version}},
        {"key": "chunk.navigation_only", "match": {"value": False}},
    ]
    domain = str(classification.get("domain") or "").strip()
    domain_filter_values = tuple(
        dict.fromkeys(
            item
            for item in (
                classification.get("domain_filter_values")
                if isinstance(classification.get("domain_filter_values"), list | tuple)
                else ()
            )
            if str(item or "").strip() in _ALLOWED_DOMAINS
        )
    )
    if domain and confidence.get("domain", 0.0) >= 0.85 and len(domain_filter_values) <= 1:
        must.append({"key": "classification.domain", "match": {"value": domain}})
    platform = str(classification.get("platform") or "").strip()
    if platform and platform != "any_platform" and confidence.get("platform", 0.0) >= 0.9:
        must.append({"key": "classification.platform", "match": {"value": platform}})
    metadata_filter: dict[str, Any] = {"must": must}
    if domain and confidence.get("domain", 0.0) >= 0.85 and len(domain_filter_values) > 1:
        metadata_filter["should"] = [
            {"key": "classification.domain", "match": {"value": item}}
            for item in domain_filter_values
        ]
    return metadata_filter


def _embedding_queries(
    *,
    raw_query: str,
    normalized_query: str,
    baseline: StructuredQuerySignals,
    search_signals: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    objects = search_signals.get("objects", ())
    errors = search_signals.get("error_states", ())
    commands = search_signals.get("commands", ())
    command_families = search_signals.get("command_families", ())
    primary_topics = search_signals.get("primary_topics", ())
    secondary_topics = search_signals.get("secondary_topics", ())
    intents = search_signals.get("intent_labels", ())
    route_http_headers = (
        any(item.casefold() == "route" for item in objects)
        and any("header" in item.casefold() for item in (*primary_topics, *secondary_topics))
    )

    queries: list[str] = []
    english_terms = () if route_http_headers else _english_terms(objects=objects, errors=errors, primary_topics=primary_topics)
    _append(
        queries,
        " ".join(
            dict.fromkeys(
                item
                for item in (
                    normalized_query,
                    *primary_topics,
                    *objects,
                    *errors,
                    *(secondary_topics[:1] if route_http_headers else secondary_topics[:2]),
                )
                if item
            )
        ),
    )
    if commands or command_families or {"troubleshoot", "check_status"} & set(intents):
        _append(
            queries,
            " ".join(
                dict.fromkeys(
                    item
                    for item in (
                        raw_query,
                        *errors,
                        *(commands[:1] if route_http_headers else commands[:3]),
                        *(() if route_http_headers else command_families),
                        *english_terms,
                        "troubleshooting" if "troubleshoot" in intents else "",
                    )
                    if item
                )
            ),
        )
    if english_terms and len(queries) < 2:
        _append(queries, " ".join(english_terms))
    if len(queries) < 2:
        _append(queries, _domain_specific_baseline_vector_query(baseline.vector_query, objects=objects, primary_topics=primary_topics))
    return tuple(queries[:2])


def _domain_specific_baseline_vector_query(
    vector_query: str,
    *,
    objects: tuple[str, ...],
    primary_topics: tuple[str, ...],
) -> str:
    if not vector_query:
        return ""
    object_set = {item.casefold() for item in objects}
    topic_text = " ".join(primary_topics).casefold()
    if "route" in object_set and "header" in topic_text:
        allowed = ("route", "http", "header", "request", "response", "nw-route-set-or-delete-http-headers")
        return " ".join(dict.fromkeys(term for term in vector_query.split() if any(token in term.casefold() for token in allowed)))
    return vector_query


def _english_terms(
    *,
    objects: tuple[str, ...],
    errors: tuple[str, ...],
    primary_topics: tuple[str, ...],
) -> tuple[str, ...]:
    terms: list[str] = []
    object_set = {item.lower() for item in objects}
    error_set = {item.lower() for item in errors}
    topic_set = {item.lower() for item in primary_topics}
    if "pvc" in object_set:
        _append(terms, "PersistentVolumeClaim", "PVC", "volume binding", "storage provisioning")
    if "storageclass" in object_set or "storageclass" in topic_set:
        _append(terms, "StorageClass", "dynamic provisioning")
    if any("vsphere" in item for item in (*object_set, *topic_set)):
        _append(terms, "VMware vSphere", "vSphere CSI Driver", "VMDK", "thin-csi")
        if "dynamic provisioning" in topic_set:
            _append(terms, "PersistentVolumeClaim", "StorageClass", "dynamic provisioning")
        if "static provisioning" in topic_set:
            _append(terms, "PersistentVolume", "PersistentVolumeClaim", "static provisioning")
    if "etcd" in object_set or "etcd" in topic_set:
        _append(terms, "etcd backup", "control plane node", "cluster-backup.sh")
    if "pod" in object_set and "imagepullbackoff" in error_set:
        _append(terms, "Pod", "ImagePullBackOff", "pull secret", "image registry")
    if "node" in object_set and "notready" in error_set:
        _append(terms, "Node", "NotReady", "node condition", "kubelet")
    if "upi" in topic_set or "agent-based installer" in topic_set:
        _append(terms, "UPI", "Agent-based Installer", "installation method", "OpenShift")
    return tuple(terms)


__all__ = [
    "QueryCorrection",
    "QuerySignalPlan",
    "build_query_signal_plan",
]
