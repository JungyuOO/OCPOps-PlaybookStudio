"""Small public query helpers kept after the retrieval redesign.

This module is the remaining compatibility surface used by answering and
routing. It intentionally avoids the deleted legacy intent/rewrite stack.
"""

from __future__ import annotations

import re

from .corpus_scope import detect_out_of_corpus_version, detect_unsupported_product
from .followups import has_corrective_follow_up, has_follow_up_reference
from .models import SessionContext
from .query_normalize import normalize_query
from .text_utils import collapse_spaces as _collapse_spaces
from .text_utils import contains_hangul
from .text_utils import strip_section_prefix as _strip_section_prefix
from .text_utils import token_count as _token_count

OCP_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])", re.IGNORECASE)
OPENSHIFT_RE = re.compile(r"(openshift|오픈\s*시프트|오픈시프트)", re.IGNORECASE)
KUBERNETES_RE = re.compile(r"(kubernetes|쿠버네티스)", re.IGNORECASE)
COMPARE_RE = re.compile(r"(차이|비교|vs\.?|versus|다른|구분)", re.IGNORECASE)
ROUTE_RE = re.compile(r"\broute(s)?\b|라우트", re.IGNORECASE)
INGRESS_RE = re.compile(r"\bingress(es)?\b|인그레스", re.IGNORECASE)
ARCHITECTURE_RE = re.compile(r"(architecture|아키텍처|구조)", re.IGNORECASE)
LOGGING_RE = re.compile(r"(log|logs|logging|로그|로깅)", re.IGNORECASE)
AUDIT_RE = re.compile(r"(audit|감사)", re.IGNORECASE)
EVENT_RE = re.compile(r"(event|events|이벤트)", re.IGNORECASE)
APP_RE = re.compile(r"(application|app|pod|container|애플리케이션|파드|컨테이너)", re.IGNORECASE)
POD_PENDING_RE = re.compile(r"(pod|파드).*(pending|펜딩)|(pending|펜딩)", re.IGNORECASE)
CRASH_LOOP_RE = re.compile(r"(crashloopbackoff|crash loop backoff)", re.IGNORECASE)
POD_LIFECYCLE_RE = re.compile(r"(pod|파드).*(lifecycle|생명|라이프사이클)", re.IGNORECASE)
OC_LOGIN_RE = re.compile(r"\boc\s+login\b|login", re.IGNORECASE)
INFRA_RE = re.compile(r"(infra|infrastructure|node|control plane|인프라|노드|컨트롤\s*플레인)", re.IGNORECASE)
MONITORING_RE = re.compile(r"(monitoring|prometheus|alertmanager|모니터링)", re.IGNORECASE)
SECURITY_RE = re.compile(r"(security|보안|蹂댁븞)", re.IGNORECASE)
AUTH_RE = re.compile(r"(authentication|인증)", re.IGNORECASE)
AUTHZ_RE = re.compile(r"(authorization|rbac|권한)", re.IGNORECASE)
UPDATE_RE = re.compile(r"(update|upgrade|업데이트|업그레이드)", re.IGNORECASE)
CERT_RE = re.compile(r"(certificate|certificates|cert|인증서)", re.IGNORECASE)
EXPIRY_RE = re.compile(r"(expire|expiry|expiration|만료)", re.IGNORECASE)
DEPLOYMENT_RE = re.compile(r"(deployment(?!config)|deployments|배포)", re.IGNORECASE)
DEPLOYMENTCONFIG_RE = re.compile(r"(deploymentconfig|\bdc\b)", re.IGNORECASE)
SCALE_RE = re.compile(r"(scale|scaling|스케일|늘리|줄이|조정)", re.IGNORECASE)
REPLICA_RE = re.compile(r"(replica|replicas|복제)", re.IGNORECASE)
RBAC_RE = re.compile(r"(\brbac\b|rolebinding|clusterrolebinding|clusterrole|권한|역할)", re.IGNORECASE)
PROJECT_SCOPE_RE = re.compile(r"(project|projects|namespace|namespaces|프로젝트|네임스페이스)", re.IGNORECASE)
ROLE_ASSIGN_RE = re.compile(r"(grant|assign|bind|add|부여|할당|추가|바인딩)", re.IGNORECASE)
ROLE_API_STYLE_RE = re.compile(r"(api|yaml|manifest|json|spec|curl)", re.IGNORECASE)
USER_SUBJECT_RE = re.compile(r"(user|serviceaccount|group|사용자|서비스\s*계정|그룹)", re.IGNORECASE)
ADMIN_ROLE_RE = re.compile(r"(admin|관리자)", re.IGNORECASE)
EDIT_ROLE_RE = re.compile(r"\bedit\b|편집", re.IGNORECASE)
VIEW_ROLE_RE = re.compile(r"\bview\b|보기|읽기", re.IGNORECASE)
CLUSTER_ADMIN_RE = re.compile(r"\bcluster-admin\b", re.IGNORECASE)
MCO_RE = re.compile(r"(machine\s*config\s*operator|\bmco\b|machine\s*config|머신\s*구성)", re.IGNORECASE)
DISCONNECTED_RE = re.compile(r"(disconnected|disconnect|분리망|연결.*없)", re.IGNORECASE)
ETCD_RE = re.compile(r"etcd", re.IGNORECASE)
BACKUP_RE = re.compile(r"(backup|백업)", re.IGNORECASE)
RESTORE_RE = re.compile(r"(restore|복구|복원)", re.IGNORECASE)
NODE_RE = re.compile(r"(node|nodes|worker|노드)", re.IGNORECASE)
DRAIN_RE = re.compile(r"(drain|evacuate|비우)", re.IGNORECASE)
TOP_RE = re.compile(r"(\btop\b|cpu|memory|메모리|사용량)", re.IGNORECASE)
HOSTED_CONTROL_PLANE_RE = re.compile(r"(hosted\s*control\s*plane|hosted\s*cluster|hypershift)", re.IGNORECASE)
PROJECT_TERMINATING_RE = re.compile(
    r"(project|namespace|프로젝트|네임스페이스).*(terminating|삭제|종료|지연)",
    re.IGNORECASE,
)
FINALIZER_RE = re.compile(r"(finalizer|finalizers|metadata\.finalizers|파이널라이저)", re.IGNORECASE)
REMAINING_RESOURCE_RE = re.compile(r"(remaining resource|error resolving resource|crd|custom resource|남은 리소스)", re.IGNORECASE)
OPERATOR_RE = re.compile(r"(operator|operators|오퍼레이터)", re.IGNORECASE)
DOC_LOCATOR_RE = re.compile(r"(문서|가이드|wiki|위키|어디|찾|참고|보려면|경로|대디|\?대뵒)", re.IGNORECASE)
FIRST_STEP_RE = re.compile(r"(first step|first command|start with|먼저|처음|첫\s*(단계|명령)|어디부터)", re.IGNORECASE)
SECURITY_SCOPE_RE = re.compile(
    r"(compliance|audit|authentication|authorization|rbac|network|tls|certificate|cert|egress|ingress|보안|감사|인증|권한)",
    re.IGNORECASE,
)
EXPLAINER_RE = re.compile(r"(what is|what does|explain|summary|요약|설명|뭐야|무엇|개념|차이)", re.IGNORECASE)
GENERIC_INTRO_RE = re.compile(r"(openshift|ocp|오픈\s*시프트|오픈시프트).*(뭐야|무엇|소개|개요|요약|설명|architecture|아키텍처)", re.IGNORECASE)
COMPARE_DECOMPOSE_RE = re.compile(r"(?P<left>.+?)(?:\s*(?:vs\.?|versus|와|과)\s*)(?P<right>.+)", re.IGNORECASE)
ROUTE_TIMEOUT_RE = re.compile(r"(route|라우트).*(timeout|타임아웃|시간)", re.IGNORECASE)
NODE_NOTREADY_RE = re.compile(r"(node|노드|worker).*(notready|not ready|문제|장애)", re.IGNORECASE)
CONJUNCTION_SPLIT_RE = re.compile(r"\s*(?:그리고|또한|및|and then|and also|and)\s*", re.IGNORECASE)
GENERIC_CONTEXT_TOPIC_RE = re.compile(r"(운영 설정|복구 절차|일반 설정)", re.IGNORECASE)
MACHINE_CONFIG_REBOOT_RE = re.compile(r"(machine\s*config|\bmco\b|머신\s*구성).*(reboot|재부팅)", re.IGNORECASE)
REGISTRY_RE = re.compile(r"(registry|image registry|openshift-image-registry|레지스트리)", re.IGNORECASE)
IMAGE_RE = re.compile(r"(image|이미지)", re.IGNORECASE)
STORAGE_RE = re.compile(r"(storage|pvc|pv|storageclass|스토리지|저장소|s3|ceph|nfs)", re.IGNORECASE)


