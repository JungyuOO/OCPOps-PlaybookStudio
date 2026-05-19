"""One-shot query signal planning for the RAG retrieval pipeline.

This layer turns a user question into retrieval-only signals. It does not
answer the user and it does not call a separate intent-agent service.
"""

from __future__ import annotations

import re
import json
import time
from dataclasses import dataclass
from typing import Any

from .domain_lexicon import (
    DOMAIN_LEXICONS,
    query_matches_domain,
    query_matches_dynamic_variant,
    query_matches_static_variant,
)

from .query_understanding import StructuredQuerySignals, understand_query_signals


@dataclass(frozen=True, slots=True)
class QueryCorrection:
    type: str
    source: str
    replacement: str

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "from": self.source,
            "to": self.replacement,
        }


@dataclass(frozen=True, slots=True)
class QuerySignalPlan:
    raw_query: str
    normalized_query: str
    correction_notes: tuple[QueryCorrection, ...]
    classification: dict[str, Any]
    search_signals: dict[str, tuple[str, ...]]
    confidence: dict[str, float]
    embedding_queries: tuple[str, ...]
    metadata_filter: dict[str, Any]
    debug: dict[str, Any]

    @property
    def vector_query(self) -> str:
        return self.embedding_queries[0] if self.embedding_queries else self.normalized_query

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "normalized_query": self.normalized_query,
            "correction_notes": [item.to_dict() for item in self.correction_notes],
            "classification": dict(self.classification),
            "search_signals": {key: list(value) for key, value in self.search_signals.items()},
            "confidence": dict(self.confidence),
            "embedding_queries": list(self.embedding_queries),
            "metadata_filter": self.metadata_filter,
            "vector_query": self.vector_query,
            "debug": self.debug,
        }


_NORMALIZATION_RULES: tuple[tuple[str, str, str], ...] = (
    (r"피\s*브이\s*씨|피브이씨", "PVC", "object_alias"),
    (r"피\s*브이|피브이", "PV", "object_alias"),
    (r"파드", "Pod", "object_alias"),
    (r"라우트", "Route", "object_alias"),
    (r"시크릿", "Secret", "object_alias"),
    (r"노드", "Node", "object_alias"),
    (r"이미지\s*풀\s*백\s*오프|이미지풀백오프", "ImagePullBackOff", "error_alias"),
    (r"노트\s*레디|노트레디", "NotReady", "error_alias"),
    (r"\bnot\s+ready\b", "NotReady", "error_alias"),
    (r"\bimage\s+pull\s+back\s+off\b", "ImagePullBackOff", "error_alias"),
    (
        r"(?<![A-Za-z])peding(?![A-Za-z])|"
        r"(?<![A-Za-z])pendding(?![A-Za-z])|"
        r"(?<![A-Za-z])pendig(?![A-Za-z])",
        "Pending",
        "error_alias",
    ),
)

