"""Lightweight query understanding for retrieval planning.

This module classifies user intent and proposes retrieval terms only. It must
not return user-facing answers or fixed question-answer pairs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_OPENSHIFT_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])|openshift|오픈\s*시프트|오픈시프트", re.IGNORECASE)
_INSTALL_RE = re.compile(r"설치|install|installation|installer|클러스터.*구축|구축.*클러스터", re.IGNORECASE)
_COMMAND_RE = re.compile(r"명령어|커맨드|command|cli|\boc\b|확인(?:해|하는|할)?", re.IGNORECASE)
_TROUBLE_RE = re.compile(
    r"오류|에러|왜이래|왜\s*이래|안\s*돼|안돼|실패|문제|장애|trouble|troubleshoot|fail|error|degraded|pending|crashloop",
    re.IGNORECASE,
)
_SECRET_CONFIG_RE = re.compile(r"secret|시크릿|configmap|config\s*map|컨피그맵|컨피그", re.IGNORECASE)
_NAMESPACE_RE = re.compile(r"namespace|namespaces|네임스페이스|project|projects|프로젝트", re.IGNORECASE)


# Keep readable UTF-8 Korean aliases in addition to older mojibake patterns.
# These are intent signals only; they do not map questions to fixed answers.
_OPENSHIFT_KO_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])|openshift|오픈\s*시프트|오픈시프트", re.IGNORECASE)
_INSTALL_KO_RE = re.compile(r"설치|구축|클러스터.*구성|구성.*클러스터|install|installation|installer", re.IGNORECASE)
_COMMAND_KO_RE = re.compile(r"명령어|명령|커맨드|command|cli|\boc\b|확인(?:하는|해|하려면|할 때)?", re.IGNORECASE)
_TROUBLE_KO_RE = re.compile(
    r"오류|에러|장애|문제|실패|안\s*돼|안\s*됨|안된다|왜\s*이래|트러블슈팅|원인|trouble|troubleshoot|fail|error|degraded|pending|crashloop",
    re.IGNORECASE,
)
_SECRET_CONFIG_KO_RE = re.compile(
    r"secret|시크릿|configmap|config\s*map|컨피그맵|컨피그",
    re.IGNORECASE,
)
_NAMESPACE_KO_RE = re.compile(r"namespace|namespaces|네임스페이스|프로젝트|project|projects", re.IGNORECASE)

_DEPLOYMENT_YAML_AUTHORING_RE = re.compile(
    r"(?:deployment|deploy|배포|디플로이먼트).*(?:yaml|manifest|매니페스트|작성|생성|만들|명령|apply|create)"
    r"|(?:yaml|manifest|매니페스트).*(?:deployment|deploy|배포|디플로이먼트)",
    re.IGNORECASE,
)
_POD_RESOURCE_INSPECTION_RE = re.compile(
    r"(?:pod|pods|파드).*(?:resource|usage|cpu|memory|메모리|리소스|자원|사용량|top)"
    r"|(?:resource|usage|cpu|memory|메모리|리소스|자원|사용량|top).*(?:pod|pods|파드)",
    re.IGNORECASE,
)
_SERVICE_FAILURE_DIAGNOSIS_RE = re.compile(
    r"(?:service|services|svc|서비스).*(?:장애|오류|에러|안\s*됨|안됨|접속|연결|원인|trouble|fail|error|endpoint)"
    r"|(?:endpoint|route|selector).*(?:장애|오류|에러|안\s*됨|안됨|접속|연결|원인|trouble|fail|error)",
    re.IGNORECASE,
)
_NAMESPACE_CREATE_RE = re.compile(
    r"(?:namespace|namespaces|project|projects|네임스페이스|프로젝트).*(?:create|new|make|만들|만드|생성|추가)"
    r"|(?:create|new|make|만들|만드|생성|추가).*(?:namespace|namespaces|project|projects|네임스페이스|프로젝트)",
    re.IGNORECASE,
)
_PVC_RE = re.compile(r"(?<![a-z0-9])PVC(?![a-z0-9])|persistent\s*volume\s*claim|퍼시스턴트\s*볼륨\s*클레임", re.IGNORECASE)
_PV_RE = re.compile(r"(?<![a-z0-9])PV(?![a-z0-9])|persistent\s*volume(?!\s*claim)|퍼시스턴트\s*볼륨", re.IGNORECASE)
_VSPHERE_RE = re.compile(r"vsphere|vmware", re.IGNORECASE)
_STORAGE_VOLUME_RE = re.compile(r"볼륨|volume|스토리지|storage|프로비저닝|provision", re.IGNORECASE)
_POD_RE = re.compile(r"(?<![a-z0-9])pods?(?![a-z0-9])|파드", re.IGNORECASE)
_ROUTE_RE = re.compile(r"(?<![a-z0-9])routes?(?![a-z0-9])|라우트", re.IGNORECASE)
_ROUTE_HTTP_HEADER_RE = re.compile(
    r"(?:route|routes|라우트|경로).*(?:http|헤더|header|요청|응답)"
    r"|(?:http|헤더|header|요청|응답).*(?:route|routes|라우트|경로)",
    re.IGNORECASE,
)
_ETCD_RE = re.compile(r"\betcd\b", re.IGNORECASE)
_MCO_RE = re.compile(r"machine\s*config\s*operator|\bMCO\b|머신\s*구성\s*오퍼레이터", re.IGNORECASE)
_RBAC_RE = re.compile(r"\brbac\b|rolebinding|clusterrolebinding|권한|롤바인딩", re.IGNORECASE)
_PENDING_RE = re.compile(r"(?<![a-z0-9])Pending(?![a-z0-9])|펜딩|대기", re.IGNORECASE)
_IMAGE_PULL_RE = re.compile(r"ImagePullBackOff|ErrImagePull|이미지.*풀|이미지.*가져", re.IGNORECASE)
_NOT_READY_RE = re.compile(r"\bNotReady\b|not\s*ready|준비.*안|레디.*안", re.IGNORECASE)
_BACKUP_RE = re.compile(r"backup|백업|스냅샷|snapshot", re.IGNORECASE)
_RESTORE_RE = re.compile(r"restore|복구|복원", re.IGNORECASE)
_COMPARE_RE = re.compile(r"차이|비교|compare|versus|vs\.?", re.IGNORECASE)
_EXECUTION_TARGET_RE = re.compile(r"어느\s*노드|어디서\s*실행|실행\s*위치|where.*run|which.*node", re.IGNORECASE)
_UPI_RE = re.compile(r"(?<![a-z0-9])UPI(?![a-z0-9])|user[- ]provisioned|사용자.*인프라", re.IGNORECASE)
_AGENT_BASED_RE = re.compile(r"agent[- ]based|에이전트", re.IGNORECASE)
_YAML_RE = re.compile(r"yaml|매니페스트|manifest", re.IGNORECASE)

INTENT_LABELS: tuple[str, ...] = (
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
)

ANSWER_SHAPES: tuple[str, ...] = (
    "short_explanation",
    "step_by_step",
    "command",
    "checklist",
    "yaml_example",
    "decision_guide",
    "warning",
    "troubleshooting_flow",
    "document_link",
)


@dataclass(frozen=True, slots=True)
class QueryUnderstanding:
    intents: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    answer_shape: str = "grounded_explanation"

    def has_intent(self, intent: str) -> bool:
        return intent in self.intents


@dataclass(frozen=True, slots=True)
class StructuredQuerySignals:
    raw_query: str
    normalized_query: str
    classification: dict[str, Any]
    search_signals: dict[str, tuple[str, ...]]
    confidence: dict[str, float]
    metadata_filter: dict[str, Any]
    vector_query: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "normalized_query": self.normalized_query,
            "classification": dict(self.classification),
            "search_signals": {key: list(value) for key, value in self.search_signals.items()},
            "confidence": dict(self.confidence),
            "metadata_filter": self.metadata_filter,
            "vector_query": self.vector_query,
        }


def understand_query(query: str) -> QueryUnderstanding:
    text = " ".join(str(query or "").split())
    lowered = text.lower()
    intents: list[str] = []
    terms: list[str] = []
    answer_shape = "grounded_explanation"

    openshift = bool(_OPENSHIFT_RE.search(text) or _OPENSHIFT_KO_RE.search(text))
    install = bool(_INSTALL_RE.search(text) or _INSTALL_KO_RE.search(text))
    command = bool(_COMMAND_RE.search(text) or _COMMAND_KO_RE.search(text))
    troubleshooting = bool(_TROUBLE_RE.search(text) or _TROUBLE_KO_RE.search(text))
    secret_config = bool(_SECRET_CONFIG_RE.search(text) or _SECRET_CONFIG_KO_RE.search(text))
    namespace = bool(_NAMESPACE_RE.search(text) or _NAMESPACE_KO_RE.search(text))
    deployment_yaml = bool(_DEPLOYMENT_YAML_AUTHORING_RE.search(text))
    pod_resource = bool(_POD_RESOURCE_INSPECTION_RE.search(text))
    service_failure = bool(_SERVICE_FAILURE_DIAGNOSIS_RE.search(text))
    namespace_create = bool(_NAMESPACE_CREATE_RE.search(text))

    if openshift:
        _append_terms(terms, ["OpenShift Container Platform", "OCP", "OpenShift"])
    if openshift and install:
        intents.append("install_overview")
        answer_shape = "beginner_install_overview"
        _append_terms(
            terms,
            [
                "installation overview",
                "installing a cluster",
                "installation methods",
                "Assisted Installer",
                "Agent-based Installer",
                "Single Node OpenShift",
                "SNO",
                "IPI",
                "UPI",
                "pull secret",
                "openshift-install",
                "kubeconfig",
                "설치 개요",
                "클러스터 설치",
            ],
        )
    if command or any(token in lowered for token in ("어떻게 확인", "확인하는", "확인할")):
        intents.append("command_lookup")
        answer_shape = "command_with_judgement"
        _append_terms(terms, ["oc", "CLI", "command", "명령어", "상태 확인", "판단 기준"])
    if troubleshooting:
        intents.append("troubleshooting")
        answer_shape = "troubleshooting_steps"
        _append_terms(terms, ["troubleshooting", "events", "describe", "logs", "status", "condition", "원인", "조치"])
    if secret_config:
        intents.append("secret_config_troubleshooting" if troubleshooting else "secret_config_concept")
        _append_terms(
            terms,
            [
                "Secret",
                "Secrets",
                "ConfigMap",
                "configuration",
                "environment variables",
                "volume mount",
                "oc describe secret",
                "oc get secret",
                "oc describe configmap",
                "oc get configmap",
            ],
        )
    if namespace:
        intents.append("namespace_or_project")
        _append_terms(
            terms,
            [
                "namespace",
                "namespaces",
                "project",
                "projects",
                "oc get namespaces",
                "oc get projects",
                "oc project",
            ],
        )
    if deployment_yaml:
        intents.append("deployment_yaml_authoring")
        answer_shape = "command_with_judgement" if command else "grounded_explanation"
        _append_terms(
            terms,
            [
                "Deployment",
                "kind: Deployment",
                "Deployment manifest",
                "YAML",
                "Pod template",
                "ReplicaSet",
                "oc apply -f",
                "oc create deployment",
                "oc rollout status deployment",
            ],
        )
    if pod_resource:
        intents.append("pod_resource_inspection")
        answer_shape = "command_with_judgement"
        _append_terms(
            terms,
            [
                "resource usage",
                "CPU",
                "memory",
                "requests",
                "limits",
                "oc adm top pods",
                "oc top pod",
                "metrics",
            ],
        )
    if service_failure:
        intents.append("service_failure_diagnosis")
        answer_shape = "troubleshooting_steps"
        _append_terms(
            terms,
            [
                "Service",
                "Endpoint",
                "EndpointSlice",
                "Route",
                "selector",
                "targetPort",
                "oc describe service",
                "oc get endpoints",
                "oc describe route",
            ],
        )
    if namespace_create:
        intents.append("namespace_create")
        answer_shape = "command_with_judgement"
        _append_terms(
            terms,
            [
                "Namespace",
                "Project",
                "oc create namespace",
                "oc new-project",
                "kind: Namespace",
            ],
        )
    if not intents and openshift:
        intents.append("concept_explanation")
    return QueryUnderstanding(
        intents=tuple(dict.fromkeys(intents)),
        retrieval_terms=tuple(dict.fromkeys(terms)),
        answer_shape=answer_shape,
    )


def understand_query_signals(
    query: str,
    *,
    ocp_version: str = "4.20",
    locale: str = "ko",
) -> StructuredQuerySignals:
    raw_query = " ".join(str(query or "").split())
    legacy = understand_query(raw_query)
    domains: list[str] = []
    book_slug_candidates: list[str] = []
    objects: list[str] = []
    error_states: list[str] = []
    intent_labels: list[str] = []
    answer_shapes: list[str] = []
    command_families: list[str] = []
    primary_topics: list[str] = []
    cluster_phase: list[str] = []
    execution_target: list[str] = []
    confidence: dict[str, float] = {}

    def add_intent(value: str) -> None:
        if value in INTENT_LABELS:
            _append_unique(intent_labels, value)

    def add_shape(value: str) -> None:
        if value in ANSWER_SHAPES:
            _append_unique(answer_shapes, value)

    if _PVC_RE.search(raw_query):
        _append_unique(objects, "PVC")
        _append_unique(primary_topics, "PVC")
        _append_unique(domains, "storage")
        _append_unique(book_slug_candidates, "storage")
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.95)
    if _PV_RE.search(raw_query):
        _append_unique(objects, "PV")
        _append_unique(primary_topics, "Persistent Volume")
        _append_unique(domains, "storage")
        _append_unique(book_slug_candidates, "storage")
    if _VSPHERE_RE.search(raw_query) and _STORAGE_VOLUME_RE.search(raw_query):
        _append_unique(domains, "storage")
        _append_unique(book_slug_candidates, "storage")
        _append_unique(primary_topics, "VMware vSphere")
        _append_unique(primary_topics, "vSphere volume provisioning")
        _append_unique(objects, "PV")
        if "pvc" in raw_query.lower() or "클레임" in raw_query:
            _append_unique(objects, "PVC")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.93)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.88)
    if _POD_RE.search(raw_query):
        _append_unique(objects, "Pod")
        _append_unique(primary_topics, "Pod")
    if _ROUTE_RE.search(raw_query):
        _append_unique(objects, "Route")
        _append_unique(primary_topics, "Route")
        _append_unique(domains, "networking")
    if _ROUTE_HTTP_HEADER_RE.search(raw_query):
        _append_unique(objects, "Route")
        _append_unique(primary_topics, "Route HTTP header configuration")
        _append_unique(primary_topics, "HTTP request header")
        _append_unique(primary_topics, "HTTP response header")
        _append_unique(domains, "networking")
        _append_unique(book_slug_candidates, "ingress_and_load_balancing")
        _append_unique(intent_labels, "configure_resource")
        _append_unique(intent_labels, "command_lookup")
        _append_unique(answer_shapes, "command")
        _append_unique(command_families, "oc_create")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.93)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
    if _ETCD_RE.search(raw_query):
        _append_unique(objects, "etcd")
        _append_unique(primary_topics, "etcd")
        _append_unique(domains, "etcd")
        _append_unique(book_slug_candidates, "etcd")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.92)
    if _MCO_RE.search(raw_query):
        _append_unique(primary_topics, "Machine Config Operator")
        _append_unique(domains, "node_ops")
        _append_unique(book_slug_candidates, "machine_configuration")
    if _RBAC_RE.search(raw_query):
        _append_unique(domains, "security")
        _append_unique(book_slug_candidates, "authentication_and_authorization")

    if _PENDING_RE.search(raw_query):
        _append_unique(error_states, "Pending")
    if _IMAGE_PULL_RE.search(raw_query):
        _append_unique(error_states, "ImagePullBackOff")
    if _NOT_READY_RE.search(raw_query):
        _append_unique(error_states, "NotReady")
    if error_states:
        confidence["error_states"] = 0.93
        add_intent("troubleshoot")
        add_shape("troubleshooting_flow")
        _append_unique(cluster_phase, "incident")

    command_requested = "command_lookup" in legacy.intents or bool(_COMMAND_KO_RE.search(raw_query))
    if command_requested:
        add_intent("command_lookup")
        add_shape("command")
        _append_unique(command_families, "oc_get")
        if error_states or _TROUBLE_KO_RE.search(raw_query):
            _append_unique(command_families, "oc_describe")
    if _TROUBLE_KO_RE.search(raw_query) or error_states:
        add_intent("troubleshoot")
        add_shape("checklist")
        _append_unique(cluster_phase, "day2")
    if "확인" in raw_query or "check" in raw_query.lower():
        add_intent("check_status")
        add_shape("checklist")
        _append_unique(command_families, "oc_get")
        if error_states:
            _append_unique(command_families, "oc_describe")
    if _BACKUP_RE.search(raw_query):
        add_intent("backup")
        _append_unique(cluster_phase, "day2")
        _append_unique(cluster_phase, "recovery")
    if _RESTORE_RE.search(raw_query):
        add_intent("restore")
        _append_unique(cluster_phase, "recovery")
    if _INSTALL_KO_RE.search(raw_query) or _UPI_RE.search(raw_query) or _AGENT_BASED_RE.search(raw_query):
        add_intent("install")
        _append_unique(domains, "install")
        _append_unique(cluster_phase, "pre_install")
        if _UPI_RE.search(raw_query):
            _append_unique(book_slug_candidates, "installing_on_any_platform")
        if _AGENT_BASED_RE.search(raw_query):
            _append_unique(book_slug_candidates, "installation_overview")
    if _COMPARE_RE.search(raw_query):
        add_intent("compare_options")
        add_shape("decision_guide")
    if _EXECUTION_TARGET_RE.search(raw_query):
        add_intent("identify_execution_target")
        add_shape("short_explanation")
        if _ETCD_RE.search(raw_query):
            _append_unique(execution_target, "control_plane_node")
    if _YAML_RE.search(raw_query):
        add_shape("yaml_example")
        add_intent("create_resource")

    if not intent_labels:
        add_intent("explain_concept")
        add_shape("short_explanation")

    if not answer_shapes:
        add_shape("short_explanation")

    domain = _first_domain(domains)
    if domain and "domain" not in confidence:
        confidence["domain"] = 0.91 if domain in {"storage", "install", "security", "node_ops"} else 0.82
    if book_slug_candidates:
        confidence["book_slug_candidates"] = 0.72
    if intent_labels:
        confidence["intent_labels"] = 0.88
    if answer_shapes:
        confidence["answer_shapes"] = 0.84
    if command_families:
        confidence["command_families"] = 0.73

    classification: dict[str, Any] = {
        "domain": domain,
        "book_slug_candidates": tuple(book_slug_candidates),
        "ocp_version": ocp_version,
        "locale": locale,
    }
    search_signals: dict[str, tuple[str, ...]] = {
        "objects": tuple(objects),
        "error_states": tuple(error_states),
        "intent_labels": tuple(intent_labels),
        "answer_shapes": tuple(answer_shapes),
        "command_families": tuple(command_families),
        "primary_topics": tuple(primary_topics),
        "cluster_phase": tuple(cluster_phase),
        "execution_target": tuple(execution_target),
    }
    normalized_query = raw_query
    vector_terms = [
        raw_query,
        *primary_topics,
        *objects,
        *error_states,
        *command_families,
        *legacy.retrieval_terms,
    ]
    vector_query = " ".join(dict.fromkeys(term for term in vector_terms if term))
    metadata_filter = _metadata_filter_for_signals(classification, confidence)
    return StructuredQuerySignals(
        raw_query=raw_query,
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
        metadata_filter=metadata_filter,
        vector_query=vector_query,
    )


def _append_terms(target: list[str], values: list[str]) -> None:
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if cleaned:
            target.append(cleaned)


def _append_unique(target: list[str], value: str) -> None:
    cleaned = " ".join(str(value or "").split())
    if cleaned and cleaned not in target:
        target.append(cleaned)


def _first_domain(domains: list[str]) -> str:
    for preferred in (
        "etcd",
        "backup_restore",
        "storage",
        "install",
        "security",
        "networking",
        "node_ops",
        "monitoring",
        "operators",
    ):
        if preferred in domains:
            return preferred
    return domains[0] if domains else ""


def _metadata_filter_for_signals(
    classification: dict[str, Any],
    confidence: dict[str, float],
) -> dict[str, Any]:
    must: list[dict[str, Any]] = [
        {"key": "source.enabled_for_chat", "match": {"value": True}},
        {"key": "source.review_status", "match": {"value": "approved"}},
        {"key": "source.citation_eligible", "match": {"value": True}},
        {"key": "classification.locale", "match": {"value": classification.get("locale", "ko")}},
        {
            "key": "classification.ocp_version",
            "match": {"value": classification.get("ocp_version", "4.20")},
        },
        {"key": "chunk.navigation_only", "match": {"value": False}},
    ]
    domain = str(classification.get("domain") or "")
    if domain and confidence.get("domain", 0.0) >= 0.85:
        must.append({"key": "classification.domain", "match": {"value": domain}})
    return {"must": must}


def has_beginner_troubleshooting_intent(query: str) -> bool:
    understanding = understand_query(query)
    return understanding.has_intent("troubleshooting") or understanding.has_intent("secret_config_troubleshooting")


__all__ = [
    "ANSWER_SHAPES",
    "INTENT_LABELS",
    "QueryUnderstanding",
    "StructuredQuerySignals",
    "has_beginner_troubleshooting_intent",
    "understand_query",
    "understand_query_signals",
]
