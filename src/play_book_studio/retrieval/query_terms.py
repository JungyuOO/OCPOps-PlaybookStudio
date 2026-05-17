from __future__ import annotations

# 질문 본문에 retrieval 보조 용어를 주입하는 façade다.
# 실제 규칙은 공통 개념/운영형/etcd 특수 규칙으로 나눠 관리한다.

from .text_utils import (
    append_terms as _append_terms,
    collapse_spaces as _collapse_spaces,
    contains_hangul as _contains_hangul,
)
from .query_terms_core import append_core_query_terms
from .query_terms_etcd import append_etcd_query_terms
from .query_terms_operations import append_operation_query_terms
from .query_understanding import understand_query
from .concept_expansion import expand_query_terms
from .cross_lingual import cross_lingual_rewrite_terms
from .intent_profile import build_intent_profile


_KOREAN_QUERY_TECH_TERM_ALLOWLIST = {
    "openshift",
    "kubernetes",
    "operator",
    "operators",
    "networking",
    "route",
    "ingress",
    "rbac",
    "yaml",
    "oc",
    "oc project",
    "oc config view",
    "oc get namespace",
    "oc get namespaces",
    "oc get project",
    "oc get projects",
    "oc create namespace",
    "oc create -f",
    "oc delete localvolume",
    "oc delete localvolumeset",
    "oc delete localvolumediscovery",
    "oc edit hpa",
    "oc get all",
    "oc delete vpa",
    "oc delete crd",
    "oc delete namespace",
    "oc create route",
    "oc expose route",
    "oc edit ingresses.config.openshift.io/cluster",
    "oc delete secrets kubeadmin",
    "oc login",
    "oc adm catalog build",
    "oc new-project",
    "oc new-app",
    "oc api-resources",
    "oc get csr",
    "oc adm certificate approve",
    "oc get clusteroperators",
    "oc get nodes",
    "oc describe node",
    "oc describe node <node-name>",
    "oc get mcp",
    "oc debug node",
    "admin",
    "edit",
    "view",
    "cluster-admin",
    "rolebinding",
    "clusterrolebinding",
    "namespace",
    "namespaces",
    "project",
    "projects",
    "pod",
    "pods",
    "node",
    "nodes",
    "drain",
    "top",
    "oc top pod",
    "oc adm top pods",
    "resource usage",
    "memory",
    "utilization",
    "requests",
    "limits",
    "metrics",
    "describe",
    "service",
    "services",
    "svc",
    "endpoint",
    "endpoints",
    "endpointslice",
    "selector",
    "targetport",
    "oc describe service",
    "oc get endpoints",
    "oc describe route",
    "deployment",
    "deployments",
    "deployment manifest",
    "pod template",
    "replicaset",
    "oc apply -f",
    "oc create deployment",
    "oc rollout status deployment",
    "replicas",
    "scale",
    "backup",
    "restore",
    "quorum",
    "administrator perspective",
    "machineconfigpool",
    "clusteroperator",
    "clusteroperators",
    "machineconfig",
    "mcp",
    "finalizer",
    "finalizers",
    "error resolving",
    "uncordon",
    "chroot",
    "chroot /host",
    "control",
    "control plane",
    "cluster architecture",
    "cluster status",
    "console overview",
    "bootstrap-complete",
    "compute",
    "compute node",
    "configmap",
    "configmaps",
    "developer perspective",
    "gunzip",
    "integritylog",
    "secret",
    "secrets",
    "troubleshooting",
    "events",
    "condition",
    "perspective",
    "plane",
    "worker",
    "worker node",
    "workloads",
}