_ALLOWED_DOMAINS = {
    "install",
    "storage",
    "networking",
    "security",
    "monitoring",
    "troubleshooting",
    "upgrade",
    "operators",
    "logging",
    "registry",
    "ui_tooling",
    "architecture",
    "release_notes",
    "node_ops",
    "backup_restore",
    "etcd",
}
_ALLOWED_PLATFORMS = {"bare_metal", "agent_based", "any_platform", "none"}
_SEARCH_SIGNAL_KEYS = (
    "objects",
    "error_states",
    "intent_labels",
    "answer_shapes",
    "command_families",
    "primary_topics",
    "cluster_phase",
    "execution_target",
    "commands",
    "secondary_topics",
    "components",
)
_ALLOWED_INTENT_LABELS = {
    "explain_concept",
    "check_status",
    "verify_result",
    "troubleshoot",
    "configure_resource",
    "create_resource",
    "update_resource",
    "delete_resource",
    "backup",
    "restore",
    "install",
    "upgrade",
    "compare_options",
    "find_document",
    "command_lookup",
    "summarize",
    "list_prerequisites",
    "identify_execution_target",
    "explain_warning",
    "next_steps",
}
_ALLOWED_ANSWER_SHAPES = {
    "short_explanation",
    "step_by_step",
    "command",
    "checklist",
    "yaml_example",
    "decision_guide",
    "warning",
    "troubleshooting_flow",
    "document_link",
}
_ALLOWED_COMMAND_FAMILIES = {
    "oc_get",
    "oc_describe",
    "oc_logs",
    "oc_debug",
    "oc_apply",
    "oc_create",
    "oc_delete",
    "oc_adm",
    "oc_project",
    "oc_explain",
    "kubectl_get",
    "kubectl_describe",
    "etcdctl",
    "cluster_backup",
}
_COMMAND_ALIAS_RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "oc_login",
        "aliases": ("oc login", "login", "로그인", "클러스터 로그인", "ocp 로그인", "openshift 로그인"),
        "commands": ("oc login -u <username>", "oc whoami"),
        "command_families": ("oc_get",),
        "objects": (),
        "primary_topics": ("OpenShift CLI login", "cluster login", "authentication"),
    },
    {
        "name": "pod_disruption_budget",
        "aliases": (
            "poddisruptionbudget",
            "pod disruption budget",
            "pdb",
            "pod 중단 예산",
            "pod 중단",
            "pdb 확인",
            "pod 중단 예산",
            "파드 중단 예산",
            "중단 예산",
        ),
        "commands": ("oc get poddisruptionbudget --all-namespaces",),
        "command_families": ("oc_get",),
        "objects": ("PodDisruptionBudget", "PDB", "Pod"),
        "primary_topics": ("PodDisruptionBudget", "pod disruption budget", "all namespaces"),
    },
    {
        "name": "openshift_version",
        "aliases": (
            "openshift-install version",
            "openshift install version",
            "openshift-install 버전",
            "ocp 버전",
            "openshift 버전",
            "버전 확인",
        ),
        "domain": "install",
        "book_slug_candidates": ("cli_tools", "installing_on_any_platform", "installation_overview"),
        "commands": ("openshift-install version", "oc version", "oc get clusterversion"),
        "command_families": ("oc_get",),
        "objects": ("ClusterVersion",),
        "primary_topics": ("OpenShift version", "OpenShift CLI", "installer version"),
    },
    {
        "name": "node_cordon_drain",
        "aliases": ("cordon", "drain", "노드 cordon", "노드 drain", "노드 중지", "노드 비우기"),
        "domain": "node_ops",
        "book_slug_candidates": ("nodes", "machine_management"),
        "commands": ("oc adm cordon <node_name>", "oc adm drain <node_name>"),
        "command_families": ("oc_adm",),
        "objects": ("Node", "Pod"),
        "primary_topics": ("node maintenance", "cordon", "drain"),
    },
    {
        "name": "node_taint",
        "aliases": ("taint", "테인트", "노드 taint", "노드에 taint"),
        "domain": "node_ops",
        "book_slug_candidates": ("nodes", "machine_management"),
        "commands": ("oc describe node <node_name>", "oc adm taint nodes <node_name> <key>=<value>:<effect>"),
        "command_families": ("oc_describe", "oc_adm"),
        "objects": ("Node", "Taint"),
        "primary_topics": ("node taint", "node scheduling"),
    },
    {
        "name": "node_debug_shell",
        "aliases": ("debug shell", "debug node", "oc debug node", "노드 debug", "노드 디버그", "debug shell로"),
        "domain": "node_ops",
        "book_slug_candidates": ("nodes", "support"),
        "commands": ("oc debug node/<node_name>", "chroot /host"),
        "command_families": ("oc_debug",),
        "objects": ("Node",),
        "primary_topics": ("node debug", "debug shell", "host shell"),
    },
    {
        "name": "pods_on_node",
        "aliases": (
            "spec.nodename",
            "field-selector spec.nodename",
            "노드에 올라간",
            "노드에 있는 pod",
            "노드의 pod",
            "특정 노드",
            "스케줄",
            "특정 노드에 스케줄",
            "노드에 올라간 pod",
            "pod 목록을 확인",
        ),
        "domain": "node_ops",
        "book_slug_candidates": ("nodes",),
        "commands": ("oc get pods -A -o wide", "oc get pods -A --field-selector spec.nodeName=<node_name>"),
        "command_families": ("oc_get",),
        "objects": ("Node", "Pod"),
        "primary_topics": ("pods on node", "node pod listing"),
    },
    {
        "name": "operator_status",
        "aliases": (
            "operator 설치 상태",
            "operator 상태",
            "csv",
            "clusterserviceversion",
            "subscription",
            "installplan",
            "operatorgroup",
            "operator 목록",
            "operator pending",
        ),
        "domain": "operators",
        "book_slug_candidates": ("operators",),
        "commands": (
            "oc get csv",
            "oc get subscription",
            "oc get installplan",
            "oc get operatorgroup",
            "oc get operators",
        ),
        "command_families": ("oc_get",),
        "objects": ("Operator", "ClusterServiceVersion", "Subscription", "InstallPlan", "OperatorGroup"),
        "primary_topics": ("Operator Lifecycle Manager", "operator status", "CSV", "Subscription", "InstallPlan"),
    },
    {
        "name": "monitoring_operator_status",
        "aliases": (
            "모니터링 operator",
            "monitoring operator",
            "prometheus pod",
            "alertmanager",
            "thanos querier",
            "serviceMonitor",
            "servicemonitor",
        ),
        "domain": "monitoring",
        "book_slug_candidates": ("monitoring", "observability_overview", "operators"),
        "commands": (
            "oc get clusteroperator monitoring",
            "oc get pods -n openshift-monitoring",
            "oc get route -n openshift-monitoring",
        ),
        "command_families": ("oc_get",),
        "objects": ("ClusterOperator", "Pod", "Route", "ServiceMonitor"),
        "primary_topics": ("monitoring", "Prometheus", "Alertmanager", "ServiceMonitor"),
    },
    {
        "name": "logging_operator_status",
        "aliases": (
            "logging operator",
            "openshift logging operator",
            "로그 수집",
            "감사 로그",
            "audit log",
            "oc adm node-logs",
            "systemd unit 로그",
        ),
        "domain": "logging",
        "book_slug_candidates": ("logging", "observability_overview", "support"),
        "commands": (
            "oc get csv -n openshift-logging",
            "oc get pods -n openshift-logging",
            "oc adm node-logs <node_name> -u <unit_name>",
        ),
        "command_families": ("oc_get", "oc_adm"),
        "objects": ("Operator", "Pod", "Node"),
        "primary_topics": ("OpenShift Logging", "audit log", "node logs"),
    },
    {
        "name": "etcd_backup_restore",
        "aliases": (
            "etcd 백업",
            "etcd 복구",
            "cluster-backup",
            "cluster-backup.sh",
            "etcdctl",
            "etcd pod",
            "etcd 멤버",
            "etcd proxy",
        ),
        "domain": "etcd",
        "book_slug_candidates": ("etcd", "backup_and_restore"),
        "commands": (
            "oc debug node/<control-plane-node>",
            "chroot /host",
            "cluster-backup.sh",
            "oc get pods -n openshift-etcd -l k8s-app=etcd",
            "oc rsh -n openshift-etcd <etcd_pod>",
            "etcdctl endpoint status",
            "oc get proxy cluster -o yaml",
        ),
        "command_families": ("oc_get", "oc_debug", "cluster_backup", "etcdctl"),
        "objects": ("Pod", "Node", "Proxy", "etcd"),
        "primary_topics": ("etcd", "etcd backup", "etcd restore", "control plane"),
    },
    {
        "name": "route_service_status",
        "aliases": ("route가 어떤 service", "route service", "route host", "admitted", "ingresscontroller", "jsonpath"),
        "domain": "networking",
        "book_slug_candidates": ("ingress_and_load_balancing", "networking"),
        "commands": (
            "oc get route",
            "oc describe route",
            "oc get service",
            "oc get ingresscontroller -n openshift-ingress-operator -o jsonpath='{.items[*].status.conditions}'",
        ),
        "command_families": ("oc_get", "oc_describe"),
        "objects": ("Route", "Service", "IngressController"),
        "primary_topics": ("Route", "IngressController", "service routing"),
    },
    {
        "name": "rbac_rolebinding_subjects",
        "aliases": (
            "rolebinding",
            "clusterrolebinding",
            "serviceaccount",
            "service account",
            "권한",
            "pull secret을 serviceaccount",
            "image pull secret",
        ),
        "domain": "security",
        "book_slug_candidates": ("authentication_and_authorization", "security_and_compliance", "images"),
        "commands": (
            "oc get rolebinding",
            "oc get clusterrolebinding",
            "oc get serviceaccount",
            "oc secrets link <serviceaccount> <pull_secret> --for=pull",
        ),
        "command_families": ("oc_get",),
        "objects": ("RoleBinding", "ClusterRoleBinding", "ServiceAccount", "Secret"),
        "primary_topics": ("RBAC", "ServiceAccount", "image pull secret"),
    },
    {
        "name": "pod_events_logs",
        "aliases": (
            "pod 이벤트",
            "pod 로그",
            "컨테이너 로그",
            "이전 컨테이너",
            "pod 이벤트",
            "pod 이벤트만",
            "pod 로그",
            "컨테이너 로그",
            "crashloopbackoff",
            "oomkilled",
            "readiness probe",
        ),
        "domain": "troubleshooting",
        "book_slug_candidates": ("support", "cli_tools", "nodes"),
        "commands": (
            "oc describe pod <pod_name>",
            "oc logs <pod_name>",
            "oc logs <pod_name> --previous",
            "oc get events",
        ),
        "command_families": ("oc_describe", "oc_logs", "oc_get"),
        "objects": ("Pod", "Event"),
        "primary_topics": ("pod troubleshooting", "pod events", "container logs"),
    },
    {
        "name": "cluster_events",
        "aliases": (
            "event",
            "events",
            "이벤트",
            "전체 네임스페이스",
            "모든 네임스페이스",
            "이벤트",
            "전체 네임스페이스 이벤트",
            "모든 네임스페이스 이벤트",
            "all namespaces event",
            "all-namespaces events",
        ),
        "domain": "troubleshooting",
        "book_slug_candidates": ("support", "nodes", "cli_tools"),
        "commands": ("oc get events -A", "oc get events --all-namespaces"),
        "command_families": ("oc_get",),
        "objects": ("Event",),
        "primary_topics": ("cluster events", "all namespaces", "troubleshooting"),
    },
    {
        "name": "namespace_project_ops",
        "aliases": (
            "oc project",
            "프로젝트 전환",
            "현재 프로젝트",
            "네임스페이스 안의 모든 리소스",
            "namespace all resources",
            "project all resources",
            "클러스터 api 주소",
            "api 주소",
        ),
        "domain": "architecture",
        "book_slug_candidates": ("cli_tools", "architecture"),
        "commands": ("oc project <project_name>", "oc get all -n <namespace>", "oc whoami --show-server"),
        "command_families": ("oc_project", "oc_get"),
        "objects": ("Project", "Namespace"),
        "primary_topics": ("OpenShift CLI project", "namespace resources", "cluster API server"),
    },
    {
        "name": "storageclass_ops",
        "aliases": (
            "storageclass",
            "storage class",
            "기본 storageclass",
            "기본 storage class",
            "default storageclass",
            "storageclass 목록",
            "allowvolumeexpansion",
            "용량 확장",
            "volumesnapshot",
        ),
        "domain": "storage",
        "book_slug_candidates": ("storage",),
        "commands": (
            "oc get storageclass",
            "oc get storageclass -o yaml",
            "oc patch storageclass <storageclass_name>",
            "oc get volumesnapshot",
            "oc get volumesnapshotclass",
        ),
        "command_families": ("oc_get",),
        "objects": ("StorageClass", "VolumeSnapshot", "VolumeSnapshotClass", "PVC"),
        "primary_topics": ("StorageClass", "default StorageClass", "volume expansion", "VolumeSnapshot"),
    },
    {
        "name": "service_endpoint_ops",
        "aliases": (
            "endpointslice",
            "endpoint slice",
            "service가 pod",
            "service pod",
            "서비스가 pod",
            "서비스 dns",
            "service dns",
            "트래픽",
            "endpoint",
        ),
        "domain": "networking",
        "book_slug_candidates": ("networking", "ingress_and_load_balancing"),
        "commands": ("oc get service", "oc describe service", "oc get endpointslice"),
        "command_families": ("oc_get", "oc_describe"),
        "objects": ("Service", "EndpointSlice", "Pod"),
        "primary_topics": ("Service", "EndpointSlice", "service discovery"),
    },
    {
        "name": "rbac_can_i",
        "aliases": (
            "can-i",
            "auth can-i",
            "권한 확인",
            "어떤 권한",
            "pod 목록을 볼 수",
            "만들 수 있는지",
            "serviceaccount 권한",
            "service account 권한",
        ),
        "domain": "security",
        "book_slug_candidates": ("authentication_and_authorization", "security_and_compliance"),
        "commands": (
            "oc auth can-i <verb> <resource>",
            "oc auth can-i get pods --as system:serviceaccount:<namespace>:<serviceaccount>",
            "oc describe serviceaccount <serviceaccount_name>",
        ),
        "command_families": ("oc_get",),
        "objects": ("ServiceAccount", "RoleBinding", "ClusterRoleBinding", "Pod"),
        "primary_topics": ("RBAC", "oc auth can-i", "ServiceAccount permissions"),
    },
    {
        "name": "node_and_cluster_logs",
        "aliases": (
            "이전 로그",
            "--previous",
            "kubelet 로그",
            "kubelet 서비스 로그",
            "journal",
            "node-logs",
            "ovn node pod 로그",
            "ovn-kubernetes 로그",
            "operator pod 로그",
            "현재 로그 이전 로그",
        ),
        "domain": "logging",
        "book_slug_candidates": ("support", "logging", "networking"),
        "commands": (
            "oc adm node-logs <node_name> -u kubelet",
            "oc logs -n openshift-ovn-kubernetes <pod_name>",
            "oc logs -n <namespace> <pod_name>",
            "oc logs -n <namespace> <pod_name> --previous",
        ),
        "command_families": ("oc_logs", "oc_adm"),
        "objects": ("Node", "Pod"),
        "primary_topics": ("node logs", "kubelet", "OVN Kubernetes logs", "pod logs"),
    },
    {
        "name": "oc_mirror_ops",
        "aliases": (
            "oc-mirror",
            "미러링 결과",
            "imagecontentsourcepolicy",
            "imagedigestmirrorset",
            "catalogsource",
            "disconnected 미러링",
        ),
        "domain": "install",
        "book_slug_candidates": ("disconnected_installation_mirroring", "installing_on_any_platform", "operators"),
        "commands": (
            "oc get imagecontentsourcepolicy",
            "oc get imagedigestmirrorset",
            "oc get catalogsource -A",
        ),
        "command_families": ("oc_get",),
        "objects": ("ImageContentSourcePolicy", "ImageDigestMirrorSet", "CatalogSource"),
        "primary_topics": ("disconnected installation", "oc-mirror", "mirror registry"),
    },
    {
        "name": "operator_action_ops",
        "aliases": (
            "수동 승인 installplan",
            "installplan 승인",
            "operatorhub",
            "packagemanifest",
            "catalogsource 상태",
            "csv failed",
        ),
        "domain": "operators",
        "book_slug_candidates": ("operators",),
        "commands": (
            "oc patch installplan <installplan_name> --type merge -p '{\"spec\":{\"approved\":true}}'",
            "oc get packagemanifest",
            "oc describe packagemanifest <package_name>",
            "oc get catalogsource -n openshift-marketplace",
            "oc get csv",
        ),
        "command_families": ("oc_get", "oc_describe"),
        "objects": ("InstallPlan", "PackageManifest", "CatalogSource", "ClusterServiceVersion"),
        "primary_topics": ("OperatorHub", "InstallPlan approval", "CatalogSource", "CSV"),
    },
    {
        "name": "workload_node_scheduling",
        "aliases": (
            "daemonset",
            "daemonset on every node",
            "scheduled on node",
            "spec.nodename",
            "field-selector spec.nodename",
            "노드마다",
            "특정 노드",
            "스케줄",
            "스케줄됐",
            "노드에 올라간 pod",
        ),
        "domain": "node_ops",
        "book_slug_candidates": ("nodes", "support"),
        "commands": (
            "oc get daemonset -A -o wide",
            "oc get pods -A -o wide",
            "oc get pods -A --field-selector spec.nodeName=<node_name>",
        ),
        "command_families": ("oc_get",),
        "objects": ("DaemonSet", "Pod", "Node"),
        "primary_topics": ("pod scheduling", "DaemonSet", "node workloads"),
    },
    {
        "name": "cluster_network_config",
        "aliases": (
            "cluster network",
            "network.operator",
            "network config",
            "cluster network config",
            "클러스터 네트워크",
            "네트워크 설정",
            "describe해서 봐",
        ),
        "domain": "networking",
        "book_slug_candidates": ("networking", "networking_overview"),
        "commands": ("oc describe network.operator cluster", "oc get network.operator cluster -o yaml"),
        "command_families": ("oc_get", "oc_describe"),
        "objects": ("Network",),
        "primary_topics": ("cluster network configuration", "Network operator"),
    },
    {
        "name": "install_prereq_and_fips",
        "aliases": (
            "pull secret",
            "ssh key",
            "ssh 키",
            "fips installer",
            "fips 설치 프로그램",
            "rhcos iso",
            "kernel argument",
            "kernel arguments",
            "disconnected",
            "설치 방식",
            "준비 항목",
            "설치 전에",
            "커널 argument",
        ),
        "domain": "install",
        "book_slug_candidates": ("installation_overview", "installing_on_any_platform", "disconnected_installation_mirroring"),
        "commands": (
            "openshift-install create install-config",
            "openshift-install coreos print-stream-json",
            "oc adm release extract --command=openshift-install",
        ),
        "command_families": ("oc_adm",),
        "objects": ("InstallConfig", "Secret"),
        "primary_topics": ("OpenShift installation", "pull secret", "SSH key", "RHCOS"),
    },
    {
        "name": "monitoring_runtime_ops",
        "aliases": (
            "cluster alert",
            "cluster alerts",
            "alertmanager route",
            "prometheus pod",
            "thanos querier",
            "servicemonitor",
            "service monitor",
            "클러스터 알람",
            "알람",
            "메트릭 수집",
            "현재 채널",
            "업데이트 가능한 채널",
        ),
        "domain": "monitoring",
        "book_slug_candidates": ("monitoring", "support", "updating_clusters"),
        "commands": (
            "oc get co monitoring",
            "oc get pods -n openshift-monitoring",
            "oc logs -n openshift-monitoring <pod_name>",
            "oc get route -n openshift-monitoring",
            "oc get servicemonitor -A",
            "oc adm upgrade",
        ),
        "command_families": ("oc_get", "oc_logs", "oc_adm"),
        "objects": ("Prometheus", "Alertmanager", "ServiceMonitor", "ClusterVersion"),
        "primary_topics": ("monitoring", "alerts", "Prometheus", "Alertmanager", "cluster updates"),
    },
    {
        "name": "security_runtime_ops",
        "aliases": (
            "oauth pod",
            "rolebinding 대상",
            "serviceaccount pod 목록",
            "특정 리소스를 만들 수",
            "imagepullbackoff",
            "pull secret",
            "serviceaccount에 연결",
            "권한 확인",
        ),
        "domain": "security",
        "book_slug_candidates": ("authentication_and_authorization", "security_and_compliance", "images"),
        "commands": (
            "oc auth can-i <verb> <resource>",
            "oc auth can-i get pods --as system:serviceaccount:<namespace>:<serviceaccount>",
            "oc get rolebinding -o wide",
            "oc get clusterrolebinding -o wide",
            "oc get pods -n openshift-authentication",
            "oc logs -n openshift-authentication <pod_name>",
            "oc get serviceaccount <serviceaccount_name> -o yaml",
            "oc secrets link <serviceaccount> <pull_secret> --for=pull",
        ),
        "command_families": ("oc_get", "oc_logs"),
        "objects": ("OAuth", "Pod", "ServiceAccount", "RoleBinding", "Secret"),
        "primary_topics": ("authentication", "authorization", "RBAC", "pull secret"),
    },
    {
        "name": "odf_storage_ops",
        "aliases": (
            "odf cluster",
            "odf 클러스터",
            "ceph 상태",
            "볼륨 분리",
            "node shutdown",
            "volume detach",
        ),
        "domain": "storage",
        "book_slug_candidates": ("storage",),
        "commands": (
            "oc get storagecluster -n openshift-storage",
            "oc get cephcluster -n openshift-storage",
            "oc get pods -n openshift-storage",
            "oc describe volumeattachment <volumeattachment_name>",
        ),
        "command_families": ("oc_get", "oc_describe"),
        "objects": ("StorageCluster", "CephCluster", "Pod", "VolumeAttachment"),
        "primary_topics": ("OpenShift Data Foundation", "Ceph", "volume detach"),
    },
)


