import json

from play_book_studio.pbs_operator.runtime import (
    OperatorRuntimeConfig,
    apply_desired_resources,
    config_from_env,
    handle_watch_event,
    patch_custom_resource_status,
    run_watch_once,
)


SAMPLE_CR = {
    "apiVersion": "pbs.ocpops.io/v1alpha1",
    "kind": "PlaybookStudio",
    "metadata": {"name": "pbs", "namespace": "pbs-ocpops"},
    "spec": {
        "chat": {"provider": "lightspeed"},
        "route": {"enabled": True},
        "namespaceMode": {"autoCreate": False},
        "lightspeed": {
            "manageOLSConfig": True,
            "mcp": {"enabled": True, "serverName": "pbs-tools"},
        },
        "console": {"executorMode": "service-account"},
    },
}


def test_operator_runtime_config_uses_in_cluster_api_from_env() -> None:
    config = config_from_env(
        {
            "KUBERNETES_SERVICE_HOST": "kubernetes.default.svc",
            "KUBERNETES_SERVICE_PORT": "443",
            "WATCH_NAMESPACE": "pbs-ocpops",
            "PBS_OPERATOR_MODE": "dry-run",
            "PBS_OPERATOR_WATCH_ENABLED": "true",
            "PBS_OPERATOR_APPLY_ENABLED": "true",
        }
    )

    assert config.api_server == "https://kubernetes.default.svc:443"
    assert config.namespace == "pbs-ocpops"
    assert config.mode == "dry-run"
    assert config.watch_enabled is True
    assert config.apply_enabled is True


def test_operator_runtime_detects_added_modified_and_deleted_events() -> None:
    logs: list[str] = []

    def fake_transport(url: str, _headers: dict[str, str], _timeout: float):
        if "watch=true" not in url:
            yield json.dumps({"metadata": {"resourceVersion": "42"}, "items": [SAMPLE_CR]}).encode("utf-8")
            return
        modified = dict(SAMPLE_CR)
        modified["metadata"] = {"name": "pbs", "namespace": "pbs-ocpops"}
        yield json.dumps({"type": "MODIFIED", "object": modified}).encode("utf-8") + b"\n"
        yield json.dumps({"type": "DELETED", "object": {"metadata": {"name": "pbs", "namespace": "pbs-ocpops"}}}).encode("utf-8") + b"\n"

    processed = run_watch_once(
        OperatorRuntimeConfig(
            mode="dry-run",
            namespace="pbs-ocpops",
            api_server="https://kubernetes.default.svc:443",
            token_path="missing-token",
        ),
        transport=fake_transport,
        log=logs.append,
    )

    assert processed == 2
    assert any("detected added PlaybookStudio" in entry for entry in logs)
    assert any("detected modified PlaybookStudio" in entry for entry in logs)
    assert any("detected deleted PlaybookStudio" in entry for entry in logs)
    assert any("desiredResources=" in entry for entry in logs)


def test_operator_runtime_applies_desired_resources_when_enabled() -> None:
    logs: list[str] = []
    writes: list[tuple[str, str, str]] = []

    def fake_transport(url: str, _headers: dict[str, str], _timeout: float):
        if "watch=true" not in url:
            yield json.dumps({"metadata": {"resourceVersion": "42"}, "items": []}).encode("utf-8")
            return
        yield json.dumps({"type": "MODIFIED", "object": SAMPLE_CR}).encode("utf-8") + b"\n"

    def fake_write(method: str, url: str, _headers: dict[str, str], body: bytes, content_type: str, _timeout: float):
        assert body
        writes.append((method, url, content_type))
        return 200, b"{}"

    processed = run_watch_once(
        OperatorRuntimeConfig(
            mode="reconcile",
            namespace="pbs-ocpops",
            api_server="https://kubernetes.default.svc:443",
            token_path="missing-token",
            apply_enabled=True,
        ),
        transport=fake_transport,
        write_transport=fake_write,
        log=logs.append,
    )

    assert processed == 1
    assert any("reconciled modified PlaybookStudio" in entry for entry in logs)
    assert any("appliedResources=" in entry for entry in logs)
    assert any(item[0] == "PATCH" and "/apis/apps/v1/namespaces/pbs-ocpops/deployments/playbookstudio-app" in item[1] for item in writes)
    assert any(item[0] == "PATCH" and "/apis/rbac.authorization.k8s.io/v1/clusterroles/pbs-terminal-broker" in item[1] for item in writes)
    assert any(item[0] == "PATCH" and "/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/pbs-terminal-broker" in item[1] for item in writes)
    assert any(item[0] == "PATCH" and item[1].endswith("/playbookstudios/pbs/status") for item in writes)
    assert any(item[2] == "application/apply-patch+yaml" for item in writes)
    assert any(item[2] == "application/merge-patch+json" for item in writes)


def test_operator_runtime_patches_status_without_applying_resources_in_dry_run() -> None:
    logs: list[str] = []
    writes: list[tuple[str, str, str]] = []

    def fake_write(method: str, url: str, _headers: dict[str, str], body: bytes, content_type: str, _timeout: float):
        assert body
        writes.append((method, url, content_type))
        return 200, b"{}"

    handled = handle_watch_event(
        {"type": "ADDED", "object": SAMPLE_CR},
        logs.append,
        OperatorRuntimeConfig(
            mode="dry-run",
            namespace="pbs-ocpops",
            api_server="https://kubernetes.default.svc:443",
            apply_enabled=False,
        ),
        {"Authorization": "Bearer token"},
        fake_write,
    )

    assert handled is True
    assert writes == [
        (
            "PATCH",
            "https://kubernetes.default.svc:443/apis/pbs.ocpops.io/v1alpha1/namespaces/pbs-ocpops/playbookstudios/pbs/status",
            "application/merge-patch+json",
        )
    ]
    assert any("statusPatch=patched" in entry for entry in logs)
    assert not any("application/apply-patch+yaml" in item[2] for item in writes)


def test_operator_runtime_apply_helpers_target_supported_resource_urls() -> None:
    writes: list[tuple[str, str, str]] = []

    def fake_write(method: str, url: str, _headers: dict[str, str], _body: bytes, content_type: str, _timeout: float):
        writes.append((method, url, content_type))
        return 200, b"{}"

    config = OperatorRuntimeConfig(
        mode="reconcile",
        namespace="pbs-ocpops",
        api_server="https://kubernetes.default.svc:443",
        apply_enabled=True,
    )
    applied = apply_desired_resources(
        [
            {
                "apiVersion": "route.openshift.io/v1",
                "kind": "Route",
                "metadata": {"name": "playbookstudio", "namespace": "pbs-ocpops"},
            }
        ],
        config,
        {},
        fake_write,
    )
    patch_custom_resource_status(SAMPLE_CR, {"phase": "Rendered"}, config, {}, fake_write)

    assert applied == ["Route/pbs-ocpops/playbookstudio"]
    assert writes[0][1].startswith("https://kubernetes.default.svc:443/apis/route.openshift.io/v1")
    assert writes[0][1].endswith("/routes/playbookstudio?fieldManager=pbs-operator&force=true")
    assert writes[1][1].endswith("/apis/pbs.ocpops.io/v1alpha1/namespaces/pbs-ocpops/playbookstudios/pbs/status")


def test_operator_runtime_ignores_non_playbookstudio_watch_events() -> None:
    logs: list[str] = []

    handled = handle_watch_event({"type": "BOOKMARK", "object": {"metadata": {"name": "pbs"}}}, logs.append)

    assert handled is False
    assert logs == []
