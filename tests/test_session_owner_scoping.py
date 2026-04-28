from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from play_book_studio.app.session_owner import OWNER_COOKIE_NAME, resolve_session_owner
from play_book_studio.app.sessions import SessionStore, Turn


OWNER_A = "sessionownera0000000000000000001"
OWNER_B = "sessionownerb0000000000000000002"


def _cleanup_owner_dirs(root: Path) -> None:
    sessions_root = root / "artifacts" / "runtime" / "sessions"
    for owner_scope in (OWNER_A, OWNER_B):
        shutil.rmtree(sessions_root / owner_scope, ignore_errors=True)


def _store_with_one_turn(root: Path, *, owner_scope: str, session_id: str, query: str) -> SessionStore:
    store = SessionStore(root, load_persisted=False).for_owner(owner_scope)
    session = store.get(session_id)
    session.history.append(Turn(query=query, mode="chat", answer=f"answer: {query}"))
    session.revision += 1
    store.update(session)
    return store


def test_session_summaries_are_isolated_by_owner_scope() -> None:
    root = Path.cwd()
    _cleanup_owner_dirs(root)
    try:
        store_a = _store_with_one_turn(root, owner_scope=OWNER_A, session_id="shared-session", query="owner a")
        store_b = _store_with_one_turn(root, owner_scope=OWNER_B, session_id="shared-session", query="owner b")

        summaries_a = store_a.list_summaries()
        summaries_b = store_b.list_summaries()

        assert [item["first_query"] for item in summaries_a] == ["owner a"]
        assert [item["first_query"] for item in summaries_b] == ["owner b"]
        assert (root / "artifacts" / "runtime" / "sessions" / OWNER_A / "recent_chat_session.json").exists()
        assert (root / "artifacts" / "runtime" / "sessions" / OWNER_B / "recent_chat_session.json").exists()
        assert not (root / "artifacts" / "runtime" / "recent_chat_session.json").exists()
    finally:
        _cleanup_owner_dirs(root)


def test_other_owner_session_id_is_not_loaded() -> None:
    root = Path.cwd()
    _cleanup_owner_dirs(root)
    try:
        _store_with_one_turn(root, owner_scope=OWNER_A, session_id="private-session", query="owner a")
        store_b = SessionStore(root, load_persisted=False).for_owner(OWNER_B)

        loaded = store_b.peek("private-session")

        assert loaded is None
    finally:
        _cleanup_owner_dirs(root)


def test_delete_all_removes_only_current_owner_scope() -> None:
    root = Path.cwd()
    _cleanup_owner_dirs(root)
    try:
        store_a = _store_with_one_turn(root, owner_scope=OWNER_A, session_id="a-session", query="owner a")
        store_b = _store_with_one_turn(root, owner_scope=OWNER_B, session_id="b-session", query="owner b")

        deleted_count = store_a.delete_all()

        assert deleted_count == 1
        assert store_a.list_summaries() == []
        assert [item["session_id"] for item in store_b.list_summaries()] == ["b-session"]
        assert not (root / "artifacts" / "runtime" / "sessions" / OWNER_A / "a-session.json").exists()
        assert (root / "artifacts" / "runtime" / "sessions" / OWNER_B / "b-session.json").exists()
    finally:
        _cleanup_owner_dirs(root)


def test_session_id_is_sanitized_before_snapshot_path_use() -> None:
    root = Path.cwd()
    _cleanup_owner_dirs(root)
    try:
        store = _store_with_one_turn(root, owner_scope=OWNER_A, session_id="../other-owner/session", query="unsafe id")
        assert store.peek("../other-owner/session") is not None
        owner_dir = root / "artifacts" / "runtime" / "sessions" / OWNER_A
        snapshots = list(owner_dir.glob("session-*.json"))
        assert len(snapshots) == 1
        assert owner_dir in snapshots[0].parents
    finally:
        _cleanup_owner_dirs(root)


def test_owner_cookie_is_issued_when_request_has_no_identity() -> None:
    handler = SimpleNamespace(headers={})

    owner = resolve_session_owner(handler)

    assert owner.source == "new_cookie"
    assert owner.owner_hash
    assert f"{OWNER_COOKIE_NAME}=" in owner.set_cookie_header
    assert "HttpOnly" in owner.set_cookie_header


def test_proxy_header_owner_takes_precedence_over_cookie() -> None:
    cookie_handler = SimpleNamespace(headers={})
    cookie_owner = resolve_session_owner(cookie_handler)
    header_handler = SimpleNamespace(
        headers={
            "X-Forwarded-User": "alice@example.com",
            "Cookie": cookie_owner.set_cookie_header,
        }
    )

    owner = resolve_session_owner(header_handler)

    assert owner.source == "X-Forwarded-User"
    assert owner.owner_hash != cookie_owner.owner_hash
    assert owner.set_cookie_header == ""
