from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from play_book_studio.app.course_api import (
    course_viewer_html,
    course_viewer_source_meta,
    handle_course_get,
    handle_course_post,
)

_BODY_RE = re.compile(r"<body[^>]*>(?P<body>.*)</body>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>(?P<style>.*?)</style>", re.IGNORECASE | re.DOTALL)


def _frontend_path(root_dir: Path, request_path: str) -> Path | None:
    dist = root_dir / "presentation-ui" / "dist"
    normalized_path = request_path.strip("/")
    has_file_suffix = bool(Path(normalized_path).suffix)
    if request_path in {"", "/"} or not has_file_suffix:
        path = dist / "index.html"
    else:
        path = dist / normalized_path
    try:
        resolved = path.resolve()
        dist_resolved = dist.resolve()
    except OSError:
        return None
    if not resolved.is_file() or (resolved != dist_resolved and dist_resolved not in resolved.parents):
        return None
    return resolved


def _course_viewer_document_payload(viewer_path: str, html_text: str) -> dict[str, Any]:
    body_match = _BODY_RE.search(html_text)
    body_html = body_match.group("body") if body_match else html_text
    inline_styles = [
        match.group("style")
        for match in _STYLE_RE.finditer(html_text)
        if str(match.group("style") or "").strip()
    ]
    return {
        "viewer_path": viewer_path,
        "body_class_name": "course-viewer-document",
        "inline_styles": inline_styles,
        "html": body_html,
        "interaction_policy": {
            "code_copy": True,
            "code_wrap_toggle": True,
            "recent_position_tracking": True,
            "anchor_navigation": True,
        },
    }


def build_handler(root_dir: Path) -> type[BaseHTTPRequestHandler]:
    class CourseAuditHandler(BaseHTTPRequestHandler):
        server_version = "PlayBookStudioCourseAudit/0.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return None

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, body: bytes, *, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _parse_request_payload(self) -> dict[str, Any] | None:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length else b""
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON request"}, HTTPStatus.BAD_REQUEST)
                return None
            return payload if isinstance(payload, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/v1/") and handle_course_get(self, parsed.path, parsed.query, root_dir=root_dir):
                return
            if parsed.path == "/api/source-meta":
                params = parse_qs(parsed.query, keep_blank_values=False)
                viewer_path = str((params.get("viewer_path") or [""])[0]).strip()
                meta = course_viewer_source_meta(root_dir, viewer_path)
                if meta is None:
                    self._send_json({"error": "Unsupported course viewer_path"}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(meta)
                return
            if parsed.path == "/api/viewer-document":
                params = parse_qs(parsed.query, keep_blank_values=False)
                viewer_path = str((params.get("viewer_path") or [""])[0]).strip()
                html = course_viewer_html(root_dir, viewer_path)
                if html is None:
                    self._send_json({"error": "Course viewer document not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(_course_viewer_document_payload(viewer_path, html))
                return
            asset = _frontend_path(root_dir, parsed.path)
            if asset is not None:
                content_type = mimetypes.guess_type(str(asset))[0] or "text/html; charset=utf-8"
                self._send_bytes(asset.read_bytes(), content_type=content_type)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            payload = self._parse_request_payload()
            if payload is None:
                return
            if parsed.path.startswith("/api/v1/") and handle_course_post(self, parsed.path, payload, root_dir=root_dir):
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    return CourseAuditHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve only course UI/API for Playwright visual audits.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8876)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root_dir = args.root_dir.resolve()
    server = ThreadingHTTPServer((args.host, args.port), build_handler(root_dir))
    print(f"Course audit server running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
