from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .k8s_client import KubernetesClient
from .workspace_models import WorkspaceHandle


DEFAULT_SANDBOX_IMAGE = "ghcr.io/jungyuoo/ocpops-playbookstudio-sandbox:dev"
LEARNER_SERVICE_ACCOUNT = "learner"
HOME_PVC_NAME = "home-learner"
SANDBOX_DEPLOYMENT_NAME = "sandbox"


def user_workspace_namespace(owner_hash: str) -> str:
    short_hash = _short_owner_hash(owner_hash)
    return f"pbs-user-{short_hash}"


def build_user_workspace_manifests(
    owner_hash: str,
    *,
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE,
    now: datetime | None = None,
    storage_size: str = "1Gi",
) -> tuple[dict[str, Any], ...]:
    namespace = user_workspace_namespace(owner_hash)
    labels = _workspace_labels(owner_hash, now=now)
    selector_labels = {
        "app.kubernetes.io/name": SANDBOX_DEPLOYMENT_NAME,
        "app.kubernetes.io/part-of": "playbookstudio",
        "pbs.owner-hash": _normalized_owner_hash(owner_hash),
    }
    return (
        _namespace_manifest(namespace, labels),
        _resource_quota_manifest(namespace, labels),
        _network_policy_manifest(namespace, labels),
        _service_account_manifest(namespace, labels),
        _role_binding_manifest(namespace, labels),
        _pvc_manifest(namespace, labels, storage_size=storage_size),
        _deployment_manifest(namespace, labels, selector_labels, sandbox_image=sandbox_image),
    )


def ensure_user_workspace(
    owner_hash: str,
    *,
    client: Any | None = None,
    sandbox_image: str = DEFAULT_SANDBOX_IMAGE,
    now: datetime | None = None,
    timeout_seconds: int = 20,
) -> WorkspaceHandle:
    resolved_client = client or KubernetesClient.in_cluster()
    namespace = user_workspace_namespace(owner_hash)
    manifests = build_user_workspace_manifests(owner_hash, sandbox_image=sandbox_image, now=now)
    created = False
    for manifest in manifests:
        result = resolved_client.apply_manifest(manifest)
        created = created or bool(result.get("_created"))
    resolved_client.wait_for_deployment_ready(namespace, SANDBOX_DEPLOYMENT_NAME, timeout_seconds=timeout_seconds)
    pod_name = resolved_client.first_ready_pod(
        namespace,
        label_selector=f"app.kubernetes.io/name={SANDBOX_DEPLOYMENT_NAME},pbs.owner-hash={_normalized_owner_hash(owner_hash)}",
    )
    return WorkspaceHandle(
        namespace=namespace,
        pod_name=pod_name,
        service_account_name=LEARNER_SERVICE_ACCOUNT,
        pvc_name=HOME_PVC_NAME,
        deployment_name=SANDBOX_DEPLOYMENT_NAME,
        ready=bool(pod_name),
        created=created,
        hibernated=False,
        manifests=manifests,
    )


def hibernate_user_workspace(owner_hash: str, *, client: Any | None = None) -> None:
    namespace = user_workspace_namespace(owner_hash)
    resolved_client = client or KubernetesClient.in_cluster()
    resolved_client.patch_resource(
        f"/apis/apps/v1/namespaces/{namespace}/deployments/{SANDBOX_DEPLOYMENT_NAME}",
        {"spec": {"replicas": 0}},
    )
    _patch_namespace_labels(resolved_client, namespace, {"pbs.hibernated": "true"})


def wake_user_workspace(owner_hash: str, *, client: Any | None = None, timeout_seconds: int = 20) -> WorkspaceHandle:
    namespace = user_workspace_namespace(owner_hash)
    resolved_client = client or KubernetesClient.in_cluster()
    resolved_client.patch_resource(
        f"/apis/apps/v1/namespaces/{namespace}/deployments/{SANDBOX_DEPLOYMENT_NAME}",
        {"spec": {"replicas": 1}},
    )
    _patch_namespace_labels(resolved_client, namespace, {"pbs.hibernated": "false"})
    resolved_client.wait_for_deployment_ready(namespace, SANDBOX_DEPLOYMENT_NAME, timeout_seconds=timeout_seconds)
    pod_name = resolved_client.first_ready_pod(namespace, label_selector=f"app.kubernetes.io/name={SANDBOX_DEPLOYMENT_NAME}")
    return WorkspaceHandle(namespace=namespace, pod_name=pod_name, ready=bool(pod_name), hibernated=False)


