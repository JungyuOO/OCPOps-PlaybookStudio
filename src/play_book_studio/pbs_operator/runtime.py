from __future__ import annotations

from dataclasses import dataclass
import json
import os
import signal
import ssl
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from play_book_studio.pbs_operator.reconciler import render_desired_resources, render_status


TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


Transport = Callable[[str, dict[str, str], float], Iterable[bytes]]
WriteTransport = Callable[[str, str, dict[str, str], bytes, str, float], tuple[int, bytes]]


@dataclass(frozen=True)
class OperatorRuntimeConfig:
    mode: str
    namespace: str
    api_server: str
    token_path: str = TOKEN_PATH
    ca_path: str = CA_PATH
    watch_enabled: bool = True
    apply_enabled: bool = False
    reconnect_seconds: float = 10.0
    request_timeout_seconds: float = 60.0


def config_from_env(env: dict[str, str] | None = None) -> OperatorRuntimeConfig:
    values = env or os.environ
    host = values.get("KUBERNETES_SERVICE_HOST", "")
    port = values.get("KUBERNETES_SERVICE_PORT", "443")
    api_server = values.get("KUBERNETES_API_SERVER", f"https://{host}:{port}" if host else "")
    namespace = values.get("WATCH_NAMESPACE") or values.get("POD_NAMESPACE") or "pbs-ocpops"
    mode = values.get("PBS_OPERATOR_MODE", "dry-run")
    return OperatorRuntimeConfig(
        mode=mode,
        namespace=namespace,
        api_server=api_server,
        token_path=values.get("KUBERNETES_TOKEN_PATH", TOKEN_PATH),
        ca_path=values.get("KUBERNETES_CA_PATH", CA_PATH),
        watch_enabled=values.get("PBS_OPERATOR_WATCH_ENABLED", "true").lower() == "true",
        apply_enabled=values.get("PBS_OPERATOR_APPLY_ENABLED", "false").lower() == "true"
        or mode in {"apply", "reconcile"},
        reconnect_seconds=float(values.get("PBS_OPERATOR_RECONNECT_SECONDS", "10")),
        request_timeout_seconds=float(values.get("PBS_OPERATOR_REQUEST_TIMEOUT_SECONDS", "60")),
    )


def main() -> int:
    config = config_from_env()
    running = True

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print(
        f"pbs-operator runtime started mode={config.mode} namespace={config.namespace} watch={config.watch_enabled}",
        flush=True,
    )
    while running:
        if not config.watch_enabled or not config.api_server:
            time.sleep(config.reconnect_seconds)
            continue
        try:
            processed = run_watch_once(config)
            if processed == 0:
                time.sleep(config.reconnect_seconds)
        except (OSError, URLError, json.JSONDecodeError) as exc:
            print(f"pbs-operator watch reconnecting after error={exc}", flush=True)
            time.sleep(config.reconnect_seconds)
    print("pbs-operator runtime stopped", flush=True)
    return 0


