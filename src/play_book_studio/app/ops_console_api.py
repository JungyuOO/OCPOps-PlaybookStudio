from __future__ import annotations

import difflib
import json
import mimetypes
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

from play_book_studio.config.settings import load_settings


RESOURCE_TYPES = ("pods", "deployments", "services", "routes", "events")
EDITABLE_RESOURCE_TYPES = {"deployments", "services", "routes"}
REAL_OCP_CONNECT_TIMEOUT_SECONDS = 10
REAL_OCP_READ_TIMEOUT_SECONDS = 20
REAL_OCP_RETRY_ATTEMPTS = 3
REAL_OCP_RETRY_BACKOFF_SECONDS = 0.6
RESOURCE_KIND_LABELS = {
    "pods": "Pod",
    "deployments": "Deployment",
    "services": "Service",
    "routes": "Route",
    "events": "Event",
}
RESOURCE_KEYWORDS = {
    "pods": ("pod", "pods", "파드", "pods"),
    "deployments": ("deployment", "deployments", "deploy", "배포", "디플로이"),
    "services": ("service", "services", "svc", "서비스"),
    "routes": ("route", "routes", "ingress", "라우트", "인그레스"),
    "events": ("event", "events", "이벤트"),
}
LIST_INTENT_TERMS = ("list", "show", "get", "find", "목록", "리스트", "보여", "조회", "확인")
DETAIL_INTENT_TERMS = ("yaml", "manifest", "detail", "describe", "상세", "세부", "내용")
EDIT_INTENT_TERMS = ("edit", "update", "patch", "apply", "modify", "수정", "변경", "편집", "적용")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower())
    normalized = normalized.strip("-")
    return normalized or "workspace"


def _ops_state_path(root_dir: Path) -> Path:
    return root_dir / "artifacts" / "ops_console_v1" / "state.json"


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_workspace_record() -> dict[str, Any]:
    timestamp = _now_iso()
    return {
        "workspace_id": "ws_default",
        "name": "Default Ops Workspace",
        "slug": "default-ops-workspace",
        "industry": "",
        "environment": "dev",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _default_state() -> dict[str, Any]:
    workspace = _seed_workspace_record()
    return {
        "version": 1,
        "workspaces": [workspace],
        "connections": [],
        "connection_inventory": {},
        "recommendations": [],
        "batch_jobs": [],
        "action_requests": [],
        "action_executions": [],
        "action_audit": [],
        "scm_connections": [],
        "scm_repositories": [],
        "oauth_states": [],
    }


def _load_state(root_dir: Path) -> dict[str, Any]:
    path = _ops_state_path(root_dir)
    state = _read_json_object(path)
    if not state:
        state = _default_state()
        _write_json_object(path, state)
        return state
    state.setdefault("version", 1)
    state.setdefault("workspaces", [])
    state.setdefault("connections", [])
    state.setdefault("connection_inventory", {})
    state.setdefault("recommendations", [])
    state.setdefault("batch_jobs", [])
    state.setdefault("action_requests", [])
    state.setdefault("action_executions", [])
    state.setdefault("action_audit", [])
    state.setdefault("scm_connections", [])
    state.setdefault("scm_repositories", [])
    state.setdefault("oauth_states", [])
    if not state["workspaces"]:
        workspace = _seed_workspace_record()
        state["workspaces"].append(workspace)
        _write_json_object(path, state)
    return state


def _save_state(root_dir: Path, state: dict[str, Any]) -> None:
    _write_json_object(_ops_state_path(root_dir), state)


def _ops_settings(root_dir: Path):
    return load_settings(root_dir)


def _real_ocp_config(root_dir: Path) -> dict[str, str] | None:
    settings = _ops_settings(root_dir)
    base_url = str(getattr(settings, "ocp_api_base_url", "") or "").strip().rstrip("/")
    token = str(getattr(settings, "ocp_api_token", "") or "").strip()
    if not base_url or not token:
        return None
    return {
        "base_url": base_url,
        "token": token,
        "namespace": "demo",
    }


def _scm_provider_status(root_dir: Path) -> dict[str, dict[str, Any]]:
    settings = _ops_settings(root_dir)
    github_id = str(getattr(settings, "scm_github_client_id", "") or "").strip()
    github_secret = str(getattr(settings, "scm_github_client_secret", "") or "").strip()
    gitlab_id = str(getattr(settings, "scm_gitlab_client_id", "") or "").strip()
    gitlab_secret = str(getattr(settings, "scm_gitlab_client_secret", "") or "").strip()
    return {
        "github": {
            "configured": bool(github_id and github_secret),
            "client_id_present": bool(github_id),
            "client_secret_present": bool(github_secret),
        },
        "gitlab": {
            "configured": bool(gitlab_id and gitlab_secret),
            "client_id_present": bool(gitlab_id),
            "client_secret_present": bool(gitlab_secret),
        },
    }


def _oauth_authorize_url(handler: Any, root_dir: Path, provider: str, state_token: str) -> str:
    settings = _ops_settings(root_dir)
    host = str(handler.headers.get("Host") or "127.0.0.1:8765").strip()
    redirect_uri = f"http://{host}/api/v1/oauth/{provider}/callback"
    if provider == "github" and settings.scm_github_client_id:
        return (
            "https://github.com/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": settings.scm_github_client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "read:user repo",
                    "state": state_token,
                }
            )
        )
    if provider == "gitlab" and settings.scm_gitlab_client_id:
        return (
            "https://gitlab.com/oauth/authorize?"
            + urlencode(
                {
                    "client_id": settings.scm_gitlab_client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "read_user api",
                    "state": state_token,
                }
            )
        )
    return f"/api/v1/oauth/{provider}/callback?{urlencode({'state': state_token})}"


def _is_real_ocp_connection(root_dir: Path, connection: dict[str, Any]) -> bool:
    config = _real_ocp_config(root_dir)
    if config is None:
        return False
    return str(connection.get("cluster_url") or "").strip().rstrip("/") == config["base_url"]


def _real_ocp_request_json(root_dir: Path, path: str) -> dict[str, Any]:
    return _real_ocp_request(root_dir, "GET", path)