def build_query_signal_plan(
    query: str,
    *,
    ocp_version: str = "4.20",
    locale: str = "ko",
    llm_client: Any | None = None,
) -> QuerySignalPlan:
    fallback = _build_rule_based_query_signal_plan(query, ocp_version=ocp_version, locale=locale)
    if llm_client is None:
        return fallback
    try:
        return _build_llm_query_signal_plan(
            raw_query=fallback.raw_query,
            fallback=fallback,
            llm_client=llm_client,
            ocp_version=ocp_version,
            locale=locale,
        )
    except Exception:  # noqa: BLE001
        return fallback


def _build_rule_based_query_signal_plan(
    query: str,
    *,
    ocp_version: str = "4.20",
    locale: str = "ko",
) -> QuerySignalPlan:
    raw_query = " ".join(str(query or "").split())
    normalized_query, correction_notes = _normalize_query(raw_query)
    baseline = understand_query_signals(normalized_query, ocp_version=ocp_version, locale=locale)
    classification = dict(baseline.classification)
    classification.setdefault("platform", "any_platform")
    search_signals = {key: list(value) for key, value in baseline.search_signals.items()}
    confidence = dict(baseline.confidence)

    _apply_domain_specific_enrichment(
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )
    _prune_query_signal_noise(
        raw_query=raw_query,
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )

    normalized_signals = {
        key: tuple(dict.fromkeys(item for item in values if str(item or "").strip()))
        for key, values in search_signals.items()
    }
    embedding_queries = _embedding_queries(
        raw_query=raw_query,
        normalized_query=normalized_query,
        baseline=baseline,
        search_signals=normalized_signals,
    )
    metadata_filter = _metadata_filter(
        classification=classification,
        confidence=confidence,
        search_signals=normalized_signals,
    )

    return QuerySignalPlan(
        raw_query=raw_query,
        normalized_query=normalized_query,
        correction_notes=correction_notes,
        classification=classification,
        search_signals=normalized_signals,
        confidence=confidence,
        embedding_queries=embedding_queries,
        metadata_filter=metadata_filter,
        debug={
            "mode": "rule_based",
            "llm_enabled": False,
            "raw_query": raw_query,
        },
    )


