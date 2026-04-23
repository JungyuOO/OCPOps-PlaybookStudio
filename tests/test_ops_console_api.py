from __future__ import annotations

import tempfile
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import requests

from play_book_studio.app import server
from play_book_studio.config.settings import load_settings


class _FakeLlmClient:
    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
        }


class _FakeAnswerer:
    def __init__(self, root: Path) -> None:
        self.settings = load_settings(root)
        self.llm_client = _FakeLlmClient()
        self.retriever = SimpleNamespace(reranker=None)


@contextmanager
def _test_server(root: Path):
    answerer = _FakeAnswerer(root)
    store = server.SessionStore(root)
    handler = server._build_handler(answerer=answerer, store=store, root_dir=root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_ops_console_workspaces_create_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with _test_server(root) as base_url:
            response = requests.get(f"{base_url}/api/v1/workspaces", timeout=10)
            response.raise_for_status()
            payload = response.json()

            assert payload["items"][0]["workspace_id"] == "ws_default"

            create_response = requests.post(
                f"{base_url}/api/v1/workspaces",
                json={"name": "Customer A", "environment": "stage"},
                timeout=10,
            )
            create_response.raise_for_status()
            created = create_response.json()

            reload_response = requests.get(f"{base_url}/api/v1/workspaces", timeout=10)
            reload_response.raise_for_status()
            reload_payload = reload_response.json()

            assert any(item["workspace_id"] == created["workspace_id"] for item in reload_payload["items"])


def test_ops_console_connection_recommendations_and_resources_flow() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with _test_server(root) as base_url:
            connect_response = requests.post(
                f"{base_url}/api/v1/auth/ocp/connect",
                json={
                    "workspace_id": "ws_default",
                    "cluster_url": "https://api.cluster.example.com:6443",
                    "auth_mode": "token",
                    "verify_ssl": True,
                    "default_namespace": "default",
                    "display_name": "dev-cluster",
                    "save_profile": True,
                    "token": "sha256~demo-token",
                },
                timeout=10,
            )
            connect_response.raise_for_status()
            connection = connect_response.json()["connection"]

            namespaces_response = requests.get(
                f"{base_url}/api/v1/ocp/namespaces/{connection['connection_id']}",
                timeout=10,
            )
            namespaces_response.raise_for_status()
            namespaces_payload = namespaces_response.json()

            assert "payments" in namespaces_payload["items"]

            resources_response = requests.get(
                f"{base_url}/api/v1/ocp/resources/{connection['connection_id']}?resource=deployments&namespace=payments",
                timeout=10,
            )
            resources_response.raise_for_status()
            resources_payload = resources_response.json()

            assert resources_payload["items"][0]["name"] == "payments-api"

            detail_response = requests.get(
                f"{base_url}/api/v1/ocp/resource-detail/{connection['connection_id']}?resource=deployments&namespace=payments&name=payments-api",
                timeout=10,
            )
            detail_response.raise_for_status()
            detail_payload = detail_response.json()

            assert "replicas: 3" in detail_payload["manifest_yaml"]

            refresh_response = requests.post(
                f"{base_url}/api/v1/workspaces/ws_default/recommendations/refresh",
                json={"connection_id": connection["connection_id"]},
                timeout=10,
            )
            refresh_response.raise_for_status()
            recommendations = refresh_response.json()["items"]

            assert recommendations[0]["resource_name"] == "payments-api"


def test_ops_console_actions_execute_scale_updates_resource_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        with _test_server(root) as base_url:
            connect_response = requests.post(
                f"{base_url}/api/v1/auth/ocp/connect",
                json={
                    "workspace_id": "ws_default",
                    "cluster_url": "https://api.cluster.example.com:6443",
                    "auth_mode": "token",
                    "verify_ssl": True,
                    "default_namespace": "default",
                    "display_name": "dev-cluster",
                    "save_profile": True,
                    "token": "sha256~demo-token",
                },
                timeout=10,
            )
            connect_response.raise_for_status()
            connection_id = connect_response.json()["connection"]["connection_id"]

            request_response = requests.post(
                f"{base_url}/api/v1/actions/requests",
                json={
                    "connection_id": connection_id,
                    "actor_id": "alice",
                    "actor_roles": ["operator"],
                    "action_type": "scale_deployment",
                    "namespace": "payments",
                    "resource_name": "payments-api",
                    "replicas": 5,
                    "reason": "scale out",
                },
                timeout=10,
            )
            request_response.raise_for_status()
            request_id = request_response.json()["request_id"]

            approve_response = requests.post(
                f"{base_url}/api/v1/actions/requests/{request_id}/approve",
                json={"actor_id": "alice", "actor_roles": ["operator"], "decision_note": "approved"},
                timeout=10,
            )
            approve_response.raise_for_status()

            execute_response = requests.post(
                f"{base_url}/api/v1/actions/requests/{request_id}/execute",
                json={"actor_id": "alice", "actor_roles": ["operator"], "execution_note": "run", "force": False},
                timeout=10,
            )
            execute_response.raise_for_status()
            execution = execute_response.json()

            assert execution["status"] == "succeeded"

            detail_response = requests.get(
                f"{base_url}/api/v1/ocp/resource-detail/{connection_id}?resource=deployments&namespace=payments&name=payments-api",
                timeout=10,
            )
            detail_response.raise_for_status()
            detail_payload = detail_response.json()

            assert "replicas: 5" in detail_payload["manifest_yaml"]
