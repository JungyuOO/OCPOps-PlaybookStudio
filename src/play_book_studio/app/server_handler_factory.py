"""HTTP handler factory split out of server.py."""
from __future__ import annotations

import mimetypes
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from play_book_studio.app.server_chat import (
    handle_chat as _handle_chat_request,
    handle_chat_stream as _handle_chat_stream_request,
)
from play_book_studio.app.course_api import (
    handle_course_get as _handle_course_get_request,
    handle_course_post as _handle_course_post_request,
)
from play_book_studio.app.ops_console_api import (
    handle_ops_console_get as _handle_ops_console_get_request,
    handle_ops_console_patch as _handle_ops_console_patch_request,
    handle_ops_console_post as _handle_ops_console_post_request,
    handle_ops_console_put as _handle_ops_console_put_request,
)
from play_book_studio.app.server_routes import (
    resolve_viewer_html as _resolve_viewer_html,
    handle_data_control_room as _handle_data_control_room_request,
    handle_data_control_room_chunks as _handle_data_control_room_chunks_request,
    handle_debug_chat_log as _handle_debug_chat_log_request,
    handle_debug_session as _handle_debug_session_request,
    handle_customer_pack_book as _handle_customer_pack_book_request,
    handle_buyer_packet as _handle_buyer_packet_request,
    handle_customer_pack_capture as _handle_customer_pack_capture_request,
    handle_customer_pack_captured as _handle_customer_pack_captured_request,
    handle_customer_pack_draft_create as _handle_customer_pack_draft_create_request,
    handle_customer_pack_drafts as _handle_customer_pack_drafts_request,
    handle_customer_pack_ingest as _handle_customer_pack_ingest_request,
    handle_customer_pack_delete_draft as _handle_customer_pack_delete_draft_request,
    handle_sessions_list as _handle_sessions_list_request,
    handle_session_load as _handle_session_load_request,
    handle_session_delete as _handle_session_delete_request,
    handle_sessions_delete_all as _handle_sessions_delete_all_request,
    handle_customer_pack_normalize as _handle_customer_pack_normalize_request,
    handle_customer_pack_plan as _handle_customer_pack_plan_request,
    handle_customer_pack_support_matrix as _handle_customer_pack_support_matrix_request,
    handle_customer_pack_upload_draft as _handle_customer_pack_upload_draft_request,
    handle_repository_favorites as _handle_repository_favorites_request,
    handle_repository_favorites_remove as _handle_repository_favorites_remove_request,
    handle_repository_favorites_save as _handle_repository_favorites_save_request,
    handle_repository_official_catalog_request as _handle_repository_official_catalog_request,
    handle_repository_official_materialize_request as _handle_repository_official_materialize_request,
    handle_repository_search as _handle_repository_search_request,
    handle_repository_unanswered as _handle_repository_unanswered_request,
    handle_runtime_figures as _handle_runtime_figures_request,
    handle_source_meta as _handle_source_meta_request,
    handle_viewer_document as _handle_viewer_document_request,
    handle_wiki_overlay_signals as _handle_wiki_overlay_signals_request,
    handle_wiki_user_overlay_remove as _handle_wiki_user_overlay_remove_request,
    handle_wiki_user_overlay_save as _handle_wiki_user_overlay_save_request,
    handle_wiki_user_overlays as _handle_wiki_user_overlays_request,
)
from play_book_studio.app.server_support import (
    DATA_CONTROL_ROOM_CACHE_TTL_SECONDS,
    _TimedValueCache,
    _build_chat_payload,
    _resolve_frontend_asset,
)
from play_book_studio.app.server_handler_base import _HandlerBase
from play_book_studio.app.session_owner import SessionOwner, resolve_session_owner
from play_book_studio.app.chat_debug import (
    append_unanswered_question_log as _append_unanswered_question_log,
    append_chat_turn_log as _append_chat_turn_log,
    build_session_debug_payload as _build_session_debug_payload,
    build_turn_diagnosis as _build_turn_diagnosis,
    build_turn_stages as _build_turn_stages,
    write_recent_chat_session_snapshot as _write_recent_chat_session_snapshot,
)
from play_book_studio.app.presenters import _build_health_payload, _llm_runtime_signature, _refresh_answerer_llm_settings
from play_book_studio.app.session_flow import context_with_request_overrides as _context_with_request_overrides, derive_next_context as _derive_next_context
from play_book_studio.app.sessions import ChatSession, SessionStore

