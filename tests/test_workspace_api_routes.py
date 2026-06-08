from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from play_book_studio.http import ops_console_api


OWNER_HASH = "a3f9c1d2e4b567890123456789abcdef"


class FakeHandler:
    def __init__(self) -> None:
        self.payload: dict | None = None
        self.status: HTTPStatus | None = None

    def _session_owner(self):
        return SimpleNamespace(owner_hash=OWNER_HASH)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.payload = payload
        self.status = status


def test_workspace_status_route_uses_session_owner(monkeypatch) -> None:
    monkeypatch.setattr(ops_console_api, "_load_state", lambda _root: {"workspaces": []})
    monkeypatch.setattr(ops_console_api, "_with_env_ocp_connection", lambda _root, state: state)
    monkeypatch.setattr(
        ops_console_api,
        "get_user_workspace_status",
        lambda owner_hash: {"namespace": f"seen-{owner_hash[:8]}", "ready": True},
    )
    handler = FakeHandler()

    handled = ops_console_api.handle_ops_console_get(
        handler,
        "/api/v1/workspace/status",
        "",
        root_dir=Path("."),
    )

    assert handled is True
    assert handler.status == HTTPStatus.OK
    assert handler.payload == {"namespace": "seen-a3f9c1d2", "ready": True}


def test_workspace_pin_route_sets_pinned_for_session_owner(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(ops_console_api, "_load_state", lambda _root: {"workspaces": []})
    monkeypatch.setattr(ops_console_api, "set_pinned", lambda owner_hash, pinned: calls.append((owner_hash, pinned)))
    monkeypatch.setattr(
        ops_console_api,
        "get_user_workspace_status",
        lambda owner_hash: {"namespace": f"seen-{owner_hash[:8]}", "pinned": True},
    )
    handler = FakeHandler()

    handled = ops_console_api.handle_ops_console_post(
        handler,
        "/api/v1/workspace/pin",
        "",
        {"pinned": True},
        root_dir=Path("."),
    )

    assert handled is True
    assert calls == [(OWNER_HASH, True)]
    assert handler.payload == {"pinned": True, "status": {"namespace": "seen-a3f9c1d2", "pinned": True}}


def test_workspace_reset_route_deletes_session_workspace(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ops_console_api, "_load_state", lambda _root: {"workspaces": []})
    monkeypatch.setattr(ops_console_api, "delete_user_workspace", lambda owner_hash: calls.append(owner_hash) or True)
    monkeypatch.setattr(
        ops_console_api,
        "get_user_workspace_status",
        lambda owner_hash: {"namespace": f"seen-{owner_hash[:8]}", "exists": False},
    )
    handler = FakeHandler()

    handled = ops_console_api.handle_ops_console_post(
        handler,
        "/api/v1/workspace/reset",
        "",
        {},
        root_dir=Path("."),
    )

    assert handled is True
    assert calls == [OWNER_HASH]
    assert handler.payload == {"deleted": True, "status": {"namespace": "seen-a3f9c1d2", "exists": False}}


def test_ops_chat_post_injects_env_ocp_connection(monkeypatch) -> None:
    base_state = {
        "workspaces": [],
        "connections": [],
        "connection_inventory": {},
        "models": {},
        "recommendations": [],
        "batch_jobs": [],
        "action_requests": [],
        "action_executions": [],
        "action_audit": [],
        "scm_connections": [],
        "scm_repositories": [],
        "oauth_states": [],
    }
    env_connection = {
        "connection_id": ops_console_api.ENV_OCP_CONNECTION_ID,
        "workspace_id": "ws_default",
        "default_namespace": "pbs-ocpops",
        "cluster_url": "https://api.ocp.cywell.local:6443",
        "status": "connected",
        "connection_mode": "live",
    }

    monkeypatch.setattr(ops_console_api, "_load_state", lambda _root: dict(base_state))
    monkeypatch.setattr(
        ops_console_api,
        "_with_env_ocp_connection",
        lambda _root, state: {**state, "connections": [env_connection]},
    )

    def fake_chat_payload(_root, payload, *, state, answerer=None):
        assert payload["connection_id"] == ops_console_api.ENV_OCP_CONNECTION_ID
        assert state["connections"][0]["connection_id"] == ops_console_api.ENV_OCP_CONNECTION_ID
        return {"answer": "ok", "sources": [], "artifacts": []}

    monkeypatch.setattr(ops_console_api, "_chat_payload", fake_chat_payload)
    handler = FakeHandler()

    handled = ops_console_api.handle_ops_console_post(
        handler,
        "/api/v1/chat/query",
        "",
        {"message": "pod 상태 확인", "connection_id": ops_console_api.ENV_OCP_CONNECTION_ID},
        root_dir=Path("."),
    )

    assert handled is True
    assert handler.payload == {"answer": "ok", "sources": [], "artifacts": []}
