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
    "oc new-project",
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
    terms = _prioritize_phrase_terms(terms)
    if _contains_hangul(normalized):
        terms = _filter_terms_for_korean_query(normalized, terms)

    return _append_terms(normalized, terms)


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
        "oc adm top pods": 2,
        "oc apply -f": 3,
        "oc create deployment": 4,
        "oc describe service": 5,
        "oc get endpoints": 6,
        "oc get nodes": 7,
        "oc describe node": 8,
        "oc describe node <node-name>": 9,
    }
    command_terms = sorted(command_terms, key=lambda term: command_priority.get(term.lower(), 50))
    return [*command_terms, *technical_phrases, *rest]
