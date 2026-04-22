from __future__ import annotations

import re

from .intent_patterns import (
    OCP_RE,
    OPENSHIFT_RE,
    KUBERNETES_RE,
    COMPARE_RE,
    ROUTE_RE,
    INGRESS_RE,
    ARCHITECTURE_RE,
    LOGGING_RE,
    AUDIT_RE,
    EVENT_RE,
    APP_RE,
    POD_PENDING_RE,
    CRASH_LOOP_RE,
    POD_LIFECYCLE_RE,
    OC_LOGIN_RE,
    INFRA_RE,
    MONITORING_RE,
    SECURITY_RE,
    AUTH_RE,
    AUTHZ_RE,
    UPDATE_RE,
    CERT_RE,
    EXPIRY_RE,
    DEPLOYMENT_RE,
    DEPLOYMENTCONFIG_RE,
    SCALE_RE,
    REPLICA_RE,
    RBAC_RE,
    PROJECT_SCOPE_RE,
    ROLE_ASSIGN_RE,
    ROLE_API_STYLE_RE,
    USER_SUBJECT_RE,
    ADMIN_ROLE_RE,
    EDIT_ROLE_RE,
    VIEW_ROLE_RE,
    CLUSTER_ADMIN_RE,
    MCO_RE,
    DISCONNECTED_RE,
    ETCD_RE,
    BACKUP_RE,
    RESTORE_RE,
    NODE_RE,
    DRAIN_RE,
    TOP_RE,
    HOSTED_CONTROL_PLANE_RE,
    PROJECT_TERMINATING_RE,
    FINALIZER_RE,
    REMAINING_RESOURCE_RE,
    OPERATOR_RE,
    DOC_LOCATOR_RE,
    FIRST_STEP_RE,
    SECURITY_SCOPE_RE,
    EXPLAINER_RE,
    GENERIC_INTRO_RE,
    COMPARE_DECOMPOSE_RE,
    ROUTE_TIMEOUT_RE,
    NODE_NOTREADY_RE,
    CONJUNCTION_SPLIT_RE,
    GENERIC_CONTEXT_TOPIC_RE,
    MACHINE_CONFIG_REBOOT_RE,
    REGISTRY_RE,
    IMAGE_RE,
    STORAGE_RE,
)


def has_doc_locator_intent(query: str) -> bool:
    return bool(DOC_LOCATOR_RE.search(query or ""))


def has_first_step_intent(query: str) -> bool:
    return bool(FIRST_STEP_RE.search(query or ""))


def has_update_doc_locator_intent(query: str) -> bool:
    normalized = query or ""
    if not UPDATE_RE.search(normalized):
        return False
    if has_doc_locator_intent(normalized):
        return True
    return any(
        token in normalized
        for token in (
            "릴리스 노트",
            "release notes",
            "업데이트 가이드",
            "업데이트 문서",
            "뭐부터 보면",
            "뭐부터 봐야",
        )
    )


def has_pod_pending_troubleshooting_intent(query: str) -> bool:
    return bool(POD_PENDING_RE.search(query or ""))


def has_backup_restore_intent(query: str) -> bool:
    return bool(BACKUP_RE.search(query or "") or RESTORE_RE.search(query or ""))


def has_hosted_control_plane_signal(query: str) -> bool:
    return bool(HOSTED_CONTROL_PLANE_RE.search(query or ""))


def has_certificate_monitor_intent(query: str) -> bool:
    normalized = query or ""
    return bool(CERT_RE.search(normalized)) and bool(
        EXPIRY_RE.search(normalized)
        or "확인" in normalized
        or "조회" in normalized
        or "모니터" in normalized
        or "monitor" in normalized.lower()
    )


def has_rbac_intent(query: str) -> bool:
    normalized = query or ""
    if RBAC_RE.search(normalized):
        return True
    if (
        PROJECT_SCOPE_RE.search(normalized)
        and USER_SUBJECT_RE.search(normalized)
        and (
            ROLE_ASSIGN_RE.search(normalized)
            or "역할" in normalized
            or "role" in normalized.lower()
        )
        and (
            ADMIN_ROLE_RE.search(normalized)
            or EDIT_ROLE_RE.search(normalized)
            or VIEW_ROLE_RE.search(normalized)
            or CLUSTER_ADMIN_RE.search(normalized)
        )
    ):
        return True
    return bool(AUTHZ_RE.search(normalized)) and bool(
        PROJECT_SCOPE_RE.search(normalized)
        or ROLE_ASSIGN_RE.search(normalized)
        or ADMIN_ROLE_RE.search(normalized)
        or EDIT_ROLE_RE.search(normalized)
        or VIEW_ROLE_RE.search(normalized)
        or CLUSTER_ADMIN_RE.search(normalized)
    )