if TYPE_CHECKING:
    from play_book_studio.answering.answerer import ChatAnswerer


def _build_handler(
    *,
    answerer: ChatAnswerer,
    store: SessionStore,
    root_dir: Path,
) -> type[BaseHTTPRequestHandler]:
    # REST endpoint를 answerer, session store, viewer, customer-pack helper에
    # 실제로 연결하는 구간이다.
    answerer_lock = threading.Lock()
    current_llm_signature = _llm_runtime_signature(answerer.settings)
    data_control_room_cache = _TimedValueCache(DATA_CONTROL_ROOM_CACHE_TTL_SECONDS)

    def current_answerer() -> ChatAnswerer:
        nonlocal answerer, current_llm_signature
        with answerer_lock:
            answerer, current_llm_signature = _refresh_answerer_llm_settings(
                answerer,
                root_dir=root_dir,
                current_signature=current_llm_signature,
            )
            return answerer

    class ChatHandler(_HandlerBase, BaseHTTPRequestHandler):
        server_version = "PlayBookStudio/0.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return None

        def _session_owner(self) -> SessionOwner:
            owner = getattr(self, "_resolved_session_owner", None)
            if isinstance(owner, SessionOwner):
                return owner
            owner = resolve_session_owner(self)
            self._resolved_session_owner = owner
            if owner.set_cookie_header:
                self._queue_response_header("Set-Cookie", owner.set_cookie_header)
            return owner

        def _session_store(self) -> SessionStore:
            return store.for_owner(self._session_owner().owner_hash)

        def do_GET(self) -> None:  # noqa: N802
            parsed_request = urlparse(self.path)
            request_path = parsed_request.path
            started_at = time.monotonic()
            if request_path.startswith("/assets/") or request_path in {"/", "/favicon.svg", "/studio", "/workspace", "/playbook-library", "/details"}:
                asset_path = _resolve_frontend_asset(
                    root_dir,
                    request_path if request_path.startswith("/assets/") or request_path == "/favicon.svg" else "/index.html",
                )
                if asset_path is not None:
                    content_type = mimetypes.guess_type(str(asset_path))[0] or "text/html; charset=utf-8"
                    self._send_bytes(asset_path.read_bytes(), content_type=content_type)
                    return
            if request_path.startswith(("/playbooks/wiki-runtime/", "/playbooks/customer-packs/", "/docs/", "/wiki/entities/", "/wiki/figures/", "/buyer-packets/")):
                viewer_html = _resolve_viewer_html(root_dir, self.path)
                if viewer_html is not None:
                    self._send_bytes(
                        viewer_html.encode("utf-8"),
                        content_type="text/html; charset=utf-8",
                    )
                    return
            if request_path.startswith("/playbooks/wiki-assets/"):
                relative = request_path.removeprefix("/playbooks/wiki-assets/").strip("/")
                asset_path = (root_dir / "data" / "wiki_assets" / relative).resolve()
                assets_root = (root_dir / "data" / "wiki_assets").resolve()
                if asset_path.is_file() and (asset_path == assets_root or assets_root in asset_path.parents):
                    content_type = mimetypes.guess_type(str(asset_path))[0] or "application/octet-stream"
                    self._send_bytes(asset_path.read_bytes(), content_type=content_type)
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            if request_path == "/api/health":
                self._send_json(_build_health_payload(current_answerer()))
                return
            if request_path == "/api/data-control-room":
                started_at = time.monotonic()
                self._handle_data_control_room(parsed_request.query)
                self._debug_timing("data-control-room", started_at)
                return
            if request_path == "/api/data-control-room/chunks":
                self._handle_data_control_room_chunks(parsed_request.query)
                return
            if request_path == "/api/buyer-packet":
                self._handle_buyer_packet(parsed_request.query)
                return
            if request_path == "/api/customer-packs/support-matrix":
                self._handle_customer_pack_support_matrix(parsed_request.query)
                return
            if request_path == "/api/sessions":
                self._handle_sessions_list(parsed_request.query)
                return
            if request_path == "/api/sessions/load":
                self._handle_session_load(parsed_request.query)
                return
            if request_path == "/api/debug/session":
                self._handle_debug_session(parsed_request.query)
                return
            if request_path == "/api/debug/chat-log":
                self._handle_debug_chat_log(parsed_request.query)
                return
            if request_path == "/api/source-meta":
                self._handle_source_meta(parsed_request.query)
                return
            if request_path == "/api/viewer-document":
                self._handle_viewer_document(parsed_request.query)
                return
            if request_path == "/api/runtime-figures":
                self._handle_runtime_figures(parsed_request.query)
                return
            if request_path == "/api/repositories/search":
                self._handle_repository_search(parsed_request.query)
                return
            if request_path == "/api/repositories/official-catalog":
                self._handle_repository_official_catalog(parsed_request.query)
                return
            if request_path == "/api/repositories/unanswered":
                self._handle_repository_unanswered(parsed_request.query)
                return
            if request_path == "/api/repositories/favorites":
                self._handle_repository_favorites(parsed_request.query)
                return
            if request_path == "/api/wiki-overlays":
                self._handle_wiki_user_overlays(parsed_request.query)
                return
            if request_path == "/api/wiki-overlay-signals":
                self._handle_wiki_overlay_signals(parsed_request.query)
                return
            if request_path == "/api/customer-packs/drafts":
                self._handle_customer_pack_drafts(parsed_request.query)
                return
            if request_path == "/api/customer-packs/book":
                self._handle_customer_pack_book(parsed_request.query)
                return
            if request_path == "/api/customer-packs/captured":
                self._handle_customer_pack_captured(parsed_request.query)
                return
            if request_path.startswith("/api/v1/"):
                if self._handle_course_get(request_path, parsed_request.query):
                    return
                if self._handle_ops_console_get(request_path, parsed_request.query):
                    return
            frontend_fallback = _resolve_frontend_asset(root_dir, request_path)
            if frontend_fallback is not None:
                content_type = mimetypes.guess_type(str(frontend_fallback))[0] or "application/octet-stream"
                self._send_bytes(frontend_fallback.read_bytes(), content_type=content_type)
                return
            if not request_path.startswith(("/api/", "/playbooks/", "/docs/", "/wiki/")):
                index_path = _resolve_frontend_asset(root_dir, "/index.html")
                if index_path is not None:
                    self._send_bytes(index_path.read_bytes(), content_type="text/html; charset=utf-8")
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed_request = urlparse(self.path)
            payload = self._parse_request_payload()
            if payload is None:
                return

            if parsed_request.path == "/api/chat":
                self._handle_chat(payload)
                return
            if parsed_request.path == "/api/chat/stream":
                self._handle_chat_stream(payload)
                return
            if parsed_request.path == "/api/sessions/delete":
                self._handle_session_delete(payload)
                return
            if parsed_request.path == "/api/sessions/delete-all":
                self._handle_sessions_delete_all(payload)
                return
            if parsed_request.path == "/api/customer-packs/plan":
                self._handle_customer_pack_plan(payload)
                return
            if parsed_request.path == "/api/customer-packs/drafts":
                self._handle_customer_pack_draft_create(payload)
                return
            if parsed_request.path == "/api/customer-packs/upload-draft":
                self._handle_customer_pack_upload_draft(payload)
                return
            if parsed_request.path == "/api/customer-packs/ingest":
                self._handle_customer_pack_ingest(payload)
                return
            if parsed_request.path == "/api/customer-packs/capture":
                self._handle_customer_pack_capture(payload)
                return
            if parsed_request.path == "/api/customer-packs/normalize":
                self._handle_customer_pack_normalize(payload)
                return
            if parsed_request.path == "/api/customer-packs/delete-draft":
                self._handle_customer_pack_delete_draft(payload)
                return
            if parsed_request.path == "/api/repositories/favorites":
                self._handle_repository_favorites_save(payload)
                return
            if parsed_request.path == "/api/repositories/favorites/remove":
                self._handle_repository_favorites_remove(payload)
                return
            if parsed_request.path == "/api/repositories/official-materialize":
                self._handle_repository_official_materialize(payload)
                return
            if parsed_request.path == "/api/wiki-overlays":
                self._handle_wiki_user_overlay_save(payload)
                return
            if parsed_request.path == "/api/wiki-overlays/remove":
                self._handle_wiki_user_overlay_remove(payload)
                return
            if parsed_request.path == "/api/reset":
                self._handle_reset(payload)
                return
            if parsed_request.path.startswith("/api/v1/"):
                if self._handle_course_post(parsed_request.path, payload):
                    return
                if self._handle_ops_console_post(parsed_request.path, parsed_request.query, payload):
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_PUT(self) -> None:  # noqa: N802
            parsed_request = urlparse(self.path)
            payload = self._parse_request_payload()
            if payload is None:
                return
            if parsed_request.path.startswith("/api/v1/"):
                if self._handle_ops_console_put(parsed_request.path, payload):
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_PATCH(self) -> None:  # noqa: N802
            parsed_request = urlparse(self.path)
            payload = self._parse_request_payload()
            if payload is None:
                return
            if parsed_request.path.startswith("/api/v1/"):
                if self._handle_ops_console_patch(parsed_request.path, payload):
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def _handle_source_meta(self, query: str) -> None:
            _handle_source_meta_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_viewer_document(self, query: str) -> None:
            _handle_viewer_document_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_repository_search(self, query: str) -> None:
            _handle_repository_search_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_runtime_figures(self, query: str) -> None:
            _handle_runtime_figures_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_repository_favorites(self, query: str) -> None:
            _handle_repository_favorites_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_repository_unanswered(self, query: str) -> None:
            _handle_repository_unanswered_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_repository_official_catalog(self, query: str) -> None:
            _handle_repository_official_catalog_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_wiki_user_overlays(self, query: str) -> None:
            _handle_wiki_user_overlays_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_wiki_overlay_signals(self, query: str) -> None:
            _handle_wiki_overlay_signals_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_data_control_room(self, query: str) -> None:
            del query
            cached_payload = data_control_room_cache.get("payload")
            if isinstance(cached_payload, dict):
                self._send_json(cached_payload)
                return
            payload = _handle_data_control_room_request(
                self,
                "",
                root_dir=root_dir,
            )
            if payload is not None:
                data_control_room_cache.set("payload", payload)

        def _handle_buyer_packet(self, query: str) -> None:
            _handle_buyer_packet_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_data_control_room_chunks(self, query: str) -> None:
            _handle_data_control_room_chunks_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_sessions_list(self, query: str) -> None: _handle_sessions_list_request(self, query, store=self._session_store())
        def _handle_session_load(self, query: str) -> None:
            _handle_session_load_request(self, query, store=self._session_store(), legacy_store=store)
        def _handle_session_delete(self, payload: dict[str, Any]) -> None: _handle_session_delete_request(self, payload, store=self._session_store())
        def _handle_sessions_delete_all(self, payload: dict[str, Any]) -> None: _handle_sessions_delete_all_request(self, payload, store=self._session_store())

        def _handle_debug_session(self, query: str) -> None:
            _handle_debug_session_request(
                self,
                query,
                store=self._session_store(),
                legacy_store=store,
                build_session_debug_payload=_build_session_debug_payload,
            )

        def _handle_debug_chat_log(self, query: str) -> None:
            _handle_debug_chat_log_request(
                self,
                query,
                root_dir=root_dir,
            )

        def _handle_customer_pack_plan(self, payload: dict[str, Any]) -> None: _handle_customer_pack_plan_request(self, payload)
        def _handle_customer_pack_support_matrix(self, query: str) -> None: _handle_customer_pack_support_matrix_request(self, query, root_dir=root_dir)
        def _handle_customer_pack_drafts(self, query: str) -> None: _handle_customer_pack_drafts_request(self, query, root_dir=root_dir)
        def _handle_customer_pack_captured(self, query: str) -> None: _handle_customer_pack_captured_request(self, query, root_dir=root_dir)
        def _handle_customer_pack_book(self, query: str) -> None: _handle_customer_pack_book_request(self, query, root_dir=root_dir)
        def _handle_customer_pack_draft_create(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_draft_create_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_customer_pack_upload_draft(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_upload_draft_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_customer_pack_ingest(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_ingest_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_customer_pack_capture(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_capture_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_customer_pack_normalize(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_normalize_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_customer_pack_delete_draft(self, payload: dict[str, Any]) -> None:
            _handle_customer_pack_delete_draft_request(self, payload, root_dir=root_dir)
            data_control_room_cache.set("payload", None)
        def _handle_repository_favorites_save(self, payload: dict[str, Any]) -> None: _handle_repository_favorites_save_request(self, payload, root_dir=root_dir)
        def _handle_repository_favorites_remove(self, payload: dict[str, Any]) -> None: _handle_repository_favorites_remove_request(self, payload, root_dir=root_dir)
        def _handle_repository_official_materialize(self, payload: dict[str, Any]) -> None:
            result = _handle_repository_official_materialize_request(self, payload, root_dir=root_dir)
            if result is not None:
                data_control_room_cache.set("payload", None)
        def _handle_wiki_user_overlay_save(self, payload: dict[str, Any]) -> None: _handle_wiki_user_overlay_save_request(self, payload, root_dir=root_dir)
        def _handle_wiki_user_overlay_remove(self, payload: dict[str, Any]) -> None: _handle_wiki_user_overlay_remove_request(self, payload, root_dir=root_dir)

        def _handle_chat(self, payload: dict[str, Any]) -> None:
            _handle_chat_request(
                self,
                payload,
                current_answerer=current_answerer,
                store=self._session_store(),
                root_dir=root_dir,
                build_chat_payload=_build_chat_payload,
                context_with_request_overrides=_context_with_request_overrides,
                derive_next_context=_derive_next_context,
                append_chat_turn_log=_append_chat_turn_log,
                append_unanswered_question_log=_append_unanswered_question_log,
                write_recent_chat_session_snapshot=_write_recent_chat_session_snapshot,
                build_turn_stages=_build_turn_stages,
                build_turn_diagnosis=_build_turn_diagnosis,
            )

        def _handle_chat_stream(self, payload: dict[str, Any]) -> None:
            _handle_chat_stream_request(
                self,
                payload,
                current_answerer=current_answerer,
                store=self._session_store(),
                root_dir=root_dir,
                build_chat_payload=_build_chat_payload,
                context_with_request_overrides=_context_with_request_overrides,
                derive_next_context=_derive_next_context,
                append_chat_turn_log=_append_chat_turn_log,
                append_unanswered_question_log=_append_unanswered_question_log,
                write_recent_chat_session_snapshot=_write_recent_chat_session_snapshot,
                build_turn_stages=_build_turn_stages,
                build_turn_diagnosis=_build_turn_diagnosis,
            )

        def _handle_reset(self, payload: dict[str, Any]) -> None:
            session_id = str(payload.get("session_id") or uuid.uuid4().hex)
            session = self._session_store().reset(session_id)
            self._send_json(
                {
                    "session_id": session.session_id,
                    "mode": session.mode,
                    "context": session.context.to_dict(),
                }
            )

        def _handle_ops_console_get(self, request_path: str, query: str) -> bool:
            return bool(_handle_ops_console_get_request(self, request_path, query, root_dir=root_dir))

        def _handle_course_get(self, request_path: str, query: str) -> bool:
            return bool(_handle_course_get_request(self, request_path, query, root_dir=root_dir))

        def _handle_ops_console_post(self, request_path: str, query: str, payload: dict[str, Any]) -> bool:
            return bool(_handle_ops_console_post_request(self, request_path, query, payload, root_dir=root_dir, answerer=current_answerer()))

        def _handle_course_post(self, request_path: str, payload: dict[str, Any]) -> bool:
            return bool(_handle_course_post_request(self, request_path, payload, root_dir=root_dir, store=self._session_store()))

        def _handle_ops_console_put(self, request_path: str, payload: dict[str, Any]) -> bool:
            return bool(_handle_ops_console_put_request(self, request_path, payload, root_dir=root_dir))

        def _handle_ops_console_patch(self, request_path: str, payload: dict[str, Any]) -> bool:
            return bool(_handle_ops_console_patch_request(self, request_path, payload, root_dir=root_dir))

    return ChatHandler


__all__ = ["_build_handler"]
