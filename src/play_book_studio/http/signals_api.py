from __future__ import annotations

import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import load_settings

_COMMAND_PATTERN = re.compile(
    r"^(oc|kubectl)\s+(create|apply|delete|edit|patch|rollout|scale|expose|adm|set\s+image)\b",
    re.IGNORECASE,
)


def _int_query(value: str, *, default: int, upper: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return default
    return max(1, min(parsed, upper))


def _signal_from_command(row: dict[str, Any]) -> dict[str, Any] | None:
    command = str(row.get("command_text") or "").strip()
    match = _COMMAND_PATTERN.match(command)
    if not match:
        return None
    rest = command[match.end():].strip()
    tokens = [token for token in re.split(r"\s+", rest) if token]
    namespace = "default"
    for index, token in enumerate(tokens):
        if token in {"-n", "--namespace"} and index + 1 < len(tokens):
            namespace = tokens[index + 1]
            break
    resource_tokens = [token for token in tokens if not token.startswith("-") and "=" not in token]
    return {
        "signal_id": str(row.get("id") or ""),
        "timestamp": str(row.get("created_at") or ""),
        "operation_type": match.group(2).lower(),
        "resource_kind": resource_tokens[0] if resource_tokens else "resource",
        "resource_name": resource_tokens[1] if len(resource_tokens) > 1 else "",
        "namespace": namespace,
        "status": "observed",
        "source_command": command,
        "terminal_session_id": str(row.get("terminal_session_id") or ""),
    }


def build_signals_response(root_dir: Path, query: str) -> dict[str, Any]:
    database_url = load_settings(root_dir).database_url.strip()
    if not database_url:
        return {"database": "disabled", "count": 0, "items": []}

    params = parse_qs(query, keep_blank_values=False)
    limit = _int_query(str((params.get("limit") or ["50"])[0]), default=50, upper=200)
    session_id = str((params.get("terminal_session_id") or [""])[0] or "").strip()

    import psycopg
    from psycopg.rows import dict_row

    where = "WHERE te.command_text <> ''"
    values: list[Any] = []
    if session_id:
        where += " AND te.terminal_session_id = %s::uuid"
        values.append(session_id)
    values.append(limit * 3)

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT te.id::text, te.terminal_session_id::text, te.command_text, te.created_at
                FROM terminal_events te
                {where}
                ORDER BY te.created_at DESC
                LIMIT %s
                """,
                values,
            )
            rows = cursor.fetchall()

    items = [item for row in rows if (item := _signal_from_command(dict(row))) is not None]
    items = items[:limit]
    return {"database": "postgres", "count": len(items), "items": items}


def handle_signals(handler: Any, query: str, *, root_dir: Path) -> None:
    try:
        payload = build_signals_response(root_dir, query)
    except Exception as exc:  # noqa: BLE001
        handler._send_json({"error": f"signals load failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    handler._send_json(payload)


__all__ = ["build_signals_response", "handle_signals"]