def delete_user_workspace(owner_hash: str, *, client: Any | None = None) -> bool:
    namespace = user_workspace_namespace(owner_hash)
    resolved_client = client or KubernetesClient.in_cluster()
    resolved_client.delete_resource(f"/api/v1/namespaces/{namespace}")
    return True


def touch_last_active(owner_hash: str, *, client: Any | None = None, now: datetime | None = None) -> None:
    namespace = user_workspace_namespace(owner_hash)
    resolved_client = client or KubernetesClient.in_cluster()
    _patch_namespace_labels(resolved_client, namespace, {"pbs.last-active-at": _label_timestamp(now)})


def set_pinned(owner_hash: str, pinned: bool, *, client: Any | None = None) -> None:
    namespace = user_workspace_namespace(owner_hash)
    resolved_client = client or KubernetesClient.in_cluster()
    _patch_namespace_labels(resolved_client, namespace, {"pbs.pinned": "true" if pinned else "false"})


def _patch_namespace_labels(client: Any, namespace: str, labels: dict[str, str]) -> None:
    client.patch_resource(
        f"/api/v1/namespaces/{namespace}",
        {"metadata": {"labels": labels}},
    )


def _normalized_owner_hash(owner_hash: str) -> str:
    normalized = str(owner_hash or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{32}", normalized):
        raise ValueError("owner_hash must be a 32-character lowercase hex digest")
    return normalized


def _short_owner_hash(owner_hash: str) -> str:
    return _normalized_owner_hash(owner_hash)[:8]


def _label_timestamp(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    return current.strftime("%Y%m%dT%H%M%SZ")


def _workspace_labels(owner_hash: str, *, now: datetime | None = None) -> dict[str, str]:
    normalized = _normalized_owner_hash(owner_hash)
    timestamp = _label_timestamp(now)
    return {
        "app.kubernetes.io/part-of": "playbookstudio",
        "pbs.session": "true",
        "pbs.owner-hash": normalized,
        "pbs.short-hash": normalized[:8],
        "pbs.created-at": timestamp,
        "pbs.last-active-at": timestamp,
        "pbs.hibernated": "false",
        "pbs.pinned": "false",
    }


def _metadata(name: str, namespace: str | None, labels: dict[str, str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": name,
        "labels": dict(labels),
    }
    if namespace:
        metadata["namespace"] = namespace
    return metadata


def _namespace_manifest(namespace: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": _metadata(namespace, None, labels),
    }


def _resource_quota_manifest(namespace: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": _metadata("pbs-user-quota", namespace, labels),
        "spec": {
            "hard": {
                "requests.cpu": "500m",
                "requests.memory": "1Gi",
                "pods": "5",
                "persistentvolumeclaims": "2",
                "requests.storage": "2Gi",
            }
        },
    }


def _network_policy_manifest(namespace: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": _metadata("pbs-user-isolation", namespace, labels),
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {
                            "podSelector": {},
                        }
                    ]
                }
            ],
            "egress": [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "openshift-dns",
                                }
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "default",
                                }
                            }
                        }
                    ]
                },
            ],
        },
    }


def _service_account_manifest(namespace: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": _metadata(LEARNER_SERVICE_ACCOUNT, namespace, labels),
    }


def _role_binding_manifest(namespace: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": _metadata("learner-edit", namespace, labels),
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "edit",
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": LEARNER_SERVICE_ACCOUNT,
                "namespace": namespace,
            }
        ],
    }


def _pvc_manifest(namespace: str, labels: dict[str, str], *, storage_size: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": _metadata(HOME_PVC_NAME, namespace, labels),
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {
                "requests": {
                    "storage": storage_size,
                }
            },
        },
    }


def _deployment_manifest(
    namespace: str,
    labels: dict[str, str],
    selector_labels: dict[str, str],
    *,
    sandbox_image: str,
) -> dict[str, Any]:
    deployment_labels = {**labels, **selector_labels}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": _metadata(SANDBOX_DEPLOYMENT_NAME, namespace, deployment_labels),
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": deployment_labels,
                },
                "spec": {
                    "serviceAccountName": LEARNER_SERVICE_ACCOUNT,
                    "securityContext": {
                        "runAsNonRoot": True,
                    },
                    "containers": [
                        {
                            "name": "sandbox",
                            "image": sandbox_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["/bin/bash", "-lc", "sleep infinity"],
                            "workingDir": "/home/learner",
                            "volumeMounts": [
                                {
                                    "name": "home-learner",
                                    "mountPath": "/home/learner",
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "home-learner",
                            "persistentVolumeClaim": {
                                "claimName": HOME_PVC_NAME,
                            },
                        }
                    ],
                },
            },
        },
    }
