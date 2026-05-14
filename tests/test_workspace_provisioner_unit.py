from __future__ import annotations

from datetime import UTC, datetime

import pytest

from play_book_studio.cluster.k8s_client import resource_path
from play_book_studio.cluster.workspace_provisioner import (
    DEFAULT_SANDBOX_IMAGE,
    build_user_workspace_manifests,
    delete_user_workspace,
    ensure_user_workspace,
    get_user_workspace_status,
    hibernate_user_workspace,
    set_pinned,
    touch_last_active,
    user_workspace_namespace,
    wake_user_workspace,
)


OWNER_HASH = "a3f9c1d2e4b567890123456789abcdef"


class FakeKubernetesClient:
    def __init__(self) -> None:
        self.applied: list[dict] = []
        self.patches: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        self.waits: list[tuple[str, str, int]] = []
        self.pod_queries: list[tuple[str, str]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    def apply_manifest(self, manifest: dict) -> dict:
        self.applied.append(manifest)
        return {"_created": manifest["kind"] == "Namespace"}

    def patch_resource(self, path: str, patch: dict) -> dict:
        self.patches.append((path, patch))
        return {}

    def delete_resource(self, path: str) -> dict:
        self.deleted.append(path)
        return {}

    def wait_for_deployment_ready(self, namespace: str, name: str, *, timeout_seconds: int = 20) -> dict:
        self.waits.append((namespace, name, timeout_seconds))
        return {}

    def first_ready_pod(self, namespace: str, *, label_selector: str) -> str:
        self.pod_queries.append((namespace, label_selector))
        return "sandbox-abc123"

    def request_json(self, method: str, path: str) -> dict:
        response = self.responses.get((method, path))
        if response is None:
            raise RuntimeError(f"missing fake response for {method} {path}")
        return response


def _by_kind_name(manifests: tuple[dict, ...]) -> dict[tuple[str, str], dict]:
    return {
        (item["kind"], item["metadata"]["name"]): item
        for item in manifests
    }


def test_user_workspace_namespace_uses_owner_hash_prefix() -> None:
    assert user_workspace_namespace(OWNER_HASH) == "pbs-user-a3f9c1d2"


def test_user_workspace_namespace_rejects_invalid_owner_hash() -> None:
    with pytest.raises(ValueError, match="owner_hash"):
        user_workspace_namespace("not-a-hash")


def test_build_user_workspace_manifests_labels_every_resource() -> None:
    now = datetime(2026, 5, 14, 4, 37, 58, tzinfo=UTC)
    manifests = build_user_workspace_manifests(OWNER_HASH, now=now)

    assert [item["kind"] for item in manifests] == [
        "Namespace",
        "ResourceQuota",
        "NetworkPolicy",
        "ServiceAccount",
        "RoleBinding",
        "PersistentVolumeClaim",
        "Deployment",
    ]
    for item in manifests:
        labels = item["metadata"]["labels"]
        assert labels["pbs.session"] == "true"
        assert labels["pbs.owner-hash"] == OWNER_HASH
        assert labels["pbs.short-hash"] == "a3f9c1d2"
        assert labels["pbs.created-at"] == "20260514T043758Z"
        assert labels["pbs.last-active-at"] == "20260514T043758Z"
        assert labels["pbs.pinned"] == "false"
        assert labels["pbs.hibernated"] == "false"


def test_build_user_workspace_manifests_create_learner_rbac_and_home_pvc() -> None:
    manifests = _by_kind_name(build_user_workspace_manifests(OWNER_HASH))

    service_account = manifests[("ServiceAccount", "learner")]
    role_binding = manifests[("RoleBinding", "learner-edit")]
    pvc = manifests[("PersistentVolumeClaim", "home-learner")]

    assert service_account["metadata"]["namespace"] == "pbs-user-a3f9c1d2"
    assert role_binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "edit",
    }
    assert role_binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "learner",
            "namespace": "pbs-user-a3f9c1d2",
        }
    ]
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pvc["spec"]["resources"]["requests"]["storage"] == "1Gi"