def _build_llm_query_signal_plan(
    *,
    raw_query: str,
    fallback: QuerySignalPlan,
    llm_client: Any,
    ocp_version: str,
    locale: str,
) -> QuerySignalPlan:
    total_started_at = time.perf_counter()
    timeline_origin = total_started_at

    def _elapsed_ms() -> float:
        return round((time.perf_counter() - timeline_origin) * 1000, 1)

    timeline_ms: dict[str, float] = {
        "rewrite_start": 0.0,
        "messages_build_start": 0.0,
    }
    messages_started_at = time.perf_counter()
    messages = _query_signal_messages(raw_query=raw_query, ocp_version=ocp_version, locale=locale)
    messages_ms = round((time.perf_counter() - messages_started_at) * 1000, 1)
    timeline_ms["messages_build_done"] = _elapsed_ms()
    timeline_ms["llm_request_start"] = _elapsed_ms()
    llm_started_at = time.perf_counter()
    query_signal_max_tokens = 300
    content = llm_client.generate(
        messages,
        max_tokens=query_signal_max_tokens,
    )
    llm_runtime_meta = (
        llm_client.runtime_metadata()
        if hasattr(llm_client, "runtime_metadata")
        else {}
    )
    llm_ms = round((time.perf_counter() - llm_started_at) * 1000, 1)
    timeline_ms["llm_response_received"] = _elapsed_ms()
    timeline_ms["json_parse_start"] = _elapsed_ms()
    parse_started_at = time.perf_counter()
    payload = _expand_minimal_query_signal_payload(
        _extract_json_object(content),
        fallback=fallback,
        ocp_version=ocp_version,
        locale=locale,
    )
    parse_ms = round((time.perf_counter() - parse_started_at) * 1000, 1)
    timeline_ms["json_parse_done"] = _elapsed_ms()
    timeline_ms["validation_start"] = _elapsed_ms()
    validate_started_at = time.perf_counter()
    plan = _validated_llm_plan(
        raw_query=raw_query,
        payload=payload,
        fallback=fallback,
        ocp_version=ocp_version,
        locale=locale,
    )
    validate_ms = round((time.perf_counter() - validate_started_at) * 1000, 1)
    total_ms = round((time.perf_counter() - total_started_at) * 1000, 1)
    timeline_ms["validation_done"] = _elapsed_ms()
    timeline_ms["rewrite_done"] = total_ms
    debug = {
        "mode": "llm",
        "llm_enabled": True,
        "raw_query": raw_query,
        "messages": messages,
        "request": {
            "max_tokens": query_signal_max_tokens,
            "message_count": len(messages),
            "prompt_chars": sum(len(str(message.get("content") or "")) for message in messages),
        },
        "llm_runtime": llm_runtime_meta,
        "llm_http_debug": llm_runtime_meta.get("last_http_debug", {}),
        "raw_response": content,
        "parsed_payload": payload,
        "validated_plan": {
            "normalized_query": plan.normalized_query,
            "correction_notes": [item.to_dict() for item in plan.correction_notes],
            "classification": dict(plan.classification),
            "search_signals": {key: list(value) for key, value in plan.search_signals.items()},
            "confidence": dict(plan.confidence),
            "embedding_queries": list(plan.embedding_queries),
            "metadata_filter": plan.metadata_filter,
        },
        "timings_ms": {
            "messages_build": messages_ms,
            "llm_generate": llm_ms,
            "json_parse": parse_ms,
            "validation": validate_ms,
            "total": total_ms,
        },
        "timeline_ms": timeline_ms,
    }
    return QuerySignalPlan(
        raw_query=plan.raw_query,
        normalized_query=plan.normalized_query,
        correction_notes=plan.correction_notes,
        classification=plan.classification,
        search_signals=plan.search_signals,
        confidence=plan.confidence,
        embedding_queries=plan.embedding_queries,
        metadata_filter=plan.metadata_filter,
        debug=debug,
    )


def _query_signal_messages(*, raw_query: str, ocp_version: str, locale: str) -> list[dict[str, str]]:
    domains = ",".join(sorted(_ALLOWED_DOMAINS))
    intents = ",".join(sorted(_ALLOWED_INTENT_LABELS))
    command_families = ",".join(sorted(_ALLOWED_COMMAND_FAMILIES))
    return [
        {
            "role": "system",
            "content": (
                "Extract minimal OpenShift RAG retrieval signals. Return JSON only. "
                "No markdown, no explanation, no user answer. "
                "Output exactly these keys: normalized_query, domain, objects, "
                "error_states, intent_labels, command_families, commands, queries, confidence. "
                "Keep strings short. Arrays max 3. queries exactly 2. "
                "If commands are known, include exact commands in normalized_query and each query. "
                f"domains={domains}. intents={intents}. command_families={command_families}. "
                "Use resource domain for troubleshooting: Node=>node_ops, PVC=>storage, "
                "ImagePullBackOff=>registry."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": raw_query,
                    "context": {"ocp_version": ocp_version, "locale": locale},
                },
                ensure_ascii=False,
            ),
        },
    ]


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("query signal LLM response must be a JSON object")
    return payload


def _expand_minimal_query_signal_payload(
    payload: dict[str, Any],
    *,
    fallback: QuerySignalPlan,
    ocp_version: str,
    locale: str,
) -> dict[str, Any]:
    if isinstance(payload.get("classification"), dict) or isinstance(payload.get("search_signals"), dict):
        return payload

    domain = _clean_text(payload.get("domain"), max_chars=40)
    domain_values = payload.get("domain_filter_values") or payload.get("domains") or ([domain] if domain else [])
    commands = payload.get("commands") or []
    objects = payload.get("objects") or []
    error_states = payload.get("error_states") or []
    normalized_query = _clean_text(payload.get("normalized_query"), fallback.normalized_query, max_chars=180)
    queries = list(_string_tuple(payload.get("queries") or payload.get("embedding_queries") or [], max_items=2, max_chars=140))
    confidence = payload.get("confidence") if isinstance(payload.get("confidence"), dict) else {}
    if not confidence:
        confidence = {
            "domain": 0.9 if domain else 0.0,
            "objects": 0.9 if payload.get("objects") else 0.0,
            "commands": 0.9 if commands else 0.0,
        }

    return {
        "normalized_query": normalized_query,
        "correction_notes": payload.get("correction_notes") or [],
        "classification": {
            "domain": domain,
            "book_slug_candidates": payload.get("book_slug_candidates") or [],
            "domain_filter_values": domain_values,
            "platform": payload.get("platform") or "any_platform",
            "ocp_version": ocp_version,
            "locale": locale,
        },
        "search_signals": {
            "objects": objects,
            "error_states": error_states,
            "intent_labels": payload.get("intent_labels") or payload.get("intents") or [],
            "answer_shapes": payload.get("answer_shapes") or (["command"] if commands else []),
            "command_families": payload.get("command_families") or [],
            "primary_topics": payload.get("primary_topics") or [],
            "cluster_phase": payload.get("cluster_phase") or [],
            "execution_target": payload.get("execution_target") or [],
            "commands": commands,
            "secondary_topics": payload.get("secondary_topics") or [],
            "components": payload.get("components") or [],
        },
        "confidence": confidence,
        "embedding_queries": queries,
    }


