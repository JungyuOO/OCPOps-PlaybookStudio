from play_book_studio.pbs_operator.reconciler import (
    dump_yaml_documents,
    render_desired_resources,
    render_status,
)


SAMPLE_CR = {
    "apiVersion": "pbs.ocpops.io/v1alpha1",
    "kind": "PlaybookStudio",
    "metadata": {"name": "pbs", "namespace": "pbs-ocpops"},
    "spec": {
        "image": "ghcr.io/jungyuoo/ocpops-playbookstudio-app:v0.3.0",
        "route": {"enabled": True},
        "chat": {"provider": "lightspeed"},
        "lightspeed": {
            "manageOLSConfig": True,
            "auth": {"mode": "service-account", "secretName": "pbs-ols-auth"},
            "byoKnowledge": {
                "enabled": True,
                "imageRepository": "image-registry.openshift-image-registry.svc:5000/pbs-ocpops/pbs-knowledge",
                "registrySecret": "pbs-byok-registry",
                "updateMode": "manualApproval",
            },
            "mcp": {"enabled": True, "registerWithOLS": True, "serverName": "pbs-tools"},
        },
        "console": {"enabled": True, "executorMode": "service-account"},
        "namespaceMode": {"autoCreate": False},
        "library": {"ingestion": {"outputFormat": "lightspeed-byok-markdown", "qdrantEnabled": False}},
    },
}


def test_pbs_operator_reconciler_renders_managed_resources_from_cr() -> None:
    resources = render_desired_resources(SAMPLE_CR)
    identities = {(resource["kind"], resource["metadata"]["name"]) for resource in resources}

    assert ("Deployment", "playbookstudio-app") in identities
    assert ("Deployment", "playbookstudio-web") in identities
    assert ("Deployment", "pbs-mcp") in identities
    assert ("Service", "playbookstudio-app") in identities
    assert ("Service", "playbookstudio-web") in identities
    assert ("Service", "pbs-mcp") in identities
    assert ("Route", "playbookstudio") in identities
    assert ("ConfigMap", "pbs-config") in identities
    assert ("ConfigMap", "pbs-olsconfig-patch-preview") in identities
    assert ("Role", "pbs-byok-builder") in identities


def test_pbs_operator_reconciler_maps_cr_fields_to_runtime_config() -> None:
    config = next(
        resource for resource in render_desired_resources(SAMPLE_CR) if resource["kind"] == "ConfigMap" and resource["metadata"]["name"] == "pbs-config"
    )

    assert config["data"]["CHAT_PROVIDER"] == "lightspeed"
    assert config["data"]["PBS_AUTO_CREATE_NAMESPACE"] == "false"
    assert config["data"]["CONSOLE_EXECUTOR_MODE"] == "service-account"
    assert config["data"]["BYOK_PIPELINE_ENABLED"] == "true"
    assert config["data"]["BYOK_OUTPUT_MODE"] == "manualApproval"
    assert config["data"]["QDRANT_ENABLED"] == "false"


def test_pbs_operator_reconciler_status_does_not_claim_live_success() -> None:
    status = render_status(SAMPLE_CR)

    assert status["phase"] == "Rendered"
    assert status["lightspeedReady"] is False
    assert status["mcpRegistered"] is False
    assert "live reconciliation is not claimed" in status["conditions"][0]["message"]


def test_pbs_operator_reconciler_yaml_dump_contains_expected_documents() -> None:
    output = dump_yaml_documents(render_desired_resources(SAMPLE_CR))

    assert "kind: Deployment" in output
    assert "name: playbookstudio-app" in output
    assert "play_book_studio.http.server" in output
    assert "play_book_studio.mcp.server" in output
    assert "kind: OLSConfig" in output