def has_doc_locator_intent(query: str) -> bool:
    return bool(DOC_LOCATOR_RE.search(query or ""))


def has_first_step_intent(query: str) -> bool:
    return bool(FIRST_STEP_RE.search(query or ""))


def has_update_doc_locator_intent(query: str) -> bool:
    normalized = query or ""
    return bool(UPDATE_RE.search(normalized)) and has_doc_locator_intent(normalized)


def has_pod_pending_troubleshooting_intent(query: str) -> bool:
    return bool(POD_PENDING_RE.search(query or ""))


def has_backup_restore_intent(query: str) -> bool:
    normalized = query or ""
    return bool(BACKUP_RE.search(normalized) or RESTORE_RE.search(normalized))


def has_hosted_control_plane_signal(query: str) -> bool:
    return bool(HOSTED_CONTROL_PLANE_RE.search(query or ""))


def has_certificate_monitor_intent(query: str) -> bool:
    normalized = query or ""
    lowered = normalized.lower()
    return bool(CERT_RE.search(normalized)) and (
        bool(EXPIRY_RE.search(normalized))
        or "monitor" in lowered
        or "check" in lowered
        or "확인" in normalized
    )


def has_rbac_intent(query: str) -> bool:
    normalized = query or ""
    lowered = normalized.lower()
    if RBAC_RE.search(normalized) or "can-i" in lowered:
        return True
    return bool(AUTHZ_RE.search(normalized)) and bool(
        PROJECT_SCOPE_RE.search(normalized)
        or ROLE_ASSIGN_RE.search(normalized)
        or USER_SUBJECT_RE.search(normalized)
    )


