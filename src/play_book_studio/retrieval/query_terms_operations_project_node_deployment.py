from __future__ import annotations

from .intents import (
    has_cluster_node_usage_intent,
    has_command_request,
    has_deployment_scaling_intent,
    has_node_drain_intent,
    has_pod_pending_troubleshooting_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
)
from .intent_profile import build_intent_profile


def append_operation_project_node_deployment_terms(normalized: str, terms: list[str]) -> None:
    profile = build_intent_profile(normalized)
    terms.extend(profile.query_terms)

    if has_command_request(normalized) and any(
        token in normalized for token in ("namespace", "namespaces", "네임스페이스", "project", "projects", "프로젝트")
    ):
        terms.extend(["namespace", "project", "current-context", "oc config view"])
        if any(token in normalized for token in ("목록", "list", "전체", "조회")):
            terms.extend(
                [
                    "namespace list",
                    "project list",
                    "oc get namespaces",
                    "oc get namespace",
                    "oc get projects",
                ]
            )
        else:
            terms.extend(
                [
                    "CLI 프로필",
                    "현재 프로젝트 보기",
                    "current project",
                    "oc project",
                ]
            )
    if any(token in normalized for token in ("bootstrap", "부트스트랩")) and any(
        token in normalized for token in ("확인", "기다", "wait", "complete", "완료", "단계", "흐름")
    ):
        terms.extend(
            [
                "Waiting for the bootstrap process to complete",
                "wait-for bootstrap-complete",
                "bootstrap-complete",
                "openshift-install",
                "installation_directory",
                "log-level",
                "Monitor the bootstrap process",
                "Installing a cluster on any platform",
            ]
        )
    if (
        "clusteroperator" in normalized
        or "cluster operator" in normalized
        or "clusteroperators" in normalized
        or "클러스터 오퍼레이터" in normalized
    ):
        terms.extend(
            [
                "ClusterOperator",
                "clusteroperators",
                "oc get clusteroperators",
                "Available Progressing Degraded",
                "Cluster Version Operator",
                "oc adm upgrade status",
            ]
        )
    if "dns" in normalized:
        terms.extend(
            [
                "DNS",
                "DNS Operator",
                "External DNS Operator",
                "dns.operator",
                "networking operators",
                "CoreDNS",
                "openshift-dns",
            ]
        )
    if "event" in normalized or "이벤트" in normalized:
        terms.extend(
            [
                "events",
                "oc get events",
                "lastTimestamp",
                "Warning",
                "describe",
            ]
        )
    if any(token in normalized for token in ("route", "라우트", "경로")) and any(
        token in normalized for token in ("service", "서비스", "endpoint", "엔드포인트", "붙었", "backend")
    ):
        terms.extend(
            [
                "route service endpoints",
                "oc get route",
                "oc get service",
                "oc get endpoints",
                "spec.to.name",
            ]
        )
    if "alertmanager" in normalized or "prometheus" in normalized or "firing alert" in normalized:
        terms.extend(
            [
                "Alertmanager",
                "Prometheus",
                "firing alerts",
                "openshift-monitoring",
                "monitoring",
            ]
        )
    if "resourcequota" in normalized or "resource quota" in normalized:
        terms.extend(["ResourceQuota", "resource quota", "quota", "oc describe resourcequota"])
    if "limitrange" in normalized or "limit range" in normalized:
        terms.extend(["LimitRange", "limit range", "resource requests", "resource limits"])
    if "hpa" in normalized or "horizontalpodautoscaler" in normalized:
        terms.extend(["HorizontalPodAutoscaler", "HPA", "oc describe hpa", "metrics"])
    if "pdb" in normalized or "poddisruptionbudget" in normalized:
        terms.extend(["PodDisruptionBudget", "PDB", "allowed disruptions", "drain"])
    if has_project_terminating_intent(normalized):
        terms.extend(
            [
                "project",
                "namespace",
                "Terminating",
                "delete",
                "oc get project",
                "oc get namespace",
                "oc get events",
                "프로젝트 삭제",
                "종료 중",
            ]
        )
    if has_project_finalizer_intent(normalized):
        terms.extend(
            [
                "finalizer",
                "finalizers",
                "metadata.finalizers",
                "CRD",
                "custom resource",
                "error resolving resource",
            ]
        )
    if has_node_drain_intent(normalized):
        terms.extend(
            [
                "oc",
                "adm",
                "drain",
                "oc adm drain",
                "oc adm uncordon",
                "ignore-daemonsets",
                "cordon",
                "uncordon",
                "worker",
                "node",
            ]
        )
    if any(token in normalized for token in ("oc debug", "debug", "디버그")) and any(
        token in normalized for token in ("node", "노드", "host", "호스트", "chroot")
    ):
        terms.extend(
            [
                "oc debug node",
                "oc debug --as-root node",
                "chroot /host",
                "node debug",
                "host root",
            ]
        )
    if any(token in normalized.lower() for token in ("machineconfigpool", "machine config pool", "mcp", "machineconfig")) or any(
        token in normalized for token in ("머신컨피그", "머신 구성")
    ):
        terms.extend(
            [
                "MachineConfigPool",
                "machine config pool",
                "MCP",
                "oc get mcp",
                "oc describe mcp",
                "oc get co machine-config",
                "Machine Config Operator",
            ]
        )
    if has_cluster_node_usage_intent(normalized):
        terms.extend(
            [
                "oc",
                "adm",
                "top",
                "nodes",
                "cpu",
                "memory",
            ]
        )
    if has_deployment_scaling_intent(normalized):
        terms.extend(
            [
                "deployment",
                "deployments",
                "replicas",
                "oc",
                "scale",
                "--replicas",
                "수동 스케일링",
            ]
        )
    if has_pod_pending_troubleshooting_intent(normalized):
        terms.extend(
            [
                "Pending",
                "pod",
                "status",
                "scheduling",
                "FailedScheduling",
                "scheduler",
                "events",
                "describe",
                "oc",
                "logs",
                "troubleshooting",
                "pod issues",
                "error states",
                "node affinity",
                "taint",
                "toleration",
            ]
        )
