# ambiguity 판별 로직만 따로 모아 둔 파일.
# 질문이 애매해서 clarification 이 필요한지 판단할 때 먼저 본다.

from __future__ import annotations

import re

from .followups import has_follow_up_reference
from .models import SessionContext
from .text_utils import collapse_spaces, token_count


def has_logging_ambiguity(query: str) -> bool:
    from .query import APP_RE, AUDIT_RE, EVENT_RE, INFRA_RE, LOGGING_RE

    normalized = query or ""
    if not LOGGING_RE.search(normalized):
        return False
    if AUDIT_RE.search(normalized) or EVENT_RE.search(normalized):
        return False
    if APP_RE.search(normalized) or INFRA_RE.search(normalized):
        return False
    return "어디서" in normalized or "보" in normalized


def has_multiple_entity_ambiguity(query: str) -> bool:
    from .query import (
        ETCD_RE,
        EXPLAINER_RE,
        KUBERNETES_RE,
        LOGGING_RE,
        MCO_RE,
        MONITORING_RE,
        OPENSHIFT_RE,
        OPERATOR_RE,
        RBAC_RE,
        has_mco_concept_intent,
        has_openshift_kubernetes_compare_intent,
    )

    normalized = query or ""
    if has_mco_concept_intent(normalized):
        return False
    entities = []
    if OPENSHIFT_RE.search(normalized):
        entities.append("OpenShift")
    if KUBERNETES_RE.search(normalized):
        entities.append("Kubernetes")
    has_mco = bool(MCO_RE.search(normalized))
    if MCO_RE.search(normalized):
        entities.append("MCO")
    if ETCD_RE.search(normalized):
        entities.append("etcd")
    if RBAC_RE.search(normalized):
        entities.append("RBAC")
    if OPERATOR_RE.search(normalized) and not has_mco:
        entities.append("Operator")
    if LOGGING_RE.search(normalized):
        entities.append("Logging")
    if MONITORING_RE.search(normalized):
        entities.append("Monitoring")

    if len(entities) < 2:
        return False
    if has_openshift_kubernetes_compare_intent(normalized):
        return False
    if token_count(normalized) > 12:
        return False
    return bool(EXPLAINER_RE.search(normalized)) or "뭐 " in normalized or "설명" in normalized


def has_update_doc_locator_ambiguity(query: str) -> bool:
    from .query import UPDATE_RE, has_doc_locator_intent

    normalized = query or ""
    if not UPDATE_RE.search(normalized):
        return False
    if not has_doc_locator_intent(normalized):
        return False
    has_scope = any(
        token in normalized.lower()
        for token in ("4.20", "4.21", "eus", "단일", "단일 노드", "hypershift", "rosa", "microshift")
    )
    return not has_scope


def has_postinstall_doc_locator_ambiguity(query: str) -> bool:
    from .query import has_explicit_topic_signal

    normalized = collapse_spaces(query)
    lowered = normalized.lower()
    if not any(
        token in lowered
        for token in (
            "설치 후",
            "설치후",
            "설치한 뒤",
            "설치하고 나서",
            "설치 완료 후",
            "설치 완료 뒤",
            "post-install",
            "postinstall",
            "post installation",
        )
    ):
        return False
    if not any(
        token in normalized
        for token in (
            "뭘 먼저",
            "뭐부터",
            "어디서부터",
            "먼저 해야",
            "먼저 할",
            "먼저 봐야",
            "먼저 보면",
        )
    ):
        return False
    if has_explicit_topic_signal(normalized):
        return False
    has_scope = any(
        token in lowered
        for token in (
            "네트워크",
            "network",
            "보안",
            "security",
            "인증",
            "authentication",
            "권한",
            "authorization",
            "rbac",
            "레지스트리",
            "registry",
            "스토리지",
            "storage",
            "이미지",
            "image",
            "머신셋",
            "machineset",
            "노드",
            "node",
            "모니터링",
            "monitoring",
            "로깅",
            "logging",
            "백업",
            "backup",
            "복구",
            "restore",
            "etcd",
            "검증",
            "validation",
        )
    )
    return not has_scope


def has_security_doc_locator_ambiguity(query: str) -> bool:
    from .query import SECURITY_RE, SECURITY_SCOPE_RE, has_doc_locator_intent

    normalized = query or ""
    if not SECURITY_RE.search(normalized):
        return False
    if not has_doc_locator_intent(normalized):
        return False
    if SECURITY_SCOPE_RE.search(normalized):
        return False
    return any(
        token in normalized
        for token in (
            "기본 문서",
            "중심",
            "뭐가 중심",
            "뭐부터",
            "어디서",
            "어디를",
        )
    )


def has_follow_up_entity_ambiguity(query: str, context: SessionContext | None = None) -> bool:
    from .query import (
        GENERIC_CONTEXT_TOPIC_RE,
        has_command_request,
        has_doc_locator_intent,
        has_explicit_topic_signal,
    )

    normalized = collapse_spaces(query)
    context = context or SessionContext()
    open_entities = [str(entity).strip() for entity in context.open_entities if str(entity).strip()]
    entity_roots: set[str] = set()
    for entity in open_entities:
        lowered = entity.lower()
        if "image registry" in lowered or "registry" in lowered or "레지스트리" in entity:
            entity_roots.add("registry")
        elif "machine config operator" in lowered or "machineconfigpool" in lowered:
            entity_roots.add(lowered.replace(" ", ""))
        else:
            entity_roots.add(lowered.replace(" ", ""))
    if len(entity_roots) < 2:
        return False
    if not has_follow_up_reference(normalized):
        return False
    if has_explicit_topic_signal(normalized):
        return False
    if context.current_topic:
        current_topic = collapse_spaces(context.current_topic)
        if current_topic and not GENERIC_CONTEXT_TOPIC_RE.search(current_topic) and token_count(current_topic) >= 3:
            return False
    return any(
        [
            bool(re.search(r"\b[1-9]\d*번\b", normalized)),
            "그 설정" in normalized,
            "그 방법" in normalized,
            "그거" in normalized,
            "그 내용" in normalized,
            "해당 설정" in normalized,
            has_command_request(normalized),
            has_doc_locator_intent(normalized),
            token_count(normalized) <= 6,
        ]
    )
