from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any


OWNER_COOKIE_NAME = "pbs_session_owner"
OWNER_HEADER_CANDIDATES = ("X-Forwarded-User", "X-Remote-User", "X-User")


@dataclass(frozen=True, slots=True)
class SessionOwner:
    raw_owner: str
    owner_hash: str
    source: str
    set_cookie_header: str = ""


def _owner_hash(raw_owner: str) -> str:
    normalized = str(raw_owner or "").strip()
    if not normalized:
        normalized = "anonymous"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _read_cookie_owner(cookie_header: str) -> str:
    if not cookie_header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:  # noqa: BLE001
        return ""
    morsel = cookie.get(OWNER_COOKIE_NAME)
    return str(morsel.value or "").strip() if morsel is not None else ""


def _safe_cookie_value(value: str) -> str:
    normalized = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]{16,128}", normalized):
        return normalized
    return ""


def _build_owner_cookie(value: str) -> str:
    cookie = SimpleCookie()
    cookie[OWNER_COOKIE_NAME] = value
    cookie[OWNER_COOKIE_NAME]["path"] = "/"
    cookie[OWNER_COOKIE_NAME]["httponly"] = True
    cookie[OWNER_COOKIE_NAME]["samesite"] = "Lax"
    cookie[OWNER_COOKIE_NAME]["max-age"] = 60 * 60 * 24 * 365
    return cookie.output(header="").strip()


def resolve_session_owner(handler: Any) -> SessionOwner:
    for header_name in OWNER_HEADER_CANDIDATES:
        header_value = str(handler.headers.get(header_name) or "").strip()
        if header_value:
            return SessionOwner(
                raw_owner=f"{header_name}:{header_value}",
                owner_hash=_owner_hash(f"header:{header_name}:{header_value}"),
                source=header_name,
            )

    cookie_value = _safe_cookie_value(_read_cookie_owner(str(handler.headers.get("Cookie") or "")))
    if cookie_value:
        return SessionOwner(
            raw_owner=f"cookie:{cookie_value}",
            owner_hash=_owner_hash(f"cookie:{cookie_value}"),
            source="cookie",
        )

    new_cookie_value = uuid.uuid4().hex
    return SessionOwner(
        raw_owner=f"cookie:{new_cookie_value}",
        owner_hash=_owner_hash(f"cookie:{new_cookie_value}"),
        source="new_cookie",
        set_cookie_header=_build_owner_cookie(new_cookie_value),
    )


__all__ = [
    "OWNER_COOKIE_NAME",
    "OWNER_HEADER_CANDIDATES",
    "SessionOwner",
    "resolve_session_owner",
]
