from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.app.customer_pack_read_boundary import (
    load_customer_pack_read_boundary,
    sanitize_customer_pack_book_payload,
    sanitize_customer_pack_draft_payload,
    sanitize_customer_pack_mutation_payload,
)
from play_book_studio.app.intake_api import (
    build_customer_pack_plan as _build_customer_pack_plan,
    build_customer_pack_support_matrix as _build_customer_pack_support_matrix,
    capture_customer_pack_draft as _capture_customer_pack_draft,
    create_customer_pack_draft as _create_customer_pack_draft,
    delete_customer_pack_draft as _delete_customer_pack_draft,
    ingest_customer_pack as _ingest_customer_pack,
    load_customer_pack_capture as _load_customer_pack_capture,
    load_customer_pack_draft as _load_customer_pack_draft,
    normalize_customer_pack_draft as _normalize_customer_pack_draft,
    upload_customer_pack_draft as _upload_customer_pack_draft,
)
from play_book_studio.app.source_books_customer_pack import (
    list_customer_pack_drafts as _list_customer_pack_drafts,
    load_customer_pack_book as _load_customer_pack_book,
)


def _send_customer_pack_read_blocked(handler: Any) -> None:
    handler._send_json(
        {"error": "요청한 customer pack runtime을 찾을 수 없습니다."},
        HTTPStatus.NOT_FOUND,
    )


def _customer_pack_read_allowed(root_dir: Path, draft_id: str) -> bool:
    summary = load_customer_pack_read_boundary(root_dir, draft_id)
    return bool(summary.get("read_allowed", False))


def handle_customer_pack_plan(handler: Any, payload: dict[str, Any]) -> None:
    try:
        plan = _build_customer_pack_plan(payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(plan)


def handle_customer_pack_support_matrix(handler: Any, query: str, *, root_dir: Path) -> None:
    del query, root_dir
    handler._send_json(_build_customer_pack_support_matrix())


def handle_customer_pack_drafts(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    draft_id = str((params.get("draft_id") or [""])[0]).strip()
    if not draft_id:
        payload = _list_customer_pack_drafts(root_dir)
        allowed_drafts = [
            sanitize_customer_pack_draft_payload(draft)
            for draft in (payload.get("drafts") or [])
            if isinstance(draft, dict)
            and _customer_pack_read_allowed(root_dir, str(draft.get("draft_id") or ""))
        ]
        handler._send_json({"drafts": allowed_drafts, "count": len(allowed_drafts)})
        return
    if not _customer_pack_read_allowed(root_dir, draft_id):
        _send_customer_pack_read_blocked(handler)
        return
    draft = _load_customer_pack_draft(root_dir, draft_id)
    if draft is None:
        handler._send_json({"error": "업로드 플레이북 초안을 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    handler._send_json(sanitize_customer_pack_draft_payload(draft))


def handle_customer_pack_captured(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    draft_id = str((params.get("draft_id") or [""])[0]).strip()
    if not draft_id:
        handler._send_json({"error": "draft_id가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    if not _customer_pack_read_allowed(root_dir, draft_id):
        _send_customer_pack_read_blocked(handler)
        return
    capture = _load_customer_pack_capture(root_dir, draft_id)
    if capture is None:
        handler._send_json({"error": "captured artifact를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND)
        return
    body, content_type = capture
    handler._send_bytes(body, content_type=content_type)


def handle_customer_pack_book(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    draft_id = str((params.get("draft_id") or [""])[0]).strip()
    if not draft_id:
        handler._send_json({"error": "draft_id가 필요합니다."}, HTTPStatus.BAD_REQUEST)
        return
    if not _customer_pack_read_allowed(root_dir, draft_id):
        _send_customer_pack_read_blocked(handler)
        return
    payload = _load_customer_pack_book(root_dir, draft_id)
    if payload is None:
        handler._send_json(
            {"error": "정규화된 플레이북 북을 찾을 수 없습니다."},
            HTTPStatus.NOT_FOUND,
        )
        return
    handler._send_json(sanitize_customer_pack_book_payload(payload))


def handle_customer_pack_draft_create(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        draft = _create_customer_pack_draft(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    handler._send_json(sanitize_customer_pack_mutation_payload(draft), HTTPStatus.CREATED)


def handle_customer_pack_upload_draft(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        draft = _upload_customer_pack_draft(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"파일 업로드 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(sanitize_customer_pack_mutation_payload(draft), HTTPStatus.CREATED)


def handle_customer_pack_ingest(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        draft = _ingest_customer_pack(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except FileNotFoundError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"ingest 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(sanitize_customer_pack_mutation_payload(draft), HTTPStatus.CREATED)


def handle_customer_pack_capture(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        draft = _capture_customer_pack_draft(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except FileNotFoundError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"capture 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(sanitize_customer_pack_mutation_payload(draft), HTTPStatus.CREATED)


def handle_customer_pack_delete_draft(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    draft_id = str(payload.get("draft_id") or "").strip()
    if not draft_id:
        handler._send_json({"error": "draft_id is required"}, HTTPStatus.BAD_REQUEST)
        return
    success = _delete_customer_pack_draft(root_dir, draft_id)
    if success:
        handler._send_json({"success": True, "draft_id": draft_id})
    else:
        handler._send_json({"error": "Draft not found"}, HTTPStatus.NOT_FOUND)


def handle_customer_pack_normalize(handler: Any, payload: dict[str, Any], *, root_dir: Path) -> None:
    try:
        draft = _normalize_customer_pack_draft(root_dir, payload)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except FileNotFoundError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"normalize 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    handler._send_json(sanitize_customer_pack_mutation_payload(draft), HTTPStatus.CREATED)


__all__ = [
    "_customer_pack_read_allowed",
    "_send_customer_pack_read_blocked",
    "handle_customer_pack_book",
    "handle_customer_pack_capture",
    "handle_customer_pack_captured",
    "handle_customer_pack_delete_draft",
    "handle_customer_pack_draft_create",
    "handle_customer_pack_drafts",
    "handle_customer_pack_ingest",
    "handle_customer_pack_normalize",
    "handle_customer_pack_plan",
    "handle_customer_pack_support_matrix",
    "handle_customer_pack_upload_draft",
]