def has_project_scoped_rbac_intent(query: str) -> bool:
    normalized = query or ""
    return has_rbac_intent(normalized) and bool(PROJECT_SCOPE_RE.search(normalized))


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
    mentions_scale = bool(SCALE_RE.search(normalized)) or bool(REPLICA_RE.search(normalized))
    if not mentions_scale:
        return False
    if DEPLOYMENTCONFIG_RE.search(normalized):
        return False
    if DEPLOYMENT_RE.search(normalized):
        return True
    lowered = normalized.lower()
    return any(
        token in lowered
        for token in (
            "oc scale deployment",
            "deployment/",
            "deployments.apps/scale",
            "replicas를",
            "복제본 개수",
            "복제본 수",
        )
    )


def has_command_request(query: str) -> bool:
    normalized = query or ""
    return bool(
        re.search(
            r"(명령어|커맨드|cli|oc\s|kubectl\s|yaml|예시|예제로|어떤 명령|뭐라고 쳐|입력하면)",
            normalized,
            re.IGNORECASE,
        )
    )


def is_generic_intro_query(query: str) -> bool:
    if has_route_ingress_compare_intent(query):
        return False
    lowered = (query or "").lower()
    has_intro_ask = bool(EXPLAINER_RE.search(query or "")) or any(
        token in lowered for token in ("뭔데", "뭐지")
    )
    if GENERIC_INTRO_RE.search(query or ""):
        return True
    has_ocp_topic = "openshift" in lowered or bool(OCP_RE.search(query or ""))
    has_kubernetes_topic = bool(KUBERNETES_RE.search(query or ""))
    if has_kubernetes_topic and has_intro_ask:
        non_generic_kubernetes_tokens = (
            "route",
            "ingress",
            "operator",
            "deployment",
            "service",
            "pod",
            "rbac",
            "namespace",
            "yaml",
            "node",
            "etcd",
            "mco",
            "monitoring",
            "logging",
            "인그레스",
            "오퍼레이터",
            "디플로이먼트",
            "파드",
            "네임스페이스",
            "노드",
            "프로젝트",
        )
        if not any(token in lowered for token in non_generic_kubernetes_tokens):
            return True
    return has_ocp_topic and bool(
        ARCHITECTURE_RE.search(query or "") or has_intro_ask
    )


def has_openshift_kubernetes_compare_intent(query: str) -> bool:
    normalized = query or ""
    return bool(OPENSHIFT_RE.search(normalized)) and bool(KUBERNETES_RE.search(normalized)) and bool(
        COMPARE_RE.search(normalized) or "차이를" in normalized or "차이점" in normalized
    )


def has_route_ingress_compare_intent(query: str) -> bool:
    normalized = query or ""
    if not ROUTE_RE.search(normalized) or not INGRESS_RE.search(normalized):
        return False
    return bool(
        COMPARE_RE.search(normalized)
        or "차이를" in normalized
        or "차이점" in normalized
        or (
            "운영 관점" in normalized
            and EXPLAINER_RE.search(normalized)
        )
    )


def is_explainer_query(query: str) -> bool:
    return bool(EXPLAINER_RE.search(query or ""))


def has_pod_lifecycle_concept_intent(query: str) -> bool:
    normalized = query or ""
    return bool(POD_LIFECYCLE_RE.search(normalized)) and bool(is_explainer_query(normalized))


def has_crash_loop_troubleshooting_intent(query: str) -> bool:
    return bool(CRASH_LOOP_RE.search(query or ""))


