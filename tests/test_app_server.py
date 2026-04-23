from __future__ import annotations

import tempfile
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from play_book_studio.app import server
from play_book_studio.app.server_support import _build_chat_payload
from play_book_studio.app.sessions import ChatSession
from play_book_studio.answering.models import AnswerResult
from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.models import SessionContext


class _FakeReranker:
    def __init__(self) -> None:
        self.model_name = "fake-reranker"
        self.warmup_calls = 0

    def warmup(self) -> bool:
        self.warmup_calls += 1
        return True


class _FakeThread:
    def __init__(self, *, target, args, name, daemon) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1


class _FakeLlmClient:
    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
        }


class _FakeAnswerer:
    def __init__(self, root: Path) -> None:
        self.settings = load_settings(root)
        self.llm_client = _FakeLlmClient()
        self.retriever = SimpleNamespace(reranker=None)


def _write_frontend_shell(root: Path) -> None:
    dist_dir = root / "presentation-ui" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body><div id='pbs-shell'>shared-shell</div></body></html>",
        encoding="utf-8",
    )


@contextmanager
def _test_server(root: Path):
    answerer = _FakeAnswerer(root)
    store = server.SessionStore(root)
    handler = server._build_handler(answerer=answerer, store=store, root_dir=root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_start_runtime_warmup_skips_when_reranker_missing() -> None:
    answerer = SimpleNamespace(retriever=SimpleNamespace(reranker=None))

    with patch("play_book_studio.app.server.threading.Thread") as thread_mock:
        thread = server._start_runtime_warmup(answerer)

    assert thread is None
    thread_mock.assert_not_called()


def test_start_runtime_warmup_starts_daemon_thread_when_reranker_present() -> None:
    answerer = SimpleNamespace(retriever=SimpleNamespace(reranker=_FakeReranker()))
    created_threads: list[_FakeThread] = []

    def _build_thread(*, target, args, name, daemon):
        thread = _FakeThread(target=target, args=args, name=name, daemon=daemon)
        created_threads.append(thread)
        return thread

    with patch("play_book_studio.app.server.threading.Thread", side_effect=_build_thread):
        thread = server._start_runtime_warmup(answerer)

    assert thread is created_threads[0]
    assert thread.target is server._warmup_runtime_components
    assert thread.args == (answerer,)
    assert thread.name == "pbs-runtime-warmup"
    assert thread.daemon is True
    assert thread.start_calls == 1


def test_spa_deep_links_return_index_html_for_pbs_surfaces() -> None:
    spa_routes = (
        "/",
        "/details",
        "/studio",
        "/workspace",
        "/llmwikibook",
        "/studio-v2",
        "/playbook-library",
        "/playbook-library/control-tower",
        "/playbook-library/repository",
        "/workspaces",
        "/connections",
        "/models",
        "/overview",
        "/resources",
        "/library",
        "/chat",
        "/actions",
        "/scm",
        "/partner",
        "/partner/workspace",
        "/partner/library",
        "/partner/viewer",
        "/partner/details",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _write_frontend_shell(root)

        with _test_server(root) as base_url:
            for route in spa_routes:
                response = requests.get(f"{base_url}{route}", timeout=10)

                assert response.status_code == 200, route
                assert response.headers["Content-Type"].startswith("text/html"), route
                assert "<!DOCTYPE html>" in response.text, route
                assert "pbs-shell" in response.text, route


def test_runtime_namespaces_resolve_viewer_html_instead_of_shared_spa_shell() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _write_frontend_shell(root)

        with _test_server(root) as base_url:
            response = requests.get(f"{base_url}/wiki/entities/etcd/index.html", timeout=10)

        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("text/html")
        assert "OCP 출처 뷰어" in response.text
        assert "pbs-shell" not in response.text


def test_build_chat_payload_includes_runtime_compact_graph_artifact() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        answerer = _FakeAnswerer(root)
        session = ChatSession(
            session_id="session-runtime",
            context=SessionContext(mode="chat", ocp_version=answerer.settings.ocp_version),
        )
        result = AnswerResult(
            query="runtime probe",
            mode="chat",
            answer="ok",
            rewritten_query="runtime probe",
            citations=[],
            response_kind="rag",
        )

        payload = _build_chat_payload(
            root_dir=root,
            answerer=answerer,
            session=session,
            result=result,
        )

        runtime = payload.get("runtime")
        assert isinstance(runtime, dict)
        assert isinstance(runtime.get("graph_compact_artifact"), dict)
        assert "config_fingerprint" in runtime