def _validated_llm_plan(
    *,
    raw_query: str,
    payload: dict[str, Any],
    fallback: QuerySignalPlan,
    ocp_version: str,
    locale: str,
) -> QuerySignalPlan:
    normalized_query = _clean_text(payload.get("normalized_query"), fallback.normalized_query, max_chars=500)
    correction_notes = _validated_corrections(payload.get("correction_notes"))
    classification = _validated_classification(
        payload.get("classification"),
        fallback=fallback.classification,
        ocp_version=ocp_version,
        locale=locale,
    )
    search_signals = _validated_search_signals(payload.get("search_signals"), fallback.search_signals)
    confidence = _validated_confidence(payload.get("confidence"), fallback.confidence)
    enrichment_query = " ".join(part for part in (raw_query, normalized_query) if str(part or "").strip())
    _apply_domain_specific_enrichment(
        normalized_query=enrichment_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )
    _prune_query_signal_noise(
        raw_query=raw_query,
        normalized_query=normalized_query,
        classification=classification,
        search_signals=search_signals,
        confidence=confidence,
    )
    normalized_signals = {
        key: tuple(dict.fromkeys(item for item in values if str(item or "").strip()))
        for key, values in search_signals.items()
    }
    embedding_queries = _embedding_queries(
        raw_query=raw_query,
        normalized_query=normalized_query,
        baseline=fallback,
        search_signals=normalized_signals,
    )
    metadata_filter = _metadata_filter(
        classification=classification,
        confidence=confidence,
        search_signals=normalized_signals,
    )
    return QuerySignalPlan(
        raw_query=raw_query,
        normalized_query=normalized_query,
        correction_notes=correction_notes,
        classification=classification,
        search_signals=normalized_signals,
        confidence=confidence,
        embedding_queries=embedding_queries,
        metadata_filter=metadata_filter,
        debug={
            "mode": "llm_validated",
            "llm_enabled": True,
            "raw_query": raw_query,
        },
    )


def _clean_text(value: Any, default: str = "", *, max_chars: int = 300) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        cleaned = default
    return cleaned[:max_chars].strip()


def _command_families_for_commands(commands: tuple[str, ...]) -> list[str]:
    families: list[str] = []
    for command in commands:
        lowered = command.casefold()
        if lowered.startswith("oc get") or lowered.startswith("kubectl get"):
            _append(families, "oc_get" if lowered.startswith("oc ") else "kubectl_get")
        if lowered.startswith("oc describe") or lowered.startswith("kubectl describe"):
            _append(families, "oc_describe" if lowered.startswith("oc ") else "kubectl_describe")
        if lowered.startswith("oc logs") or lowered.startswith("kubectl logs"):
            _append(families, "oc_logs")
        if lowered.startswith("oc adm"):
            _append(families, "oc_adm")
        if lowered.startswith("oc apply"):
            _append(families, "oc_apply")
        if lowered.startswith("oc patch"):
            _append(families, "oc_get")
    return families or ["oc_get"]


def _prune_query_signal_noise(
    *,
    raw_query: str,
    normalized_query: str,
    classification: dict[str, Any],
    search_signals: dict[str, list[str]],
    confidence: dict[str, float],
) -> None:
    text = " ".join(
        part for part in (str(raw_query or ""), str(normalized_query or "")) if part.strip()
    ).casefold()
    errors = search_signals.setdefault("error_states", [])
    commands = search_signals.setdefault("commands", [])
    command_families = search_signals.setdefault("command_families", [])
    intents = search_signals.setdefault("intent_labels", [])

    def reset_scope(
        *,
        domain: str,
        books: tuple[str, ...],
        objects: tuple[str, ...] = (),
        scoped_commands: tuple[str, ...] = (),
        topics: tuple[str, ...] = (),
    ) -> None:
        classification["domain"] = domain
        classification["domain_filter_values"] = (domain,)
        classification["book_slug_candidates"] = books
        search_signals["objects"] = list(dict.fromkeys(objects))
        if scoped_commands:
            scoped_command_list = list(dict.fromkeys(scoped_commands))
            scoped_family_list = _command_families_for_commands(scoped_commands)
            search_signals["commands"] = scoped_command_list
            search_signals["command_families"] = scoped_family_list
            commands[:] = scoped_command_list
            command_families[:] = scoped_family_list
        if topics:
            search_signals["primary_topics"] = list(dict.fromkeys(topics))
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        _append(search_signals.setdefault("answer_shapes", []), "command", "checklist")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.93)
        if objects:
            confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        if scoped_commands:
            confidence["commands"] = max(confidence.get("commands", 0.0), 0.92)

    if "dpa" in text or "oadp" in text:
        reset_scope(
            domain="backup_restore",
            books=("backup_and_restore",),
            objects=("DataProtectionApplication", "DPA", "OADP"),
            scoped_commands=(
                "oc get dpa -n openshift-adp -o yaml",
                "oc get dpa -n openshift-adp -o jsonpath='{.items[*].status.conditions}'",
                "oc get all -n openshift-adp",
            ),
            topics=("OADP", "Data Protection Application", "backup restore"),
        )
    elif "event" in text and "pod" in text:
        reset_scope(
            domain="troubleshooting",
            books=("cli_tools", "support"),
            objects=("Pod", "Event"),
            scoped_commands=(
                "oc get events --field-selector involvedObject.kind=Pod",
                "oc get events -n <namespace> --sort-by=.lastTimestamp",
                "oc events",
            ),
            topics=("pod events", "cluster events"),
        )
    elif "--previous" in text or "previous" in text:
        reset_scope(
            domain="troubleshooting",
            books=("support", "cli_tools"),
            objects=("Pod", "Container"),
            scoped_commands=(
                "oc logs <pod-name> -n <namespace> --previous",
                "oc logs <pod-name> --previous",
            ),
            topics=("pod logs", "previous container logs"),
        )
    elif "endpointslice" in text or "endpoint slice" in text:
        reset_scope(
            domain="networking",
            books=("networking", "ingress_and_load_balancing", "cli_tools"),
            objects=("EndpointSlice", "Service", "Pod"),
            scoped_commands=(
                "oc get endpointslice -n <namespace>",
                "oc get endpointslices -n <namespace>",
                "oc describe service <service-name> -n <namespace>",
            ),
            topics=("EndpointSlice", "service discovery"),
        )
    elif "oc get all" in " ".join(commands).casefold() and (
        "namespace" in text or "project" in text or "네임스페이스" in text
    ):
        reset_scope(
            domain="architecture",
            books=("cli_tools", "architecture"),
            objects=("Namespace", "Project"),
            scoped_commands=("oc get all -n <namespace>", "oc project <project-name>"),
            topics=("namespace resources", "OpenShift CLI"),
        )
    elif "prometheus" in text or "alertmanager" in text or "servicemonitor" in text or "thanos" in text:
        reset_scope(
            domain="monitoring",
            books=("monitoring", "observability_overview", "support"),
            objects=("Prometheus", "Alertmanager", "ServiceMonitor", "Pod"),
            scoped_commands=(
                "oc get pods -n openshift-monitoring",
                "oc logs -n openshift-monitoring <pod-name>",
                "oc get clusteroperator monitoring",
            ),
            topics=("monitoring", "Prometheus", "Alertmanager", "ServiceMonitor"),
        )

    filtered_errors = [error for error in errors if _error_state_supported_by_query(error, text)]
    if len(filtered_errors) != len(errors):
        search_signals["error_states"] = filtered_errors
        if not filtered_errors:
            confidence["error_states"] = 0.0
            if "troubleshoot" in intents and not _looks_troubleshooting_query(text):
                search_signals["intent_labels"] = [item for item in intents if item != "troubleshoot"]

    filtered_commands = [command for command in commands if _command_supported_by_query(command, text)]
    if len(filtered_commands) != len(commands):
        search_signals["commands"] = filtered_commands
        if not filtered_commands:
            confidence["commands"] = 0.0

    if not any("debug" in command.casefold() for command in search_signals.get("commands", [])):
        search_signals["command_families"] = [family for family in command_families if family != "oc_debug"]

    if _looks_pdb_query(text):
        classification["domain"] = classification.get("domain") or "node_ops"
        _append(search_signals.setdefault("objects", []), "PodDisruptionBudget", "PDB")
        _append(search_signals.setdefault("commands", []), "oc get poddisruptionbudget --all-namespaces")
        _append(search_signals.setdefault("command_families", []), "oc_get")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        _append(search_signals.setdefault("answer_shapes", []), "command", "checklist")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.92)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
    elif _looks_rbac_can_i_query(text):
        classification["domain"] = "security"
        _append(search_signals.setdefault("objects", []), "RoleBinding", "ClusterRoleBinding", "Pod")
        _append(search_signals.setdefault("commands", []), "oc auth can-i get pods")
        _append(search_signals.setdefault("command_families", []), "oc_get")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.92)
    elif _looks_ingresscontroller_query(text):
        classification["domain"] = "networking"
        _append(search_signals.setdefault("objects", []), "IngressController")
        _append(search_signals.setdefault("commands", []), "oc get ingresscontroller")
        _append(search_signals.setdefault("command_families", []), "oc_get")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)
    elif _looks_pod_on_node_query(text):
        classification["domain"] = "node_ops"
        search_signals["commands"] = [
            command
            for command in search_signals.get("commands", [])
            if "get nodes" not in command.casefold() and "describe node" not in command.casefold()
        ]
        _append(search_signals.setdefault("objects", []), "Pod", "Node")
        _append(search_signals.setdefault("commands", []), "oc get pods -o wide")
        _append(search_signals.setdefault("command_families", []), "oc_get")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)
    elif _looks_node_detail_query(text):
        classification["domain"] = "node_ops"
        _append(search_signals.setdefault("objects", []), "Node")
        _append(search_signals.setdefault("commands", []), "oc describe node <node-name>", "oc get nodes")
        _append(search_signals.setdefault("command_families", []), "oc_describe", "oc_get")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        _append(search_signals.setdefault("answer_shapes", []), "command", "checklist")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.9)
    elif _looks_node_status_query(text):
        classification["domain"] = "node_ops"
        _append(search_signals.setdefault("objects", []), "Node")
        _append(search_signals.setdefault("commands", []), "oc get nodes", "oc describe node <node-name>")
        _append(search_signals.setdefault("command_families", []), "oc_get", "oc_describe")
        _append(search_signals.setdefault("intent_labels", []), "command_lookup", "check_status")
        _append(search_signals.setdefault("answer_shapes", []), "command", "checklist")
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.9)


