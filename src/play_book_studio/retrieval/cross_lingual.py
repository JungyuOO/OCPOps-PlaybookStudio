"""Deterministic Korean-to-technical-term expansion for retrieval."""

from __future__ import annotations

from .text_utils import collapse_spaces


CROSS_LINGUAL_REWRITE_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("리소스 사용량", "자원 사용량", "cpu", "메모리", "사용량"), ("resource usage", "CPU", "memory", "utilization", "oc adm top pods")),
    (("배포 매니페스트", "배포 yaml", "deployment yaml", "매니페스트"), ("Deployment manifest", "kind: Deployment", "YAML", "oc apply -f")),
    (("서비스 장애", "service 장애", "서비스 안됨", "서비스 접속"), ("Service", "Endpoint", "EndpointSlice", "Route", "selector")),
    (("네임스페이스", "namespace", "프로젝트"), ("Namespace", "Project", "oc create namespace", "oc new-project")),
    (("권한", "can-i", "rbac"), ("RBAC", "oc auth can-i", "RoleBinding", "ClusterRole")),
)


def cross_lingual_rewrite_terms(query: str) -> list[str]:
    normalized = collapse_spaces(query).lower()
    if not normalized:
        return []
    terms: list[str] = []
    for triggers, additions in CROSS_LINGUAL_REWRITE_RULES:
        if any(trigger.lower() in normalized for trigger in triggers):
            terms.extend(additions)
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
