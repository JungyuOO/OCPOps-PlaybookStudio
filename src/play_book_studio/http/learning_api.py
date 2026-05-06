from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings


def build_learning_paths_response(root_dir: Path, query: str) -> dict[str, Any]:
    params = parse_qs(query or "")
    workspace_slug = _first(params, "workspace_slug", "default")
    slug = _first(params, "slug", "")
    limit = _int_param(_first(params, "limit", "50"), default=50)
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return {
            "schema": "learning_path_catalog_v1",
            "source": "postgres.learning_paths",
            "count": 0,
            "paths": [],
            "unavailable_reason": "DATABASE_URL is not configured",
        }

    import psycopg

    from play_book_studio.db.learning_repository import load_learning_path_catalog

    with psycopg.connect(database_url) as connection:
        return load_learning_path_catalog(
            connection,
            workspace_slug=workspace_slug,
            slug=slug,
            limit=limit,
        )


def build_learning_command_results_response(root_dir: Path, query: str) -> tuple[dict[str, Any], HTTPStatus]:
    params = parse_qs(query or "")
    lab_task_id = _first(params, "lab_task_id", "")
    learner_id = _first(params, "learner_id", "")
    if not lab_task_id:
        return {"error": "lab_task_id is required"}, HTTPStatus.BAD_REQUEST

    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return (
            {
                "schema": "learning_command_check_results_v1",
                "source": "postgres.command_check_results",
                "lab_task_id": lab_task_id,
                "learner_id": learner_id,
                "count": 0,
                "items": [],
                "unavailable_reason": "DATABASE_URL is not configured",
            },
            HTTPStatus.OK,
        )

    import psycopg

    from play_book_studio.db.terminal_learning_repository import list_command_check_results

    with psycopg.connect(database_url) as connection:
        items = list_command_check_results(
            connection,
            lab_task_id=lab_task_id,
            learner_id=learner_id,
        )
    return (
        {
            "schema": "learning_command_check_results_v1",
            "source": "postgres.command_check_results",
            "lab_task_id": lab_task_id,
            "learner_id": learner_id,
            "count": len(items),
            "items": items,
        },
        HTTPStatus.OK,
    )


def handle_learning_paths(handler: Any, query: str, *, root_dir: Path) -> None:
    try:
        payload = build_learning_paths_response(root_dir, query)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"learning paths failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


def handle_learning_command_results(handler: Any, query: str, *, root_dir: Path) -> None:
    try:
        payload, status = build_learning_command_results_response(root_dir, query)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"learning command results failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload, status)


def _first(params: dict[str, list[str]], key: str, default: str) -> str:
    values = params.get(key)
    if not values:
        return default
    value = str(values[0] or "").strip()
    return value or default


def _int_param(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


__all__ = [
    "build_learning_command_results_response",
    "build_learning_paths_response",
    "handle_learning_command_results",
    "handle_learning_paths",
]
