from __future__ import annotations

from copy import deepcopy
import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_APP_IMAGE = "ghcr.io/jungyuoo/ocpops-playbookstudio-app:v0.3.0"
DEFAULT_WEB_IMAGE = "ghcr.io/jungyuoo/ocpops-playbookstudio-web:v0.3.0"
DEFAULT_NAMESPACE = "pbs-ocpops"
DEFAULT_OLS_NAMESPACE = "openshift-lightspeed"
DEFAULT_OLS_BASE_URL = "https://lightspeed-app-server.openshift-lightspeed.svc.cluster.local:8443"


def render_desired_resources(custom_resource: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = custom_resource.get("metadata") or {}
    spec = custom_resource.get("spec") or {}
    name = str(metadata.get("name") or "pbs")
    namespace = str(metadata.get("namespace") or DEFAULT_NAMESPACE)

    resources: list[dict[str, Any]] = [
        _service_account("playbookstudio", namespace),
        _service_account("terminal-broker", namespace),
        _service_account("pbs-console-executor", namespace),
        _terminal_broker_cluster_role(),
        _terminal_broker_cluster_role_binding(namespace),
        _config_map(name, namespace, spec),
        _app_compat_service(namespace),
        _service("web", namespace, 8080, "http", selector_name="playbookstudio-web"),
        _service("playbookstudio-app", namespace, 8765, "http"),
        _service("playbookstudio-web", namespace, 8080, "http"),
        _deployment(
            "playbookstudio-app",
            namespace,
            _app_image(spec),
            8765,
            None,
            extra_ports=[{"containerPort": 8770, "name": "terminal-ws"}],
            runtime_secret_name=_runtime_secret_name(spec),
        ),
        _deployment("playbookstudio-web", namespace, _web_image(spec), 8080, None),
    ]

    if _route_enabled(spec):
        resources.append(_route("playbookstudio", namespace, "playbookstudio-web"))

    if _mcp_enabled(spec):
        resources.extend(
            [
                _service("pbs-mcp", namespace, 8080, "mcp"),
                _deployment("pbs-mcp", namespace, _app_image(spec), 8080, ["python", "-m", "play_book_studio.mcp.server"]),
            ]
        )

    if _manage_ols_config(spec):
        resources.append(_olsconfig_preview(namespace, spec))

    if _manage_lightspeed_network_policy(spec):
        resources.append(_lightspeed_network_policy(namespace, spec))

    return resources


def render_status(custom_resource: dict[str, Any]) -> dict[str, Any]:
    spec = custom_resource.get("spec") or {}
    return {
        "phase": "Rendered",
        "lightspeedReady": False,
        "mcpRegistered": False,
        "conditions": [
            {
                "type": "DesiredStateRendered",
                "status": "True",
                "reason": "DryRunOnly",
                "message": "Desired PBS resources rendered locally; live reconciliation is not claimed.",
            },
            {
                "type": "LightspeedIntegrationRequested",
                "status": "True" if _manage_ols_config(spec) else "False",
                "reason": "OLSConfigPreview" if _manage_ols_config(spec) else "Disabled",
                "message": "OLSConfig changes require explicit live approval.",
            },
            {
                "type": "LightspeedNetworkPolicyRequested",
                "status": "True" if _manage_lightspeed_network_policy(spec) else "False",
                "reason": "NetworkPolicyRendered" if _manage_lightspeed_network_policy(spec) else "Disabled",
                "message": "Lightspeed ingress NetworkPolicy is rendered only when explicitly enabled.",
            },
        ],
    }


def dump_yaml_documents(resources: list[dict[str, Any]]) -> str:
    return "\n---\n".join(_dump_yaml(resource) for resource in resources) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render PBS Operator desired resources from a PlaybookStudio CR JSON.")
    parser.add_argument("--cr-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--status-output", type=Path)
    args = parser.parse_args(argv)

    custom_resource = json.loads(args.cr_json.read_text(encoding="utf-8"))
    resources = render_desired_resources(custom_resource)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dump_yaml_documents(resources), encoding="utf-8")
    if args.status_output:
        args.status_output.parent.mkdir(parents=True, exist_ok=True)
        args.status_output.write_text(json.dumps(render_status(custom_resource), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _config_map(name: str, namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    lightspeed = spec.get("lightspeed") or {}
    auth = lightspeed.get("auth") or {}
    console = spec.get("console") or {}
    namespace_mode = spec.get("namespaceMode") or {}
    chat = spec.get("chat") or {}
    library = spec.get("library") or {}
    ingestion = library.get("ingestion") or {}
    data = {
        "CHAT_PROVIDER": str(chat.get("provider") or "lightspeed"),
        "LIGHTSPEED_KNOWLEDGE_MODE": str(
            lightspeed.get("knowledgeMode") or "lightspeed-rag-with-pbs-private-context"
        ),
        "OLS_BASE_URL": str(lightspeed.get("baseUrl") or DEFAULT_OLS_BASE_URL),
        "OLS_AUTH_MODE": str(auth.get("mode") or "service-account"),
        "OLS_AUTH_SECRET_NAME": str(auth.get("secretName") or "pbs-ols-auth"),
        "PBS_AUTO_CREATE_NAMESPACE": _bool_text(namespace_mode.get("autoCreate", False)),
        "PBS_NAMESPACE_MODE": "auto" if namespace_mode.get("autoCreate", False) else "disabled",
        "CONSOLE_EXECUTOR_MODE": str(console.get("executorMode") or "service-account"),
        "PBS_OPERATOR_READY_MODE": "true",
        "PBS_OPERATOR_MANIFEST_PROFILE": "sno",
        "QDRANT_ENABLED": _bool_text(ingestion.get("qdrantEnabled", False)),
        "LIBRARY_OUTPUT_FORMAT": str(ingestion.get("outputFormat") or "pbs-private-context-markdown"),
    }
    data.update(_runtime_config(spec))
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": _metadata(f"{name}-config", namespace, "playbookstudio"),
        "data": data,
    }


def _deployment(
    name: str,
    namespace: str,
    image: str,
    port: int,
    command: list[str] | None,
    *,
    extra_ports: list[dict[str, Any]] | None = None,
    runtime_secret_name: str = "",
) -> dict[str, Any]:
    container: dict[str, Any] = {
        "name": name.removeprefix("playbookstudio-"),
        "image": image,
        "imagePullPolicy": "Always",
        "ports": [
            {"containerPort": port, "name": "http" if name != "pbs-mcp" else "mcp"},
            *(extra_ports or []),
        ],
    }
    if command:
        container["command"] = command
    if name == "playbookstudio-app":
        container["envFrom"] = [{"configMapRef": {"name": "pbs-config"}}]
        secret_env = _runtime_secret_env(runtime_secret_name)
        if secret_env:
            container["env"] = secret_env
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": _metadata(name, namespace, name),
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": name}},
            "template": {
                "metadata": {"labels": _labels(name)},
                "spec": {
                    "serviceAccountName": "terminal-broker" if name == "playbookstudio-app" else "playbookstudio",
                    "containers": [container],
                },
            },
        },
    }