def test_build_user_workspace_manifests_create_sandbox_deployment() -> None:
    manifests = _by_kind_name(build_user_workspace_manifests(OWNER_HASH))
    deployment = manifests[("Deployment", "sandbox")]

    pod_spec = deployment["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]

    assert deployment["metadata"]["namespace"] == "pbs-user-a3f9c1d2"
    assert deployment["spec"]["replicas"] == 1
    assert pod_spec["serviceAccountName"] == "learner"
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    assert container["image"] == DEFAULT_SANDBOX_IMAGE
    assert container["workingDir"] == "/home/learner"
    assert container["volumeMounts"] == [
        {
            "name": "home-learner",
            "mountPath": "/home/learner",
        }
    ]
    assert pod_spec["volumes"] == [
        {
            "name": "home-learner",
            "persistentVolumeClaim": {
                "claimName": "home-learner",
            },
        }
    ]


def test_build_user_workspace_manifests_include_quota_and_network_policy() -> None:
    manifests = _by_kind_name(build_user_workspace_manifests(OWNER_HASH))
    quota = manifests[("ResourceQuota", "pbs-user-quota")]
    policy = manifests[("NetworkPolicy", "pbs-user-isolation")]

    assert quota["spec"]["hard"]["requests.cpu"] == "500m"
    assert quota["spec"]["hard"]["requests.memory"] == "1Gi"
    assert quota["spec"]["hard"]["pods"] == "5"
    assert quota["spec"]["hard"]["persistentvolumeclaims"] == "2"
    assert policy["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert policy["spec"]["podSelector"] == {}


def test_resource_path_maps_supported_workspace_manifests() -> None:
    paths = {
        item["kind"]: resource_path(item)
        for item in build_user_workspace_manifests(OWNER_HASH)
    }

    assert paths["Namespace"] == "/api/v1/namespaces/pbs-user-a3f9c1d2"
    assert paths["ResourceQuota"] == "/api/v1/namespaces/pbs-user-a3f9c1d2/resourcequotas/pbs-user-quota"
    assert paths["NetworkPolicy"] == "/apis/networking.k8s.io/v1/namespaces/pbs-user-a3f9c1d2/networkpolicies/pbs-user-isolation"
    assert paths["ServiceAccount"] == "/api/v1/namespaces/pbs-user-a3f9c1d2/serviceaccounts/learner"
    assert paths["RoleBinding"] == "/apis/rbac.authorization.k8s.io/v1/namespaces/pbs-user-a3f9c1d2/rolebindings/learner-edit"
    assert paths["PersistentVolumeClaim"] == "/api/v1/namespaces/pbs-user-a3f9c1d2/persistentvolumeclaims/home-learner"
    assert paths["Deployment"] == "/apis/apps/v1/namespaces/pbs-user-a3f9c1d2/deployments/sandbox"


def test_ensure_user_workspace_applies_manifests_and_returns_ready_handle() -> None:
    client = FakeKubernetesClient()

    handle = ensure_user_workspace(OWNER_HASH, client=client, timeout_seconds=7)

    assert [item["kind"] for item in client.applied] == [
        "Namespace",
        "ResourceQuota",
        "NetworkPolicy",
        "ServiceAccount",
        "RoleBinding",
        "PersistentVolumeClaim",
        "Deployment",
    ]
    assert client.waits == [("pbs-user-a3f9c1d2", "sandbox", 7)]
    assert client.pod_queries == [
        (
            "pbs-user-a3f9c1d2",
            "app.kubernetes.io/name=sandbox,pbs.owner-hash=a3f9c1d2e4b567890123456789abcdef",
        )
    ]
    assert handle.namespace == "pbs-user-a3f9c1d2"
    assert handle.pod_name == "sandbox-abc123"
    assert handle.ready is True
    assert handle.created is True


def test_workspace_lifecycle_helpers_patch_and_delete_expected_resources() -> None:
    client = FakeKubernetesClient()

    hibernate_user_workspace(OWNER_HASH, client=client)
    wake_handle = wake_user_workspace(OWNER_HASH, client=client, timeout_seconds=3)
    touch_last_active(
        OWNER_HASH,
        client=client,
        now=datetime(2026, 5, 14, 4, 37, 58, tzinfo=UTC),
    )
    set_pinned(OWNER_HASH, True, client=client)
    assert delete_user_workspace(OWNER_HASH, client=client) is True

    assert client.patches[0] == (
        "/apis/apps/v1/namespaces/pbs-user-a3f9c1d2/deployments/sandbox",
        {"spec": {"replicas": 0}},
    )
    assert client.patches[1] == (
        "/api/v1/namespaces/pbs-user-a3f9c1d2",
        {"metadata": {"labels": {"pbs.hibernated": "true"}}},
    )
    assert client.patches[2] == (
        "/apis/apps/v1/namespaces/pbs-user-a3f9c1d2/deployments/sandbox",
        {"spec": {"replicas": 1}},
    )
    assert client.patches[3] == (
        "/api/v1/namespaces/pbs-user-a3f9c1d2",
        {"metadata": {"labels": {"pbs.hibernated": "false"}}},
    )
    assert client.patches[4] == (
        "/api/v1/namespaces/pbs-user-a3f9c1d2",
        {"metadata": {"labels": {"pbs.last-active-at": "20260514T043758Z"}}},
    )
    assert client.patches[5] == (
        "/api/v1/namespaces/pbs-user-a3f9c1d2",
        {"metadata": {"labels": {"pbs.pinned": "true"}}},
    )
    assert client.deleted == ["/api/v1/namespaces/pbs-user-a3f9c1d2"]
    assert wake_handle.pod_name == "sandbox-abc123"


def test_get_user_workspace_status_reads_labels_and_deployment_readiness() -> None:
    client = FakeKubernetesClient()
    client.responses = {
        ("GET", "/api/v1/namespaces/pbs-user-a3f9c1d2"): {
            "metadata": {
                "labels": {
                    "pbs.pinned": "true",
                    "pbs.hibernated": "false",
                    "pbs.created-at": "20260514T043758Z",
                    "pbs.last-active-at": "20260514T050000Z",
                }
            }
        },
        ("GET", "/apis/apps/v1/namespaces/pbs-user-a3f9c1d2/deployments/sandbox"): {
            "spec": {"replicas": 1},
            "status": {"readyReplicas": 1},
        },
    }

    status = get_user_workspace_status(OWNER_HASH, client=client)

    assert status["available"] is True
    assert status["namespace"] == "pbs-user-a3f9c1d2"
    assert status["ready"] is True
    assert status["pinned"] is True
    assert status["hibernated"] is False
    assert status["last_active_at"] == "20260514T050000Z"
