from __future__ import annotations

import re
from dataclasses import dataclass, field

from .intent_detectors import (
    has_cluster_node_usage_intent,
    has_command_request,
    has_deployment_scaling_intent,
    has_node_drain_intent,
    has_pod_pending_troubleshooting_intent,
    has_project_terminating_intent,
)


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
    lowered = (text or "").lower()
    return any(token.lower() in lowered for token in tokens)


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns)


def _profile(
    *,
    intent: str,
    target_object: str,
    task: str,
    needs_command: bool,
    primary_commands: tuple[str, ...],
    evidence_terms: tuple[str, ...],
    query_terms: tuple[str, ...] = (),
    confidence: float,
    reasons: tuple[str, ...],
) -> IntentProfile:
    ordered_terms = (*primary_commands, *evidence_terms, *query_terms)
    seen: set[str] = set()
    deduped_terms: list[str] = []
    for term in ordered_terms:
        cleaned = re.sub(r"\s+", " ", term).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped_terms.append(cleaned)
    return IntentProfile(
        intent=intent,
        target_object=target_object,
        task=task,
        needs_command=needs_command,
        primary_commands=primary_commands,
        evidence_terms=evidence_terms,
        query_terms=tuple(deduped_terms),
        confidence=confidence,
        reasons=reasons,
    )


