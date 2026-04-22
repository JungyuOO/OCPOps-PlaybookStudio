from __future__ import annotations

# 제품/개념/문서 탐색 성격의 질의 확장 용어를 모아 둔 helper다.

import re

from .intents import (
    ARCHITECTURE_RE,
    BACKUP_RE,
    CERT_RE,
    DISCONNECTED_RE,
    LOGGING_RE,
    MCO_RE,
    MONITORING_RE,
    OBSERVABILITY_RE,
    OCP_RE,
    OPENSHIFT_RE,
    RESTORE_RE,
    SECURITY_RE,
    AUTH_RE,
    AUTHZ_RE,
    KUBERNETES_RE,
    has_doc_locator_intent,
    has_mco_concept_intent,
    has_operator_concept_intent,
    has_openshift_kubernetes_compare_intent,
    has_route_ingress_compare_intent,
    has_update_doc_locator_intent,
    is_explainer_query,
    is_generic_intro_query,
)


_LATIN_RE = re.compile(r"[A-Za-z]")


def _english_expansion_enabled(normalized: str) -> bool:
    return bool(_LATIN_RE.search(normalized or ""))


def append_core_query_terms(normalized: str, terms: list[str]) -> None:
    allow_english = _english_expansion_enabled(normalized)
    route_ingress_compare = has_route_ingress_compare_intent(normalized)
    generic_intro = is_generic_intro_query(normalized)

    if OCP_RE.search(normalized) and allow_english:
        terms.extend(["OpenShift", "Container", "Platform"])
    if OPENSHIFT_RE.search(normalized) and allow_english:
        terms.append("OpenShift")
    if KUBERNETES_RE.search(normalized) and allow_english:
        terms.append("Kubernetes")
    if ARCHITECTURE_RE.search(normalized):
        terms.append("구조")
        if allow_english:
            terms.append("architecture")
    if LOGGING_RE.search(normalized):
        terms.append("로깅")
        if allow_english:
            terms.append("logging")
    if MONITORING_RE.search(normalized):
        terms.append("모니터링")
        if allow_english:
            terms.append("monitoring")
    if OBSERVABILITY_RE.search(normalized):
        terms.append("관찰 기능")
        if allow_english:
            terms.extend(["observability", "monitoring"])
    if SECURITY_RE.search(normalized):
        terms.append("보안")
        if allow_english:
            terms.append("security")
    if AUTH_RE.search(normalized):
        terms.append("인증")
        if allow_english:
            terms.append("authentication")
    if CERT_RE.search(normalized):
        terms.append("인증서")
        if allow_english:
            terms.extend(["certificate", "certificates"])
    if AUTHZ_RE.search(normalized):
        terms.append("권한")
        if allow_english:
            terms.append("authorization")
    if route_ingress_compare:
        terms.extend(["애플리케이션 노출", "비교", "차이점", "유사점"])
        if allow_english:
            terms.extend(
                [
                    "route",
                    "ingress",
                    "networking",
                    "router",
                    "ingresscontroller",
                    "application exposure",
                    "comparison",
                    "difference",
                    "Kubernetes",
                ]
            )

    if MCO_RE.search(normalized):
        terms.extend(["머신 구성", "오퍼레이터", "운영", "관리"])
        if allow_english:
            terms.extend(["Machine", "Config", "Operator", "machine", "configuration", "operators"])
    if has_mco_concept_intent(normalized):
        terms.extend(["머신 구성 오퍼레이터", "노드 설정", "운영", "관리"])
        if allow_english:
            terms.extend(
                [
                    "Machine Config Operator",
                    "MCO",
                    "machineconfigpool",
                    "machine config pool",
                    "machine config daemon",
                    "MCD",
                    "Ignition",
                    "node",
                    "configuration",
                    "RHCOS",
                    "kubelet",
                    "CRI-O",
                    "About the Machine Config Operator",
                    "Machine configuration overview",
                    ]
            )
    if has_operator_concept_intent(normalized):
        terms.extend(["오퍼레이터", "운영", "관리"])
        if allow_english:
            terms.extend(
                [
                    "Operator",
                    "operators",
                    "controller",
                    "lifecycle",
                    "automation",
                    "Operator Lifecycle Manager",
                    "OLM",
                    "operator framework",
                ]
            )
    if DISCONNECTED_RE.search(normalized):
        terms.append("연결이 끊긴 환경")
        if allow_english:
            terms.append("disconnected")

    if "기본 문서" in normalized:
        terms.append("개요")
        if allow_english:
            terms.append("overview")

    if has_doc_locator_intent(normalized):
        terms.extend(["문서", "가이드", "참고"])
        if allow_english:
            terms.extend(["guide", "documentation"])
    if has_update_doc_locator_intent(normalized):
        terms.extend(["릴리스 노트", "클러스터 업데이트", "업데이트 준비", "업데이트 이해"])
        if allow_english:
            terms.extend(
                [
                    "update guide",
                    "updating clusters",
                    "release notes",
                ]
            )
    if BACKUP_RE.search(normalized):
        terms.append("백업")
        if allow_english:
            terms.append("backup")
    if RESTORE_RE.search(normalized):
        terms.append("복원")
        if allow_english:
            terms.append("restore")
    if is_explainer_query(normalized) and not route_ingress_compare and not generic_intro:
        terms.append("개요")
        if allow_english:
            terms.append("overview")
    if generic_intro:
        if OCP_RE.search(normalized) or OPENSHIFT_RE.search(normalized):
            terms.extend(["개요", "플랫폼"])
            if allow_english:
                terms.append("overview")
        elif KUBERNETES_RE.search(normalized):
            terms.extend(["개요", "플랫폼"])
            if allow_english:
                terms.append("overview")
        else:
            terms.append("개요")
            if allow_english:
                terms.append("overview")
    if has_openshift_kubernetes_compare_intent(normalized):
        terms.extend(["비교", "차이점", "유사점"])
        if allow_english:
            terms.extend(["comparison", "difference"])
