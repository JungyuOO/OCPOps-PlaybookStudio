from __future__ import annotations

from .intents import (
    has_cluster_node_usage_intent,
    has_deployment_scaling_intent,
    has_node_drain_intent,
    has_pod_pending_troubleshooting_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
)


def append_operation_project_node_deployment_terms(normalized: str, terms: list[str]) -> None:
    if "clusteroperator" in normalized or "cluster operator" in normalized or "clusteroperators" in normalized:
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
        terms.extend(["project", "namespace", "Terminating", "delete"])
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
                "ignore-daemonsets",
                "cordon",
                "worker",
                "node",
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