def _service(
    name: str,
    namespace: str,
    port: int,
    port_name: str,
    *,
    selector_name: str | None = None,
) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": _metadata(name, namespace, name),
        "spec": {
            "selector": {"app.kubernetes.io/name": selector_name or name},
            "ports": [{"name": port_name, "port": port, "targetPort": port_name}],
        },
    }


def _app_compat_service(namespace: str) -> dict[str, Any]:
    service = _service("app", namespace, 8765, "http", selector_name="playbookstudio-app")
    service["spec"]["ports"].append(
        {"name": "terminal-ws", "port": 8770, "targetPort": "terminal-ws"}
    )
    return service


def _route(name: str, namespace: str, service_name: str) -> dict[str, Any]:
    return {
        "apiVersion": "route.openshift.io/v1",
        "kind": "Route",
        "metadata": _metadata(name, namespace, "playbookstudio-web"),
        "spec": {
            "to": {"kind": "Service", "name": service_name},
            "port": {"targetPort": "http"},
            "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"},
        },
    }


def _service_account(name: str, namespace: str) -> dict[str, Any]:
    return {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _metadata(name, namespace, name)}


def _terminal_broker_cluster_role() -> dict[str, Any]:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": "pbs-terminal-broker", "labels": _labels("terminal-broker")},
        "rules": [
            {"apiGroups": [""], "resources": ["namespaces"], "verbs": ["create", "get", "list", "patch", "delete"]},
            {
                "apiGroups": [""],
                "resources": ["configmaps", "events", "persistentvolumeclaims", "pods", "secrets", "serviceaccounts", "services"],
                "verbs": ["create", "get", "list", "watch", "patch", "update", "delete"],
            },
            {"apiGroups": [""], "resources": ["pods/exec"], "verbs": ["create"]},
            {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get", "list"]},
            {"apiGroups": ["apps"], "resources": ["deployments", "replicasets", "statefulsets"], "verbs": ["create", "get", "list", "watch", "patch", "update", "delete"]},
            {"apiGroups": ["batch"], "resources": ["cronjobs", "jobs"], "verbs": ["create", "get", "list", "watch", "patch", "update", "delete"]},
            {"apiGroups": ["networking.k8s.io"], "resources": ["networkpolicies"], "verbs": ["create", "get", "list", "patch", "update", "delete"]},
            {"apiGroups": ["project.openshift.io"], "resources": ["projects"], "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["route.openshift.io"], "resources": ["routes"], "verbs": ["create", "get", "list", "watch", "patch", "update", "delete"]},
            {"apiGroups": ["rbac.authorization.k8s.io"], "resources": ["rolebindings", "roles"], "verbs": ["create", "get", "list", "patch", "update", "delete"]},
        ],
    }


def _terminal_broker_cluster_role_binding(namespace: str) -> dict[str, Any]:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {"name": "pbs-terminal-broker", "labels": _labels("terminal-broker")},
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "pbs-terminal-broker",
        },
        "subjects": [{"kind": "ServiceAccount", "name": "terminal-broker", "namespace": namespace}],
    }