def _error_state_supported_by_query(error_state: str, text: str) -> bool:
    error = str(error_state or "").casefold()
    if not error:
        return False
    if "notready" in error or error in {"ready", "not ready"}:
        return any(
            token in text
            for token in ("notready", "not ready", "노트레디", "준비 안", "레디 안", "ready/notready")
        )
    if "crashloop" in error:
        return any(token in text for token in ("crashloop", "crash loop", "crashloopbackoff"))
    if "imagepull" in error or "errimagepull" in error:
        return any(token in text for token in ("imagepull", "errimagepull", "이미지풀", "이미지 pull"))
    if "pending" in error:
        return any(token in text for token in ("pending", "펜딩", "대기"))
    if "degraded" in error:
        return "degraded" in text
    return error in text


def _command_supported_by_query(command: str, text: str) -> bool:
    command_text = str(command or "").casefold()
    if not command_text:
        return False
    if "debug" in command_text and not any(
        token in text for token in ("debug", "디버그", "host", "chroot", "백업", "backup", "etcd", "복구")
    ):
        return False
    if _looks_pdb_query(text):
        return "pdb" in command_text or "poddisruptionbudget" in command_text
    if _looks_rbac_can_i_query(text):
        return "auth can-i" in command_text
    if _looks_ingresscontroller_query(text):
        return "ingresscontroller" in command_text
    if _looks_pod_on_node_query(text) and ("get nodes" in command_text or "describe node" in command_text):
        return False
    return True


def _looks_pdb_query(text: str) -> bool:
    return any(
        token in text
        for token in (
            "poddisruptionbudget",
            "pod disruption budget",
            "pdb",
            "pod 중단 예산",
            "pod 중단",
            "파드 중단 예산",
            "중단 예산",
        )
    )


def _looks_rbac_can_i_query(text: str) -> bool:
    return "auth can-i" in text or ("권한" in text and "get pods" in text)


def _looks_ingresscontroller_query(text: str) -> bool:
    return "ingresscontroller" in text or "ingress controller" in text


def _looks_pod_on_node_query(text: str) -> bool:
    return "pod" in text and any(token in text for token in ("node", "노드")) and any(
        token in text for token in ("스케줄", "scheduled", "specific node", "특정 노드", "출력")
    )


def _looks_node_detail_query(text: str) -> bool:
    return any(token in text for token in ("node", "노드")) and any(
        token in text for token in ("describe", "자세", "상세", "세부", "detail")
    )


def _looks_node_status_query(text: str) -> bool:
    return any(token in text for token in ("node", "nodes", "노드")) and any(
        token in text for token in ("상태", "status", "명령", "command", "확인", "ready")
    )


def _looks_troubleshooting_query(text: str) -> bool:
    return any(
        token in text
        for token in (
            "trouble",
            "장애",
            "문제",
            "실패",
            "오류",
            "에러",
            "안됨",
            "안 돼",
            "failed",
            "error",
            "degraded",
            "pending",
            "crashloop",
            "notready",
            "not ready",
            "노트레디",
        )
    )


def _validated_corrections(value: Any) -> tuple[QueryCorrection, ...]:
    if not isinstance(value, list):
        return ()
    corrections: list[QueryCorrection] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        correction_type = _clean_text(item.get("type"), "normalization", max_chars=40)
        source = _clean_text(item.get("from") or item.get("source"), max_chars=160)
        replacement = _clean_text(item.get("to") or item.get("replacement"), max_chars=160)
        if source and replacement and source != replacement:
            corrections.append(QueryCorrection(correction_type, source, replacement))
    return tuple(corrections)


def _validated_classification(
    value: Any,
    *,
    fallback: dict[str, Any],
    ocp_version: str,
    locale: str,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    domain = _clean_text(source.get("domain"), str(fallback.get("domain") or ""), max_chars=40)
    if domain not in _ALLOWED_DOMAINS:
        domain = str(fallback.get("domain") or "") if str(fallback.get("domain") or "") in _ALLOWED_DOMAINS else ""
    platform = _clean_text(source.get("platform"), str(fallback.get("platform") or "any_platform"), max_chars=40)
    if platform not in _ALLOWED_PLATFORMS:
        platform = "any_platform"
    return {
        "domain": domain,
        "domain_filter_values": _domain_filter_values(
            source.get("domain_filter_values"),
            fallback.get("domain_filter_values"),
            domain=domain,
        ),
        "book_slug_candidates": _string_tuple(source.get("book_slug_candidates"), fallback.get("book_slug_candidates")),
        "ocp_version": ocp_version,
        "locale": locale,
        "platform": platform,
    }


def _domain_filter_values(value: Any, fallback: Any, *, domain: str) -> tuple[str, ...]:
    raw_values = _string_tuple(value, fallback, max_items=4, max_chars=40)
    values = tuple(item for item in raw_values if item in _ALLOWED_DOMAINS)
    if values:
        return values
    return (domain,) if domain in _ALLOWED_DOMAINS else ()


def _validated_search_signals(value: Any, fallback: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, list[str]] = {}
    for key in _SEARCH_SIGNAL_KEYS:
        values = list(_string_tuple(source.get(key), fallback.get(key, ()), max_items=12, max_chars=120))
        if key == "intent_labels":
            values = [item for item in values if item in _ALLOWED_INTENT_LABELS]
        elif key == "answer_shapes":
            values = [item for item in values if item in _ALLOWED_ANSWER_SHAPES]
        elif key == "command_families":
            values = [item for item in values if item in _ALLOWED_COMMAND_FAMILIES]
        result[key] = values
    return result


def _validated_confidence(value: Any, fallback: dict[str, float]) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    result = dict(fallback)
    for key, raw in source.items():
        if not isinstance(key, str):
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError):
            continue
        result[key] = min(1.0, max(0.0, score))
    return result


def _validated_embedding_queries(
    value: Any,
    *,
    fallback: tuple[str, ...],
    normalized_query: str,
) -> tuple[str, ...]:
    queries = _string_tuple(value, (), max_items=3, max_chars=300)
    queries = tuple(
        dict.fromkeys(
            query
            for query in (normalized_query, *queries)
            if str(query or "").strip()
        )
    )
    if not queries:
        queries = fallback
    if not queries:
        queries = (normalized_query,)
    return tuple(dict.fromkeys(query for query in queries if query))[:3]


def _string_tuple(
    value: Any,
    default: Any = (),
    *,
    max_items: int = 8,
    max_chars: int = 80,
) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list | tuple) else default
    items: list[str] = []
    if isinstance(raw_items, list | tuple):
        for item in raw_items:
            cleaned = _clean_text(item, max_chars=max_chars)
            if cleaned:
                items.append(cleaned)
    return tuple(dict.fromkeys(items))[:max_items]


def _normalize_query(query: str) -> tuple[str, tuple[QueryCorrection, ...]]:
    normalized = " ".join(str(query or "").split())
    corrections: list[QueryCorrection] = []
    for pattern, replacement, correction_type in _NORMALIZATION_RULES:
        next_value = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        if next_value != normalized:
            corrections.append(QueryCorrection(correction_type, normalized, next_value))
            normalized = next_value
    return normalized, tuple(corrections)


def _append(values: list[str], *items: str) -> None:
    for item in items:
        cleaned = " ".join(str(item or "").split())
        if cleaned and cleaned not in values:
            values.append(cleaned)