def has_project_scoped_rbac_intent(query: str) -> bool:
    return has_rbac_intent(query) and bool(PROJECT_SCOPE_RE.search(query or ""))


def has_rbac_assignment_intent(query: str) -> bool:
    normalized = query or ""
    return has_rbac_intent(normalized) and bool(
        ROLE_ASSIGN_RE.search(normalized)
        or USER_SUBJECT_RE.search(normalized)
        or ADMIN_ROLE_RE.search(normalized)
        or EDIT_ROLE_RE.search(normalized)
        or VIEW_ROLE_RE.search(normalized)
        or CLUSTER_ADMIN_RE.search(normalized)
    )


def has_deployment_scaling_intent(query: str) -> bool:
    normalized = query or ""
    if DEPLOYMENTCONFIG_RE.search(normalized):
        return False
    return bool(DEPLOYMENT_RE.search(normalized)) and bool(SCALE_RE.search(normalized) or REPLICA_RE.search(normalized))


def has_command_request(query: str) -> bool:
    normalized = query or ""
    lowered = normalized.lower()
    return any(
        token in lowered
        for token in ("command", "cli", "what command", "which command", "oc ", "kubectl ", "명령", "커맨드")
    )


def is_generic_intro_query(query: str) -> bool:
    normalized = query or ""
    lowered = normalized.lower()
    if has_route_ingress_compare_intent(normalized):
        return False
    if GENERIC_INTRO_RE.search(normalized):
        return True
    has_intro_ask = bool(EXPLAINER_RE.search(normalized))
    has_ocp_topic = "openshift" in lowered or bool(OCP_RE.search(normalized))
    has_kubernetes_topic = bool(KUBERNETES_RE.search(normalized))
    if has_kubernetes_topic and has_intro_ask:
        non_generic_tokens = ("route", "ingress", "operator", "deployment", "service", "pod", "rbac", "namespace", "node", "etcd")
        return not any(token in lowered for token in non_generic_tokens)
    return has_ocp_topic and bool(ARCHITECTURE_RE.search(normalized) or has_intro_ask)


def has_openshift_kubernetes_compare_intent(query: str) -> bool:
    normalized = query or ""
    return bool(OPENSHIFT_RE.search(normalized)) and bool(KUBERNETES_RE.search(normalized)) and bool(COMPARE_RE.search(normalized))


def has_route_ingress_compare_intent(query: str) -> bool:
    normalized = query or ""
    return bool(ROUTE_RE.search(normalized)) and bool(INGRESS_RE.search(normalized)) and bool(COMPARE_RE.search(normalized))


def is_explainer_query(query: str) -> bool:
    return bool(EXPLAINER_RE.search(query or ""))


def has_pod_lifecycle_concept_intent(query: str) -> bool:
    normalized = query or ""
    return bool(POD_LIFECYCLE_RE.search(normalized)) and is_explainer_query(normalized)