def run_watch_once(
    config: OperatorRuntimeConfig,
    transport: Transport | None = None,
    write_transport: WriteTransport | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    logger = log or (lambda message: print(message, flush=True))
    headers = _auth_headers(config)
    resource_version = _list_existing_custom_resources(config, headers, transport, write_transport, logger)
    params = {"watch": "true"}
    if resource_version:
        params["resourceVersion"] = resource_version
    url = _custom_resource_url(config, params)
    processed = 0
    for line in _stream_lines(url, headers, config.request_timeout_seconds, transport):
        if not line.strip():
            continue
        event = json.loads(line.decode("utf-8"))
        handled = handle_watch_event(event, logger, config, headers, write_transport)
        if handled:
            processed += 1
    return processed


def handle_watch_event(
    event: dict[str, Any],
    log: Callable[[str], None] | None = None,
    config: OperatorRuntimeConfig | None = None,
    headers: dict[str, str] | None = None,
    write_transport: WriteTransport | None = None,
) -> bool:
    logger = log or (lambda message: print(message, flush=True))
    event_type = str(event.get("type") or "")
    custom_resource = event.get("object") or {}
    if event_type not in {"ADDED", "MODIFIED", "DELETED"} or not isinstance(custom_resource, dict):
        return False
    metadata = custom_resource.get("metadata") or {}
    name = metadata.get("name", "unknown")
    namespace = metadata.get("namespace", "")
    if event_type == "DELETED":
        logger(f"pbs-operator detected deleted PlaybookStudio namespace={namespace} name={name}")
        return True

    desired = render_desired_resources(custom_resource)
    status = render_status(custom_resource)
    if config and config.apply_enabled:
        applied = apply_desired_resources(desired, config, headers or {}, write_transport)
        patch_custom_resource_status(custom_resource, status, config, headers or {}, write_transport)
        logger(
            "pbs-operator reconciled "
            f"{event_type.lower()} PlaybookStudio namespace={namespace} name={name} "
            f"appliedResources={len(applied)} statusPhase={status['phase']}"
        )
        return True
    status_patch = "skipped"
    if config and headers.get("Authorization"):
        patch_custom_resource_status(custom_resource, status, config, headers, write_transport)
        status_patch = "patched"
    logger(
        "pbs-operator detected "
        f"{event_type.lower()} PlaybookStudio namespace={namespace} name={name} "
        f"desiredResources={len(desired)} dryRunPhase={status['phase']} statusPatch={status_patch}"
    )
    return True


def apply_desired_resources(
    resources: list[dict[str, Any]],
    config: OperatorRuntimeConfig,
    headers: dict[str, str],
    write_transport: WriteTransport | None = None,
) -> list[str]:
    applied: list[str] = []
    for resource in resources:
        url = _resource_url(config, resource)
        body = json.dumps(resource, sort_keys=True).encode("utf-8")
        _write_request(
            "PATCH",
            f"{url}?fieldManager=pbs-operator&force=true",
            headers,
            body,
            "application/apply-patch+yaml",
            config.request_timeout_seconds,
            write_transport,
        )
        metadata = resource.get("metadata") or {}
        applied.append(f"{resource.get('kind')}/{metadata.get('namespace', config.namespace)}/{metadata.get('name')}")
    return applied


def patch_custom_resource_status(
    custom_resource: dict[str, Any],
    status: dict[str, Any],
    config: OperatorRuntimeConfig,
    headers: dict[str, str],
    write_transport: WriteTransport | None = None,
) -> None:
    metadata = custom_resource.get("metadata") or {}
    name = str(metadata.get("name") or "")
    namespace = str(metadata.get("namespace") or config.namespace)
    if not name:
        return
    url = _custom_resource_item_url(config, namespace, name, subresource="status")
    body = json.dumps({"status": status}, sort_keys=True).encode("utf-8")
    _write_request(
        "PATCH",
        url,
        headers,
        body,
        "application/merge-patch+json",
        config.request_timeout_seconds,
        write_transport,
    )


def _list_existing_custom_resources(
    config: OperatorRuntimeConfig,
    headers: dict[str, str],
    transport: Transport | None,
    write_transport: WriteTransport | None,
    log: Callable[[str], None],
) -> str:
    url = _custom_resource_url(config, {})
    payload = b"".join(_stream_lines(url, headers, config.request_timeout_seconds, transport))
    if not payload.strip():
        return ""
    listing = json.loads(payload.decode("utf-8"))
    for item in listing.get("items") or []:
        handle_watch_event({"type": "ADDED", "object": item}, log, config, headers, write_transport)
    metadata = listing.get("metadata") or {}
    return str(metadata.get("resourceVersion") or "")


def _stream_lines(
    url: str,
    headers: dict[str, str],
    timeout: float,
    transport: Transport | None,
) -> Iterable[bytes]:
    if transport:
        yield from transport(url, headers, timeout)
        return
    request = Request(url, headers=headers)
    context = _ssl_context()
    with urlopen(request, timeout=timeout, context=context) as response:  # nosec B310 - in-cluster Kubernetes API URL
        for line in response:
            yield line


def _write_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    content_type: str,
    timeout: float,
    write_transport: WriteTransport | None,
) -> tuple[int, bytes]:
    if write_transport:
        return write_transport(method, url, headers, body, content_type, timeout)
    request_headers = dict(headers)
    request_headers["Content-Type"] = content_type
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout, context=_ssl_context()) as response:  # nosec B310 - in-cluster Kubernetes API URL
            return response.status, response.read()
    except HTTPError as exc:
        payload = exc.read()
        if exc.code >= 400:
            raise
        return exc.code, payload


def _auth_headers(config: OperatorRuntimeConfig) -> dict[str, str]:
    token = ""
    try:
        token = open(config.token_path, encoding="utf-8").read().strip()
    except OSError:
        pass
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ssl_context() -> ssl.SSLContext:
    if os.path.exists(CA_PATH):
        return ssl.create_default_context(cafile=CA_PATH)
    return ssl.create_default_context()


def _custom_resource_url(config: OperatorRuntimeConfig, params: dict[str, str]) -> str:
    query = f"?{urlencode(params)}" if params else ""
    return (
        f"{config.api_server}/apis/pbs.ocpops.io/v1alpha1/namespaces/"
        f"{config.namespace}/playbookstudios{query}"
    )


def _custom_resource_item_url(config: OperatorRuntimeConfig, namespace: str, name: str, subresource: str = "") -> str:
    suffix = f"/{subresource}" if subresource else ""
    return f"{config.api_server}/apis/pbs.ocpops.io/v1alpha1/namespaces/{namespace}/playbookstudios/{name}{suffix}"


def _resource_url(config: OperatorRuntimeConfig, resource: dict[str, Any]) -> str:
    api_version = str(resource.get("apiVersion") or "")
    kind = str(resource.get("kind") or "")
    metadata = resource.get("metadata") or {}
    namespace = str(metadata.get("namespace") or config.namespace)
    name = str(metadata.get("name") or "")
    plural = _resource_plural(kind)
    if not plural or not name:
        raise ValueError(f"Unsupported resource for operator apply: {api_version} {kind} {namespace}/{name}")
    if api_version == "v1":
        base = f"{config.api_server}/api/v1/namespaces/{namespace}/{plural}"
    else:
        base = f"{config.api_server}/apis/{api_version}/namespaces/{namespace}/{plural}"
    return f"{base}/{name}"


def _resource_plural(kind: str) -> str:
    return {
        "ConfigMap": "configmaps",
        "Deployment": "deployments",
        "Role": "roles",
        "RoleBinding": "rolebindings",
        "Route": "routes",
        "Service": "services",
        "ServiceAccount": "serviceaccounts",
    }.get(kind, "")


if __name__ == "__main__":
    raise SystemExit(main())