def _apply_domain_specific_enrichment(
    *,
    normalized_query: str,
    classification: dict[str, Any],
    search_signals: dict[str, list[str]],
    confidence: dict[str, float],
) -> None:
    lowered = normalized_query.lower()
    route_http_headers = (
        any(token in lowered for token in ("route", "routes", "라우트", "경로"))
        and any(token in lowered for token in ("http", "header", "headers", "헤더", "요청", "응답"))
    )
    objects = search_signals.setdefault("objects", [])
    commands = search_signals.setdefault("commands", [])
    command_families = search_signals.setdefault("command_families", [])
    error_states = search_signals.setdefault("error_states", [])
    intent_labels = search_signals.setdefault("intent_labels", [])
    answer_shapes = search_signals.setdefault("answer_shapes", [])
    primary_topics = search_signals.setdefault("primary_topics", [])
    secondary_topics = search_signals.setdefault("secondary_topics", [])
    cluster_phase = search_signals.setdefault("cluster_phase", [])
    execution_target = search_signals.setdefault("execution_target", [])
    components = search_signals.setdefault("components", [])

    _apply_command_alias_enrichment(
        lowered_query=lowered,
        classification=classification,
        objects=objects,
        commands=commands,
        command_families=command_families,
        intent_labels=intent_labels,
        answer_shapes=answer_shapes,
        primary_topics=primary_topics,
        confidence=confidence,
    )

    if route_http_headers:
        classification["domain"] = "networking"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "ingress_and_load_balancing",
        )
        _append(objects, "Route")
        _append(primary_topics, "Route HTTP header configuration", "HTTP request header", "HTTP response header")
        _append(secondary_topics, "nw-route-set-or-delete-http-headers")
        _append(intent_labels, "configure_resource", "command_lookup")
        _append(answer_shapes, "command", "step_by_step")
        _append(commands, "oc -n app-example create -f app-example-route.yaml")
        _append(command_families, "oc_create")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.93)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)

    storage_lexicon = DOMAIN_LEXICONS["storage"]
    if query_matches_domain(normalized_query, "storage"):
        classification["domain"] = classification.get("domain") or storage_lexicon.domain
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            *storage_lexicon.book_slugs,
        )
        _append(objects, *storage_lexicon.objects)
        _append(primary_topics, *storage_lexicon.primary_topics)
        _append(secondary_topics, *storage_lexicon.secondary_topics)
        _append(commands, *storage_lexicon.commands)
        _append(command_families, *storage_lexicon.command_families)
        if query_matches_static_variant(normalized_query, "storage"):
            _append(primary_topics, "static provisioning")
        if query_matches_dynamic_variant(normalized_query, "storage"):
            _append(primary_topics, "dynamic provisioning")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.9)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.86)

    has_vsphere_storage = (
        any(token in lowered for token in ("vsphere", "vmware"))
        and query_matches_domain(normalized_query, "storage")
    )
    if has_vsphere_storage:
        classification["domain"] = "storage"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "storage",
        )
        _append(objects, "PV", "PVC", "StorageClass")
        _append(
            primary_topics,
            "VMware vSphere",
            "vSphere volume provisioning",
            "VMware vSphere CSI Driver",
        )
        _append(secondary_topics, "VMDK", "thin-csi", "storage provisioning")
        _append(components, "vSphere CSI Driver", "CSI Driver", "StorageClass")
        _append(intent_labels, "configure_resource", "create_resource", "command_lookup")
        _append(answer_shapes, "step_by_step", "command")
        _append(command_families, "oc_create", "oc_get")
        if query_matches_dynamic_variant(normalized_query, "storage"):
            _append(primary_topics, "dynamic provisioning")
            _append(secondary_topics, "thin StorageClass", "PersistentVolumeClaim")
        elif query_matches_static_variant(normalized_query, "storage"):
            _append(primary_topics, "static provisioning")
            _append(secondary_topics, "PersistentVolume", "PersistentVolumeClaim")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.94)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.93)

    if "etcd" in lowered and ("백업" in normalized_query or "backup" in lowered):
        classification["domain"] = "etcd"
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "etcd",
            "backup_and_restore",
        )
        _append(primary_topics, "etcd", "etcd backup")
        _append(intent_labels, "backup", "identify_execution_target")
        _append(answer_shapes, "step_by_step", "command")
        _append(cluster_phase, "day2", "recovery")
        _append(execution_target, "control_plane_node")
        _append(commands, "oc debug node/<control-plane-node>", "chroot /host", "cluster-backup.sh")
        _append(command_families, "oc_debug")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.92)
        confidence["execution_target"] = max(confidence.get("execution_target", 0.0), 0.9)

    signal_text = f"{lowered} {normalized_query.lower()}"
    if "imagepullbackoff" in signal_text or "errimagepull" in signal_text:
        classification["domain"] = "registry"
        classification["domain_filter_values"] = ("registry", "troubleshooting")
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "images",
            "registry",
        )
        _append(objects, "Pod", "Secret")
        _append(primary_topics, "ImagePullBackOff", "pull secret", "container image registry")
        _append(error_states, "ImagePullBackOff")
        _append(intent_labels, "troubleshoot", "check_status")
        _append(answer_shapes, "troubleshooting_flow", "checklist", "command")
        _append(cluster_phase, "incident", "day2")
        _append(commands, "oc describe pod", "oc get secret")
        _append(command_families, "oc_describe", "oc_get")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.88)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.92)
        confidence["error_states"] = max(confidence.get("error_states", 0.0), 0.97)

    if "notready" in lowered and "node" in lowered:
        classification["domain"] = "node_ops"
        classification["domain_filter_values"] = ("node_ops", "troubleshooting")
        classification["book_slug_candidates"] = _tuple_append(
            classification.get("book_slug_candidates", ()),
            "nodes",
        )
        _append(objects, "Node")
        _append(primary_topics, "Node", "node status")
        _append(error_states, "NotReady")
        _append(intent_labels, "troubleshoot", "check_status")
        _append(answer_shapes, "checklist", "command", "troubleshooting_flow")
        _append(cluster_phase, "incident", "day2")
        _append(execution_target, "cluster_admin_cli")
        _append(commands, "oc get nodes", "oc describe node")
        _append(command_families, "oc_get", "oc_describe")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.91)
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.94)
        confidence["error_states"] = max(confidence.get("error_states", 0.0), 0.95)

    if classification.get("domain") == "troubleshooting" and "imagepullbackoff" in signal_text:
        classification["domain"] = "registry"
        classification["domain_filter_values"] = ("registry", "troubleshooting")
        confidence["domain"] = max(confidence.get("domain", 0.0), 0.88)

    if classification.get("domain") == "install":
        classification["platform"] = "any_platform"
        _append(primary_topics, "UPI", "Agent-based Installer", "installation method")
        _append(answer_shapes, "decision_guide")
        _append(intent_labels, "install", "compare_options")
        confidence["platform"] = max(confidence.get("platform", 0.0), 0.72)

    if commands:
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.82)
    if intent_labels:
        confidence["intent_labels"] = max(confidence.get("intent_labels", 0.0), 0.88)
    if answer_shapes:
        confidence["answer_shapes"] = max(confidence.get("answer_shapes", 0.0), 0.84)
    if objects:
        confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)
    if "csi driver" in " ".join(components).lower():
        return
    if query_matches_domain(normalized_query, "storage"):
        _append(components, "CSI Driver", "scheduler")


def _apply_command_alias_enrichment(
    *,
    lowered_query: str,
    classification: dict[str, Any],
    objects: list[str],
    commands: list[str],
    command_families: list[str],
    intent_labels: list[str],
    answer_shapes: list[str],
    primary_topics: list[str],
    confidence: dict[str, float],
) -> None:
    for rule in _COMMAND_ALIAS_RULES:
        aliases = tuple(str(item).casefold() for item in rule.get("aliases", ()) if str(item).strip())
        if not aliases or not any(alias in lowered_query for alias in aliases):
            continue
        domain = str(rule.get("domain") or "").strip()
        if (
            domain == "security"
            and classification.get("domain") == "registry"
            and any(token in lowered_query for token in ("imagepullbackoff", "errimagepull"))
        ):
            continue
        _append(objects, *(str(item) for item in rule.get("objects", ()) if str(item).strip()))
        _append(commands, *(str(item) for item in rule.get("commands", ()) if str(item).strip()))
        _append(
            command_families,
            *(str(item) for item in rule.get("command_families", ()) if str(item).strip()),
        )
        _append(primary_topics, *(str(item) for item in rule.get("primary_topics", ()) if str(item).strip()))
        _append(intent_labels, "command_lookup", "check_status")
        _append(answer_shapes, "command", "checklist")
        if domain in _ALLOWED_DOMAINS:
            classification["domain"] = domain
            classification["domain_filter_values"] = _tuple_append(
                classification.get("domain_filter_values", ()),
                domain,
            )
            confidence["domain"] = max(confidence.get("domain", 0.0), float(rule.get("domain_confidence", 0.9)))
        book_slugs = tuple(str(item) for item in rule.get("book_slug_candidates", ()) if str(item).strip())
        if book_slugs:
            classification["book_slug_candidates"] = _tuple_append(
                classification.get("book_slug_candidates", ()),
                *book_slugs,
            )
        confidence["commands"] = max(confidence.get("commands", 0.0), 0.9)
        confidence["intent_labels"] = max(confidence.get("intent_labels", 0.0), 0.88)
        confidence["answer_shapes"] = max(confidence.get("answer_shapes", 0.0), 0.84)
        if rule.get("objects"):
            confidence["objects"] = max(confidence.get("objects", 0.0), 0.9)


