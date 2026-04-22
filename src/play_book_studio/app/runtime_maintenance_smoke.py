from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL
from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.graph_sidecar import (
    graph_sidecar_compact_artifact_status,
    refresh_active_runtime_graph_artifacts,
)


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_json(response: requests.Response) -> dict[str, Any] | list[Any] | str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return response.text[:1000]
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return payload
    return str(payload)


def build_runtime_maintenance_smoke(
    root_dir: str | Path,
    *,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    query: str = "OpenShift architecture overview",
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    base_url = ui_base_url.rstrip("/")
    refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=False,
        allow_compact_degrade=True,
    )
    compact_artifact = graph_sidecar_compact_artifact_status(settings)

    health_report: dict[str, Any] = {"base_url": base_url}
    chat_report: dict[str, Any] = {"base_url": base_url, "query": query}

    try:
        response = requests.get(f"{base_url}/api/health", timeout=10)
        health_report["status_code"] = response.status_code
        health_report["payload"] = _safe_json(response)
    except Exception as exc:  # noqa: BLE001
        health_report["error"] = str(exc)

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        chat_report["status_code"] = response.status_code
        chat_payload = _safe_json(response)
        if isinstance(chat_payload, dict):
            runtime_payload = (
                dict(chat_payload.get("runtime", {}))
                if isinstance(chat_payload.get("runtime"), dict)
                else {}
            )
            retrieval_trace = (
                dict(chat_payload.get("retrieval_trace", {}))
                if isinstance(chat_payload.get("retrieval_trace"), dict)
                else {}
            )
            graph_trace = (
                dict(retrieval_trace.get("graph", {}))
                if isinstance(retrieval_trace.get("graph"), dict)
                else {}
            )
            graph_summary = (
                dict(graph_trace.get("summary", {}))
                if isinstance(graph_trace.get("summary"), dict)
                else {}
            )
            chat_report["payload"] = {
                "response_kind": str(chat_payload.get("response_kind") or ""),
                "warnings": list(chat_payload.get("warnings") or []),
                "runtime": runtime_payload,
                "graph_summary": graph_summary,
            }
        else:
            chat_report["payload"] = chat_payload
    except Exception as exc:  # noqa: BLE001
        chat_report["error"] = str(exc)

    health_payload = (
        dict(health_report.get("payload", {}))
        if isinstance(health_report.get("payload"), dict)
        else {}
    )
    health_runtime = (
        dict(health_payload.get("runtime", {}))
        if isinstance(health_payload.get("runtime"), dict)
        else {}
    )
    chat_payload = (
        dict(chat_report.get("payload", {}))
        if isinstance(chat_report.get("payload"), dict)
        else {}
    )
    chat_runtime = (
        dict(chat_payload.get("runtime", {}))
        if isinstance(chat_payload.get("runtime"), dict)
        else {}
    )
    graph_summary = (
        dict(chat_payload.get("graph_summary", {}))
        if isinstance(chat_payload.get("graph_summary"), dict)
        else {}
    )
    compact_ready = bool(compact_artifact.get("ready"))
    health_ok = int(health_report.get("status_code", 0) or 0) < 400 and bool(health_payload)
    chat_ok = int(chat_report.get("status_code", 0) or 0) < 400 and bool(chat_payload)
    health_exposes_compact_artifact = isinstance(
        health_runtime.get("graph_compact_artifact"),
        dict,
    )
    chat_exposes_compact_artifact = isinstance(
        chat_runtime.get("graph_compact_artifact"),
        dict,
    )
    chat_graph_summary_present = bool(graph_summary)
    runtime_uses_compact_artifact = compact_ready and chat_exposes_compact_artifact
    ok = all(
        (
            compact_ready,
            health_ok,
            chat_ok,
            health_exposes_compact_artifact,
            chat_exposes_compact_artifact,
            chat_graph_summary_present,
            runtime_uses_compact_artifact,
        )
    )
    return {
        "generated_at": _iso_timestamp(),
        "maintenance": {
            "graph_refresh": refresh,
            "graph_compact_artifact": compact_artifact,
        },
        "probes": {
            "health": health_report,
            "chat": chat_report,
        },
        "summary": {
            "ok": ok,
            "compact_ready": compact_ready,
            "health_ok": health_ok,
            "chat_ok": chat_ok,
            "health_exposes_compact_artifact": health_exposes_compact_artifact,
            "chat_exposes_compact_artifact": chat_exposes_compact_artifact,
            "chat_graph_summary_present": chat_graph_summary_present,
            "runtime_uses_compact_artifact": runtime_uses_compact_artifact,
        },
    }


def write_runtime_maintenance_smoke(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    query: str = "OpenShift architecture overview",
) -> tuple[Path, dict[str, Any]]:
    settings = load_settings(root_dir)
    payload = build_runtime_maintenance_smoke(
        root_dir,
        ui_base_url=ui_base_url,
        query=query,
    )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else settings.root_dir / "reports" / "build_logs" / "runtime_maintenance_smoke.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target, payload