def has_operator_concept_intent(query: str) -> bool:
    normalized = query or ""
    return (
        bool(OPERATOR_RE.search(normalized))
        and not bool(MCO_RE.search(normalized))
        and bool(
            is_explainer_query(normalized)
            or "뭐 하는" in normalized
            or "뭘 해" in normalized
            or "하는 거야" in normalized
            or "어떤 역할" in normalized
            or "왜 필요" in normalized
            or "왜 중요한" in normalized
            or "예시" in normalized
            or "누가 관리" in normalized
            or "뭘 관리" in normalized
            or "관리해" in normalized
            or (
                has_doc_locator_intent(normalized)
                and any(
                    token in normalized
                    for token in ("처음", "설명", "개념", "기초", "입문")
                )
            )
        )
    )


def has_mco_concept_intent(query: str) -> bool:
    normalized = query or ""
    return bool(MCO_RE.search(normalized)) and bool(
        is_explainer_query(normalized)
        or "뭐 하는" in normalized
        or "뭘 해" in normalized
        or "하는 거야" in normalized
        or "어떤 역할" in normalized
        or "누가 관리" in normalized
        or "뭘 관리" in normalized
        or "건드리면" in normalized
        or "관리해" in normalized
        or (
            has_doc_locator_intent(normalized)
            and any(
                token in normalized
                for token in ("처음", "설명", "개념", "기초", "입문")
            )
        )
    )


def has_machine_config_reboot_intent(query: str) -> bool:
    return bool(MACHINE_CONFIG_REBOOT_RE.search(query or ""))


def has_registry_storage_ops_intent(query: str) -> bool:
    normalized = query or ""
    lowered = normalized.lower()
    registry_signal = bool(REGISTRY_RE.search(normalized)) and (
        bool(IMAGE_RE.search(normalized))
        or "image registry" in lowered
        or "openshift-image-registry" in lowered
    )
    if not registry_signal:
        return False
    return bool(STORAGE_RE.search(normalized)) or any(
        token in normalized
        for token in (
            "구성",
            "설정",
            "변경",
            "적용",
            "연결",
            "생성",
            "만들",
            "구축",
            "절차",
            "방법",
            "하려면",
            "어떻게",
        )
    )


def has_project_terminating_intent(query: str) -> bool:
    normalized = query or ""
    return bool(PROJECT_TERMINATING_RE.search(normalized))


def has_project_finalizer_intent(query: str) -> bool:
    normalized = query or ""
    return bool(FINALIZER_RE.search(normalized)) or (
        has_project_terminating_intent(normalized)
        and bool(REMAINING_RESOURCE_RE.search(normalized))
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
        [
            bool(OCP_RE.search(normalized)),
            bool(OPENSHIFT_RE.search(normalized)),
            bool(ETCD_RE.search(normalized)),
            bool(MCO_RE.search(normalized)),
            bool(RBAC_RE.search(normalized)),
            bool(PROJECT_SCOPE_RE.search(normalized)),
            bool(LOGGING_RE.search(normalized)),
            bool(MONITORING_RE.search(normalized)),
            bool(SECURITY_RE.search(normalized)),
            bool(AUTH_RE.search(normalized)),
            bool(AUTHZ_RE.search(normalized)),
            bool(DEPLOYMENT_RE.search(normalized) and (SCALE_RE.search(normalized) or REPLICA_RE.search(normalized))),
            bool(ARCHITECTURE_RE.search(normalized)),
            bool(OPERATOR_RE.search(normalized)),
            bool(has_registry_storage_ops_intent(normalized)),
            bool(has_route_ingress_compare_intent(normalized)),
        ]
    )

__all__ = [
    "has_doc_locator_intent",
    "has_first_step_intent",
    "has_update_doc_locator_intent",
    "has_pod_pending_troubleshooting_intent",
    "has_backup_restore_intent",
    "has_hosted_control_plane_signal",
    "has_certificate_monitor_intent",
    "has_rbac_intent",
    "has_project_scoped_rbac_intent",
    "has_rbac_assignment_intent",
    "has_deployment_scaling_intent",
    "has_command_request",
    "is_generic_intro_query",
    "has_openshift_kubernetes_compare_intent",
    "has_route_ingress_compare_intent",
    "is_explainer_query",
    "has_pod_lifecycle_concept_intent",
    "has_crash_loop_troubleshooting_intent",
    "has_operator_concept_intent",
    "has_mco_concept_intent",
    "has_machine_config_reboot_intent",
    "has_project_terminating_intent",
    "has_project_finalizer_intent",
    "has_node_drain_intent",
    "has_cluster_node_usage_intent",
    "has_explicit_topic_signal",
]
