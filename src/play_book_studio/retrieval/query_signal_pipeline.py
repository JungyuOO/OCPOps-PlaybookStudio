"""One-shot query signal planning for the RAG retrieval pipeline.

This layer turns a user question into retrieval-only signals. It does not
answer the user and it does not call a separate intent-agent service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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
    rank_signals: dict[str, tuple[str, ...]]

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
            "rank_signals": {key: list(value) for key, value in self.rank_signals.items()},
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


def build_query_signal_plan(
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
    rank_signals = _rank_signals(classification, normalized_signals)
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
        rank_signals=rank_signals,
    )


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

    if "pvc" in lowered:
        _append(objects, "PVC", "StorageClass")
        _append(primary_topics, "PVC", "StorageClass")
        _append(secondary_topics, "volume binding", "storage provisioning")
        _append(commands, "oc get pvc", "oc describe pvc")
        _append(command_families, "oc_get", "oc_describe")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.86)

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
    if "pvc" in lowered:
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
    if domain and confidence.get("domain", 0.0) >= 0.85:
        must.append({"key": "classification.domain", "match": {"value": domain}})
    platform = str(classification.get("platform") or "").strip()
    if platform and platform != "any_platform" and confidence.get("platform", 0.0) >= 0.9:
        must.append({"key": "classification.platform", "match": {"value": platform}})
    return {"must": must}


def _rank_signals(
    classification: dict[str, Any],
    search_signals: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    return {
        "book_slug_candidates": tuple(classification.get("book_slug_candidates") or ()),
        "objects": search_signals.get("objects", ()),
        "commands": search_signals.get("commands", ()),
        "command_families": search_signals.get("command_families", ()),
        "error_states": search_signals.get("error_states", ()),
        "intent_labels": search_signals.get("intent_labels", ()),
        "answer_shapes": search_signals.get("answer_shapes", ()),
        "cluster_phase": search_signals.get("cluster_phase", ()),
        "execution_target": search_signals.get("execution_target", ()),
    }


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

    queries: list[str] = []
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
                    *secondary_topics[:2],
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
                        *commands[:3],
                        *command_families,
                        "troubleshooting" if "troubleshoot" in intents else "",
                    )
                    if item
                )
            ),
        )
    english_terms = _english_terms(objects=objects, errors=errors, primary_topics=primary_topics)
    if english_terms:
        _append(queries, " ".join(english_terms))
    _append(queries, baseline.vector_query)
    return tuple(queries[:3])


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
