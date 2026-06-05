from __future__ import annotations

import json
import tempfile
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from play_book_studio.answering.models import AnswerResult
from play_book_studio.http import server
from play_book_studio.config.settings import load_settings


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
        self.last_query = ""

    def answer(self, query: str, **kwargs) -> AnswerResult:
        del kwargs
        self.last_query = query
        return AnswerResult(
            query=query,
            mode="chat",
            answer="답변: OpenShift Lightspeed 공식 답변과 PBS 근거를 함께 반영했습니다.",
            rewritten_query=query,
            citations=[],
            cited_indices=[],
            pipeline_trace={
                "answer_source": "lightspeed_with_pbs_rag",
                "external_answer": {
                    "status": "used",
                    "viewer_path": "/external/lightspeed/http-test",
                    "label": "OpenShift Lightspeed 공식 답변",
                    "source_lane": "openshift_lightspeed",
                    "boundary_truth": "external_openshift_lightspeed",
                    "runtime_truth_label": "OpenShift Lightspeed",
                    "boundary_badge": "Lightspeed",
                },
            },
        )

    def append_log(self, result: AnswerResult) -> None:
        del result


def _write_frontend_shell(root: Path) -> None:
    dist_dir = root / "apps" / "web" / "dist"
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


def test_start_runtime_warmup_starts_daemon_thread_when_reranker_missing() -> None:
    answerer = SimpleNamespace(retriever=SimpleNamespace(reranker=None))
    root_dir = Path("fake-root")
    created_threads: list[_FakeThread] = []

    def _build_thread(*, target, args, name, daemon):
        thread = _FakeThread(target=target, args=args, name=name, daemon=daemon)
        created_threads.append(thread)
        return thread

    with patch("play_book_studio.http.server.threading.Thread", side_effect=_build_thread):
        thread = server._start_runtime_warmup(answerer, root_dir)

    assert thread is created_threads[0]
    assert thread.target is server._warmup_runtime_components
    assert thread.args == (answerer, root_dir)
    assert thread.name == "pbs-runtime-warmup"
    assert thread.daemon is True
    assert thread.start_calls == 1


def test_start_runtime_warmup_starts_daemon_thread_when_reranker_present() -> None:
    answerer = SimpleNamespace(retriever=SimpleNamespace(reranker=_FakeReranker()))
    root_dir = Path("fake-root")
    created_threads: list[_FakeThread] = []

    def _build_thread(*, target, args, name, daemon):
        thread = _FakeThread(target=target, args=args, name=name, daemon=daemon)
        created_threads.append(thread)
        return thread

    with patch("play_book_studio.http.server.threading.Thread", side_effect=_build_thread):
        thread = server._start_runtime_warmup(answerer, root_dir)

    assert thread is created_threads[0]
    assert thread.target is server._warmup_runtime_components
    assert thread.args == (answerer, root_dir)
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


def test_chat_payload_exposes_lightspeed_answer_source_and_related_link() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _write_frontend_shell(root)

        with _test_server(root) as base_url:
            response = requests.post(
                f"{base_url}/api/chat",
                json={
                    "session_id": "lightspeed-session",
                    "query": "Pod Pending 상태면 무엇을 먼저 확인해야 해?",
                },
                timeout=10,
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["answer_source"] == "lightspeed_with_pbs_rag"
        assert payload["pipeline_trace"]["external_answer"]["status"] == "used"
        assert payload["primary_source_lane"] == "openshift_lightspeed"
        assert payload["primary_boundary_truth"] == "external_openshift_lightspeed"
        assert payload["primary_runtime_truth_label"] == "OpenShift Lightspeed"
        assert payload["primary_boundary_badge"] == "Lightspeed"
        assert payload["related_links"][0]["href"] == "/external/lightspeed/http-test"
        assert payload["related_links"][0]["boundary_badge"] == "Lightspeed"
        assert payload["related_links"][0]["source_lane"] == "openshift_lightspeed"
        log_path = load_settings(root).lightspeed_call_log_path
        log_payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        assert log_payload["record_kind"] == "openshift_lightspeed_call_audit"
        assert log_payload["status"] == "used"
        assert log_payload["answer_source"] == "lightspeed_with_pbs_rag"
        assert log_payload["badge_applied"] is True
        assert log_payload["related_link_present"] is True
        assert log_payload["viewer_path"] == "/external/lightspeed/http-test"
        assert log_payload["provider"] == ""
        assert log_payload["model"] == ""


def test_chat_stream_result_exposes_lightspeed_answer_source_and_related_link() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _write_frontend_shell(root)

        with _test_server(root) as base_url:
            response = requests.post(
                f"{base_url}/api/chat/stream",
                json={
                    "session_id": "lightspeed-stream-session",
                    "query": "Pod Pending 상태면 무엇을 먼저 확인해야 해?",
                },
                timeout=10,
            )

        assert response.status_code == 200
        events = [
            line
            for line in (response.text or "").splitlines()
            if line.strip()
        ]
        payload_events = [event for event in (json.loads(line) for line in events) if event.get("type") == "result"]
        assert payload_events
        payload = payload_events[-1]["payload"]
        assert payload["answer_source"] == "lightspeed_with_pbs_rag"
        assert payload["pipeline_trace"]["external_answer"]["status"] == "used"
        assert payload["primary_source_lane"] == "openshift_lightspeed"
        assert payload["primary_boundary_truth"] == "external_openshift_lightspeed"
        assert payload["primary_runtime_truth_label"] == "OpenShift Lightspeed"
        assert payload["primary_boundary_badge"] == "Lightspeed"
        assert payload["related_links"][0]["href"] == "/external/lightspeed/http-test"
        assert payload["related_links"][0]["boundary_badge"] == "Lightspeed"
        assert payload["related_links"][0]["source_lane"] == "openshift_lightspeed"
        log_path = load_settings(root).lightspeed_call_log_path
        log_payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
        assert log_payload["status"] == "used"
        assert log_payload["badge_applied"] is True
        assert log_payload["viewer_path"] == "/external/lightspeed/http-test"
