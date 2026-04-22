"""세션 기록, 최근 대화 snapshot, 디버그용 turn 모델을 관리한다."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from play_book_studio.config.packs import default_core_pack
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.models import SessionContext

RUNTIME_CHAT_MODE = "chat"
DEFAULT_CORE_VERSION = default_core_pack().version


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _session_display_name(session_id: str) -> str:
    short_id = (session_id or "").strip()[:8] or "unknown"
    return f"세션 {short_id}"


def serialize_turn(turn: "Turn") -> dict[str, Any]:
    return {
        "turn_id": turn.turn_id,
        "parent_turn_id": turn.parent_turn_id,
        "created_at": turn.created_at,
        "query": turn.query,
        "user": turn.query,
        "mode": turn.mode,
        "answer": turn.answer,
        "chatbot": turn.answer,
        "rewritten_query": turn.rewritten_query,
        "response_kind": turn.response_kind,
        "citations": list(turn.citations),
        "related_links": list(turn.related_links),
        "related_sections": list(turn.related_sections),
        "warnings": list(turn.warnings),
        "stages": list(turn.stages),
        "diagnosis": dict(turn.diagnosis),
        "primary_source_lane": turn.primary_source_lane,
        "primary_boundary_truth": turn.primary_boundary_truth,
        "primary_runtime_truth_label": turn.primary_runtime_truth_label,
        "primary_boundary_badge": turn.primary_boundary_badge,
        "primary_publication_state": turn.primary_publication_state,
        "primary_approval_state": turn.primary_approval_state,
    }


def deserialize_turn(payload: dict[str, Any]) -> "Turn":
    citations = payload.get("citations") or []
    related_links = payload.get("related_links") or []
    related_sections = payload.get("related_sections") or []
    warnings = payload.get("warnings") or []
    stages = payload.get("stages") or []
    diagnosis = payload.get("diagnosis") or {}
    if not isinstance(citations, list):
        citations = []
    if not isinstance(related_links, list):
        related_links = []
    if not isinstance(related_sections, list):
        related_sections = []
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []
    if not isinstance(stages, list):
        stages = []
    if not isinstance(diagnosis, dict):
        diagnosis = {}
    query = str(payload.get("query") or payload.get("user") or "")
    answer = str(payload.get("answer") or payload.get("chatbot") or "")
    return Turn(
        turn_id=str(payload.get("turn_id") or ""),
        parent_turn_id=str(payload.get("parent_turn_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        query=query,
        mode=str(payload.get("mode") or RUNTIME_CHAT_MODE),
        answer=answer,
        rewritten_query=str(payload.get("rewritten_query") or ""),
        response_kind=str(payload.get("response_kind") or ""),
        citations=[dict(item) for item in citations if isinstance(item, dict)],
        related_links=[dict(item) for item in related_links if isinstance(item, dict)],
        related_sections=[dict(item) for item in related_sections if isinstance(item, dict)],
        warnings=[str(item) for item in warnings if str(item).strip()],
        stages=[dict(item) for item in stages if isinstance(item, dict)],
        diagnosis={str(key): value for key, value in diagnosis.items()},
        primary_source_lane=str(payload.get("primary_source_lane") or ""),
        primary_boundary_truth=str(payload.get("primary_boundary_truth") or ""),
        primary_runtime_truth_label=str(payload.get("primary_runtime_truth_label") or ""),
        primary_boundary_badge=str(payload.get("primary_boundary_badge") or ""),
        primary_publication_state=str(payload.get("primary_publication_state") or ""),
        primary_approval_state=str(payload.get("primary_approval_state") or ""),
    )


@dataclass(slots=True)
class Turn:
    query: str
    mode: str
    answer: str
    rewritten_query: str = ""
    response_kind: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    related_links: list[dict[str, Any]] = field(default_factory=list)
    related_sections: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stages: list[dict[str, object]] = field(default_factory=list)
    diagnosis: dict[str, object] = field(default_factory=dict)
    primary_source_lane: str = ""
    primary_boundary_truth: str = ""
    primary_runtime_truth_label: str = ""
    primary_boundary_badge: str = ""
    primary_publication_state: str = ""
    primary_approval_state: str = ""
    turn_id: str = ""
    parent_turn_id: str = ""
    created_at: str = ""


@dataclass(slots=True)
class ChatSession:
    session_id: str
    mode: str = RUNTIME_CHAT_MODE
    context: SessionContext = field(
        default_factory=lambda: SessionContext(mode=RUNTIME_CHAT_MODE, ocp_version=DEFAULT_CORE_VERSION)
    )
    history: list[Turn] = field(default_factory=list)
    revision: int = 0
    updated_at: str = ""

    @property
    def last_query(self) -> str:
        if not self.history:
            return ""
        return self.history[-1].query

    @property
    def display_name(self) -> str:
        if self.history and self.history[0].query.strip():
            q = self.history[0].query.strip()
            return (q[:60] + "...") if len(q) > 60 else q
        return _session_display_name(self.session_id)

    def to_snapshot_dict(self) -> dict[str, Any]:
        recent_history = self.history[-20:]
        return {
            "updated_at": self.updated_at or _now_timestamp(),
            "session_id": self.session_id,
            "session_name": self.display_name,
            "mode": self.mode,
            "revision": self.revision,
            "context": self.context.to_dict(),
            "turn_count": len(recent_history),
            "latest_turn_id": recent_history[-1].turn_id if recent_history else "",
            "turns": [serialize_turn(turn) for turn in recent_history],
        }

    @classmethod
    def from_snapshot_dict(cls, payload: dict[str, Any]) -> "ChatSession":
        turns = payload.get("turns") or payload.get("history") or []
        if not isinstance(turns, list):
            turns = []
        history = [deserialize_turn(turn) for turn in turns if isinstance(turn, dict)]
        context_payload = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        session = cls(
            session_id=str(payload.get("session_id") or ""),
            mode=str(payload.get("mode") or RUNTIME_CHAT_MODE),
            context=SessionContext.from_dict(context_payload),
            history=history,
            revision=int(payload.get("revision") or payload.get("turn_count") or len(history) or 0),
            updated_at=str(payload.get("updated_at") or ""),
        )
        return session


def serialize_session_snapshot(session: ChatSession) -> dict[str, Any]:
    return session.to_snapshot_dict()


def deserialize_session_snapshot(payload: dict[str, Any]) -> ChatSession | None:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return None
    return ChatSession.from_snapshot_dict(payload)


class SessionStore:
    def __init__(self, root_dir: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, ChatSession] = {}
        self._latest_session_id: str | None = None
        self._root_dir = Path(root_dir).resolve() if root_dir else None
        self._settings = load_settings(self._root_dir) if self._root_dir is not None else None
        if self._settings is not None:
            self._load_persisted_sessions()

    def _session_snapshot_paths(self) -> list[Path]:
        if self._settings is None:
            return []
        paths = list(self._settings.runtime_sessions_dir.glob("*.json"))
        recent = self._settings.recent_chat_session_path
        if recent.exists():
            paths.append(recent)
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        return sorted(unique, key=lambda path: path.stat().st_mtime if path.exists() else 0.0)

    def _load_session_from_payload(self, payload: dict[str, Any]) -> ChatSession | None:
        try:
            return deserialize_session_snapshot(payload)
        except Exception:  # noqa: BLE001
            return None

    def _merge_session(self, session: ChatSession) -> None:
        existing = self._sessions.get(session.session_id)
        if existing is None:
            self._sessions[session.session_id] = session
        else:
            existing_updated_at = existing.updated_at or ""
            candidate_updated_at = session.updated_at or ""
            if candidate_updated_at >= existing_updated_at:
                self._sessions[session.session_id] = session
                existing = session
            else:
                session = existing

        latest = self._sessions.get(self._latest_session_id or "")
        latest_updated_at = (latest.updated_at if latest is not None else "") or ""
        candidate_updated_at = session.updated_at or ""
        if latest is None or candidate_updated_at >= latest_updated_at:
            self._latest_session_id = session.session_id

    def _load_snapshot_path(self, snapshot_path: Path) -> ChatSession | None:
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        return self._load_session_from_payload(payload if isinstance(payload, dict) else {})

    def _refresh_persisted_sessions(self) -> None:
        if self._settings is None:
            return
        for snapshot_path in self._session_snapshot_paths():
            session = self._load_snapshot_path(snapshot_path)
            if session is None:
                continue
            self._merge_session(session)

    def _load_persisted_sessions(self) -> None:
        if self._settings is None:
            return
        self._refresh_persisted_sessions()

    def _persist_session(self, session: ChatSession) -> None:
        if self._settings is None:
            return
        payload = serialize_session_snapshot(session)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        self._settings.runtime_sessions_dir.mkdir(parents=True, exist_ok=True)
        self._settings.session_snapshot_path(session.session_id).write_text(serialized, encoding="utf-8")
        self._settings.recent_chat_session_path.write_text(serialized, encoding="utf-8")

    def _recent_session_id(self) -> str | None:
        if self._settings is None:
            return None
        recent_path = self._settings.recent_chat_session_path
        if not recent_path.exists():
            return None
        session = self._load_snapshot_path(recent_path)
        if session is None:
            return None
        return session.session_id

    def get(self, session_id: str) -> ChatSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None and self._settings is not None:
                snapshot_path = self._settings.session_snapshot_path(session_id)
                if snapshot_path.exists():
                    session = self._load_snapshot_path(snapshot_path)
                    if session is not None:
                        self._merge_session(session)
            if session is None:
                session = ChatSession(session_id=session_id)
                self._sessions[session_id] = session
            self._latest_session_id = session_id
            return session

    def reset(self, session_id: str) -> ChatSession:
        with self._lock:
            session = ChatSession(session_id=session_id, updated_at=_now_timestamp())
            self._sessions[session_id] = session
            self._latest_session_id = session_id
        self._persist_session(session)
        return session

    def update(self, session: ChatSession) -> None:
        session.updated_at = session.updated_at or _now_timestamp()
        with self._lock:
            self._sessions[session.session_id] = session
            self._latest_session_id = session.session_id
        self._persist_session(session)

    def persist(self, session: ChatSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            self._latest_session_id = session.session_id
        self._persist_session(session)

    def delete(self, session_id: str) -> bool:
        deleted = False
        next_latest: ChatSession | None = None
        with self._lock:
            removed = self._sessions.pop(session_id, None)
            deleted = removed is not None

            if self._settings is not None:
                snapshot_path = self._settings.session_snapshot_path(session_id)
                if snapshot_path.exists():
                    snapshot_path.unlink()
                    deleted = True

                recent_path = self._settings.recent_chat_session_path
                if recent_path.exists() and self._recent_session_id() == session_id:
                    recent_path.unlink()

            if self._latest_session_id == session_id:
                self._latest_session_id = None

            self._refresh_persisted_sessions()
            if self._latest_session_id:
                next_latest = self._sessions.get(self._latest_session_id)

        if next_latest is not None and self._settings is not None:
            self._persist_session(next_latest)
        return deleted

    def delete_all(self) -> int:
        deleted_ids: set[str] = set()
        with self._lock:
            deleted_ids.update(self._sessions.keys())
            self._sessions.clear()
            self._latest_session_id = None
            if self._settings is not None:
                for snapshot_path in self._settings.runtime_sessions_dir.glob("*.json"):
                    try:
                        snapshot_path.unlink()
                        deleted_ids.add(snapshot_path.stem)
                    except FileNotFoundError:
                        continue
                recent_path = self._settings.recent_chat_session_path
                if recent_path.exists():
                    recent_path.unlink()
        return len(deleted_ids)

    def peek(self, session_id: str) -> ChatSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None or self._settings is None:
                return session
            snapshot_path = self._settings.session_snapshot_path(session_id)
            if not snapshot_path.exists():
                return None
            session = self._load_snapshot_path(snapshot_path)
            if session is None:
                return None
            self._merge_session(session)
            return self._sessions.get(session_id)

    def latest(self) -> ChatSession | None:
        with self._lock:
            self._refresh_persisted_sessions()
            if not self._latest_session_id:
                return None
            return self._sessions.get(self._latest_session_id)

    def list_summaries(self, limit: int = 50) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        with self._lock:
            self._refresh_persisted_sessions()
            for session in self._sessions.values():
                if not session.history:
                    continue
                first_query = session.history[0].query.strip() if session.history else ""
                summaries.append({
                    "session_id": session.session_id,
                    "session_name": session.display_name,
                    "turn_count": len(session.history),
                    "updated_at": session.updated_at or "",
                    "first_query": first_query[:80],
                    "primary_source_lane": session.history[-1].primary_source_lane if session.history else "",
                    "primary_boundary_truth": session.history[-1].primary_boundary_truth if session.history else "",
                    "primary_runtime_truth_label": session.history[-1].primary_runtime_truth_label if session.history else "",
                    "primary_boundary_badge": session.history[-1].primary_boundary_badge if session.history else "",
                    "primary_publication_state": session.history[-1].primary_publication_state if session.history else "",
                    "primary_approval_state": session.history[-1].primary_approval_state if session.history else "",
                })
        summaries.sort(key=lambda s: s["updated_at"], reverse=True)
        return summaries[:limit]


__all__ = [
    "ChatSession",
    "RUNTIME_CHAT_MODE",
    "SessionStore",
    "Turn",
    "DEFAULT_CORE_VERSION",
    "deserialize_session_snapshot",
    "deserialize_turn",
    "serialize_session_snapshot",
    "serialize_turn",
]
