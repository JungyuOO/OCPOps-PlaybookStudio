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


def _has_pod_delete_permission_intent(text: str) -> bool:
    lowered = (text or "").lower()
    has_pod = any(token in lowered for token in ("pod", "pods", "파드"))
    has_delete = any(token in lowered for token in ("delete", "삭제", "지울", "제거"))
    has_permission = any(
        token in lowered
        for token in (
            "can-i",
            "can i",
            "권한",
            "가능",
            "할 수",
            "확인",
            "검증",
            "allowed",
            "permission",
        )
    )
    return has_pod and has_delete and has_permission


def _has_oc_login_connection_intent(text: str) -> bool:
    lowered = (text or "").lower()
    if "oc login" not in lowered:
        return False
    return any(
        token in lowered
        for token in ("token", "토큰", "server", "서버", "url", "api", "실패", "fail", "접속", "login")
    )


def _has_resource_policy_intent(text: str, *terms: str) -> bool:
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in terms)


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

    if _contains_any(text, ("csr", "certificate signing request", "인증서 서명 요청")) and _contains_any(
        text, ("approve", "approval", "승인")
    ):
        return _profile(
            intent="operation_command",
            target_object="csr",
            task="approve",
            needs_command=True,
            primary_commands=("oc get csr", "oc adm certificate approve <csr-name>"),
            evidence_terms=("CertificateSigningRequest", "CSR", "Approved", "oc adm certificate approve"),
            query_terms=("approve pending csr", "certificate signing request approval"),
            confidence=0.86,
            reasons=("csr approval command request",),
        )

    if _contains_any(text, ("api-resource", "api-resources", "api resource", "api resources", "api 리소스")):
        return _profile(
            intent="command_lookup",
            target_object="api-resource",
            task="list",
            needs_command=True,
            primary_commands=("oc api-resources",),
            evidence_terms=("APIResource", "api-resources", "namespaced", "verbs"),
            query_terms=("supported API resources", "list api resources"),
            confidence=0.84,
            reasons=("api resources list command request",),
        )

    if _contains_any(text, ("application", "app", "애플리케이션", "앱")) and _contains_any(
        text, ("create", "new", "make", "deploy", "생성", "만들", "배포")
    ):
        return _profile(
            intent="operation_command",
            target_object="application",
            task="create",
            needs_command=True,
            primary_commands=("oc new-app <image-or-template>",),
            evidence_terms=("new application", "oc new-app", "ImageStream", "template"),
            query_terms=("create application from image", "deploy application"),
            confidence=0.84,
            reasons=("application creation command request",),
        )

    if _contains_any(text, ("namespace", "namespaces", "project", "projects", "네임스페이스", "프로젝트")) and not (
        _contains_any(text, ("can-i", "can i", "rbac", "권한")) or _has_pod_delete_permission_intent(text)
    ):
        if _contains_any(text, ("create", "new", "make", "생성", "만들", "추가", "새 ")):
            return _profile(
                intent="operation_command",
                target_object="namespace",
                task="create",
                needs_command=True,
                primary_commands=("oc new-project <project-name>", "oc create namespace <namespace-name>"),
                evidence_terms=("Namespace", "Project", "oc new-project", "oc create namespace"),
                query_terms=("create project namespace", "new OpenShift project"),
                confidence=0.86,
                reasons=("namespace project creation command request",),
            )
        if _contains_any(text, ("list", "목록", "전체", "조회")):
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
        if _contains_any(text, ("current", "selected", "active", "현재", "선택", "보고 있")):
            return _profile(
                intent="command_lookup",
                target_object="namespace",
                task="current-context",
                needs_command=True,
                primary_commands=("oc project", "oc config view"),
                evidence_terms=("current project", "selected project", "CLI profile", "current-context"),
                query_terms=("view current project", "current namespace context"),
                confidence=0.84,
                reasons=("namespace current context command request",),
            )

    if _has_oc_login_connection_intent(text):
        return _profile(
            intent="command_lookup",
            target_object="oc-login",
            task="token-server-check",
            needs_command=True,
            primary_commands=("oc login --token=<token> --server=<api-url>", "oc whoami"),
            evidence_terms=("oc login", "token", "server", "OpenShift CLI"),
            query_terms=("CLI login", "authentication token", "API server URL"),
            confidence=0.84,
            reasons=("oc login token server check",),
        )

    if command_request and (
        _contains_any(text, ("can-i", "can i", "권한", "rbac")) or _has_pod_delete_permission_intent(text)
    ):
        return _profile(
            intent="command_lookup",
            target_object="rbac",
            task="access-check",
            needs_command=True,
            primary_commands=("oc auth can-i delete pods -n <namespace>", "oc auth can-i <verb> <resource> -n <namespace>"),
            evidence_terms=("oc auth can-i", "SelfSubjectAccessReview", "SubjectAccessReview", "authorization", "delete pods"),
            query_terms=("RBAC access check", "review permissions", "pods delete permission"),
            confidence=0.86,
            reasons=("rbac can-i command request",),
        )

    if _has_resource_policy_intent(text, "resourcequota", "resource quota", "quota"):
        return _profile(
            intent="troubleshooting",
            target_object="resourcequota",
            task="admission-denied",
            needs_command=True,
            primary_commands=("oc get resourcequota -n <namespace>", "oc describe resourcequota <quota-name> -n <namespace>"),
            evidence_terms=("ResourceQuota", "quota", "hard", "used", "exceeded quota"),
            query_terms=("resource quota admission", "Pod creation quota", "oc get events"),
            confidence=0.82,
            reasons=("resource quota pod admission troubleshooting",),
        )

    if _has_resource_policy_intent(text, "limitrange", "limit range"):
        return _profile(
            intent="troubleshooting",
            target_object="limitrange",
            task="resource-request-rejected",
            needs_command=True,
            primary_commands=("oc get limitrange -n <namespace>", "oc describe limitrange <limitrange-name> -n <namespace>"),
            evidence_terms=("LimitRange", "min", "max", "default", "defaultRequest"),
            query_terms=("resource requests", "resource limits", "admission rejected"),
            confidence=0.82,
            reasons=("limit range resource request troubleshooting",),
        )

    if _contains_any(text, ("machine config operator", "machineconfigoperator", "machine config", "mco")):
        return _profile(
            intent="troubleshooting",
            target_object="machineconfigpool",
            task="operator-status",
            needs_command=True,
            primary_commands=("oc get co machine-config", "oc get mcp", "oc describe mcp <pool-name>"),
            evidence_terms=("Machine Config Operator", "MachineConfigPool", "machine-config", "Degraded"),
            query_terms=("machine config operator status", "node configuration rollout"),
            confidence=0.86,
            reasons=("machine config operator status troubleshooting",),
        )

    if _contains_any(text, ("cluster version operator", "clusterversion", "cluster version", "cvo")):
        return _profile(
            intent="troubleshooting",
            target_object="clusterversion",
            task="update-status",
            needs_command=True,
            primary_commands=("oc get clusterversion", "oc describe clusterversion version"),
            evidence_terms=("Cluster Version Operator", "ClusterVersion", "Available", "Progressing", "Failing"),
            query_terms=("cluster update status", "cluster version operator degraded"),
            confidence=0.86,
            reasons=("cluster version operator update troubleshooting",),
        )

    if _contains_any(text, ("clusteroperator", "cluster operator", "clusteroperators")) and _contains_any(
        text,
        ("update", "upgrade", "precheck", "before", "status", "degraded", "node", "nodes"),
    ):
        return _profile(
            intent="troubleshooting",
            target_object="cluster-health",
            task="update-precheck",
            needs_command=True,
            primary_commands=("oc get clusteroperators", "oc get nodes", "oc adm upgrade status"),
            evidence_terms=("ClusterOperator", "clusteroperators", "Cluster Version Operator", "node", "update"),
            query_terms=("cluster update precheck", "operator status before upgrade", "node status before update"),
            confidence=0.84,
            reasons=("cluster update precheck status request",),
        )

    if _contains_any(text, ("networkpolicy", "network policy")):
        return _profile(
            intent="troubleshooting",
            target_object="networkpolicy",
            task="pod-connectivity",
            needs_command=True,
            primary_commands=("oc get networkpolicy -n <namespace>", "oc describe networkpolicy <policy-name> -n <namespace>"),
            evidence_terms=("NetworkPolicy", "ingress", "egress", "podSelector"),
            query_terms=("pod communication blocked", "network policy troubleshooting"),
            confidence=0.84,
            reasons=("network policy connectivity troubleshooting",),
        )

    if _contains_any(text, ("egress", "external api", "outbound", "external traffic")):
        return _profile(
            intent="troubleshooting",
            target_object="egress-network",
            task="outbound-connectivity",
            needs_command=True,
            primary_commands=("oc get networkpolicy -n <namespace>", "oc describe networkpolicy <policy-name> -n <namespace>"),
            evidence_terms=("egress", "NetworkPolicy", "EgressIP", "external traffic"),
            query_terms=("egress network policy", "outbound traffic blocked", "external API connectivity"),
            confidence=0.82,
            reasons=("egress connectivity troubleshooting",),
        )

    if _contains_any(text, ("dns", "openshift-dns", "cluster dns")):
        return _profile(
            intent="troubleshooting",
            target_object="dns",
            task="cluster-dns",
            needs_command=True,
            primary_commands=("oc get dns.operator/default -o yaml", "oc get pods -n openshift-dns"),
            evidence_terms=("DNS", "openshift-dns", "dns.operator", "CoreDNS"),
            query_terms=(
                "DNS Operator",
                "DNS Operator in OpenShift Container Platform",
                "dns.operator.openshift.io",
                "cluster DNS operator",
                "name resolution troubleshooting",
                "openshift-dns pods",
            ),
            confidence=0.84,
            reasons=("cluster dns troubleshooting",),
        )

    if _contains_any(text, ("route timeout", "timeout")) and _contains_any(text, ("route", "router", "haproxy")):
        return _profile(
            intent="troubleshooting",
            target_object="route",
            task="timeout",
            needs_command=True,
            primary_commands=("oc get route <route-name> -n <namespace> -o yaml", "oc describe route <route-name> -n <namespace>"),
            evidence_terms=("Route", "timeout", "haproxy.router.openshift.io/timeout", "IngressController"),
            query_terms=("route timeout", "haproxy router timeout annotation", "ingress route timeout"),
            confidence=0.82,
            reasons=("route timeout troubleshooting",),
        )

    if _contains_any(text, ("allowedregistries", "allowed registries")) or (
        _contains_any(text, ("registry", "레지스트리")) and _contains_any(text, ("allowed", "허용", "제한", "limit"))
    ):
        return _profile(
            intent="troubleshooting",
            target_object="image-config",
            task="allowed-registries",
            needs_command=True,
            primary_commands=("oc get image.config.openshift.io/cluster -o yaml",),
            evidence_terms=("allowedRegistries", "registry", "image.config.openshift.io"),
            query_terms=("image registry policy", "allowed registries"),
            confidence=0.84,
            reasons=("allowed registries policy check",),
        )

    if _contains_any(text, ("image registry", "internal registry", "내부 image registry", "내부 registry")):
        return _profile(
            intent="troubleshooting",
            target_object="image-registry",
            task="operator-storage",
            needs_command=True,
            primary_commands=("oc get configs.imageregistry.operator.openshift.io/cluster -o yaml", "oc get co image-registry"),
            evidence_terms=("image registry", "Image Registry Operator", "storage", "managementState"),
            query_terms=("internal image registry storage operator status"),
            confidence=0.84,
            reasons=("internal image registry operator status",),
        )

    if _contains_any(text, ("scc", "securitycontextconstraints", "security context constraints")):
        return _profile(
            intent="troubleshooting",
            target_object="scc",
            task="pod-admission",
            needs_command=True,
            primary_commands=("oc get scc", "oc adm policy who-can use scc/<scc-name>"),
            evidence_terms=("SecurityContextConstraints", "SCC", "use scc", "restricted-v2"),
            query_terms=("pod security admission", "security context constraints"),
            confidence=0.84,
            reasons=("security context constraints troubleshooting",),
        )

    if _contains_any(text, ("local storage operator", "localvolume", "localvolumeset", "localvolumediscovery", "로컬 스토리지")) and _contains_any(
        text, ("remove", "delete", "uninstall", "cleanup", "제거", "삭제", "정리")
    ):
        return _profile(
            intent="operation_command",
            target_object="local-storage-operator",
            task="cleanup-before-removal",
            needs_command=True,
            primary_commands=(
                "oc delete localvolume --all --all-namespaces",
                "oc delete localvolumeset --all --all-namespaces",
                "oc delete localvolumediscovery --all --all-namespaces",
            ),
            evidence_terms=("Local Storage Operator", "LocalVolume", "LocalVolumeSet", "LocalVolumeDiscovery"),
            query_terms=("local storage operator removal", "delete local storage custom resources"),
            confidence=0.86,
            reasons=("local storage operator cleanup command request",),
        )

    if _contains_any(text, ("poddisruptionbudget", "pod disruption budget", "pdb")):
        if _contains_any(text, ("apply", "create", "set", "policy", "정책", "적용", "생성")):
            return _profile(
                intent="operation_command",
                target_object="poddisruptionbudget",
                task="apply-policy",
                needs_command=True,
                primary_commands=("oc create -f pod-disruption-budget.yaml",),
                evidence_terms=("PodDisruptionBudget", "PDB", "unhealthyPodEvictionPolicy", "pod-disruption-budget.yaml"),
                query_terms=("apply pod disruption budget policy", "unhealthy pod eviction policy"),
                confidence=0.84,
                reasons=("pod disruption budget policy apply command request",),
            )
        return _profile(
            intent="troubleshooting",
            target_object="poddisruptionbudget",
            task="drain-or-availability-blocked",
            needs_command=True,
            primary_commands=("oc get poddisruptionbudget --all-namespaces", "oc get pdb -n <namespace>", "oc describe pdb <pdb-name> -n <namespace>"),
            evidence_terms=("PodDisruptionBudget", "PDB", "Allowed disruptions", "minAvailable", "maxUnavailable"),
            query_terms=("pod disruption budget", "node drain blocked", "application availability during disruption"),
            confidence=0.84,
            reasons=("pod disruption budget availability troubleshooting",),
        )

    if _contains_any(text, ("horizontalpodautoscaler", "horizontal pod autoscaler", "hpa")):
        if _contains_any(text, ("edit", "modify", "change", "policy", "수정", "변경", "정책")):
            return _profile(
                intent="operation_command",
                target_object="horizontalpodautoscaler",
                task="edit-policy",
                needs_command=True,
                primary_commands=("oc edit hpa <hpa-name> -n <namespace>",),
                evidence_terms=("HorizontalPodAutoscaler", "HPA", "behavior", "scaleDown", "scaleUp"),
                query_terms=("edit hpa scaling policy", "horizontal pod autoscaler behavior"),
                confidence=0.86,
                reasons=("horizontal pod autoscaler policy edit command request",),
            )
        return _profile(
            intent="troubleshooting",
            target_object="horizontalpodautoscaler",
            task="scale-out-not-working",
            needs_command=True,
            primary_commands=("oc get hpa -n <namespace>", "oc describe hpa <hpa-name> -n <namespace>"),
            evidence_terms=("HorizontalPodAutoscaler", "HPA", "TARGETS", "metrics", "scale target"),
            query_terms=("horizontal pod autoscaler metrics", "autoscaling target", "scale out not working"),
            confidence=0.84,
            reasons=("horizontal pod autoscaler troubleshooting",),
        )

    if _has_resource_policy_intent(text, "imagepullbackoff", "errimagepull", "pull secret"):
        return _profile(
            intent="troubleshooting",
            target_object="pod",
            task="image-pull",
            needs_command=True,
            primary_commands=("oc describe pod <pod-name> -n <namespace>", "oc get secret -n <namespace>"),
            evidence_terms=("ImagePullBackOff", "ErrImagePull", "pull secret", "registry"),
            query_terms=("image pull", "image registry", "pod events"),
            confidence=0.82,
            reasons=("image pull pod troubleshooting",),
        )

    if _contains_any(text, ("odf", "openshift data foundation", "ceph", "rook")):
        return _profile(
            intent="troubleshooting",
            target_object="storage",
            task="odf-status",
            needs_command=True,
            primary_commands=("oc get pods -n openshift-storage", "oc get cephcluster -n openshift-storage"),
            evidence_terms=("ODF", "OpenShift Data Foundation", "storage", "openshift-storage", "CephCluster"),
            query_terms=("ODF storage operator status", "OpenShift Data Foundation troubleshooting", "openshift-storage pods"),
            confidence=0.82,
            reasons=("odf storage status troubleshooting",),
        )

    if _contains_any(text, ("prometheus", "alertmanager", "firing alert", "alerts", "alert")):
        return _profile(
            intent="troubleshooting",
            target_object="monitoring",
            task="firing-alerts",
            needs_command=True,
            primary_commands=("oc -n openshift-monitoring get pods", "oc -n openshift-monitoring get route alertmanager-main"),
            evidence_terms=("Prometheus", "Alertmanager", "firing alerts", "openshift-monitoring"),
            query_terms=("Prometheus alerts", "Alertmanager firing alerts", "openshift-monitoring troubleshooting"),
            confidence=0.82,
            reasons=("monitoring alert troubleshooting",),
        )

    if _contains_any(text, ("must-gather", "must gather", "머스트게더")):
        return _profile(
            intent="command_lookup",
            target_object="must-gather",
            task="support-data-collection",
            needs_command=True,
            primary_commands=("oc adm must-gather",),
            evidence_terms=("must-gather", "oc adm must-gather", "support data", "diagnostic data"),
            query_terms=("collect troubleshooting data", "support logs", "diagnostic collection"),
            confidence=0.84,
            reasons=("must-gather support collection command request",),
        )

    if _contains_any(text, ("oc adm inspect", "inspect")):
        return _profile(
            intent="command_lookup",
            target_object="inspect",
            task="namespace-resource-snapshot",
            needs_command=True,
            primary_commands=("oc adm inspect ns/<namespace>", "oc adm inspect namespace/<namespace>"),
            evidence_terms=("oc adm inspect", "inspect", "namespace", "resource status"),
            query_terms=("collect namespace resources", "support inspection", "resource snapshot"),
            confidence=0.84,
            reasons=("oc adm inspect namespace support handoff",),
        )

    if _contains_any(
        text,
        ("top pods", "top pod", "oc adm top", "cpu", "memory", "resource usage", "리소스", "메모리", "사용량", "잡아먹"),
    ) and _contains_any(text, ("pod", "pods", "파드", "namespace", "네임스페이스")):
        return _profile(
            intent="command_lookup",
            target_object="pod-metrics",
            task="top-pods",
            needs_command=True,
            primary_commands=("oc adm top pod --namespace=<namespace>", "oc adm top pod"),
            evidence_terms=("oc adm top pod", "top pod", "top pods", "CPU", "memory", "metrics"),
            query_terms=("pod resource usage", "pod cpu memory", "metrics top pods"),
            confidence=0.84,
            reasons=("pod metrics command request",),
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

    if _contains_any(text, ("node", "nodes", "노드")) and _contains_any(
        text, ("확인", "status", "상태", "명령", "command", "ready", "notready")
    ):
        return _profile(
            intent="command_lookup",
            target_object="node",
            task="status",
            needs_command=True,
            primary_commands=("oc get nodes", "oc describe node <node-name>"),
            evidence_terms=("Node", "Ready", "NotReady", "oc get nodes"),
            query_terms=("node status", "cluster node status"),
            confidence=0.84,
            reasons=("node status command request",),
        )

    if command_request and _contains_any(text, ("namespace", "namespaces", "네임스페이스", "프로젝트")):
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
            target_object="project-finalizer",
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
