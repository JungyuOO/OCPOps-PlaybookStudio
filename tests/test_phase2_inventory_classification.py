from pathlib import Path

from play_book_studio.cluster.live_inventory import (
    ResourceIdentity,
    classify_inventory,
    desired_yaml_paths,
    inventory_yaml_paths,
    load_resources_from_paths,
    write_decision_report,
)


def test_phase2_inventory_classifies_adopt_remove_replace_and_external_owner(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory"
    desired_dir = tmp_path / "desired"
    (inventory / "namespaces" / "pbs-ocpops").mkdir(parents=True)
    (inventory / "namespaces" / "openshift-lightspeed").mkdir(parents=True)
    desired_dir.mkdir()

    (inventory / "namespaces" / "pbs-ocpops" / "deployments.yaml").write_text(
        """
apiVersion: v1
kind: List
items:
- apiVersion: apps/v1
  kind: Deployment
  metadata:
    name: playbookstudio-app
    namespace: pbs-ocpops
  spec:
    replicas: 1
- apiVersion: v1
  kind: ConfigMap
  metadata:
    name: manual-test-config
    namespace: pbs-ocpops
  data:
    created-by: oc-patch-test
""",
        encoding="utf-8",
    )
    (inventory / "namespaces" / "openshift-lightspeed" / "subscriptions.yaml").write_text(
        """
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: lightspeed-operator
  namespace: openshift-lightspeed
""",
        encoding="utf-8",
    )
    (desired_dir / "pbs.yaml").write_text(
        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: playbookstudio-app
  namespace: pbs-ocpops
spec:
  replicas: 1
---
apiVersion: v1
kind: Service
metadata:
  name: playbookstudio-app
  namespace: pbs-ocpops
""",
        encoding="utf-8",
    )

    live = load_resources_from_paths(inventory_yaml_paths(inventory))
    desired = load_resources_from_paths(desired_yaml_paths([desired_dir]))
    decisions = {decision.identity: decision for decision in classify_inventory(live, desired)}

    assert decisions[ResourceIdentity("Deployment", "pbs-ocpops", "playbookstudio-app")].decision == "adopt"
    assert decisions[ResourceIdentity("ConfigMap", "pbs-ocpops", "manual-test-config")].decision == "remove"
    assert decisions[ResourceIdentity("Service", "pbs-ocpops", "playbookstudio-app")].decision == "replace"
    assert (
        decisions[ResourceIdentity("Subscription", "openshift-lightspeed", "lightspeed-operator")].decision
        == "external-owner"
    )


def test_phase2_inventory_report_is_deterministic_json(tmp_path: Path) -> None:
    identity = ResourceIdentity("Deployment", "pbs-ocpops", "playbookstudio-app")
    decisions = classify_inventory(
        live={},
        desired={
            identity: load_resources_from_paths(
                [
                    _write(
                        tmp_path / "desired.yaml",
                        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: playbookstudio-app
  namespace: pbs-ocpops
""",
                    )
                ]
            )[identity]
        },
    )
    output = tmp_path / "report.json"

    write_decision_report(decisions, output)

    report = output.read_text(encoding="utf-8")
    assert '"decision": "replace"' in report
    assert '"key": "Deployment/pbs-ocpops/playbookstudio-app"' in report


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
