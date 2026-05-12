"""Lightweight query understanding for retrieval planning.

This module classifies user intent and proposes retrieval terms only. It must
not return user-facing answers or fixed question-answer pairs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_OPENSHIFT_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])|openshift|오픈\s*시프트|오픈시프트", re.IGNORECASE)
_INSTALL_RE = re.compile(r"설치|install|installation|installer|클러스터.*구축|구축.*클러스터", re.IGNORECASE)
_COMMAND_RE = re.compile(r"명령어|커맨드|command|cli|\boc\b|확인(?:해|하는|할)?", re.IGNORECASE)
_TROUBLE_RE = re.compile(
    r"오류|에러|왜이래|왜\s*이래|안\s*돼|안돼|실패|문제|장애|trouble|troubleshoot|fail|error|degraded|pending|crashloop",
    re.IGNORECASE,
)
_SECRET_CONFIG_RE = re.compile(r"secret|시크릿|configmap|config\s*map|컨피그맵|컨피그|configuration|설정", re.IGNORECASE)
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
    r"secret|시크릿|configmap|config\s*map|컨피그맵|컨피그|configuration|설정",
    re.IGNORECASE,
)
_NAMESPACE_KO_RE = re.compile(r"namespace|namespaces|네임스페이스|프로젝트|project|projects", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class QueryUnderstanding:
    intents: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    answer_shape: str = "grounded_explanation"

    def has_intent(self, intent: str) -> bool:
        return intent in self.intents


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
    if not intents and openshift:
        intents.append("concept_explanation")
    return QueryUnderstanding(
        intents=tuple(dict.fromkeys(intents)),
        retrieval_terms=tuple(dict.fromkeys(terms)),
        answer_shape=answer_shape,
    )


def _append_terms(target: list[str], values: list[str]) -> None:
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if cleaned:
            target.append(cleaned)


def has_beginner_troubleshooting_intent(query: str) -> bool:
    understanding = understand_query(query)
    return understanding.has_intent("troubleshooting") or understanding.has_intent("secret_config_troubleshooting")


__all__ = ["QueryUnderstanding", "has_beginner_troubleshooting_intent", "understand_query"]