def _real_ocp_request(
    root_dir: Path,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    raw_body: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    config = _real_ocp_config(root_dir)
    if config is None:
        raise RuntimeError("OCP API env is not configured")
    import requests
    import urllib3
    from requests import exceptions as requests_exceptions

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    response = None
    last_error: Exception | None = None
    for attempt in range(1, REAL_OCP_RETRY_ATTEMPTS + 1):
        try:
            response = requests.request(
                method.upper(),
                f"{config['base_url']}{path}",
                headers=headers,
                json=json_payload if raw_body is None else None,
                data=raw_body.encode("utf-8") if raw_body is not None else None,
                timeout=(REAL_OCP_CONNECT_TIMEOUT_SECONDS, REAL_OCP_READ_TIMEOUT_SECONDS),
                verify=False,
            )
            break
        except (
            requests_exceptions.ConnectTimeout,
            requests_exceptions.ReadTimeout,
            requests_exceptions.ConnectionError,
        ) as exc:
            last_error = exc
            if attempt >= REAL_OCP_RETRY_ATTEMPTS:
                raise
            time.sleep(REAL_OCP_RETRY_BACKOFF_SECONDS * attempt)
    if response is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Real OCP request failed before a response was created")
    response.raise_for_status()
    payload = response.json() if response.content else {}
    return payload if isinstance(payload, dict) else {}


def _real_ocp_resources_payload(root_dir: Path, resource_type: str) -> dict[str, Any]:
    namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
    if resource_type == "pods":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/pods")
    if resource_type == "deployments":
        return _real_ocp_request_json(root_dir, f"/apis/apps/v1/namespaces/{namespace}/deployments")
    if resource_type == "services":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/services")
    if resource_type == "routes":
        return _real_ocp_request_json(root_dir, f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes")
    if resource_type == "events":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/events")
    raise ValueError("Unsupported resource type")


def _real_ocp_resource_detail_payload(root_dir: Path, resource_type: str, name: str) -> dict[str, Any]:
    namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
    if resource_type == "pods":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/pods/{name}")
    if resource_type == "deployments":
        return _real_ocp_request_json(root_dir, f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}")
    if resource_type == "services":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/services/{name}")
    if resource_type == "routes":
        return _real_ocp_request_json(root_dir, f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes/{name}")
    if resource_type == "events":
        return _real_ocp_request_json(root_dir, f"/api/v1/namespaces/{namespace}/events/{name}")
    raise ValueError("Unsupported resource type")


def _real_ocp_items(resource_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("items")
    items = [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []
    normalized: list[dict[str, Any]] = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        row: dict[str, Any] = {
            "name": str(metadata.get("name") or ""),
            "namespace": str(metadata.get("namespace") or "demo"),
            "kind": str(item.get("kind") or ""),
            "created_at": str(metadata.get("creationTimestamp") or ""),
            "manifest_json": item,
            "manifest_yaml": _yaml_dump(item),
        }
        if resource_type == "pods":
            row["phase"] = str(status.get("phase") or "")
            row["node_name"] = str(spec.get("nodeName") or "")
        elif resource_type == "deployments":
            row["ready_replicas"] = int(status.get("readyReplicas") or 0)
            row["replicas"] = int(spec.get("replicas") or status.get("replicas") or 0)
        elif resource_type == "services":
            row["type"] = str(spec.get("type") or "")
            row["cluster_ip"] = str(spec.get("clusterIP") or "")
        elif resource_type == "routes":
            route_to = spec.get("to") if isinstance(spec.get("to"), dict) else {}
            row["host"] = str(spec.get("host") or "")
            row["to"] = str(route_to.get("name") or "")
        elif resource_type == "events":
            row["phase"] = str(item.get("type") or "")
        normalized.append(row)
    return normalized


def _yaml_scalar(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in [":", "#", "{", "}", "[", "]", "\n"]):
        return json.dumps(text, ensure_ascii=False)
    return text


def _yaml_dump(value: Any, *, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_yaml_dump(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines) if lines else f"{prefix}{{}}"
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_yaml_dump(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def _parse_cpu_to_mcores(value: str) -> float:
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    if text.endswith("n"):
        return float(text[:-1] or 0) / 1_000_000.0
    if text.endswith("u"):
        return float(text[:-1] or 0) / 1_000.0
    if text.endswith("m"):
        return float(text[:-1] or 0)
    return float(text) * 1000.0


def _parse_memory_to_mib(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    units = {
        "Ki": 1 / 1024.0,
        "Mi": 1.0,
        "Gi": 1024.0,
        "Ti": 1024.0 * 1024.0,
        "K": 1 / (1024.0 * 1024.0),
        "M": 1 / 1024.0,
        "G": 1.0,
    }
    for suffix, factor in units.items():
        if text.endswith(suffix):
            return float(text.removesuffix(suffix) or 0) * factor
    return float(text) / (1024.0 * 1024.0)


def _real_ocp_pod_metrics_payload(root_dir: Path) -> dict[str, Any]:
    namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
    return _real_ocp_request_json(root_dir, f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods")


def _connection_metrics_summary(
    root_dir: Path,
    state: dict[str, Any],
    connection: dict[str, Any],
    namespace: str,
) -> dict[str, Any]:
    pod_cpu_top: list[dict[str, Any]] = []
    pod_memory_top: list[dict[str, Any]] = []
    if _is_real_ocp_connection(root_dir, connection):
        try:
            metrics_payload = _real_ocp_pod_metrics_payload(root_dir)
            metric_items = metrics_payload.get("items")
            for item in metric_items if isinstance(metric_items, list) else []:
                if not isinstance(item, dict):
                    continue
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                containers = item.get("containers") if isinstance(item.get("containers"), list) else []
                cpu_total = 0.0
                memory_total = 0.0
                for container in containers:
                    if not isinstance(container, dict):
                        continue
                    usage = container.get("usage") if isinstance(container.get("usage"), dict) else {}
                    cpu_total += _parse_cpu_to_mcores(str(usage.get("cpu") or "0"))
                    memory_total += _parse_memory_to_mib(str(usage.get("memory") or "0"))
                pod_cpu_top.append({"name": str(metadata.get("name") or ""), "cpu_mcores": round(cpu_total, 1)})
                pod_memory_top.append({"name": str(metadata.get("name") or ""), "memory_mib": round(memory_total, 1)})
        except Exception:  # noqa: BLE001
            pod_cpu_top = []
            pod_memory_top = []
    pod_cpu_top.sort(key=lambda item: float(item.get("cpu_mcores") or 0), reverse=True)
    pod_memory_top.sort(key=lambda item: float(item.get("memory_mib") or 0), reverse=True)
    deployments = _connection_resource_items(root_dir, state, connection, "deployments", namespace)
    events = _connection_resource_items(root_dir, state, connection, "events", namespace)
    workload_health = [
        {
            "kind": "Deployment",
            "name": str(item.get("name") or ""),
            "ready_replicas": int(item.get("ready_replicas") or 0),
            "replicas": int(item.get("replicas") or 0),
            "status": "degraded",
        }
        for item in deployments
        if int(item.get("ready_replicas") or 0) < int(item.get("replicas") or 0)
    ][:10]
    warning_events = [
        {
            "name": str(item.get("name") or ""),
            "phase": str(item.get("phase") or ""),
        }
        for item in events
        if str(item.get("phase") or "").strip().lower() == "warning"
    ]
    return {
        "connection_id": str(connection.get("connection_id") or ""),
        "namespace": namespace,
        "window": "15m",
        "source": {
            "provider": "metrics.k8s.io+kube-api" if _is_real_ocp_connection(root_dir, connection) else "simulated",
            "live": _is_real_ocp_connection(root_dir, connection),
        },
        "summary": {
            "warning_events": len(warning_events),
            "degraded_deployments": len(workload_health),
            "top_cpu_pod": pod_cpu_top[0] if pod_cpu_top else None,
            "top_memory_pod": pod_memory_top[0] if pod_memory_top else None,
        },
        "pod_cpu_top": pod_cpu_top[:5],
        "pod_memory_top": pod_memory_top[:5],
        "workload_health": workload_health,
        "event_summary": warning_events[:10],
    }


def _sample_connection_inventory(default_namespace: str) -> dict[str, Any]:
    namespace = str(default_namespace or "default").strip() or "default"
    timestamp = _now_iso()
    inventory = {
        "namespaces": [namespace, "payments", "openshift-monitoring", "openshift-ingress"],
        "resources": {
            "pods": [
                {
                    "name": "payments-api-66f9f4d6f5-k8xbx",
                    "namespace": "payments",
                    "kind": "Pod",
                    "created_at": timestamp,
                    "phase": "Running",
                    "node_name": "worker-0",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "metadata": {"name": "payments-api-66f9f4d6f5-k8xbx", "namespace": "payments"},
                        "spec": {"nodeName": "worker-0"},
                        "status": {"phase": "Running"},
                    },
                },
                {
                    "name": "console-84c9fd97f4-wr5m8",
                    "namespace": namespace,
                    "kind": "Pod",
                    "created_at": timestamp,
                    "phase": "Pending",
                    "node_name": "worker-1",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "metadata": {"name": "console-84c9fd97f4-wr5m8", "namespace": namespace},
                        "spec": {"nodeName": "worker-1"},
                        "status": {"phase": "Pending"},
                    },
                },
            ],
            "deployments": [
                {
                    "name": "payments-api",
                    "namespace": "payments",
                    "kind": "Deployment",
                    "created_at": timestamp,
                    "ready_replicas": 1,
                    "replicas": 3,
                    "manifest_json": {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "metadata": {"name": "payments-api", "namespace": "payments"},
                        "spec": {"replicas": 3, "template": {"spec": {"containers": [{"name": "api", "image": "quay.io/demo/payments-api:v2.4.1"}]}}},
                        "status": {"readyReplicas": 1, "replicas": 3},
                    },
                },
                {
                    "name": "ops-console",
                    "namespace": namespace,
                    "kind": "Deployment",
                    "created_at": timestamp,
                    "ready_replicas": 2,
                    "replicas": 2,
                    "manifest_json": {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "metadata": {"name": "ops-console", "namespace": namespace},
                        "spec": {"replicas": 2, "template": {"spec": {"containers": [{"name": "web", "image": "quay.io/demo/ops-console:v1.2.0"}]}}},
                        "status": {"readyReplicas": 2, "replicas": 2},
                    },
                },
            ],
            "services": [
                {
                    "name": "payments-api",
                    "namespace": "payments",
                    "kind": "Service",
                    "created_at": timestamp,
                    "type": "ClusterIP",
                    "cluster_ip": "172.30.40.18",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "metadata": {"name": "payments-api", "namespace": "payments"},
                        "spec": {"type": "ClusterIP", "clusterIP": "172.30.40.18", "ports": [{"port": 8080}]},
                    },
                },
                {
                    "name": "ops-console",
                    "namespace": namespace,
                    "kind": "Service",
                    "created_at": timestamp,
                    "type": "ClusterIP",
                    "cluster_ip": "172.30.90.14",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "metadata": {"name": "ops-console", "namespace": namespace},
                        "spec": {"type": "ClusterIP", "clusterIP": "172.30.90.14", "ports": [{"port": 3000}]},
                    },
                },
            ],
            "routes": [
                {
                    "name": "payments-api",
                    "namespace": "payments",
                    "kind": "Route",
                    "created_at": timestamp,
                    "host": "payments.apps.cluster.example.com",
                    "to": "payments-api",
                    "manifest_json": {
                        "apiVersion": "route.openshift.io/v1",
                        "kind": "Route",
                        "metadata": {"name": "payments-api", "namespace": "payments"},
                        "spec": {"host": "payments.apps.cluster.example.com", "to": {"kind": "Service", "name": "payments-api"}},
                    },
                },
                {
                    "name": "ops-console",
                    "namespace": namespace,
                    "kind": "Route",
                    "created_at": timestamp,
                    "host": "ops-console.apps.cluster.example.com",
                    "to": "ops-console",
                    "manifest_json": {
                        "apiVersion": "route.openshift.io/v1",
                        "kind": "Route",
                        "metadata": {"name": "ops-console", "namespace": namespace},
                        "spec": {"host": "ops-console.apps.cluster.example.com", "to": {"kind": "Service", "name": "ops-console"}},
                    },
                },
            ],
            "events": [
                {
                    "name": "payments-api.182b4e18fbf1",
                    "namespace": "payments",
                    "kind": "Event",
                    "created_at": timestamp,
                    "phase": "Warning",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Event",
                        "metadata": {"name": "payments-api.182b4e18fbf1", "namespace": "payments"},
                        "reason": "ScalingReplicaSet",
                        "message": "Scaled up replica set payments-api-66f9f4d6f5 to 3",
                        "type": "Warning",
                    },
                },
                {
                    "name": "ops-console.182b4e18fbf2",
                    "namespace": namespace,
                    "kind": "Event",
                    "created_at": timestamp,
                    "phase": "Normal",
                    "manifest_json": {
                        "apiVersion": "v1",
                        "kind": "Event",
                        "metadata": {"name": "ops-console.182b4e18fbf2", "namespace": namespace},
                        "reason": "Started",
                        "message": "Started container web",
                        "type": "Normal",
                    },
                },
            ],
        },
    }
    for resource_type in RESOURCE_TYPES:
        for item in inventory["resources"][resource_type]:
            item["manifest_yaml"] = _yaml_dump(item["manifest_json"])
    return inventory


def _ensure_connection_inventory(state: dict[str, Any], connection_id: str, default_namespace: str) -> dict[str, Any]:
    inventory = state["connection_inventory"].get(connection_id)
    if isinstance(inventory, dict):
        return inventory
    inventory = _sample_connection_inventory(default_namespace)
    state["connection_inventory"][connection_id] = inventory
    return inventory


def _find_by_id(rows: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get(key) or "").strip() == value:
            return row
    return None


def _require_workspace(state: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    workspace = _find_by_id(state["workspaces"], "workspace_id", workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")
    return workspace


def _require_connection(state: dict[str, Any], connection_id: str) -> dict[str, Any]:
    connection = _find_by_id(state["connections"], "connection_id", connection_id)
    if connection is None:
        raise ValueError("Connection not found")
    return connection


def _resource_summary(resource_type: str, item: dict[str, Any]) -> dict[str, Any]:
    base = {
        "name": str(item.get("name") or ""),
        "namespace": str(item.get("namespace") or ""),
        "kind": str(item.get("kind") or RESOURCE_KIND_LABELS.get(resource_type, "")),
        "created_at": str(item.get("created_at") or ""),
        "resource_type": resource_type,
    }
    if resource_type == "pods":
        base.update(
            {
                "phase": str(item.get("phase") or ""),
                "node_name": str(item.get("node_name") or ""),
            }
        )
    elif resource_type == "deployments":
        base.update(
            {
                "ready_replicas": int(item.get("ready_replicas") or 0),
                "replicas": int(item.get("replicas") or 0),
            }
        )
    elif resource_type == "services":
        base.update(
            {
                "type": str(item.get("type") or ""),
                "cluster_ip": str(item.get("cluster_ip") or ""),
            }
        )
    elif resource_type == "routes":
        base.update(
            {
                "host": str(item.get("host") or ""),
                "to": str(item.get("to") or ""),
            }
        )
    elif resource_type == "events":
        base.update(
            {
                "phase": str(item.get("phase") or ""),
            }
        )
    return base


def _connection_namespace(connection: dict[str, Any], requested_namespace: str) -> str:
    namespace = str(requested_namespace or "").strip()
    if namespace:
        return namespace
    return str(connection.get("default_namespace") or "default").strip() or "default"


def _resource_api_path(resource_type: str, namespace: str, name: str = "") -> str:
    encoded_name = f"/{name}" if name else ""
    if resource_type == "pods":
        return f"/api/v1/namespaces/{namespace}/pods{encoded_name}"
    if resource_type == "deployments":
        return f"/apis/apps/v1/namespaces/{namespace}/deployments{encoded_name}"
    if resource_type == "services":
        return f"/api/v1/namespaces/{namespace}/services{encoded_name}"
    if resource_type == "routes":
        return f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes{encoded_name}"
    if resource_type == "events":
        return f"/api/v1/namespaces/{namespace}/events{encoded_name}"
    raise ValueError("Unsupported resource type")


def _connection_resource_items(
    root_dir: Path,
    state: dict[str, Any],
    connection: dict[str, Any],
    resource_type: str,
    namespace: str,
) -> list[dict[str, Any]]:
    if _is_real_ocp_connection(root_dir, connection):
        return _real_ocp_items(resource_type, _real_ocp_resources_payload(root_dir, resource_type))
    inventory = _ensure_connection_inventory(state, str(connection.get("connection_id") or ""), str(connection.get("default_namespace") or "default"))
    return [
        item for item in inventory["resources"][resource_type]
        if str(item.get("namespace") or "").strip() == namespace
    ]


def _connection_resource_detail(
    root_dir: Path,
    state: dict[str, Any],
    connection: dict[str, Any],
    resource_type: str,
    namespace: str,
    name: str,
) -> dict[str, Any] | None:
    if _is_real_ocp_connection(root_dir, connection):
        payload = _real_ocp_resource_detail_payload(root_dir, resource_type, name)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        return {
            "name": str(metadata.get("name") or name),
            "namespace": str(metadata.get("namespace") or namespace),
            "kind": str(payload.get("kind") or RESOURCE_KIND_LABELS.get(resource_type, "")),
            "created_at": str(metadata.get("creationTimestamp") or ""),
            "resource_type": resource_type,
            "manifest_json": payload,
            "manifest_yaml": _yaml_dump(payload),
        }
    inventory = _ensure_connection_inventory(state, str(connection.get("connection_id") or ""), str(connection.get("default_namespace") or "default"))
    return next(
        (
            item for item in inventory["resources"].get(resource_type, [])
            if str(item.get("namespace") or "").strip() == namespace and str(item.get("name") or "").strip() == name
        ),
        None,
    )


def _normalize_ops_query(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _detect_resource_type(query: str) -> str | None:
    normalized = _normalize_ops_query(query)
    best_type = None
    best_score = 0
    for resource_type, keywords in RESOURCE_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in normalized)
        if score > best_score:
            best_score = score
            best_type = resource_type
    return best_type


def _resolve_named_resource(query: str, resource_groups: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]] | None:
    normalized = _normalize_ops_query(query)
    for resource_type, items in resource_groups.items():
        for item in items:
            name = str(item.get("name") or "").strip().lower()
            if name and name in normalized:
                return resource_type, item
    return None


def _infer_manifest_resource_type(manifest_yaml: str, fallback: str = "deployments") -> str:
    match = re.search(r"^\s*kind:\s*([A-Za-z]+)\s*$", str(manifest_yaml or ""), flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return fallback
    kind = match.group(1).strip().lower()
    if kind == "pod":
        return "pods"
    if kind == "deployment":
        return "deployments"
    if kind == "service":
        return "services"
    if kind == "route":
        return "routes"
    if kind == "event":
        return "events"
    return fallback


def _classify_ops_chat_intent(
    root_dir: Path,
    state: dict[str, Any],
    connection: dict[str, Any],
    query: str,
    namespace: str,
) -> dict[str, Any] | None:
    normalized = _normalize_ops_query(query)
    explicit_resource_type = _detect_resource_type(normalized)
    resource_groups: dict[str, list[dict[str, Any]]] = {}
    if explicit_resource_type:
        resource_groups[explicit_resource_type] = _connection_resource_items(root_dir, state, connection, explicit_resource_type, namespace)
    else:
        for resource_type in RESOURCE_TYPES:
            resource_groups[resource_type] = _connection_resource_items(root_dir, state, connection, resource_type, namespace)
    named_resource = _resolve_named_resource(normalized, resource_groups)
    resource_type = explicit_resource_type or (named_resource[0] if named_resource else None)
    if resource_type is None:
        return None
    list_score = sum(1 for token in LIST_INTENT_TERMS if token in normalized)
    detail_score = sum(1 for token in DETAIL_INTENT_TERMS if token in normalized)
    edit_score = sum(1 for token in EDIT_INTENT_TERMS if token in normalized)
    if named_resource and edit_score > 0:
        action = "edit"
    elif named_resource and detail_score > 0:
        action = "detail"
    elif named_resource and list_score == 0:
        action = "detail"
    elif edit_score > 0:
        action = "edit"
    elif detail_score > 0:
        action = "detail"
    else:
        action = "list"
    return {
        "resource_type": resource_type,
        "action": action,
        "resource_groups": resource_groups,
        "resource_name": str(named_resource[1].get("name") or "") if named_resource else "",
    }


def _recommendations_for_connection(
    *,
    root_dir: Path,
    state: dict[str, Any],
    workspace_id: str,
    connection_id: str,
) -> list[dict[str, Any]]:
    connection = _require_connection(state, connection_id)
    if _is_real_ocp_connection(root_dir, connection):
        deployments = _real_ocp_items("deployments", _real_ocp_resources_payload(root_dir, "deployments"))
    else:
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        deployments = inventory["resources"]["deployments"]
    recommendations: list[dict[str, Any]] = []
    for deployment in deployments:
        ready = int(deployment.get("ready_replicas") or 0)
        replicas = int(deployment.get("replicas") or 0)
        if ready < replicas:
            recommendations.append(
                {
                    "recommendation_id": _make_id("reco"),
                    "workspace_id": workspace_id,
                    "connection_id": connection_id,
                    "namespace": str(deployment.get("namespace") or ""),
                    "resource_kind": "Deployment",
                    "resource_name": str(deployment.get("name") or ""),
                    "recommendation_type": "deployment_health",
                    "risk_level": "high",
                    "summary": f"{deployment.get('name')} has only {ready}/{replicas} ready replicas.",
                    "rationale": "Ready replica count is lower than desired replicas.",
                    "created_at": _now_iso(),
                }
            )
    if not recommendations:
        recommendations.append(
            {
                "recommendation_id": _make_id("reco"),
                "workspace_id": workspace_id,
                "connection_id": connection_id,
                "namespace": str(connection.get("default_namespace") or "default"),
                "resource_kind": "Cluster",
                "resource_name": str(connection.get("display_name") or connection_id),
                "recommendation_type": "cluster_info",
                "risk_level": "info",
                "summary": "No urgent deployment health issues detected.",
                "rationale": "All sampled deployments match their desired replica counts.",
                "created_at": _now_iso(),
            }
        )
    return recommendations


def _store_recommendations(root_dir: Path, state: dict[str, Any], workspace_id: str, connection_id: str) -> list[dict[str, Any]]:
    state["recommendations"] = [
        item
        for item in state["recommendations"]
        if str(item.get("workspace_id") or "").strip() != workspace_id
    ]
    recommendations = _recommendations_for_connection(root_dir=root_dir, state=state, workspace_id=workspace_id, connection_id=connection_id)
    state["recommendations"].extend(recommendations)
    return recommendations


def _document_root(root_dir: Path) -> Path:
    return root_dir / "data" / "gold_manualbook_ko" / "playbooks"


def _iter_document_rows(root_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    document_root = _document_root(root_dir)
    if not document_root.exists():
        return rows
    for path in sorted(document_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(payload, dict):
            continue
        sections = payload.get("sections")
        section_rows = sections if isinstance(sections, list) else []
        rows.append(
            {
                "document_key": path.stem,
                "title": str(payload.get("title") or path.stem),
                "relative_path": str(path.relative_to(root_dir)).replace("\\", "/"),
                "source_type": str(((payload.get("source_metadata") or {}) if isinstance(payload.get("source_metadata"), dict) else {}).get("source_type") or "playbook_document"),
                "group": str(payload.get("pack_id") or "official_ocp"),
                "indexed": True,
                "chunk_count": len(section_rows),
                "original_kind": "json",
                "original_key": path.name,
                "description": str(payload.get("source_uri") or payload.get("translation_source_uri") or ""),
                "path": path,
                "payload": payload,
            }
        )
    return rows


def _flatten_block_text(block: dict[str, Any]) -> str:
    if not isinstance(block, dict):
        return ""
    if str(block.get("kind") or "").strip() == "code":
        return str(block.get("code") or "").strip()
    return str(block.get("text") or block.get("caption") or "").strip()


def _document_chunks(document_row: dict[str, Any]) -> list[dict[str, Any]]:
    payload = document_row["payload"]
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return []
    chunks: list[dict[str, Any]] = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        blocks = section.get("blocks")
        block_rows = [item for item in blocks if isinstance(item, dict)] if isinstance(blocks, list) else []
        preview = " ".join(filter(None, (_flatten_block_text(block) for block in block_rows))).strip()
        chunks.append(
            {
                "chunk_id": str(section.get("anchor") or section.get("section_id") or f"chunk-{index}"),
                "chunk_order": index,
                "page_number": index,
                "section_title": str(section.get("heading") or f"Section {index}"),
                "block_types": [str(block.get("kind") or "") for block in block_rows if str(block.get("kind") or "").strip()],
                "preview_text": preview[:320],
                "viewer_path": str(section.get("viewer_path") or ""),
                "section_path": [str(item) for item in (section.get("section_path") or []) if str(item).strip()],
                "blocks": block_rows,
            }
        )
    return chunks


def _document_content(document_row: dict[str, Any]) -> str:
    lines = [f"# {document_row['title']}"]
    for chunk in _document_chunks(document_row)[:80]:
        lines.append("")
        lines.append(f"## {chunk['section_title']}")
        preview = str(chunk.get("preview_text") or "").strip()
        if preview:
            lines.append(preview)
    return "\n".join(lines).strip()


def _document_summary_payload(root_dir: Path, workspace_id: str) -> dict[str, Any]:
    rows = _iter_document_rows(root_dir)
    chunk_total = sum(int(row.get("chunk_count") or 0) for row in rows)
    summary: dict[str, Any] = {}
    manualbook_rows: list[dict[str, Any]] = []
    try:
        from play_book_studio.app.data_control_room import build_data_control_room_payload

        control_room_payload = build_data_control_room_payload(root_dir)
        summary = control_room_payload.get("summary") if isinstance(control_room_payload.get("summary"), dict) else {}
        manualbooks = control_room_payload.get("manualbooks") if isinstance(control_room_payload.get("manualbooks"), dict) else {}
        manualbook_rows = manualbooks.get("books") if isinstance(manualbooks.get("books"), list) else []
    except Exception:  # noqa: BLE001
        summary = {}
        manualbook_rows = []
    return {
        "workspace_id": workspace_id,
        "source_root": str(_document_root(root_dir)),
        "extract_root": str(root_dir / "data" / "gold_manualbook_ko"),
        "corpus_files": int(summary.get("known_book_count") or len(rows)),
        "manifest_entries": int(summary.get("known_book_count") or len(rows)),
        "extracted_artifacts": int(summary.get("manualbook_count") or len(rows)),
        "indexed_documents": int(summary.get("manualbook_count") or len(rows)),
        "indexed_chunks": int(summary.get("chunk_count") or chunk_total),
        "batch_jobs": int(summary.get("active_queue_count") or 0),
        "latest_batch_status": "idle",
        "source_breakdown": {
            "playbook_document": len(rows),
            "approved_runtime_books": len(manualbook_rows),
        },
        "indexed_samples": [str(item.get("book_slug") or "") for item in manualbook_rows[:5] if str(item.get("book_slug") or "").strip()] or [row["document_key"] for row in rows[:5]],
        "message": "Loaded from current runtime data-control-room summary." if summary else "Loaded from local playbook corpus.",
    }


def _search_match_score(query: str, document_row: dict[str, Any]) -> int:
    tokens = [token for token in re.split(r"[^\w가-힣]+", query.lower()) if len(token) > 1]
    if not tokens:
        return 0
    haystack = " ".join(
        [
            str(document_row.get("document_key") or "").lower(),
            str(document_row.get("title") or "").lower(),
            _document_content(document_row).lower()[:4000],
        ]
    )
    score = 0
    for token in tokens:
        if token in haystack:
            score += 1
        if token in str(document_row.get("title") or "").lower():
            score += 2
        if token in str(document_row.get("document_key") or "").lower():
            score += 2
    return score


def _preview_lines(text: str, *, count: int = 8) -> list[str]:
    return [line for line in str(text or "").splitlines()[:count]]


def _docs_preview_payload(root_dir: Path, source_path: str, chunk_id: str) -> dict[str, Any]:
    target_path = (root_dir / source_path).resolve()
    if not target_path.exists() or root_dir.resolve() not in target_path.parents:
        raise FileNotFoundError(source_path)
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid document payload")
    title = str(payload.get("title") or target_path.stem)
    sections = payload.get("sections")
    section_rows = [item for item in sections if isinstance(item, dict)] if isinstance(sections, list) else []
    match = next(
        (
            item for item in section_rows
            if str(item.get("anchor") or item.get("section_id") or "").strip() == chunk_id
        ),
        section_rows[0] if section_rows else None,
    )
    if not isinstance(match, dict):
        raise ValueError("Chunk not found")
    preview_text = " ".join(
        filter(
            None,
            (_flatten_block_text(block) for block in (match.get("blocks") or []) if isinstance(block, dict)),
        )
    ).strip()
    lines = _preview_lines(preview_text)
    return {
        "source_path": str(target_path),
        "relative_source_path": str(target_path.relative_to(root_dir)).replace("\\", "/"),
        "repo_relative_path": str(target_path.relative_to(root_dir)).replace("\\", "/"),
        "repo_locator": str(target_path.relative_to(root_dir)).replace("\\", "/"),
        "file_name": target_path.name,
        "chunk_id": str(match.get("anchor") or match.get("section_id") or ""),
        "source_type": str(((payload.get("source_metadata") or {}) if isinstance(payload.get("source_metadata"), dict) else {}).get("source_type") or "playbook_document"),
        "title": title,
        "section_title": str(match.get("heading") or ""),
        "section_path": [str(item) for item in (match.get("section_path") or []) if str(item).strip()],
        "page_number": 1,
        "line_start": 1,
        "line_end": len(lines),
        "snippet": "\n".join(lines),
        "lines": lines,
    }


def _chat_payload(root_dir: Path, payload: dict[str, Any], *, state: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("message") or "").strip()
    connection_id = str(payload.get("connection_id") or "").strip()
    if not query:
        raise ValueError("message is required")
    live_mode = bool(connection_id)
    response: dict[str, Any] = {
        "lane": "live" if live_mode else "rag",
        "mode": "hybrid" if connection_id else "docs",
        "fallback_used": False,
        "preview_ready": False,
        "answer": "",
        "sources": [],
        "artifacts": [],
        "citation_map": {},
    }
    if live_mode:
        connection = _require_connection(state, connection_id)
        namespace = _connection_namespace(connection, str(payload.get("namespace") or "").strip())
        intent = _classify_ops_chat_intent(root_dir, state, connection, query, namespace)
        if intent is not None:
            resource_type = str(intent.get("resource_type") or "")
            action = str(intent.get("action") or "list")
            resource_name = str(intent.get("resource_name") or "")
            resource_groups = intent.get("resource_groups") if isinstance(intent.get("resource_groups"), dict) else {}
            items = [_resource_summary(resource_type, item) for item in resource_groups.get(resource_type, [])]
            if action == "list":
                response["answer"] = (
                    f"{namespace} 네임스페이스에서 {RESOURCE_KIND_LABELS.get(resource_type, resource_type)} {len(items)}건을 찾았습니다. "
                    "원하는 리소스를 열어 상세 YAML을 확인하거나, 편집 가능한 리소스는 바로 YAML editor로 이어갈 수 있습니다."
                )
                response["artifacts"] = [
                    {
                        "kind": "resource_list",
                        "title": f"{RESOURCE_KIND_LABELS.get(resource_type, resource_type)} list in {namespace}",
                        "connection_id": connection_id,
                        "resource_type": resource_type,
                        "namespace": namespace,
                        "editable": resource_type in EDITABLE_RESOURCE_TYPES,
                        "total_count": len(items),
                        "items": items[:20],
                    }
                ]
                response["preview_ready"] = bool(items)
                return response
            if resource_name:
                detail = _connection_resource_detail(root_dir, state, connection, resource_type, namespace, resource_name)
                if detail is not None:
                    response["answer"] = (
                        f"{resource_name} {RESOURCE_KIND_LABELS.get(resource_type, resource_type)}를 찾았습니다. "
                        f"{'YAML 편집이 가능한 리소스입니다.' if resource_type in EDITABLE_RESOURCE_TYPES else '상세 YAML 확인 전용 리소스입니다.'}"
                    )
                    response["artifacts"] = [
                        {
                            "kind": "resource_editor" if resource_type in EDITABLE_RESOURCE_TYPES else "resource_detail",
                            "title": f"{resource_name} · {RESOURCE_KIND_LABELS.get(resource_type, resource_type)}",
                            "connection_id": connection_id,
                            "resource_type": resource_type,
                            "namespace": namespace,
                            "name": resource_name,
                            "editable": resource_type in EDITABLE_RESOURCE_TYPES,
                            "summary": _resource_summary(resource_type, detail),
                            "manifest_preview": "\n".join(_preview_lines(str(detail.get("manifest_yaml") or ""), count=10)),
                            "items": [],
                        }
                    ]
                    response["preview_ready"] = True
                    return response
    if live_mode and False:
        connection = _require_connection(state, connection_id)
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        namespace_items = [
            item
            for resource_type in ("deployments", "pods", "services", "routes")
            for item in inventory["resources"][resource_type]
            if str(item.get("namespace") or "") == namespace
        ]
        response["answer"] = (
            f"{namespace} 네임스페이스 기준으로 샘플 라이브 리소스 {len(namespace_items)}건을 확인했습니다. "
            "배포/서비스/라우트 상태를 먼저 검토한 뒤 YAML 상세 보기로 이어갈 수 있습니다."
        )
        artifact_items = [_resource_summary("deployments", item) for item in inventory["resources"]["deployments"] if str(item.get("namespace") or "") == namespace]
        response["artifacts"] = [
            {
                "kind": "resource_list",
                "title": f"Deployments in {namespace}",
                "items": artifact_items,
            }
        ]
        response["preview_ready"] = bool(artifact_items)
        return response

    document_rows = _iter_document_rows(root_dir)
    ranked = [
        (score, row)
        for row in document_rows
        if (score := _search_match_score(query, row)) > 0
    ]
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("title") or "")))
    top_rows = [row for _, row in ranked[:3]]
    if not top_rows:
        response["answer"] = "로컬 플레이북에서 직접 매칭되는 문서를 찾지 못했습니다. 더 구체적인 OpenShift 주제나 리소스 이름으로 다시 질문해 주세요."
        return response
    answer_lines = ["관련 문서를 기준으로 우선 확인할 항목입니다."]
    for index, row in enumerate(top_rows, start=1):
        chunks = _document_chunks(row)
        first_chunk = chunks[0] if chunks else {}
        answer_lines.append(f"{index}. {row['title']} - {first_chunk.get('section_title') or 'overview'}")
        response["sources"].append(
            {
                "index": index,
                "source_path": row["relative_path"],
                "title": row["title"],
                "section_title": str(first_chunk.get("section_title") or ""),
                "viewer_path": str(first_chunk.get("viewer_path") or ""),
                "chunk_id": str(first_chunk.get("chunk_id") or ""),
            }
        )
    response["answer"] = "\n".join(answer_lines)
    response["citation_map"] = {
        str(source["index"]): source
        for source in response["sources"]
    }
    return response


def _action_preview_from_payload(root_dir: Path, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(payload.get("connection_id") or "").strip()
    action_type = str(payload.get("action_type") or "").strip()
    resource_type = str(payload.get("resource_type") or "").strip()
    resource_name = str(payload.get("resource_name") or "").strip()
    if action_type not in {"scale_deployment", "rollout_restart", "log_bundle", "yaml_apply"}:
        raise ValueError("Unsupported action type")
    connection = _require_connection(state, connection_id)
    namespace = _connection_namespace(connection, str(payload.get("namespace") or "").strip())
    risk_level = "medium"
    blocked_reasons: list[str] = []
    diff_unified = ""
    summary = f"{action_type} preview ready."
    if action_type == "scale_deployment":
        replicas = int(payload.get("replicas") or 0)
        deployment = _connection_resource_detail(root_dir, state, connection, "deployments", namespace, resource_name)
        if deployment is None:
            blocked_reasons.append("Target deployment not found.")
        else:
            current_replicas = int(deployment.get("replicas") or 0)
            diff_unified = "\n".join(
                difflib.unified_diff(
                    [f"replicas: {current_replicas}\n"],
                    [f"replicas: {replicas}\n"],
                    fromfile="before",
                    tofile="after",
                )
            )
            risk_level = "high" if abs(replicas - current_replicas) >= 2 else "medium"
            summary = f"Scale deployment {resource_name} from {current_replicas} to {replicas}."
    elif action_type == "yaml_apply":
        manifest_yaml = str(payload.get("manifest_yaml") or "").strip()
        target_type = resource_type or _infer_manifest_resource_type(manifest_yaml)
        target = _connection_resource_detail(root_dir, state, connection, target_type, namespace, resource_name)
        if target is None:
            blocked_reasons.append("Target resource not found.")
        else:
            diff_unified = "\n".join(
                difflib.unified_diff(
                    [line + "\n" for line in str(target.get("manifest_yaml") or "").splitlines()],
                    [line + "\n" for line in manifest_yaml.splitlines()],
                    fromfile="before",
                    tofile="after",
                )
            )
            risk_level = "high"
            summary = f"Apply YAML update to {resource_name}."
    elif action_type == "rollout_restart":
        deployment = _connection_resource_detail(root_dir, state, connection, "deployments", namespace, resource_name)
        if deployment is None:
            blocked_reasons.append("Target deployment not found.")
        else:
            summary = f"Restart rollout for {resource_name}."
    elif action_type == "log_bundle":
        summary = f"Collect log bundle for {resource_name}."
        risk_level = "low"
    allowed = not blocked_reasons
    return {
        "allowed": allowed,
        "risk_level": risk_level,
        "summary": summary,
        "preview_command": f"oc action {action_type} --namespace {namespace} --resource {resource_name}".strip(),
        "required_approvals": 1 if risk_level in {"medium", "high"} else 0,
        "approval_strategy": "single_operator" if risk_level in {"medium", "high"} else "none",
        "approval_rules": ["operator"] if risk_level in {"medium", "high"} else [],
        "policy_checks": ["simulated_preview"],
        "blocked_reasons": blocked_reasons,
        "validation_messages": [] if allowed else blocked_reasons,
        "diff_unified": diff_unified,
        "dry_run_status": "passed" if allowed else "blocked",
        "dry_run_messages": ["Preview generated locally."],
        "next_step": "create_request" if allowed and risk_level in {"medium", "high"} else "execute",
    }


def _append_audit(state: dict[str, Any], entry: dict[str, Any]) -> None:
    state["action_audit"].insert(0, entry)
    state["action_audit"] = state["action_audit"][:100]


def _execute_request(root_dir: Path, state: dict[str, Any], request_row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    preview = request_row.get("preview") if isinstance(request_row.get("preview"), dict) else {}
    action_type = str(preview.get("action_type") or request_row.get("action_type") or "")
    connection_id = str(request_row.get("connection_id") or "")
    namespace = str(request_row.get("namespace") or "")
    resource_name = str(request_row.get("resource_name") or "")
    resource_type = str(request_row.get("resource_type") or "")
    connection = _require_connection(state, connection_id)
    inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
    output_lines = [f"Simulated execution for {action_type}", f"namespace={namespace}", f"resource={resource_name}"]
    if _is_real_ocp_connection(root_dir, connection):
        if action_type == "scale_deployment":
            replicas = int(request_row.get("replicas") or 0)
            _real_ocp_request(
                root_dir,
                "PATCH",
                f"/apis/apps/v1/namespaces/{namespace}/deployments/{resource_name}/scale",
                raw_body=json.dumps({"spec": {"replicas": replicas}}, ensure_ascii=False),
                extra_headers={"Content-Type": "application/merge-patch+json"},
            )
            output_lines = [f"Scaled deployment {resource_name} to {replicas}", f"namespace={namespace}"]
        elif action_type == "yaml_apply":
            manifest_yaml = str(request_row.get("manifest_yaml") or "").strip()
            target_type = resource_type or _infer_manifest_resource_type(manifest_yaml)
            _real_ocp_request(
                root_dir,
                "PATCH",
                _resource_api_path(target_type, namespace, resource_name),
                raw_body=manifest_yaml,
                extra_headers={
                    "Content-Type": "application/apply-patch+yaml",
                    "Accept": "application/json",
                },
            )
            output_lines = [f"Applied YAML to {resource_name}", f"resource_type={target_type}", f"namespace={namespace}"]
        elif action_type == "rollout_restart":
            _real_ocp_request(
                root_dir,
                "PATCH",
                f"/apis/apps/v1/namespaces/{namespace}/deployments/{resource_name}",
                raw_body=json.dumps(
                    {
                        "spec": {
                            "template": {
                                "metadata": {
                                    "annotations": {
                                        "kubectl.kubernetes.io/restartedAt": _now_iso(),
                                    }
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                extra_headers={"Content-Type": "application/merge-patch+json"},
            )
            output_lines = [f"Restarted rollout for {resource_name}", f"namespace={namespace}"]
        elif action_type == "log_bundle":
            output_lines = [f"log_bundle is not implemented for real OCP execution", f"namespace={namespace}", f"resource={resource_name}"]
        execution = {
            "execution_id": _make_id("exec"),
            "request_id": request_row["request_id"],
            "status": "succeeded",
            "execution_mode": "live",
            "simulated": False,
            "summary": str(preview.get("summary") or "Execution completed."),
            "preflight_checks": ["live_connection"],
            "output_lines": output_lines,
            "error": "",
            "created_at": _now_iso(),
            "executed_by": str(payload.get("actor_id") or ""),
        }
        request_row["status"] = "executed"
        state["action_executions"].insert(0, execution)
        _append_audit(
            state,
            {
                "audit_id": _make_id("audit"),
                "request_id": request_row["request_id"],
                "execution_id": execution["execution_id"],
                "event_type": "executed",
                "summary": execution["summary"],
                "created_at": execution["created_at"],
            },
        )
        return execution
    if action_type == "scale_deployment":
        replicas = int(request_row.get("replicas") or 0)
        deployment = next(
            (
                item for item in inventory["resources"]["deployments"]
                if str(item.get("name") or "") == resource_name and str(item.get("namespace") or "") == namespace
            ),
            None,
        )
        if deployment is not None:
            deployment["replicas"] = replicas
            deployment["ready_replicas"] = min(replicas, max(replicas - 1, 1))
            deployment["manifest_json"]["spec"]["replicas"] = replicas
            deployment["manifest_json"]["status"]["replicas"] = replicas
            deployment["manifest_json"]["status"]["readyReplicas"] = deployment["ready_replicas"]
            deployment["manifest_yaml"] = _yaml_dump(deployment["manifest_json"])
            output_lines.append(f"Updated replicas to {replicas}")
    elif action_type == "yaml_apply":
        manifest_yaml = str(request_row.get("manifest_yaml") or "").strip()
        for editable_type in EDITABLE_RESOURCE_TYPES:
            target = next(
                (
                    item for item in inventory["resources"][editable_type]
                    if str(item.get("name") or "") == resource_name and str(item.get("namespace") or "") == namespace
                ),
                None,
            )
            if target is not None:
                target["manifest_yaml"] = manifest_yaml
                output_lines.append("Stored updated manifest YAML.")
                break
    elif action_type == "rollout_restart":
        output_lines.append("Rollout restart flag recorded.")
    elif action_type == "log_bundle":
        output_lines.append("Log bundle bundle://simulated-log-bundle.tar.gz created.")
    execution = {
        "execution_id": _make_id("exec"),
        "request_id": request_row["request_id"],
        "status": "succeeded",
        "execution_mode": "simulated",
        "simulated": True,
        "summary": str(preview.get("summary") or "Execution completed."),
        "preflight_checks": ["simulated_preview"],
        "output_lines": output_lines,
        "error": "",
        "created_at": _now_iso(),
        "executed_by": str(payload.get("actor_id") or ""),
    }
    request_row["status"] = "executed"
    state["action_executions"].insert(0, execution)
    _append_audit(
        state,
        {
            "audit_id": _make_id("audit"),
            "request_id": request_row["request_id"],
            "execution_id": execution["execution_id"],
            "event_type": "executed",
            "summary": execution["summary"],
            "created_at": execution["created_at"],
        },
    )
    return execution


def _send_json_created(handler: Any, payload: dict[str, Any]) -> None:
    handler._send_json(payload, HTTPStatus.CREATED)


def _send_not_found(handler: Any, message: str) -> None:
    handler._send_json({"error": message}, HTTPStatus.NOT_FOUND)


def _send_bad_request(handler: Any, message: str) -> None:
    handler._send_json({"error": message}, HTTPStatus.BAD_REQUEST)


def _stream_chat_result(handler: Any, result: dict[str, Any]) -> None:
    handler._start_ndjson_stream()
    handler._stream_event({"type": "stage", "stage": {"key": "retrieve", "label": "Retrieve", "detail": "Searching local playbook corpus", "status": "running"}})
    handler._stream_event({"type": "stage", "stage": {"key": "retrieve", "label": "Retrieve", "detail": "Candidates prepared", "status": "done"}})
    if str(result.get("answer") or "").strip():
        handler._stream_event({"type": "answer_delta", "delta": str(result.get("answer") or "")})
    handler._stream_event({"type": "result", "response": result})


def _redirect(handler: Any, location: str) -> None:
    body = f"Redirecting to {location}".encode("utf-8")
    handler.send_response(HTTPStatus.FOUND)
    handler.send_header("Location", location)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_ops_console_get(handler: Any, path: str, query: str, *, root_dir: Path) -> bool:
    state = _load_state(root_dir)
    if path == "/api/v1/workspaces":
        handler._send_json({"items": state["workspaces"]})
        return True

    recommendation_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/recommendations", path)
    if recommendation_match:
        workspace_id = recommendation_match.group(1)
        params = parse_qs(query, keep_blank_values=False)
        limit = int(str((params.get("limit") or ["10"])[0]).strip() or "10")
        items = [
            item for item in state["recommendations"]
            if str(item.get("workspace_id") or "").strip() == workspace_id
        ][: max(1, limit)]
        handler._send_json({"items": items})
        return True

    connection_status_match = re.fullmatch(r"/api/v1/auth/ocp/status/([^/]+)", path)
    if connection_status_match:
        connection_id = connection_status_match.group(1)
        connection = _find_by_id(state["connections"], "connection_id", connection_id)
        if connection is None:
            _send_not_found(handler, "Connection not found")
            return True
        handler._send_json(connection)
        return True

    if path == "/api/v1/auth/ocp/lease/status":
        handler._send_json(
            {
                "enabled": True,
                "running": True,
                "interval_seconds": 900,
                "last_run_at": _now_iso(),
                "last_success_at": _now_iso(),
                "last_failure_at": "",
                "last_error": "",
                "consecutive_failures": 0,
                "profiles_checked": len(state["connections"]),
                "renewals_applied": len(state["connections"]),
                "recent_failures": [],
            }
        )
        return True

    if path == "/api/v1/scm/providers/status":
        handler._send_json(_scm_provider_status(root_dir))
        return True

    if path == "/api/v1/auth/ocp/profiles":
        params = parse_qs(query, keep_blank_values=False)
        workspace_id = str((params.get("workspace_id") or [""])[0]).strip()
        items = [
            item for item in state["connections"]
            if not workspace_id or str(item.get("workspace_id") or "").strip() == workspace_id
        ]
        handler._send_json({"items": items})
        return True

    overview_match = re.fullmatch(r"/api/v1/ocp/overview/([^/]+)", path)
    if overview_match:
        connection_id = overview_match.group(1)
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        if _is_real_ocp_connection(root_dir, connection):
            namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
            counts: dict[str, int] = {}
            try:
                for resource_type in RESOURCE_TYPES:
                    counts[resource_type] = len(_real_ocp_items(resource_type, _real_ocp_resources_payload(root_dir, resource_type)))
            except Exception as exc:  # noqa: BLE001
                handler._send_json({"error": f"Real OCP overview failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
                return True
            handler._send_json(
                {
                    "connection_id": connection_id,
                    "cluster_url": connection["cluster_url"],
                    "default_namespace": namespace,
                    "namespace_count": 1,
                    "namespace_sample": [namespace],
                    "resource_counts": counts,
                    "message": "Loaded from configured OCP API.",
                }
            )
            return True
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        handler._send_json(
            {
                "connection_id": connection_id,
                "cluster_url": connection["cluster_url"],
                "default_namespace": connection["default_namespace"],
                "namespace_count": len(inventory["namespaces"]),
                "namespace_sample": inventory["namespaces"][:4],
                "resource_counts": {
                    resource_type: len(inventory["resources"][resource_type])
                    for resource_type in RESOURCE_TYPES
                },
                "message": "Simulated OCP overview generated from local inventory.",
            }
        )
        return True

    namespace_match = re.fullmatch(r"/api/v1/ocp/namespaces/([^/]+)", path)
    if namespace_match:
        connection_id = namespace_match.group(1)
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        if _is_real_ocp_connection(root_dir, connection):
            namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
            handler._send_json(
                {
                    "connection_id": connection_id,
                    "cluster_url": connection["cluster_url"],
                    "count": 1,
                    "items": [namespace],
                }
            )
            return True
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        handler._send_json(
            {
                "connection_id": connection_id,
                "cluster_url": connection["cluster_url"],
                "count": len(inventory["namespaces"]),
                "items": inventory["namespaces"],
            }
        )
        return True

    metrics_match = re.fullmatch(r"/api/v1/ocp/metrics/([^/]+)", path)
    if metrics_match:
        connection_id = metrics_match.group(1)
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        params = parse_qs(query, keep_blank_values=False)
        namespace = _connection_namespace(connection, str((params.get("namespace") or [""])[0]).strip())
        try:
            payload = _connection_metrics_summary(root_dir, state, connection, namespace)
        except Exception as exc:  # noqa: BLE001
            handler._send_json({"error": f"Metric summary failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
            return True
        handler._send_json(payload)
        return True

    resource_list_match = re.fullmatch(r"/api/v1/ocp/resources(?:/([^/]+))?", path)
    if resource_list_match:
        params = parse_qs(query, keep_blank_values=False)
        connection_id = resource_list_match.group(1) or str((params.get("connection_id") or [""])[0]).strip()
        resource_type = str((params.get("resource") or ["pods"])[0]).strip()
        namespace = str((params.get("namespace") or ["default"])[0]).strip()
        if not connection_id:
            _send_bad_request(handler, "connection_id is required")
            return True
        if resource_type not in RESOURCE_TYPES:
            _send_bad_request(handler, "Unsupported resource type")
            return True
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        if _is_real_ocp_connection(root_dir, connection):
            enforced_namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
            if namespace != enforced_namespace:
                _send_bad_request(handler, f"namespace is fixed to {enforced_namespace}")
                return True
            try:
                items = [_resource_summary(resource_type, item) for item in _real_ocp_items(resource_type, _real_ocp_resources_payload(root_dir, resource_type))]
            except Exception as exc:  # noqa: BLE001
                handler._send_json({"error": f"Real OCP resource list failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
                return True
            handler._send_json(
                {
                    "connection_id": connection_id,
                    "cluster_url": connection["cluster_url"],
                    "resource": resource_type,
                    "namespace": namespace,
                    "count": len(items),
                    "items": items,
                }
            )
            return True
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        items = [
            _resource_summary(resource_type, item)
            for item in inventory["resources"][resource_type]
            if str(item.get("namespace") or "").strip() == namespace
        ]
        handler._send_json(
            {
                "connection_id": connection_id,
                "cluster_url": connection["cluster_url"],
                "resource": resource_type,
                "namespace": namespace,
                "count": len(items),
                "items": items,
            }
        )
        return True

    resource_detail_match = re.fullmatch(r"/api/v1/ocp/resource-detail(?:/([^/]+))?", path)
    if resource_detail_match:
        params = parse_qs(query, keep_blank_values=False)
        connection_id = resource_detail_match.group(1) or str((params.get("connection_id") or [""])[0]).strip()
        resource_type = str((params.get("resource") or ["deployments"])[0]).strip()
        namespace = str((params.get("namespace") or ["default"])[0]).strip()
        name = str((params.get("name") or [""])[0]).strip()
        if not connection_id or not name:
            _send_bad_request(handler, "connection_id and name are required")
            return True
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        if _is_real_ocp_connection(root_dir, connection):
            enforced_namespace = (_real_ocp_config(root_dir) or {}).get("namespace", "demo")
            if namespace != enforced_namespace:
                _send_bad_request(handler, f"namespace is fixed to {enforced_namespace}")
                return True
            try:
                target = _real_ocp_resource_detail_payload(root_dir, resource_type, name)
            except Exception as exc:  # noqa: BLE001
                handler._send_json({"error": f"Real OCP resource detail failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
                return True
            handler._send_json(
                {
                    "connection_id": connection_id,
                    "cluster_url": connection["cluster_url"],
                    "resource": resource_type,
                    "namespace": namespace,
                    "name": name,
                    "kind": str(target.get("kind") or ""),
                    "manifest_yaml": _yaml_dump(target),
                    "manifest_json": target,
                }
            )
            return True
        inventory = _ensure_connection_inventory(state, connection_id, str(connection.get("default_namespace") or "default"))
        target = next(
            (
                item for item in inventory["resources"].get(resource_type, [])
                if str(item.get("namespace") or "").strip() == namespace and str(item.get("name") or "").strip() == name
            ),
            None,
        )
        if target is None:
            _send_not_found(handler, "Resource not found")
            return True
        handler._send_json(
            {
                "connection_id": connection_id,
                "cluster_url": connection["cluster_url"],
                "resource": resource_type,
                "namespace": namespace,
                "name": name,
                "kind": target["kind"],
                "manifest_yaml": target["manifest_yaml"],
                "manifest_json": target["manifest_json"],
            }
        )
        return True

    if path == "/api/v1/library/summary":
        params = parse_qs(query, keep_blank_values=False)
        workspace_id = str((params.get("workspace_id") or ["ws_default"])[0]).strip() or "ws_default"
        handler._send_json(_document_summary_payload(root_dir, workspace_id))
        return True

    if path == "/api/v1/library/catalog":
        params = parse_qs(query, keep_blank_values=False)
        del params
        rows = _iter_document_rows(root_dir)
        handler._send_json(
            {
                "items": [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"path", "payload"}
                    }
                    for row in rows[:120]
                ]
            }
        )
        return True

    if path == "/api/v1/library/chunks":
        params = parse_qs(query, keep_blank_values=False)
        document_key = str((params.get("document_key") or [""])[0]).strip()
        row = next((item for item in _iter_document_rows(root_dir) if item["document_key"] == document_key), None)
        if row is None:
            _send_not_found(handler, "Document not found")
            return True
        chunks = _document_chunks(row)
        handler._send_json(
            {
                "document_key": row["document_key"],
                "title": row["title"],
                "chunk_count": len(chunks),
                "chunks": [
                    {
                        key: value
                        for key, value in chunk.items()
                        if key not in {"blocks"}
                    }
                    for chunk in chunks
                ],
            }
        )
        return True

    if path == "/api/v1/library/document-content":
        params = parse_qs(query, keep_blank_values=False)
        document_key = str((params.get("document_key") or [""])[0]).strip()
        row = next((item for item in _iter_document_rows(root_dir) if item["document_key"] == document_key), None)
        if row is None:
            _send_not_found(handler, "Document not found")
            return True
        handler._send_json(
            {
                "workspace_id": str((params.get("workspace_id") or ["ws_default"])[0]).strip() or "ws_default",
                "document_key": row["document_key"],
                "title": row["title"],
                "content": _document_content(row),
            }
        )
        return True

    if path == "/api/v1/library/document-file":
        params = parse_qs(query, keep_blank_values=False)
        document_key = str((params.get("document_key") or [""])[0]).strip()
        row = next((item for item in _iter_document_rows(root_dir) if item["document_key"] == document_key), None)
        if row is None:
            _send_not_found(handler, "Document not found")
            return True
        body = row["path"].read_bytes()
        content_type = mimetypes.guess_type(str(row["path"]))[0] or "application/json"
        handler._send_bytes(body, content_type=content_type)
        return True

    batch_job_match = re.fullmatch(r"/api/v1/index/batch/jobs/([^/]+)", path)
    if batch_job_match:
        job_id = batch_job_match.group(1)
        job = _find_by_id(state["batch_jobs"], "job_id", job_id)
        if job is None:
            _send_not_found(handler, "Batch job not found")
            return True
        handler._send_json(job)
        return True

    if path == "/api/v1/index/batch/jobs":
        params = parse_qs(query, keep_blank_values=False)
        limit = int(str((params.get("limit") or ["10"])[0]).strip() or "10")
        handler._send_json({"items": state["batch_jobs"][: max(1, limit)]})
        return True

    if path == "/api/v1/docs-preview/snippet":
        params = parse_qs(query, keep_blank_values=False)
        source_path = str((params.get("source_path") or [""])[0]).strip()
        chunk_id = str((params.get("chunk_id") or [""])[0]).strip()
        if not source_path:
            _send_bad_request(handler, "source_path is required")
            return True
        try:
            payload = _docs_preview_payload(root_dir, source_path, chunk_id)
        except FileNotFoundError:
            _send_not_found(handler, "Source file not found")
            return True
        except ValueError as exc:
            _send_bad_request(handler, str(exc))
            return True
        handler._send_json(payload)
        return True

    if path == "/api/v1/actions/requests":
        params = parse_qs(query, keep_blank_values=False)
        limit = int(str((params.get("limit") or ["20"])[0]).strip() or "20")
        handler._send_json({"items": state["action_requests"][: max(1, limit)]})
        return True

    if path == "/api/v1/actions/executions":
        params = parse_qs(query, keep_blank_values=False)
        limit = int(str((params.get("limit") or ["20"])[0]).strip() or "20")
        handler._send_json({"items": state["action_executions"][: max(1, limit)]})
        return True

    if path == "/api/v1/actions/audit":
        params = parse_qs(query, keep_blank_values=False)
        limit = int(str((params.get("limit") or ["20"])[0]).strip() or "20")
        handler._send_json({"items": state["action_audit"][: max(1, limit)]})
        return True

    oauth_callback_match = re.fullmatch(r"/api/v1/oauth/([^/]+)/callback", path)
    if oauth_callback_match:
        provider = oauth_callback_match.group(1)
        params = parse_qs(query, keep_blank_values=False)
        state_token = str((params.get("state") or [""])[0]).strip()
        pending = next(
            (item for item in state["oauth_states"] if str(item.get("state") or "").strip() == state_token and str(item.get("provider") or "").strip() == provider),
            None,
        )
        if pending is None:
            _redirect(handler, f"/scm?oauth_status=error&provider={provider}&message=invalid_state")
            return True
        workspace_id = str(pending.get("workspace_id") or "").strip()
        scm_connection = {
            "scm_connection_id": _make_id("scm_conn"),
            "workspace_id": workspace_id,
            "provider": provider,
            "host_url": f"https://{provider}.com",
            "auth_type": "oauth",
            "account_label": f"{provider}-oauth",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        state["scm_connections"].insert(0, scm_connection)
        state["oauth_states"] = [
            item for item in state["oauth_states"]
            if str(item.get("state") or "").strip() != state_token
        ]
        _save_state(root_dir, state)
        _redirect(handler, f"/scm?oauth_status=connected&provider={provider}&connection_id={scm_connection['scm_connection_id']}")
        return True

    scm_connections_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/connections", path)
    if scm_connections_match:
        workspace_id = scm_connections_match.group(1)
        items = [item for item in state["scm_connections"] if str(item.get("workspace_id") or "").strip() == workspace_id]
        handler._send_json({"items": items})
        return True

    scm_repositories_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/repositories", path)
    if scm_repositories_match:
        workspace_id = scm_repositories_match.group(1)
        items = [item for item in state["scm_repositories"] if str(item.get("workspace_id") or "").strip() == workspace_id]
        handler._send_json({"items": items})
        return True

    return False


def handle_ops_console_post(handler: Any, path: str, query: str, payload: dict[str, Any], *, root_dir: Path) -> bool:
    state = _load_state(root_dir)
    if path == "/api/v1/workspaces":
        name = str(payload.get("name") or "").strip()
        if not name:
            _send_bad_request(handler, "name is required")
            return True
        workspace_id = _make_id("ws")
        now = _now_iso()
        record = {
            "workspace_id": workspace_id,
            "name": name,
            "slug": _slugify(payload.get("slug") or name),
            "industry": str(payload.get("industry") or "").strip(),
            "environment": str(payload.get("environment") or "dev").strip() or "dev",
            "created_at": now,
            "updated_at": now,
        }
        state["workspaces"].insert(0, record)
        state["models"][workspace_id] = _default_model_profile(workspace_id)
        _save_state(root_dir, state)
        _send_json_created(handler, record)
        return True

    if path == "/api/v1/auth/ocp/connect":
        workspace_id = str(payload.get("workspace_id") or "").strip() or "ws_default"
        real_config = _real_ocp_config(root_dir)
        auth_mode = "token" if real_config else str(payload.get("auth_mode") or "").strip() or "token"
        if auth_mode == "token" and not real_config and not str(payload.get("token") or "").strip():
            _send_bad_request(handler, "token is required when auth_mode=token")
            return True
        if not real_config and auth_mode == "password" and (not str(payload.get("username") or "").strip() or not str(payload.get("password") or "").strip()):
            _send_bad_request(handler, "username and password are required when auth_mode=password")
            return True
        now = _now_iso()
        connection = {
            "workspace_id": workspace_id,
            "connection_id": _make_id("conn"),
            "display_name": "managed-ocp-demo" if real_config else str(payload.get("display_name") or "cluster").strip() or "cluster",
            "cluster_url": real_config["base_url"] if real_config else str(payload.get("cluster_url") or "").strip() or "https://api.cluster.example.com:6443",
            "auth_mode": auth_mode,
            "verify_ssl": False,
            "default_namespace": "demo" if real_config else str(payload.get("default_namespace") or "default").strip() or "default",
            "username_hint": "rag-reader" if real_config else str(payload.get("username") or "developer").strip(),
            "secret_ref": "env://OCP_API_TOKEN" if real_config else f"vault://connections/{uuid.uuid4().hex[:8]}",
            "save_profile": bool(payload.get("save_profile", True)),
            "status": "connected",
            "last_verified_at": now,
            "expires_at": (datetime.now(UTC) + timedelta(hours=8)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        state["connections"].insert(0, connection)
        _ensure_connection_inventory(state, connection["connection_id"], connection["default_namespace"])
        _save_state(root_dir, state)
        _send_json_created(handler, {"connected": True, "connection": connection, "message": "Connection profile created."})
        return True

    if path == "/api/v1/auth/ocp/test" or path == "/api/v1/auth/ocp/lease/refresh":
        connection_id = str(payload.get("connection_id") or "").strip()
        try:
            connection = _require_connection(state, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        if _is_real_ocp_connection(root_dir, connection):
            try:
                user_payload = _real_ocp_request_json(root_dir, "/apis/user.openshift.io/v1/users/~")
                namespace_payload = _real_ocp_request_json(root_dir, "/api/v1/namespaces/demo")
            except Exception as exc:  # noqa: BLE001
                handler._send_json({"error": f"Real OCP connection test failed: {exc}"}, HTTPStatus.BAD_GATEWAY)
                return True
            result = {
                "success": True,
                "resolved_user": str(((user_payload.get("metadata") or {}) if isinstance(user_payload.get("metadata"), dict) else {}).get("name") or "rag-reader"),
                "resolved_groups": ["demo"],
                "resolved_roles": ["view", "read-demo"],
                "identity_source": "env-token",
                "permission_hints": ["Namespace access is fixed to demo."],
                "rbac_evidence": [f"namespace/demo ready: {str(namespace_payload.get('kind') or '')}"],
                "secret_backend": "env",
                "secret_lease_ttl_seconds": 28800,
                "secret_lease_expires_at": connection["expires_at"],
                "resolved_namespace": "demo",
                "expires_at": connection["expires_at"],
                "message": "Real OCP connection verified successfully.",
                "error": "",
            }
            connection["last_verified_at"] = _now_iso()
            _save_state(root_dir, state)
            handler._send_json(result)
            return True
        result = {
            "success": True,
            "resolved_user": str(connection.get("username_hint") or "developer"),
            "resolved_groups": ["cluster-admins", "system:authenticated"],
            "resolved_roles": ["cluster-admin", "edit"],
            "identity_source": connection["auth_mode"],
            "permission_hints": ["Can inspect deployments, services, routes"],
            "rbac_evidence": ["selfsubjectaccessreview: allowed"],
            "secret_backend": "vault-simulated",
            "secret_lease_ttl_seconds": 28800,
            "secret_lease_expires_at": connection["expires_at"],
            "resolved_namespace": connection["default_namespace"],
            "expires_at": connection["expires_at"],
            "message": "Connection verified successfully.",
            "error": "",
        }
        connection["last_verified_at"] = _now_iso()
        _save_state(root_dir, state)
        handler._send_json(result)
        return True

    if path == "/api/v1/auth/ocp/disconnect":
        connection_id = str(payload.get("connection_id") or "").strip()
        connection = _find_by_id(state["connections"], "connection_id", connection_id)
        if connection is None:
            _send_not_found(handler, "Connection not found")
            return True
        state["connections"] = [item for item in state["connections"] if str(item.get("connection_id") or "").strip() != connection_id]
        _save_state(root_dir, state)
        handler._send_json({"disconnected": True, "connection_id": connection_id})
        return True

    recommendation_refresh_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/recommendations/refresh", path)
    if recommendation_refresh_match:
        workspace_id = recommendation_refresh_match.group(1)
        connection_id = str(payload.get("connection_id") or "").strip()
        if not connection_id:
            _send_bad_request(handler, "connection_id is required")
            return True
        try:
            recommendations = _store_recommendations(root_dir, state, workspace_id, connection_id)
        except ValueError as exc:
            _send_not_found(handler, str(exc))
            return True
        _save_state(root_dir, state)
        handler._send_json({"items": recommendations})
        return True

    if path == "/api/v1/index/batch/jobs":
        request_payload = {
            "workspace_id": str(payload.get("workspace_id") or "").strip(),
            "root_path": str(payload.get("root_path") or "data").strip(),
            "explicit_source_paths": payload.get("explicit_source_paths") or [],
            "source_type": str(payload.get("source_type") or "generated-manual").strip(),
            "document_group": str(payload.get("document_group") or "official_ocp").strip(),
            "locale": str(payload.get("locale") or "").strip(),
            "max_files": int(payload.get("max_files") or 3),
            "include_subdirectories": bool(payload.get("include_subdirectories", True)),
        }
        job = {
            "job_id": _make_id("job"),
            "task_type": "batch_index",
            "status": "completed",
            "request": request_payload,
            "result": {
                "indexed_documents": min(len(_iter_document_rows(root_dir)), request_payload["max_files"]),
                "message": "Simulated batch indexing completed.",
            },
            "error": "",
            "progress_pct": 100,
            "current_file": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        state["batch_jobs"].insert(0, job)
        _save_state(root_dir, state)
        _send_json_created(handler, job)
        return True

    retry_match = re.fullmatch(r"/api/v1/index/batch/jobs/([^/]+)/retry-failed", path)
    if retry_match:
        job = _find_by_id(state["batch_jobs"], "job_id", retry_match.group(1))
        if job is None:
            _send_not_found(handler, "Batch job not found")
            return True
        job["status"] = "completed"
        job["updated_at"] = _now_iso()
        job["result"] = {"message": "Retry completed."}
        _save_state(root_dir, state)
        handler._send_json(job)
        return True

    cancel_match = re.fullmatch(r"/api/v1/index/batch/jobs/([^/]+)/cancel", path)
    if cancel_match:
        job = _find_by_id(state["batch_jobs"], "job_id", cancel_match.group(1))
        if job is None:
            _send_not_found(handler, "Batch job not found")
            return True
        job["status"] = "cancelled"
        job["updated_at"] = _now_iso()
        _save_state(root_dir, state)
        handler._send_json(job)
        return True

    if path == "/api/v1/chat/query":
        try:
            result = _chat_payload(root_dir, payload, state=state)
        except ValueError as exc:
            _send_bad_request(handler, str(exc))
            return True
        handler._send_json(result)
        return True

    if path == "/api/v1/chat/query/stream":
        try:
            result = _chat_payload(root_dir, payload, state=state)
        except ValueError as exc:
            handler._start_ndjson_stream()
            handler._stream_event({"type": "error", "status_code": 400, "message": str(exc)})
            return True
        _stream_chat_result(handler, result)
        return True

    if path == "/api/v1/actions/preview":
        try:
            preview = _action_preview_from_payload(root_dir, state, payload)
        except ValueError as exc:
            _send_bad_request(handler, str(exc))
            return True
        preview["action_type"] = str(payload.get("action_type") or "")
        handler._send_json(preview)
        return True

    if path == "/api/v1/actions/requests":
        try:
            preview = _action_preview_from_payload(root_dir, state, payload)
        except ValueError as exc:
            _send_bad_request(handler, str(exc))
            return True
        request_row = {
            "request_id": _make_id("req"),
            "status": "pending",
            "preview": {**preview, "action_type": str(payload.get("action_type") or "")},
            "requested_by": str(payload.get("actor_id") or ""),
            "requested_roles": payload.get("actor_roles") or [],
            "required_approvals": int(preview.get("required_approvals") or 0),
            "approval_count": 0,
            "approver_ids": [],
            "approver_role_map": {},
            "decision_note": "",
            "connection_id": str(payload.get("connection_id") or ""),
            "namespace": str(payload.get("namespace") or ""),
            "resource_type": str(payload.get("resource_type") or ""),
            "resource_name": str(payload.get("resource_name") or ""),
            "replicas": payload.get("replicas"),
            "manifest_yaml": str(payload.get("manifest_yaml") or ""),
            "created_at": _now_iso(),
        }
        state["action_requests"].insert(0, request_row)
        _append_audit(
            state,
            {
                "audit_id": _make_id("audit"),
                "request_id": request_row["request_id"],
                "execution_id": "",
                "event_type": "requested",
                "summary": str(preview.get("summary") or ""),
                "created_at": request_row["created_at"],
            },
        )
        _save_state(root_dir, state)
        _send_json_created(handler, request_row)
        return True

    approve_match = re.fullmatch(r"/api/v1/actions/requests/([^/]+)/approve", path)
    if approve_match:
        request_row = _find_by_id(state["action_requests"], "request_id", approve_match.group(1))
        if request_row is None:
            _send_not_found(handler, "Request not found")
            return True
        request_row["status"] = "approved"
        request_row["approval_count"] = int(request_row.get("approval_count") or 0) + 1
        request_row.setdefault("approver_ids", []).append(str(payload.get("actor_id") or ""))
        request_row["decision_note"] = str(payload.get("decision_note") or "").strip()
        _append_audit(
            state,
            {
                "audit_id": _make_id("audit"),
                "request_id": request_row["request_id"],
                "execution_id": "",
                "event_type": "approved",
                "summary": request_row["decision_note"] or "Approved from UI",
                "created_at": _now_iso(),
            },
        )
        _save_state(root_dir, state)
        handler._send_json(request_row)
        return True

    reject_match = re.fullmatch(r"/api/v1/actions/requests/([^/]+)/reject", path)
    if reject_match:
        request_row = _find_by_id(state["action_requests"], "request_id", reject_match.group(1))
        if request_row is None:
            _send_not_found(handler, "Request not found")
            return True
        request_row["status"] = "rejected"
        request_row["decision_note"] = str(payload.get("decision_note") or "").strip()
        _append_audit(
            state,
            {
                "audit_id": _make_id("audit"),
                "request_id": request_row["request_id"],
                "execution_id": "",
                "event_type": "rejected",
                "summary": request_row["decision_note"] or "Rejected from UI",
                "created_at": _now_iso(),
            },
        )
        _save_state(root_dir, state)
        handler._send_json(request_row)
        return True

    execute_match = re.fullmatch(r"/api/v1/actions/requests/([^/]+)/execute", path)
    if execute_match:
        request_row = _find_by_id(state["action_requests"], "request_id", execute_match.group(1))
        if request_row is None:
            _send_not_found(handler, "Request not found")
            return True
        execution = _execute_request(root_dir, state, request_row, payload)
        _save_state(root_dir, state)
        handler._send_json(execution)
        return True

    oauth_start_match = re.fullmatch(r"/api/v1/oauth/([^/]+)/start", path)
    if oauth_start_match:
        provider = oauth_start_match.group(1)
        params = parse_qs(query, keep_blank_values=False)
        workspace_id = str((params.get("workspace_id") or [""])[0]).strip()
        if provider not in {"github", "gitlab"}:
            _send_bad_request(handler, "Unsupported OAuth provider")
            return True
        state_token = uuid.uuid4().hex
        state["oauth_states"].append(
            {
                "state": state_token,
                "provider": provider,
                "workspace_id": workspace_id,
                "created_at": _now_iso(),
            }
        )
        _save_state(root_dir, state)
        authorize_url = _oauth_authorize_url(handler, root_dir, provider, state_token)
        handler._send_json({"provider": provider, "authorize_url": authorize_url, "state": state_token})
        return True

    scm_connections_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/connections", path)
    if scm_connections_match:
        workspace_id = scm_connections_match.group(1)
        record = {
            "scm_connection_id": _make_id("scm_conn"),
            "workspace_id": workspace_id,
            "provider": str(payload.get("provider") or "github").strip(),
            "host_url": str(payload.get("host_url") or "https://github.com").strip(),
            "auth_type": str(payload.get("auth_type") or "token").strip(),
            "account_label": str(payload.get("account_label") or "ops-admin").strip(),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        state["scm_connections"].insert(0, record)
        _save_state(root_dir, state)
        _send_json_created(handler, record)
        return True

    scm_repositories_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/repositories", path)
    if scm_repositories_match:
        workspace_id = scm_repositories_match.group(1)
        record = {
            "repository_id": _make_id("repo"),
            "workspace_id": workspace_id,
            "scm_connection_id": str(payload.get("scm_connection_id") or "").strip(),
            "repo_full_name": str(payload.get("repo_full_name") or "").strip(),
            "default_branch": str(payload.get("default_branch") or "main").strip() or "main",
            "config_path": str(payload.get("config_path") or "kustomization.yaml").strip(),
            "delivery_mode": str(payload.get("delivery_mode") or "gitops_commit").strip(),
            "manifest_kind": str(payload.get("manifest_kind") or "config_yaml").strip(),
            "target_cluster_url": str(payload.get("target_cluster_url") or "").strip(),
            "target_namespace": str(payload.get("target_namespace") or "").strip(),
            "auto_deploy_enabled": bool(payload.get("auto_deploy_enabled", False)),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        state["scm_repositories"].insert(0, record)
        _save_state(root_dir, state)
        _send_json_created(handler, record)
        return True

    deployment_plan_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/repositories/([^/]+)/deployment-plan", path)
    if deployment_plan_match:
        workspace_id = deployment_plan_match.group(1)
        repository_id = deployment_plan_match.group(2)
        repository = _find_by_id(state["scm_repositories"], "repository_id", repository_id)
        if repository is None or str(repository.get("workspace_id") or "").strip() != workspace_id:
            _send_not_found(handler, "Repository profile not found")
            return True
        plan = {
            "files_to_change": [str(repository.get("config_path") or "kustomization.yaml")],
            "suggested_updates": [
                {
                    "config_key": str(payload.get("config_key") or "replicas"),
                    "value": payload.get("replicas") or payload.get("image_tag") or "",
                    "resource_kind": str(payload.get("resource_kind") or "Deployment"),
                    "resource_name": str(payload.get("resource_name") or ""),
                }
            ],
            "trigger_kind": "pull_request" if repository.get("auto_deploy_enabled") else "manual_commit",
            "summary": f"Prepare repo-driven update for {payload.get('resource_name') or 'resource'}.",
            "commit_title": f"Update {payload.get('resource_name') or 'resource'} deployment plan",
            "commit_body": (
                f"Target namespace: {payload.get('target_namespace') or repository.get('target_namespace') or ''}\n"
                f"Reason: {payload.get('reason') or 'Apply operational change'}"
            ).strip(),
            "requires_pull_request": True,
            "next_step": "Review suggested file change and open PR in your source control workflow.",
        }
        handler._send_json(plan)
        return True

    return False


def handle_ops_console_put(handler: Any, path: str, payload: dict[str, Any], *, root_dir: Path) -> bool:
    return False


def handle_ops_console_patch(handler: Any, path: str, payload: dict[str, Any], *, root_dir: Path) -> bool:
    state = _load_state(root_dir)
    repository_match = re.fullmatch(r"/api/v1/workspaces/([^/]+)/scm/repositories/([^/]+)", path)
    if repository_match:
        workspace_id = repository_match.group(1)
        repository_id = repository_match.group(2)
        repository = _find_by_id(state["scm_repositories"], "repository_id", repository_id)
        if repository is None or str(repository.get("workspace_id") or "").strip() != workspace_id:
            _send_not_found(handler, "Repository profile not found")
            return True
        for key in (
            "repo_full_name",
            "default_branch",
            "config_path",
            "delivery_mode",
            "manifest_kind",
            "target_cluster_url",
            "target_namespace",
        ):
            if key in payload:
                repository[key] = payload[key]
        if "auto_deploy_enabled" in payload:
            repository["auto_deploy_enabled"] = bool(payload.get("auto_deploy_enabled"))
        repository["updated_at"] = _now_iso()
        _save_state(root_dir, state)
        handler._send_json(repository)
        return True
    return False


__all__ = [
    "handle_ops_console_get",
    "handle_ops_console_patch",
    "handle_ops_console_post",
    "handle_ops_console_put",
]
