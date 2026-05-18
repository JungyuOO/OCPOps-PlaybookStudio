"""Deterministic Korean-to-technical-term expansion for retrieval."""

from __future__ import annotations

from .text_utils import collapse_spaces


CROSS_LINGUAL_REWRITE_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("리소스 사용량", "자원 사용량", "cpu", "메모리", "사용량"), ("resource usage", "CPU", "memory", "utilization", "oc adm top pods")),
    (("배포 매니페스트", "배포 yaml", "deployment yaml", "매니페스트"), ("Deployment manifest", "kind: Deployment", "YAML", "oc apply -f")),
    (("서비스 장애", "service 장애", "서비스 안됨", "서비스 접속"), ("Service", "Endpoint", "EndpointSlice", "Route", "selector")),
    (("권한", "can-i", "rbac"), ("RBAC", "oc auth can-i", "RoleBinding", "ClusterRole")),
)

_PROJECT_NAMESPACE_TRIGGERS = ("네임스페이스", "namespace", "namespaces", "프로젝트", "project", "projects")
_PROJECT_LIST_TRIGGERS = ("목록", "리스트", "전체", "조회", "list", "get")
_PROJECT_CREATE_TRIGGERS = ("생성", "만들", "추가", "create", "new", "make")


def cross_lingual_rewrite_terms(query: str) -> list[str]:
    normalized = collapse_spaces(query).lower()
    if not normalized:
        return []
    terms: list[str] = []
    for triggers, additions in CROSS_LINGUAL_REWRITE_RULES:
        if any(trigger.lower() in normalized for trigger in triggers):
            terms.extend(additions)
    if any(trigger in normalized for trigger in _PROJECT_NAMESPACE_TRIGGERS):
        terms.extend(["Namespace", "Project"])
        if any(trigger in normalized for trigger in _PROJECT_LIST_TRIGGERS):
            terms.extend(["oc get projects", "oc get namespaces", "project list", "namespace list"])
        elif any(trigger in normalized for trigger in _PROJECT_CREATE_TRIGGERS):
            terms.extend(["oc create namespace", "oc new-project"])
    return _dedupe_terms(terms)


def _dedupe_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = collapse_spaces(term)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


__all__ = ["cross_lingual_rewrite_terms"]