def _olsconfig_preview(namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    lightspeed = spec.get("lightspeed") or {}
    mcp = lightspeed.get("mcp") or {}
    server_name = str(mcp.get("serverName") or "pbs-tools")
    preview = {
        "apiVersion": "ols.openshift.io/v1alpha1",
        "kind": "OLSConfig",
        "metadata": {"name": "cluster", "namespace": "openshift-lightspeed"},
        "spec": {
            "featureGates": ["MCPServer"],
            "mcpServers": [
                {
                    "name": server_name,
                    "url": f"http://pbs-mcp.{namespace}.svc.cluster.local:8080/mcp",
                    "timeout": 30,
                }
            ],
        },
    }
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": _metadata("pbs-olsconfig-patch-preview", namespace, "pbs-olsconfig-preview"),
        "data": {"olsconfig-patch-preview.yaml": dump_yaml_documents([preview])},
    }


def _lightspeed_network_policy(namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    lightspeed = spec.get("lightspeed") or {}
    policy = lightspeed.get("networkPolicy") or {}
    target_namespace = str(policy.get("targetNamespace") or DEFAULT_OLS_NAMESPACE)
    allow_all_namespaces = bool(policy.get("allowAllNamespaces", False))
    allowed_namespaces = policy.get("allowFromNamespaces") or [namespace]
    if not isinstance(allowed_namespaces, list):
        allowed_namespaces = [namespace]

    ingress_from: list[dict[str, Any]]
    if allow_all_namespaces:
        ingress_from = [{"namespaceSelector": {}}]
    else:
        ingress_from = [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": str(allowed_namespace)}
                }
            }
            for allowed_namespace in allowed_namespaces
        ]

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": _metadata("allow-pbs-to-lightspeed-app-server", target_namespace, "pbs-lightspeed-ingress"),
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/component": "application-server",
                    "app.kubernetes.io/name": "lightspeed-service-api",
                    "app.kubernetes.io/part-of": "openshift-lightspeed",
                }
            },
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": ingress_from,
                    "ports": [{"protocol": "TCP", "port": 8443}],
                }
            ],
        },
    }


def _metadata(name: str, namespace: str, app_name: str) -> dict[str, Any]:
    return {"name": name, "namespace": namespace, "labels": _labels(app_name)}


def _labels(app_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": app_name,
        "app.kubernetes.io/part-of": "playbookstudio",
        "pbs.ocpops.io/operator-managed": "true",
    }


def _route_enabled(spec: dict[str, Any]) -> bool:
    return bool((spec.get("route") or {}).get("enabled", True))


def _mcp_enabled(spec: dict[str, Any]) -> bool:
    return bool(((spec.get("lightspeed") or {}).get("mcp") or {}).get("enabled", False))


def _manage_ols_config(spec: dict[str, Any]) -> bool:
    return bool((spec.get("lightspeed") or {}).get("manageOLSConfig", False))


def _manage_lightspeed_network_policy(spec: dict[str, Any]) -> bool:
    return bool(((spec.get("lightspeed") or {}).get("networkPolicy") or {}).get("enabled", False))


def _app_image(spec: dict[str, Any]) -> str:
    return str(spec.get("image") or DEFAULT_APP_IMAGE)


def _web_image(spec: dict[str, Any]) -> str:
    image = str(spec.get("webImage") or "")
    if image:
        return image
    app_image = _app_image(spec)
    if "-app:" in app_image:
        return app_image.replace("-app:", "-web:")
    return DEFAULT_WEB_IMAGE


def _runtime_config(spec: dict[str, Any]) -> dict[str, str]:
    config = ((spec.get("runtime") or {}).get("config") or {})
    if not isinstance(config, dict):
        return {}
    return {str(key): str(value) for key, value in config.items() if value is not None}


def _runtime_secret_name(spec: dict[str, Any]) -> str:
    return str((spec.get("runtime") or {}).get("secretName") or "")


def _runtime_secret_env(secret_name: str) -> list[dict[str, Any]]:
    if not secret_name:
        return []
    return [
        {
            "name": "POSTGRES_PASSWORD",
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "POSTGRES_PASSWORD"}},
        },
        {
            "name": "OCP_API_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "OCP_API_TOKEN"}},
        },
        {
            "name": "DATABASE_URL",
            "value": "postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/$(POSTGRES_DB)",
        },
    ]


def _bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def _dump_yaml(value: Any, indent: int = 0) -> str:
    lines = _dump_yaml_lines(value, indent)
    return "\n".join(lines)


def _dump_yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                copied = deepcopy(item)
                first_key = next(iter(copied))
                first_value = copied.pop(first_key)
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_dump_yaml_lines(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {_scalar(first_value)}")
                if copied:
                    lines.extend(_dump_yaml_lines(copied, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_scalar(item)}")
        return lines
    return [f"{prefix}{_scalar(value)}"]


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    text = str(value)
    if text == "" or text.lower() in {"true", "false", "null"} or any(char in text for char in [": ", "#", "\n", "{", "}", "[", "]"]):
        return json.dumps(text)
    return text


if __name__ == "__main__":
    raise SystemExit(main())
