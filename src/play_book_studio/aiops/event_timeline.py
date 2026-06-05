from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AIOpsTimelineEvent:
    event_id: str
    event_type: str
    source: str
    created_at: str
    summary: str
    session_id: str = ""
    connection_id: str = ""
    namespace: str = ""
    resource_type: str = ""
    resource_name: str = ""
    command_text: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    yaml_diff: str = ""
    apply_result: dict[str, Any] = field(default_factory=dict)
    related_events: list[dict[str, Any]] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    resource_snapshot: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def timeline_event_path(root_dir: Path) -> Path:
    return root_dir / "artifacts" / "aiops_timeline_v1" / "events.jsonl"


def append_timeline_event(
    root_dir: Path,
    *,
    event_type: str,
    source: str,
    summary: str,
    session_id: str = "",
    connection_id: str = "",
    namespace: str = "",
    resource_type: str = "",
    resource_name: str = "",
    command_text: str = "",
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
    yaml_diff: str = "",
    apply_result: dict[str, Any] | None = None,
    related_events: list[dict[str, Any]] | None = None,
    logs: list[dict[str, Any]] | None = None,
    resource_snapshot: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AIOpsTimelineEvent:
    event = AIOpsTimelineEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        event_type=str(event_type or "event"),
        source=str(source or "pbs"),
        created_at=_now_iso(),
        summary=str(summary or "").strip(),
        session_id=str(session_id or ""),
        connection_id=str(connection_id or ""),
        namespace=str(namespace or ""),
        resource_type=str(resource_type or ""),
        resource_name=str(resource_name or ""),
        command_text=str(command_text or ""),
        stdout=str(stdout or "")[-8000:],
        stderr=str(stderr or "")[-8000:],
        exit_code=exit_code,
        yaml_diff=str(yaml_diff or "")[-12000:],
        apply_result=dict(apply_result or {}),
        related_events=list(related_events or []),
        logs=list(logs or []),
        resource_snapshot=dict(resource_snapshot or {}),
        metadata=dict(metadata or {}),
    )
    path = timeline_event_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return event


def read_timeline_events(root_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = timeline_event_path(root_dir)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    safe_limit = max(1, min(int(limit or 50), 500))
    return list(reversed(rows[-safe_limit:]))


__all__ = [
    "AIOpsTimelineEvent",
    "append_timeline_event",
    "read_timeline_events",
    "timeline_event_path",
]
