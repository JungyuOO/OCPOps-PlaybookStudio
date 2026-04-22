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
