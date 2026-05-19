"""Lightweight answer-side query intent helpers.

These helpers keep answer shaping and validation code from depending on the
legacy retrieval intent stack that Phase 5 removes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from play_book_studio.retrieval.query_normalize import normalize_query


@dataclass(frozen=True, slots=True)
class QueryUnderstanding:
    intents: tuple[str, ...]
    retrieval_terms: tuple[str, ...] = ()
    answer_shape: str = "grounded_explanation"

    def has_intent(self, intent: str) -> bool:
        return intent in self.intents


@dataclass(frozen=True, slots=True)
class IntentProfile:
    intent: str = "unknown"
    target_object: str = ""
    task: str = ""
    needs_command: bool = False
    primary_commands: tuple[str, ...] = ()
    evidence_terms: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    confidence: float = 0.0
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def _dedupe_terms(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    terms: list[str] = []
    for group in groups:
        for term in group:
            cleaned = " ".join(str(term).split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                terms.append(cleaned)
    return tuple(terms)


def understand_query(query: str) -> QueryUnderstanding:
    text = " ".join(str(query or "").split())
    lowered = text.lower()
    intents: list[str] = []
    terms: list[str] = []
    answer_shape = "grounded_explanation"

    if _contains_any(lowered, ("install", "installation", "installer", "설치", "구축")):
        intents.append("install_overview")
        answer_shape = "beginner_install_overview"
        terms.extend(("installation overview", "openshift-install", "pull secret", "kubeconfig"))
    if _contains_any(lowered, ("namespace", "namespaces", "project", "projects", "네임스페이스", "프로젝트")):
        intents.append("namespace_or_project")
        terms.extend(("namespace", "project", "oc get namespaces", "oc get projects"))
        if _contains_any(lowered, ("create", "new", "make", "만들", "생성", "추가")):
            intents.append("namespace_create")
            terms.extend(("oc create namespace", "oc new-project"))
    if re.search(r"(deployment|deploy|배포|디플로이먼트).*(yaml|manifest|매니페스트|작성|생성|만들|apply)", lowered):
        intents.append("deployment_yaml_authoring")
        terms.extend(("kind: Deployment", "oc apply -f", "deployment manifest"))
    if re.search(r"(pod|pods|파드).*(resource|usage|cpu|memory|메모리|리소스|사용량|top)", lowered):
        intents.append("pod_resource_inspection")
        terms.extend(("oc adm top pods", "cpu", "memory", "resource usage"))
    if re.search(r"(service|svc|서비스).*(장애|오류|에러|안\s*됨|접속|연결|endpoint|selector|fail|error)", lowered):
        intents.append("service_failure_diagnosis")
        terms.extend(("service", "endpoint", "selector", "route"))
    if re.search(r"오류|에러|장애|문제|실패|안\s*돼|안\s*됨|trouble|fail|error|pending|crashloop", lowered):
        intents.append("troubleshooting")
        answer_shape = "troubleshooting_steps"
        terms.extend(("troubleshooting", "events", "describe", "logs"))
    if _contains_any(lowered, ("명령", "명령어", "command", "cli", " oc ", "확인")):
        intents.append("command_lookup")
        answer_shape = "command_with_judgement"
        terms.extend(("oc", "CLI", "command"))

    return QueryUnderstanding(
        intents=tuple(dict.fromkeys(intents)),
        retrieval_terms=_dedupe_terms(tuple(terms)),
        answer_shape=answer_shape,
    )


def has_beginner_troubleshooting_intent(query: str) -> bool:
    return understand_query(query).has_intent("troubleshooting")


def build_intent_profile(query: str) -> IntentProfile:
    normalized = normalize_query(query)
    understanding = understand_query(normalized)
    query_terms = _dedupe_terms(tuple(understanding.retrieval_terms), tuple(normalized.split()))
    primary_commands = tuple(term for term in query_terms if term.startswith("oc ") or term in {"oc"})
    needs_command = understanding.has_intent("command_lookup") or bool(primary_commands)
    intent = understanding.intents[0] if understanding.intents else "unknown"
    confidence = 0.75 if intent != "unknown" else 0.0
    return IntentProfile(
        intent=intent,
        needs_command=needs_command,
        primary_commands=primary_commands,
        evidence_terms=query_terms,
        query_terms=query_terms,
        confidence=confidence,
        reasons=("answer-side lightweight intent profile",) if intent != "unknown" else (),
    )
