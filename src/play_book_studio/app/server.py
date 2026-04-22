"""Play Book Studio HTTP runtime entrypoint."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from play_book_studio.answering.answerer import ChatAnswerer

from .server_handler_factory import _build_handler
from .sessions import ChatSession, SessionStore


def _warmup_runtime_components(answerer: ChatAnswerer) -> None:
    reranker = getattr(getattr(answerer, "retriever", None), "reranker", None)
    if reranker is None:
        return
    try:
        warmed = reranker.warmup()
    except Exception as exc:  # noqa: BLE001
        print(f"[server] reranker warmup failed: {exc}")
        return
    if warmed:
        print(f"[server] reranker warmed: {reranker.model_name}")


def _start_runtime_warmup(answerer: ChatAnswerer) -> threading.Thread | None:
    reranker = getattr(getattr(answerer, "retriever", None), "reranker", None)
    if reranker is None:
        return None
    thread = threading.Thread(
        target=_warmup_runtime_components,
        args=(answerer,),
        name="pbs-runtime-warmup",
        daemon=True,
    )
    thread.start()
    return thread


def serve(
    *,
    answerer: ChatAnswerer,
    root_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    store = SessionStore(root_dir)
    handler = _build_handler(answerer=answerer, store=store, root_dir=root_dir)
    server = ThreadingHTTPServer((host, port), handler)
    backend_url = f"http://{host}:{port}"
    print(f"Play Book Studio runtime/API server running at {backend_url}")
    _start_runtime_warmup(answerer)
    if open_browser:
        import webbrowser

        webbrowser.open(backend_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = [
    "ChatSession",
    "SessionStore",
    "_start_runtime_warmup",
    "_warmup_runtime_components",
    "serve",
]
