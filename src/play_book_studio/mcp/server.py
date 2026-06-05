"""Minimal HTTP wrapper for the optional PBS MCP boundary.

The transport is intentionally small for Phase 1. It exposes the read-only tool
catalog and a JSON invoke endpoint that can later be replaced by a full MCP
transport without changing the underlying tool handlers.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from play_book_studio.mcp.boundary import execute_read_only_tool, list_pbs_mcp_tools


class PBSMcpHandler(BaseHTTPRequestHandler):
    server_version = "PBSMCP/0.3.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/healthz":
            self._send_json({"ok": True})
            return
        if self.path == "/tools":
            self._send_json({"tools": [tool.__dict__ for tool in list_pbs_mcp_tools()]})
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/invoke":
            self.send_error(404, "Not found")
            return
        try:
            payload = self._read_json()
            result = execute_read_only_tool(
                str(payload.get("tool") or ""),
                payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
                root_dir=Path("."),
            )
        except Exception as exc:  # pragma: no cover - exercised by integration smoke later
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"result": result})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        body = self.rfile.read(length) if length > 0 else b"{}"
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), PBSMcpHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
