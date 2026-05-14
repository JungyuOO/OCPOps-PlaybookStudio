from __future__ import annotations

from datetime import UTC, datetime

import pytest

from play_book_studio.cluster.workspace_provisioner import (
    DEFAULT_SANDBOX_IMAGE,
    build_user_workspace_manifests,
    user_workspace_namespace,
)


OWNER_HASH = "a3f9c1d2e4b567890123456789abcdef"


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