def _filter_terms_for_korean_query(query: str, terms: list[str]) -> list[str]:
    lowered_query = (query or "").lower()
    filtered: list[str] = []

    for term in terms:
        cleaned = _collapse_spaces(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if _contains_hangul(cleaned):
            filtered.append(cleaned)
            continue
        if lowered in lowered_query:
            filtered.append(cleaned)
            continue
        if lowered in _KOREAN_QUERY_TECH_TERM_ALLOWLIST:
            filtered.append(cleaned)
            continue
        if any(char.isupper() for char in cleaned) or any(char.isdigit() for char in cleaned):
            filtered.append(cleaned)
            continue
        if any(marker in cleaned for marker in ("-", "/", "_", ".", "<", ">")):
            filtered.append(cleaned)
            continue

    return filtered


def normalize_query(query: str) -> str:
    normalized = _collapse_spaces(query)
    if not normalized:
        return normalized

    terms: list[str] = []
    terms.extend(understand_query(normalized).retrieval_terms)
    terms.extend(cross_lingual_rewrite_terms(normalized))
    terms.extend(expand_query_terms(normalized))
    append_core_query_terms(normalized, terms)
    append_operation_query_terms(normalized, terms)
    append_etcd_query_terms(normalized, terms)
    terms = _prune_terms_for_intent(normalized, terms)
    terms = _prioritize_phrase_terms(terms)
    if _contains_hangul(normalized):
        terms = _filter_terms_for_korean_query(normalized, terms)

    return _append_terms(normalized, terms)


def _prune_terms_for_intent(query: str, terms: list[str]) -> list[str]:
    profile = build_intent_profile(query)
    if _has_web_console_doc_intent(query):
        return _prune_web_console_doc_terms(query, terms)
    if _has_architecture_node_role_intent(query):
        return _prune_architecture_node_role_terms(query, terms)
    if _has_file_integrity_log_extract_intent(query):
        return _prune_file_integrity_log_terms(query, terms)
    if _has_postinstall_cluster_status_intent(query):
        return _prune_postinstall_cluster_status_terms(query, terms)
    if _has_clusteroperator_status_intent(query):
        return _prune_clusteroperator_status_terms(query, terms)
    if profile.target_object != "route-http-headers":
        return terms

    allowed_fragments = (
        "route",
        "http",
        "header",
        "request",
        "response",
        "app-example",
        "nw-route-set-or-delete-http-headers",
        "oc -n app-example create -f app-example-route.yaml",
        "set or delete",
    )
    blocked = {
        "secret",
        "secrets",
        "configmap",
        "configmaps",
        "ingress",
        "service",
        "services",
        "tls",
        "registry",
        "odf",
        "ceph",
        "rgw",
        "openshift",
        "kubernetes",
        "ocp",
    }
    pruned: list[str] = []
    for term in (*profile.query_terms, *terms):
        cleaned = _collapse_spaces(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in blocked or any(lowered == item or lowered.startswith(f"{item} ") for item in blocked):
            continue
        if any(fragment in lowered for fragment in allowed_fragments):
            pruned.append(cleaned)
    return pruned


def _has_file_integrity_log_extract_intent(query: str) -> bool:
    lowered = (query or "").lower()
    return (
        ("integritylog" in lowered or "file integrity operator" in lowered)
        and any(token in query for token in ("로그", "압축", "해제", "확인", "명령"))
    )


def _has_web_console_doc_intent(query: str) -> bool:
    lowered = (query or "").lower()
    return (
        any(token in query for token in ("웹 콘솔", "콘솔"))
        and any(token in lowered for token in ("문서", "설명", "기능", "workload", "workloads", "상태"))
    )


def _has_architecture_node_role_intent(query: str) -> bool:
    lowered = (query or "").lower()
    return (
        any(token in query for token in ("아키텍처", "구조"))
        and any(token in lowered for token in ("control plane", "컨트롤 플레인"))
        and any(token in query for token in ("컴퓨팅 노드", "작업자 노드", "노드"))
        and any(token in query for token in ("역할", "각각", "구성"))
    )


def _has_clusteroperator_status_intent(query: str) -> bool:
    lowered = (query or "").lower()
    compact = lowered.replace(" ", "")
    return (
        "clusteroperator" in compact
        or "clusteroperators" in compact
        or "cluster operator" in lowered
        or "클러스터operator" in compact
        or "클러스터오퍼레이터" in compact
    ) and any(token in lowered for token in ("상태", "확인", "status", "degraded", "available", "progressing"))


def _has_postinstall_cluster_status_intent(query: str) -> bool:
    lowered = (query or "").lower()
    return (
        any(token in query for token in ("설치 후", "설치후"))
        and any(token in lowered for token in ("clusteroperator", "cluster operator", "operator", "오퍼레이터"))
        and any(token in query for token in ("노드", "node"))
        and any(token in query for token in ("상태", "확인", "절차"))
    )


def _prune_web_console_doc_terms(query: str, terms: list[str]) -> list[str]:
    blocked_fragments = (
        "cli",
        "oc",
        "oc cli",
        "oc get",
        "oc describe",
        "command",
        "명령어",
        "판단 기준",
    )
    allowed_terms = _filter_blocked_terms(terms, blocked_fragments)
    allowed_terms.extend(
        [
            "web console",
            "OpenShift web console",
            "웹 콘솔",
            "Administrator perspective",
            "Developer perspective",
            "cluster status",
            "workloads",
            "console overview",
        ]
    )
    return allowed_terms


def _prune_architecture_node_role_terms(query: str, terms: list[str]) -> list[str]:
    blocked_fragments = (
        "debug",
        "node /",
        "notready",
        "oc debug",
        "oc describe node",
        "oc get nodes",
        "ready",
        "troubleshooting",
        "상태 확인",
        "판단 기준",
    )
    allowed_terms = _filter_blocked_terms(terms, blocked_fragments)
    allowed_terms.extend(
        [
            "architecture",
            "아키텍처",
            "control plane",
            "컨트롤 플레인",
            "compute node",
            "컴퓨팅 노드",
            "worker node",
            "cluster architecture",
        ]
    )
    return allowed_terms


def _prune_file_integrity_log_terms(query: str, terms: list[str]) -> list[str]:
    blocked_fragments = (
        "catalogsource",
        "clusterserviceversion",
        "installplan",
        "lifecycle manager",
        "olm",
        "oc logs",
        "operator /",
        "operator framework",
        "operators",
        "pod-name",
        "previous",
        "subscription",
        "운영",
        "관리",
    )
    allowed_terms = _filter_blocked_terms(terms, blocked_fragments)
    allowed_terms.extend(
        [
            "File Integrity Operator",
            "integritylog",
            "base64 -d",
            "gunzip",
            "AIDE",
        ]
    )
    return allowed_terms


def _prune_clusteroperator_status_terms(query: str, terms: list[str]) -> list[str]:
    blocked_fragments = _olm_operator_fragments()
    allowed_terms = _filter_blocked_terms(terms, blocked_fragments)
    allowed_terms.extend(
        [
            "ClusterOperator",
            "clusteroperators",
            "oc get clusteroperators",
            "Available Progressing Degraded",
        ]
    )
    return allowed_terms


def _prune_postinstall_cluster_status_terms(query: str, terms: list[str]) -> list[str]:
    blocked_fragments = (
        *_olm_operator_fragments(),
        "agent-based installer",
        "assisted installer",
        "debug",
        "describe node",
        "installing a cluster",
        "installation methods",
        "installation overview",
        "kubeconfig",
        "openshift-install",
        "pull secret",
        "single node openshift",
        "sno",
        "upi",
        "ipi",
        "클러스터 설치",
        "설치 개요",
        "설치 프로그램",
    )
    allowed_terms = _filter_blocked_terms(terms, blocked_fragments)
    allowed_terms.extend(
        [
            "ClusterOperator",
            "ClusterOperators",
            "clusteroperators",
            "oc get clusteroperators",
            "oc get ClusterOperators",
            "Available Progressing Degraded",
            "Node",
            "oc get nodes",
            "Ready NotReady",
            "모든 노드가 준비",
            "클러스터 Operator를 모두 사용할 수",
            "postinstallation",
            "cluster status",
        ]
    )
    return allowed_terms


def _olm_operator_fragments() -> tuple[str, ...]:
    return (
        "catalogsource",
        "clusterserviceversion",
        "installplan",
        "operator /",
        "operator framework",
        "operator lifecycle manager",
        "operators",
        "subscription",
        "oc get csv",
        "oc get subscription",
        "olm",
    )


def _filter_blocked_terms(terms: list[str], blocked_fragments: tuple[str, ...]) -> list[str]:
    filtered: list[str] = []
    for term in terms:
        cleaned = _collapse_spaces(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(fragment in lowered for fragment in blocked_fragments):
            continue
        filtered.append(cleaned)
    return filtered


def _prioritize_phrase_terms(terms: list[str]) -> list[str]:
    command_terms: list[str] = []
    technical_phrases: list[str] = []
    rest: list[str] = []
    for term in terms:
        cleaned = _collapse_spaces(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered.startswith("oc "):
            command_terms.append(cleaned)
        elif " " in cleaned or ":" in cleaned:
            technical_phrases.append(cleaned)
        else:
            rest.append(cleaned)
    command_priority = {
        "oc create namespace": 0,
        "oc new-project": 1,
        "oc new-app": 2,
        "oc create -f": 3,
        "oc edit hpa": 4,
        "oc get all": 5,
        "oc delete vpa": 6,
        "oc delete crd": 7,
        "oc delete namespace": 8,
        "oc create route": 9,
        "oc expose route": 10,
        "oc edit ingresses.config.openshift.io/cluster": 11,
        "oc delete secrets kubeadmin": 12,
        "oc login": 13,
        "oc adm catalog build": 14,
        "oc delete localvolume": 15,
        "oc delete localvolumeset": 16,
        "oc delete localvolumediscovery": 17,
        "oc api-resources": 18,
        "oc get csr": 19,
        "oc adm certificate approve": 20,
        "oc adm top pods": 21,
        "oc apply -f": 22,
        "oc create deployment": 23,
        "oc describe service": 24,
        "oc get endpoints": 25,
        "oc get nodes": 26,
        "oc describe node": 27,
        "oc describe node <node-name>": 28,
        "oc -n app-example create -f app-example-route.yaml": 29,
    }
    command_terms = sorted(command_terms, key=lambda term: command_priority.get(term.lower(), 50))
    return [*command_terms, *technical_phrases, *rest]
