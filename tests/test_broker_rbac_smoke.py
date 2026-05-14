from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_broker_docs() -> list[dict]:
    path = ROOT / "deploy" / "openshift" / "broker-rbac.yaml"
    return [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]


def _resource(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"missing {kind}/{name}")


def test_terminal_broker_rbac_manifest_binds_app_service_account() -> None:
    docs = _load_broker_docs()

    service_account = _resource(docs, "ServiceAccount", "terminal-broker")
    binding = _resource(docs, "ClusterRoleBinding", "pbs-terminal-broker")

    assert service_account["metadata"]["namespace"] == "pbs-ocpops"
    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "pbs-terminal-broker",
    }
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "terminal-broker",
            "namespace": "pbs-ocpops",
        }
    ]


def test_terminal_broker_cluster_role_covers_workspace_lifecycle_and_exec() -> None:
    docs = _load_broker_docs()
    role = _resource(docs, "ClusterRole", "pbs-terminal-broker")

    rules = role["rules"]
    resource_verbs = {
        resource: set(rule["verbs"])
        for rule in rules
        for resource in rule["resources"]
    }

    assert {"create", "get", "patch", "delete"}.issubset(resource_verbs["namespaces"])
    assert {"create", "get", "patch", "delete"}.issubset(resource_verbs["serviceaccounts"])
    assert {"create", "get", "patch", "delete"}.issubset(resource_verbs["persistentvolumeclaims"])
    assert {"create", "get", "patch", "delete"}.issubset(resource_verbs["deployments"])
    assert {"create", "get", "patch", "delete"}.issubset(resource_verbs["rolebindings"])
    assert resource_verbs["pods/exec"] == {"create"}
    assert "networkpolicies" in resource_verbs
    assert "resourcequotas" in resource_verbs


def test_kustomization_includes_broker_rbac_before_app() -> None:
    path = ROOT / "deploy" / "openshift" / "kustomization.yaml"
    kustomization = yaml.safe_load(path.read_text(encoding="utf-8"))

    resources = kustomization["resources"]
    assert "broker-rbac.yaml" in resources
    assert resources.index("broker-rbac.yaml") < resources.index("app.yaml")


def test_app_deployment_uses_terminal_broker_service_account() -> None:
    path = ROOT / "deploy" / "openshift" / "app.yaml"
    docs = [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]
    app = _resource(docs, "Deployment", "app")
    web = _resource(docs, "Deployment", "web")

    assert app["spec"]["template"]["spec"]["serviceAccountName"] == "terminal-broker"
    assert web["spec"]["template"]["spec"]["serviceAccountName"] == "playbookstudio"