def _tuple_append(values: Any, *items: str) -> tuple[str, ...]:
    result = [str(value) for value in values if str(value or "").strip()] if isinstance(values, tuple | list) else []
    _append(result, *items)
    return tuple(result)


def _metadata_filter(
    *,
    classification: dict[str, Any],
    confidence: dict[str, float],
    search_signals: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    # locale/ocp_version/enabled_for_chat/navigation_only are uniform across the
    # collection, so filtering on them only adds payload-eval cost. citation_eligible
    # and corpus_scope are non-uniform chat-scope correctness filters and are kept.
    must: list[dict[str, Any]] = [
        {"key": "source.citation_eligible", "match": {"value": True}},
        {"key": "source.corpus_scope", "match": {"value": "official_docs"}},
        {
            "key": "chunk.chunk_type",
            "match": {
                "any": [
                    "command",
                    "procedure",
                    "concept",
                    "reference",
                    "troubleshooting",
                ]
            },
        },
    ]
    domain = str(classification.get("domain") or "").strip()
    domain_filter_values = tuple(
        dict.fromkeys(
            item
            for item in (
                classification.get("domain_filter_values")
                if isinstance(classification.get("domain_filter_values"), list | tuple)
                else ()
            )
            if str(item or "").strip() in _ALLOWED_DOMAINS
        )
    )
    if domain and confidence.get("domain", 0.0) >= 0.85 and len(domain_filter_values) <= 1:
        domain_filter_values = (domain,)
    if (
        domain
        and domain != "troubleshooting"
        and confidence.get("domain", 0.0) >= 0.85
        and confidence.get("commands", 0.0) >= 0.8
        and search_signals
        and search_signals.get("commands")
    ):
        domain_filter_values = (domain,)
    if (
        domain == "node_ops"
        and search_signals
        and "troubleshoot" in set(search_signals.get("intent_labels") or ())
    ):
        domain_filter_values = tuple(dict.fromkeys((*domain_filter_values, "troubleshooting")))
    platform = str(classification.get("platform") or "").strip()
    if platform and platform != "any_platform" and confidence.get("platform", 0.0) >= 0.9:
        must.append({"key": "classification.platform", "match": {"value": platform}})
    metadata_filter: dict[str, Any] = {"must": must}
    if domain_filter_values:
        metadata_filter["_domain_filter_values"] = domain_filter_values
        metadata_filter["_domain_boosts"] = domain_filter_values
    signal_boosts = _metadata_signal_boosts(search_signals or {}, confidence=confidence)
    if signal_boosts:
        metadata_filter["_intent_signal_boosts"] = signal_boosts
    return metadata_filter


def _metadata_signal_boosts(
    search_signals: dict[str, tuple[str, ...]],
    *,
    confidence: dict[str, float],
) -> dict[str, tuple[str, ...]]:
    if not search_signals:
        return {}

    boosts: dict[str, tuple[str, ...]] = {}
    objects = search_signals.get("objects", ())
    commands = search_signals.get("commands", ())
    command_families = search_signals.get("command_families", ())
    intent_labels = search_signals.get("intent_labels", ())
    if objects and confidence.get("objects", 0.0) >= 0.7:
        boosts["objects"] = _clean_signal_values(search_signals.get("objects", ()))
    if commands and confidence.get("commands", 0.0) >= 0.7:
        boosts["commands"] = _clean_signal_values(search_signals.get("commands", ()))
    if command_families and confidence.get("commands", 0.0) >= 0.7:
        boosts["command_families"] = _clean_signal_values(search_signals.get("command_families", ()))
    if intent_labels and confidence.get("intent_labels", 0.0) >= 0.7:
        boosts["intent_labels"] = _clean_signal_values(search_signals.get("intent_labels", ()))
    return boosts


def _clean_signal_values(values: tuple[str, ...], *, limit: int = 4) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))[:limit]


def _embedding_queries(
    *,
    raw_query: str,
    normalized_query: str,
    baseline: StructuredQuerySignals,
    search_signals: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    objects = search_signals.get("objects", ())
    errors = search_signals.get("error_states", ())
    commands = search_signals.get("commands", ())
    command_families = search_signals.get("command_families", ())
    primary_topics = search_signals.get("primary_topics", ())
    secondary_topics = search_signals.get("secondary_topics", ())
    intents = search_signals.get("intent_labels", ())
    route_http_headers = (
        any(item.casefold() == "route" for item in objects)
        and any("header" in item.casefold() for item in (*primary_topics, *secondary_topics))
    )

    queries: list[str] = []
    english_terms = () if route_http_headers else _english_terms(objects=objects, errors=errors, primary_topics=primary_topics)
    _append(queries, normalized_query)
    if commands or command_families or {"troubleshoot", "check_status"} & set(intents):
        _append(
            queries,
            " ".join(
                dict.fromkeys(
                    item
                    for item in (
                        *primary_topics,
                        *objects,
                        *errors,
                        *(secondary_topics[:1] if route_http_headers else secondary_topics[:2]),
                        *(commands[:1] if route_http_headers else commands[:3]),
                        *(() if route_http_headers else command_families),
                        *english_terms,
                        "troubleshooting" if "troubleshoot" in intents else "",
                    )
                    if item
                )
            ),
        )
    if english_terms and len(queries) < 2:
        _append(queries, " ".join(english_terms))
    if len(queries) < 2:
        _append(queries, _domain_specific_baseline_vector_query(baseline.vector_query, objects=objects, primary_topics=primary_topics))
    return tuple(queries[:2])


def _domain_specific_baseline_vector_query(
    vector_query: str,
    *,
    objects: tuple[str, ...],
    primary_topics: tuple[str, ...],
) -> str:
    if not vector_query:
        return ""
    object_set = {item.casefold() for item in objects}
    topic_text = " ".join(primary_topics).casefold()
    if "route" in object_set and "header" in topic_text:
        allowed = ("route", "http", "header", "request", "response", "nw-route-set-or-delete-http-headers")
        return " ".join(dict.fromkeys(term for term in vector_query.split() if any(token in term.casefold() for token in allowed)))
    return vector_query


def _english_terms(
    *,
    objects: tuple[str, ...],
    errors: tuple[str, ...],
    primary_topics: tuple[str, ...],
) -> tuple[str, ...]:
    terms: list[str] = []
    object_set = {item.lower() for item in objects}
    error_set = {item.lower() for item in errors}
    topic_set = {item.lower() for item in primary_topics}
    if "pvc" in object_set:
        _append(terms, "PersistentVolumeClaim", "PVC", "volume binding", "storage provisioning")
    if "storageclass" in object_set or "storageclass" in topic_set:
        _append(terms, "StorageClass", "dynamic provisioning")
    if any("vsphere" in item for item in (*object_set, *topic_set)):
        _append(terms, "VMware vSphere", "vSphere CSI Driver", "VMDK", "thin-csi")
        if "dynamic provisioning" in topic_set:
            _append(terms, "PersistentVolumeClaim", "StorageClass", "dynamic provisioning")
        if "static provisioning" in topic_set:
            _append(terms, "PersistentVolume", "PersistentVolumeClaim", "static provisioning")
    if "etcd" in object_set or "etcd" in topic_set:
        _append(terms, "etcd backup", "control plane node", "cluster-backup.sh")
    if "pod" in object_set and "imagepullbackoff" in error_set:
        _append(terms, "Pod", "ImagePullBackOff", "pull secret", "image registry")
    if "node" in object_set and "notready" in error_set:
        _append(terms, "Node", "NotReady", "node condition", "kubelet")
    if "upi" in topic_set or "agent-based installer" in topic_set:
        _append(terms, "UPI", "Agent-based Installer", "installation method", "OpenShift")
    return tuple(terms)


__all__ = [
    "QueryCorrection",
    "QuerySignalPlan",
    "build_query_signal_plan",
]