def has_crash_loop_troubleshooting_intent(query: str) -> bool:
    return bool(CRASH_LOOP_RE.search(query or ""))


def has_operator_concept_intent(query: str) -> bool:
    normalized = query or ""
    return bool(OPERATOR_RE.search(normalized)) and not bool(MCO_RE.search(normalized)) and is_explainer_query(normalized)


def has_mco_concept_intent(query: str) -> bool:
    normalized = query or ""
    return bool(MCO_RE.search(normalized)) and is_explainer_query(normalized)


def has_machine_config_reboot_intent(query: str) -> bool:
    return bool(MACHINE_CONFIG_REBOOT_RE.search(query or ""))


def has_registry_storage_ops_intent(query: str) -> bool:
    normalized = query or ""
    return bool(REGISTRY_RE.search(normalized)) and bool(IMAGE_RE.search(normalized)) and bool(STORAGE_RE.search(normalized))


def has_project_terminating_intent(query: str) -> bool:
    return bool(PROJECT_TERMINATING_RE.search(query or ""))


def has_project_finalizer_intent(query: str) -> bool:
    normalized = query or ""
    return bool(FINALIZER_RE.search(normalized)) or (
        has_project_terminating_intent(normalized) and bool(REMAINING_RESOURCE_RE.search(normalized))
    )


def has_node_drain_intent(query: str) -> bool:
    normalized = query or ""
    return bool(NODE_RE.search(normalized)) and bool(DRAIN_RE.search(normalized))


def has_cluster_node_usage_intent(query: str) -> bool:
    normalized = query or ""
    return bool(NODE_RE.search(normalized)) and bool(TOP_RE.search(normalized))


def has_explicit_topic_signal(query: str) -> bool:
    normalized = query or ""
    return any(
        pattern.search(normalized)
        for pattern in (
            OCP_RE,
            OPENSHIFT_RE,
            ETCD_RE,
            MCO_RE,
            RBAC_RE,
            PROJECT_SCOPE_RE,
            LOGGING_RE,
            MONITORING_RE,
            SECURITY_RE,
            AUTH_RE,
            AUTHZ_RE,
            ARCHITECTURE_RE,
            OPERATOR_RE,
            ROUTE_RE,
            INGRESS_RE,
        )
    ) or has_registry_storage_ops_intent(normalized)


def query_book_adjustments(
    query: str,
    *,
    context: SessionContext | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    return ({}, {})


def rewrite_decision(query: str, context: SessionContext) -> tuple[bool, str]:
    normalized = _collapse_spaces(query)
    if not normalized:
        return (False, "empty_query")
    if not any(
        [
            context.current_topic,
            context.user_goal,
            context.open_entities,
            context.ocp_version,
            context.unresolved_question,
        ]
    ):
        return (False, "no_context")
    if is_generic_intro_query(normalized) and not has_follow_up_reference(normalized):
        return (False, "generic_intro_query")
    if has_follow_up_reference(normalized):
        return (True, "follow_up_reference")
    if has_explicit_topic_signal(normalized):
        return (False, "explicit_topic_signal")
    if _token_count(normalized) <= 3:
        return (True, "short_contextual_query")
    return (False, "no_rewrite_needed")


def needs_rewrite(query: str, context: SessionContext) -> bool:
    return rewrite_decision(query, context)[0]


def rewrite_query(query: str, context: SessionContext | None = None) -> str:
    normalized = query
    context = context or SessionContext()
    if not needs_rewrite(normalized, context):
        return normalized

    normalized_topic = _strip_section_prefix(context.current_topic or "")
    generic_openshift_context = normalized_topic.lower() == "openshift"
    hints: list[str] = []
    if context.ocp_version:
        hints.append(f"OCP {context.ocp_version}")
    if normalized_topic and not generic_openshift_context:
        hints.append(f"topic {normalized_topic}")
    if context.open_entities and not generic_openshift_context:
        hints.append(f"entities {', '.join(context.open_entities)}")
    if context.unresolved_question and not generic_openshift_context:
        hints.append(f"unresolved {context.unresolved_question}")
    elif context.user_goal and not generic_openshift_context:
        hints.append(f"goal {context.user_goal}")
    hints.append(normalized)
    return " | ".join(hints)


from .ambiguity import (  # noqa: E402
    has_follow_up_entity_ambiguity,
    has_logging_ambiguity,
    has_multiple_entity_ambiguity,
    has_postinstall_doc_locator_ambiguity,
    has_security_doc_locator_ambiguity,
    has_update_doc_locator_ambiguity,
)
