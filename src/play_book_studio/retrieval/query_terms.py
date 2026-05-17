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
    "bootstrap-complete",
    "configmap",
    "configmaps",
    "secret",
    "secrets",
    "troubleshooting",
    "events",
    "condition",
}

_SERVICE_ROUTE_CONCEPT_MARKERS = (
    "뭔지",
    "무엇인지",
    "개념",
    "알고 싶",
    "알고싶",
    "이해",
    "설명",
    "먼저",
    "부터",
    "what is",
    "explain",
    "concept",
    "overview",
)

_FAILURE_OR_DIAGNOSIS_MARKERS = (
    "장애",
    "오류",
    "에러",
    "안됨",
    "안 돼",
    "안되",
    "실패",
    "문제",
    "trouble",
    "fail",
    "error",
    "debug",
    "diagnos",
)

_SERVICE_ROUTE_CONCEPT_BLOCKED_TERMS = {
    "oc describe service",
    "oc get endpoints",
    "endpoint",
    "endpoints",
    "endpointslice",
    "selector",
    "targetport",
    "ingress",
    "tls",
}

_SERVICE_ROUTE_CONCEPT_BLOCKED_FRAGMENTS = (
    "상태 확인",
    "판단 기준",
    "cli 명령어",
    "troubleshooting",
)


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
    terms = _prune_service_route_concept_terms(normalized, terms)
    terms = _prioritize_phrase_terms(terms)
    if _contains_hangul(normalized):
        terms = _filter_terms_for_korean_query(normalized, terms)

    return _append_terms(normalized, terms)


def _prune_terms_for_intent(query: str, terms: list[str]) -> list[str]:
    profile = build_intent_profile(query)
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


def _is_service_route_concept_query(query: str) -> bool:
    lowered = (query or "").lower()
    has_service = "service" in lowered or "서비스" in lowered
    has_route = "route" in lowered or "라우트" in lowered or "경로" in lowered
    has_concept_shape = any(marker in lowered for marker in _SERVICE_ROUTE_CONCEPT_MARKERS)
    has_failure_shape = any(marker in lowered for marker in _FAILURE_OR_DIAGNOSIS_MARKERS)
    return has_service and has_route and has_concept_shape and not has_failure_shape


def _prune_service_route_concept_terms(query: str, terms: list[str]) -> list[str]:
    if not _is_service_route_concept_query(query):
        return terms

    pruned: list[str] = []
    for term in terms:
        cleaned = _collapse_spaces(term)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in _SERVICE_ROUTE_CONCEPT_BLOCKED_TERMS:
            continue
        if any(fragment in lowered for fragment in _SERVICE_ROUTE_CONCEPT_BLOCKED_FRAGMENTS):
            continue
        pruned.append(cleaned)
    return pruned


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
