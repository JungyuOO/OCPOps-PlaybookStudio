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
    "admin",
    "edit",
    "view",
    "cluster-admin",
    "rolebinding",
    "clusterrolebinding",
    "namespace",
    "project",
    "pod",
    "pods",
    "node",
    "nodes",
    "drain",
    "top",
    "describe",
    "deployment",
    "deployments",
    "replicas",
    "scale",
    "backup",
    "restore",
    "quorum",
    "machineconfigpool",
    "finalizer",
    "finalizers",
    "error resolving",
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
    append_core_query_terms(normalized, terms)
    append_operation_query_terms(normalized, terms)
    append_etcd_query_terms(normalized, terms)
    if _contains_hangul(normalized):
        terms = _filter_terms_for_korean_query(normalized, terms)

    return _append_terms(normalized, terms)
