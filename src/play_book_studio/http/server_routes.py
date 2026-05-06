from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from .repository_registry import search_github_repositories as _search_github_repositories
from .server_routes_customer_pack import (
    _customer_pack_read_allowed,
    _send_customer_pack_read_blocked,
    handle_customer_pack_book,
    handle_customer_pack_capture,
    handle_customer_pack_captured,
    handle_customer_pack_delete_draft,
    handle_customer_pack_draft_create,
    handle_customer_pack_drafts,
    handle_customer_pack_ingest,
    handle_customer_pack_normalize,
    handle_customer_pack_plan,
    handle_customer_pack_support_matrix,
    handle_customer_pack_upload_draft,
)
from .server_routes_ops import (
    handle_repository_official_materialize,
    handle_repository_official_catalog,
    _search_official_source_candidates,
    handle_buyer_packet,
    handle_data_control_room,
    handle_data_control_room_chunks,
    handle_debug_chat_log,
    handle_debug_session,
    handle_repository_favorites,
    handle_repository_favorites_remove,
    handle_repository_favorites_save,
    handle_repository_unanswered,
    handle_session_delete,
    handle_session_load,
    handle_sessions_delete_all,
    handle_sessions_list,
    handle_wiki_overlay_signals,
    handle_wiki_user_overlay_remove,
    handle_wiki_user_overlay_save,
    handle_wiki_user_overlays,
)
from .server_routes_viewer import (
    _build_viewer_document_payload,
    _canonicalize_viewer_path,
    _viewer_source_meta,
    handle_runtime_figures,
    handle_source_meta,
    handle_viewer_document,
    resolve_viewer_html,
)


def handle_repository_search(handler: Any, query: str, *, root_dir: Path) -> None:
    params = parse_qs(query, keep_blank_values=False)
    search_query = str((params.get("query") or [""])[0]).strip()
    limit_raw = str((params.get("limit") or ["12"])[0]).strip()
    try:
        limit = int(limit_raw or "12")
    except ValueError:
        handler._send_json({"error": "limit는 정수여야 합니다."}, HTTPStatus.BAD_REQUEST)
        return
    try:
        payload = _search_github_repositories(root_dir, query=search_query, limit=limit)
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return
    except Exception as exc:  # noqa: BLE001
        handler._send_json(
            {"error": f"repository search 중 오류가 발생했습니다: {exc}"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
        return
    payload["official_candidates"] = _search_official_source_candidates(
        root_dir,
        query=search_query,
        limit=min(limit, 8),
    )
    handler._send_json(payload)


def handle_repository_official_materialize_request(
    handler: Any,
    payload: dict[str, Any],
    *,
    root_dir: Path,
) -> dict[str, Any] | None:
    return handle_repository_official_materialize(handler, payload, root_dir=root_dir)


def handle_repository_official_catalog_request(
    handler: Any,
    query: str,
    *,
    root_dir: Path,
) -> None:
    handle_repository_official_catalog(handler, query, root_dir=root_dir)


__all__ = [name for name in globals() if name.startswith("handle_") or name.startswith("_") or name == "resolve_viewer_html"]