def build_intent_profile(query: str) -> IntentProfile:
    text = query or ""
    lowered = text.lower()
    command_request = has_command_request(text)

    if command_request and _contains_any(text, ("namespace", "namespaces", "네임스페이스")):
        if _contains_any(text, ("목록", "list", "전체", "조회")):
            return _profile(
                intent="command_lookup",
                target_object="namespace",
                task="list",
                needs_command=True,
                primary_commands=("oc get namespaces", "oc get projects"),
                evidence_terms=("namespace", "project", "list"),
                query_terms=("project list", "namespace list"),
                confidence=0.86,
                reasons=("namespace list command request",),
            )
        return _profile(
            intent="command_lookup",
            target_object="namespace",
            task="current-context",
            needs_command=True,
            primary_commands=("oc project", "oc config view"),
            evidence_terms=("현재 프로젝트 보기", "CLI 프로필", "current-context"),
            confidence=0.82,
            reasons=("namespace current context command request",),
        )

    if _contains_any(text, ("bootstrap", "부트스트랩")) and _contains_any(
        text, ("확인", "기다", "wait", "complete", "완료", "단계", "흐름")
    ):
        return _profile(
            intent="install_step",
            target_object="bootstrap",
            task="wait-for-complete",
            needs_command=True,
            primary_commands=("openshift-install wait-for bootstrap-complete",),
            evidence_terms=("Waiting for the bootstrap process to complete", "wait-for bootstrap-complete"),
            query_terms=("Monitor the bootstrap process", "Installing a cluster on any platform"),
            confidence=0.88,
            reasons=("bootstrap wait step",),
        )

    if _contains_any(text, ("etcd",)) and _contains_any(text, ("backup", "snapshot", "백업", "스냅샷")):
        return _profile(
            intent="operation_sequence",
            target_object="etcd",
            task="backup",
            needs_command=True,
            primary_commands=("oc debug node/<node-name>", "chroot /host", "cluster-backup.sh"),
            evidence_terms=("Backing up etcd", "cluster-backup.sh", "chroot /host", "oc debug"),
            query_terms=("etcd backup", "disaster recovery", "control plane node"),
            confidence=0.84,
            reasons=("etcd backup command sequence",),
        )

    if _contains_any(text, ("clusteroperator", "cluster operator", "clusteroperators", "클러스터 오퍼레이터")):
        return _profile(
            intent="command_lookup",
            target_object="clusteroperator",
            task="status",
            needs_command=True,
            primary_commands=("oc get clusteroperators", "oc describe clusteroperator <operator-name>"),
            evidence_terms=("ClusterOperator", "Available Progressing Degraded", "clusteroperators"),
            query_terms=("Cluster Version Operator", "operator status"),
            confidence=0.84,
            reasons=("clusteroperator status command request",),
        )

    if _contains_any(text, ("oc debug", "debug", "디버그")) and _contains_any(
        text, ("node", "노드", "host", "호스트", "chroot")
    ):
        return _profile(
            intent="operation_sequence",
            target_object="node",
            task="host-debug",
            needs_command=True,
            primary_commands=("oc debug node/<node-name>", "chroot /host"),
            evidence_terms=("oc debug node", "chroot /host", "host root"),
            query_terms=("oc debug --as-root node", "node debug"),
            confidence=0.82,
            reasons=("node debug host access",),
        )

    if has_node_drain_intent(text):
        return _profile(
            intent="operation_sequence",
            target_object="node",
            task="drain-uncordon",
            needs_command=True,
            primary_commands=("oc adm drain <node-name>", "oc adm uncordon <node-name>"),
            evidence_terms=("oc adm drain", "oc adm uncordon", "ignore-daemonsets", "uncordon"),
            confidence=0.82,
            reasons=("node drain workflow",),
        )

    if has_cluster_node_usage_intent(text):
        return _profile(
            intent="command_lookup",
            target_object="node",
            task="resource-usage",
            needs_command=True,
            primary_commands=("oc adm top nodes",),
            evidence_terms=("cpu", "memory", "nodes"),
            confidence=0.84,
            reasons=("node resource usage command",),
        )

    if has_deployment_scaling_intent(text):
        return _profile(
            intent="operation_command",
            target_object="deployment",
            task="scale",
            needs_command=True,
            primary_commands=("oc scale",),
            evidence_terms=("deployment", "replicas", "--replicas"),
            query_terms=("수동 스케일링",),
            confidence=0.8,
            reasons=("deployment scaling command",),
        )

    if command_request and _contains_any(text, ("logs", "log", "previous", "이전", "직전")):
        return _profile(
            intent="command_lookup",
            target_object="pod",
            task="previous-logs",
            needs_command=True,
            primary_commands=("oc logs <pod-name> -n <namespace> --previous",),
            evidence_terms=("oc logs", "--previous", "previous logs"),
            query_terms=("container logs", "pod logs"),
            confidence=0.82,
            reasons=("previous container logs command request",),
        )

    if _contains_any(text, ("pvc", "persistentvolumeclaim", "persistent volume claim")):
        return _profile(
            intent="troubleshooting",
            target_object="persistentvolumeclaim",
            task="pending",
            needs_command=True,
            primary_commands=("oc describe pvc <pvc-name> -n <namespace>", "oc get pvc -n <namespace>"),
            evidence_terms=("PersistentVolumeClaim", "PVC", "Pending", "StorageClass", "Bound"),
            query_terms=("persistent volume claim", "volume binding", "storage class"),
            confidence=0.82,
            reasons=("pvc status troubleshooting",),
        )

    if command_request and _contains_any(text, ("can-i", "can i", "권한", "rbac", "delete pods")):
        return _profile(
            intent="command_lookup",
            target_object="rbac",
            task="access-check",
            needs_command=True,
            primary_commands=("oc auth can-i delete pods -n <namespace>", "oc auth can-i <verb> <resource> -n <namespace>"),
            evidence_terms=("oc auth can-i", "SelfSubjectAccessReview", "SubjectAccessReview", "authorization"),
            query_terms=("RBAC access check", "review permissions"),
            confidence=0.82,
            reasons=("rbac can-i command request",),
        )

    if command_request and _contains_any(text, ("route", "routes", "service", "svc", "endpoint", "endpoints")):
        return _profile(
            intent="command_lookup",
            target_object="route-service",
            task="exposure-check",
            needs_command=True,
            primary_commands=(
                "oc get route -n <namespace>",
                "oc get routes",
                "oc get service -n <namespace>",
                "oc get services",
                "oc get endpoints -n <namespace>",
            ),
            evidence_terms=("Route", "Service", "Endpoints", "oc get routes", "oc get svc"),
            query_terms=("application exposure", "service endpoint"),
            confidence=0.8,
            reasons=("route service exposure command request",),
        )

    if has_pod_pending_troubleshooting_intent(text):
        return _profile(
            intent="troubleshooting",
            target_object="pod",
            task="pending-events",
            needs_command=True,
            primary_commands=("oc describe pod <pod-name> -n <namespace>", "oc get events -n <namespace> --sort-by=.lastTimestamp"),
            evidence_terms=("Pending", "FailedScheduling", "events", "describe"),
            query_terms=("scheduler", "node affinity", "taint", "toleration"),
            confidence=0.8,
            reasons=("pod pending troubleshooting",),
        )

    if "crashloopbackoff" in lowered:
        return _profile(
            intent="troubleshooting",
            target_object="pod",
            task="crashloop",
            needs_command=True,
            primary_commands=("oc describe pod <pod-name> -n <namespace>", "oc logs <pod-name> -n <namespace> --previous"),
            evidence_terms=("CrashLoopBackOff", "Back-off restarting failed container", "logs", "describe"),
            query_terms=("restartCount", "livenessProbe", "readinessProbe", "OOMKilled"),
            confidence=0.82,
            reasons=("crashloop troubleshooting",),
        )

    if _contains_any(text, ("machineconfigpool", "machine config pool", "mcp", "machineconfig", "머신컨피그", "머신 구성")):
        return _profile(
            intent="troubleshooting",
            target_object="machineconfigpool",
            task="status",
            needs_command=True,
            primary_commands=("oc get mcp", "oc describe mcp <pool-name>", "oc get co machine-config"),
            evidence_terms=("MachineConfigPool", "Machine Config Operator", "machine config pool"),
            confidence=0.83,
            reasons=("machine config pool status",),
        )

    if has_project_terminating_intent(text) or (
        "terminating" in lowered
        and _contains_any(text, ("project", "namespace", "프로젝트", "네임스페이스"))
    ):
        return _profile(
            intent="troubleshooting",
            target_object="project",
            task="terminating",
            needs_command=True,
            primary_commands=("oc get project", "oc get namespace <namespace> -o yaml", "oc get namespaces"),
            evidence_terms=("Terminating", "project", "namespace", "finalizers", "error resolving resource"),
            query_terms=("프로젝트 삭제", "종료 중"),
            confidence=0.78,
            reasons=("project terminating troubleshooting",),
        )

    if command_request:
        return _profile(
            intent="command_lookup",
            target_object="",
            task="",
            needs_command=True,
            primary_commands=(),
            evidence_terms=(),
            confidence=0.42,
            reasons=("generic command request",),
        )

    return IntentProfile()
