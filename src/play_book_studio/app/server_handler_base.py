from __future__ import annotations

import json
import sys
import time
from http import HTTPStatus
from typing import Any

from play_book_studio.app.server_support import _parse_multipart_form_data


class _HandlerBase:
    def _debug_timing(self, label: str, started_at: float) -> None:
        elapsed = time.monotonic() - started_at
        print(f"[timing] {label} {elapsed:.3f}s", file=sys.stderr, flush=True)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        body: bytes,
        *,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _start_ndjson_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _stream_event(self, payload: dict[str, Any]) -> None:
        try:
            body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _parse_request_payload(self) -> dict[str, Any] | None:
        raw_content_type = str(self.headers.get("Content-Type") or "").strip()
        content_type = raw_content_type.lower()
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b""
        if content_type.startswith("multipart/form-data"):
            return _parse_multipart_form_data(raw_body, raw_content_type)
        try:
            return json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "잘못된 JSON 요청입니다."}, HTTPStatus.BAD_REQUEST)
            return None


__all__ = ["_HandlerBase"]
