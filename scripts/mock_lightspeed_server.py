from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json({"status": "ok"})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/authorized":
            self._write_json({"status": "authorized"})
            return

        if self.path != "/v1/query":
            self.send_response(404)
            self.end_headers()
            return

        self._write_json(
            {
                "response": (
                    "Mock Lightspeed: Pod Pending 상태에서는 Events의 FailedScheduling 여부, "
                    "노드 allocatable, request, quota를 먼저 확인합니다.\n\n"
                    "```bash\n"
                    "oc describe pod <pod-name>\n"
                    "oc get events -n <namespace>\n"
                    "```"
                ),
                "referenced_documents": [{"title": "Mock OpenShift Pod troubleshooting"}],
                "truncated": False,
                "echo_query": payload.get("query", ""),
            }
        )

    def _write_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
