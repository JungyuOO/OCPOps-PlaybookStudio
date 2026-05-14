from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubernetesClient:
    def __init__(self, *, base_url: str, token: str, verify: str | bool = True, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify = verify
        self.timeout_seconds = timeout_seconds

    @classmethod
    def in_cluster(cls) -> "KubernetesClient":
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "").strip()
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443").strip() or "443"
        if not host:
            raise RuntimeError("KUBERNETES_SERVICE_HOST is not set")
        token_path = SERVICE_ACCOUNT_DIR / "token"
        token = token_path.read_text(encoding="utf-8").strip()
        ca_path = SERVICE_ACCOUNT_DIR / "ca.crt"
        verify: str | bool = str(ca_path) if ca_path.exists() else True
        return cls(base_url=f"https://{host}:{port}", token=token, verify=verify)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = content_type
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            data=data,
            verify=self.verify,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Kubernetes API {method} {path} failed: {response.status_code} {response.text[:500]}")
        if not response.content:
            return {}
        return response.json()

    def apply_manifest(self, manifest: dict[str, Any], *, field_manager: str = "playbookstudio") -> dict[str, Any]:
        path = resource_path(manifest)
        query = urlencode({"fieldManager": field_manager, "force": "true"})
        return self.request_json(
            "PATCH",
            f"{path}?{query}",
            body=manifest,
            content_type="application/apply-patch+yaml",
        )

    def patch_resource(self, path: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("PATCH", path, body=patch, content_type="application/merge-patch+json")

    def delete_resource(self, path: str) -> dict[str, Any]:
        return self.request_json("DELETE", path)

    def wait_for_deployment_ready(self, namespace: str, name: str, *, timeout_seconds: int = 20) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        path = f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}"
        while True:
            deployment = self.request_json("GET", path)
            spec_replicas = int((deployment.get("spec") or {}).get("replicas") or 0)
            status = deployment.get("status") if isinstance(deployment.get("status"), dict) else {}
            ready_replicas = int(status.get("readyReplicas") or 0)
            if spec_replicas == 0 or ready_replicas >= spec_replicas:
                return deployment
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Deployment {namespace}/{name} did not become ready")
            time.sleep(1)

    def first_ready_pod(self, namespace: str, *, label_selector: str) -> str:
        query = urlencode({"labelSelector": label_selector})
        payload = self.request_json("GET", f"/api/v1/namespaces/{namespace}/pods?{query}")
        for item in payload.get("items") or []:
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            if status.get("phase") != "Running":
                continue
            for condition in status.get("conditions") or []:
                if condition.get("type") == "Ready" and condition.get("status") == "True":
                    return str((item.get("metadata") or {}).get("name") or "")
        return ""


def resource_path(manifest: dict[str, Any]) -> str:
    kind = str(manifest.get("kind") or "")
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    name = str(metadata.get("name") or "").strip()
    namespace = str(metadata.get("namespace") or "").strip()
    if not kind or not name:
        raise ValueError("manifest kind and metadata.name are required")
    if kind == "Namespace":
        return f"/api/v1/namespaces/{name}"
    if not namespace:
        raise ValueError(f"{kind} manifest requires metadata.namespace")
    if kind == "ServiceAccount":
        return f"/api/v1/namespaces/{namespace}/serviceaccounts/{name}"
    if kind == "PersistentVolumeClaim":
        return f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}"
    if kind == "ResourceQuota":
        return f"/api/v1/namespaces/{namespace}/resourcequotas/{name}"
    if kind == "Deployment":
        return f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}"
    if kind == "RoleBinding":
        return f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings/{name}"
    if kind == "NetworkPolicy":
        return f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies/{name}"
    raise ValueError(f"unsupported manifest kind: {kind}")
