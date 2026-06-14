from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_reaper_cronjob_uses_terminal_broker_and_sandbox_image() -> None:
    path = ROOT / "deploy" / "openshift" / "workspace-reaper-cronjob.yaml"
    cronjob = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert cronjob["kind"] == "CronJob"
    assert cronjob["metadata"]["name"] == "workspace-reaper"
    assert cronjob["spec"]["schedule"] == "*/15 * * * *"
    pod_spec = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "terminal-broker"
    container = pod_spec["containers"][0]
    assert container["image"] == "ghcr.io/jungyuoo/ocpops-playbookstudio-sandbox:dev"
    assert {"name": "PBS_WORKSPACE_HIBERNATE_AFTER_SECONDS", "value": "1800"} in container["env"]
    assert {"name": "PBS_WORKSPACE_DELETE_AFTER_SECONDS", "value": "1209600"} in container["env"]


def test_workspace_reaper_script_hibernates_and_deletes_by_labels() -> None:
    path = ROOT / "deploy" / "openshift" / "workspace-reaper-cronjob.yaml"
    cronjob = yaml.safe_load(path.read_text(encoding="utf-8"))
    script = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"][-1]

    assert "oc get ns -l pbs.session=true -o json" in script
    assert '(.metadata.labels."pbs.last-active-at" // .metadata.labels."pbs.created-at" // "")' in script
    assert '(.metadata.labels."pbs.pinned" // "false")' in script
    assert 'oc patch deployment sandbox -n "${namespace}" --type=merge -p \'{"spec":{"replicas":0}}\'' in script
    assert 'oc label namespace "${namespace}" pbs.hibernated=true --overwrite' in script
    assert 'oc delete namespace "${namespace}"' in script


def test_kustomization_includes_workspace_reaper_before_app() -> None:
    path = ROOT / "deploy" / "openshift" / "kustomization.yaml"
    kustomization = yaml.safe_load(path.read_text(encoding="utf-8"))

    resources = kustomization["resources"]
    assert "workspace-reaper-cronjob.yaml" in resources
    assert resources.index("broker-rbac.yaml") < resources.index("workspace-reaper-cronjob.yaml")
    assert resources.index("workspace-reaper-cronjob.yaml") < resources.index("app.yaml")
