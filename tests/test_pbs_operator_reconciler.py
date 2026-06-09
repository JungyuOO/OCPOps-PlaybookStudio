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
            "knowledgeMode": "lightspeed-rag-with-pbs-private-context",
            "manageOLSConfig": True,
            "caBundlePath": "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
            "insecureSkipTLSVerify": False,
            "auth": {"mode": "service-account", "secretName": "pbs-ols-auth"},
            "mcp": {"enabled": True, "registerWithOLS": True, "serverName": "pbs-tools"},
            "networkPolicy": {
                "enabled": True,
                "targetNamespace": "openshift-lightspeed",
                "allowFromNamespaces": ["pbs-ocpops"],
                "allowAllNamespaces": False,
            },
        },
        "console": {"enabled": True, "executorMode": "service-account"},
        "namespaceMode": {"autoCreate": False},
        "library": {"ingestion": {"outputFormat": "pbs-private-context-markdown", "qdrantEnabled": False}},
        "runtime": {
            "secretName": "playbookstudio-secret",
            "config": {
                "LLM_ENDPOINT": "http://cllm.cywell.co.kr/v1",
                "LLM_MODEL": "gemma-4-26b-a4b-it-awq-8bit",
                "POSTGRES_USER": "admin",
                "POSTGRES_DB": "playbookstudio",
            },
        },
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
    assert ("ServiceAccount", "terminal-broker") in identities
    assert ("ClusterRole", "pbs-terminal-broker") in identities
    assert ("ClusterRoleBinding", "pbs-terminal-broker") in identities
    assert ("Route", "playbookstudio") in identities
    assert ("ConfigMap", "pbs-config") in identities
    assert ("ConfigMap", "pbs-olsconfig-patch-preview") in identities
    assert ("NetworkPolicy", "allow-pbs-to-lightspeed-app-server") in identities
    assert ("Role", "pbs-byok-builder") not in identities


def test_pbs_operator_reconciler_maps_cr_fields_to_runtime_config() -> None:
    config = next(
        resource for resource in render_desired_resources(SAMPLE_CR) if resource["kind"] == "ConfigMap" and resource["metadata"]["name"] == "pbs-config"
    )

    assert config["data"]["CHAT_PROVIDER"] == "lightspeed"
    assert config["data"]["PBS_AUTO_CREATE_NAMESPACE"] == "false"
    assert config["data"]["CONSOLE_EXECUTOR_MODE"] == "service-account"
    assert config["data"]["LIGHTSPEED_KNOWLEDGE_MODE"] == "lightspeed-rag-with-pbs-private-context"
    assert config["data"]["OLS_CA_BUNDLE_PATH"] == "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"
    assert config["data"]["OLS_INSECURE_SKIP_TLS_VERIFY"] == "false"
    assert all("BYOK" not in key for key in config["data"])
    assert config["data"]["LIBRARY_OUTPUT_FORMAT"] == "pbs-private-context-markdown"
    assert config["data"]["QDRANT_ENABLED"] == "false"
    assert config["data"]["LLM_ENDPOINT"] == "http://cllm.cywell.co.kr/v1"
    assert config["data"]["POSTGRES_DB"] == "playbookstudio"


def test_pbs_operator_reconciler_maps_runtime_secret_to_app_env() -> None:
    app = next(
        resource
        for resource in render_desired_resources(SAMPLE_CR)
        if resource["kind"] == "Deployment" and resource["metadata"]["name"] == "playbookstudio-app"
    )
    env = app["spec"]["template"]["spec"]["containers"][0]["env"]

    assert env[0]["valueFrom"]["secretKeyRef"]["name"] == "playbookstudio-secret"
    assert env[0]["valueFrom"]["secretKeyRef"]["key"] == "POSTGRES_PASSWORD"
    assert env[1]["valueFrom"]["secretKeyRef"]["key"] == "OCP_API_TOKEN"
    assert env[2]["name"] == "DATABASE_URL"


def test_pbs_operator_reconciler_renders_lightspeed_network_policy() -> None:
    policy = next(
        resource
        for resource in render_desired_resources(SAMPLE_CR)
        if resource["kind"] == "NetworkPolicy"
    )

    assert policy["metadata"]["namespace"] == "openshift-lightspeed"
    assert policy["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "lightspeed-service-api"
    assert policy["spec"]["ingress"][0]["from"] == [
        {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "pbs-ocpops"}}}
    ]
    assert policy["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8443}]


def test_pbs_operator_reconciler_uses_terminal_broker_for_app() -> None:
    app = next(
        resource
        for resource in render_desired_resources(SAMPLE_CR)
        if resource["kind"] == "Deployment" and resource["metadata"]["name"] == "playbookstudio-app"
    )
    web = next(
        resource
        for resource in render_desired_resources(SAMPLE_CR)
        if resource["kind"] == "Deployment" and resource["metadata"]["name"] == "playbookstudio-web"
    )

    assert app["spec"]["template"]["spec"]["serviceAccountName"] == "terminal-broker"
    assert web["spec"]["template"]["spec"]["serviceAccountName"] == "playbookstudio"


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
    assert "name: app" in output
    assert "name: terminal-ws" in output
    assert "play_book_studio.mcp.server" in output
    assert "kind: OLSConfig" in output
    assert "kind: NetworkPolicy" in output
    assert "allow-pbs-to-lightspeed-app-server" in output


def test_pbs_operator_reconciler_always_pulls_managed_images() -> None:
    deployments = [
        resource
        for resource in render_desired_resources(SAMPLE_CR)
        if resource["kind"] == "Deployment"
    ]

    assert deployments
    assert {
        deployment["metadata"]["name"]: deployment["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"]
        for deployment in deployments
    } == {
        "playbookstudio-app": "Always",
        "playbookstudio-web": "Always",
        "pbs-mcp": "Always",
    }
