import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from play_book_studio.cli import (
    _run_lightspeed_integration_smoke,
    _run_lightspeed_auth_smoke,
    _run_lightspeed_chat_smoke,
    _run_lightspeed_smoke,
)
from play_book_studio.config.settings import Settings
from play_book_studio.integrations.lightspeed import (
    OpenShiftLightspeedApiError,
    OpenShiftLightspeedClient,
    is_openshift_operation_question,
    normalize_lightspeed_query,
)


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "response": "Pod Pending이면 Events와 resource request를 확인합니다.",
            "conversation_id": "conv-1",
            "referenced_documents": [{"title": "Pods"}],
            "truncated": False,
            "input_tokens": 11,
            "output_tokens": 22,
            "available_quotas": {"user": 1000},
            "tool_calls": [{"name": "cluster_status"}],
            "tool_results": [{"name": "cluster_status", "status": "ok"}],
        }


class FakeErrorResponse:
    status_code = 403
    text = ""

    def raise_for_status(self) -> None:
        raise requests.HTTPError("403 Client Error")

    def json(self) -> dict[str, Any]:
        return {
            "detail": {
                "response": "Forbidden",
                "cause": "User does not have ols-user role",
            }
        }


class FakeValidationErrorResponse:
    status_code = 422
    text = ""

    def raise_for_status(self) -> None:
        raise requests.HTTPError("422 Client Error")

    def json(self) -> dict[str, Any]:
        return {
            "detail": [
                {
                    "type": "value_error",
                    "loc": ["body"],
                    "msg": "Value error, LLM provider must be specified when the model is specified.",
                    "input": {"query": "Pod Pending이면?", "model": "model-a"},
                }
            ]
        }


class FakeAuthOkResponse:
    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        return {"status": "authorized"}


class FakeStreamResponse:
    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines = lines

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode: bool = False):
        del decode_unicode
        for line in self.lines:
            yield json.dumps(line, ensure_ascii=False)


class FakeViewerResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")

    def json(self) -> dict[str, Any]:
        return self.payload


def test_lightspeed_client_posts_to_query_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
            openshift_lightspeed_api_token="token-value",
            openshift_lightspeed_provider="provider-a",
            openshift_lightspeed_model="model-a",
        )
    )

    result = client.query("Pod Pending이면?")

    assert result.answer == "Pod Pending이면 Events와 resource request를 확인합니다."
    assert result.conversation_id == "conv-1"
    assert result.referenced_documents == [{"title": "Pods"}]
    assert result.input_tokens == 11
    assert result.output_tokens == 22
    assert result.available_quotas == {"user": 1000}
    assert result.tool_calls == [{"name": "cluster_status"}]
    assert result.tool_results == [{"name": "cluster_status", "status": "ok"}]
    assert calls[0]["url"] == "https://lightspeed.example.test/v1/query"
    assert calls[0]["json"]["query"] == "Pod Pending이면?"
    assert calls[0]["json"]["provider"] == "provider-a"
    assert calls[0]["json"]["model"] == "model-a"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-value"
    assert calls[0]["verify"] is True


def test_lightspeed_client_normalizes_common_korean_typo_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
        )
    )

    client.query("클러스터 이벤트중 워닝만 필터링할수잇어?")

    assert normalize_lightspeed_query("클러스터 이벤트중 워닝만 필터링할수잇어?") == "클러스터 이벤트중 워닝만 필터링할수있어?"
    assert calls[0]["json"]["query"].startswith("클러스터 이벤트중 워닝만 필터링할수있어?")


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://lightspeed.example.test/", "https://lightspeed.example.test/v1/query"),
        ("https://lightspeed.example.test/v1/query", "https://lightspeed.example.test/v1/query"),
        ("https://lightspeed.example.test/v1/query/", "https://lightspeed.example.test/v1/query"),
        ("https://lightspeed.example.test/api/v1/query", "https://lightspeed.example.test/api/v1/query"),
    ],
)
def test_lightspeed_client_accepts_base_or_full_query_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_url: str,
    expected_url: str,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url=base_url,
        )
    )

    client.query("Pod Pending이면?")

    assert calls[0]["url"] == expected_url


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://lightspeed.example.test/", "https://lightspeed.example.test/authorized"),
        ("https://lightspeed.example.test/v1/query", "https://lightspeed.example.test/authorized"),
        ("https://lightspeed.example.test/v1/query/", "https://lightspeed.example.test/authorized"),
        ("https://lightspeed.example.test/api/v1/query", "https://lightspeed.example.test/api/authorized"),
    ],
)
def test_lightspeed_client_builds_authorized_url(tmp_path: Path, base_url: str, expected_url: str) -> None:
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url=base_url,
        )
    )

    assert client.authorized_url == expected_url


def test_lightspeed_client_can_disable_tls_verification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
            openshift_lightspeed_verify_tls=False,
        )
    )

    client.query("Pod Pending이면?")

    assert calls[0]["verify"] is False


def test_lightspeed_client_checks_authorized_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeAuthOkResponse:
        calls.append({"url": url, **kwargs})
        return FakeAuthOkResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
            openshift_lightspeed_api_token="token-value",
        )
    )

    result = client.check_authorized()

    assert result.authorized is True
    assert result.status_code == 200
    assert calls[0]["url"] == "https://lightspeed.example.test/authorized"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-value"


def test_lightspeed_client_reports_api_error_detail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_post(url: str, **kwargs: Any) -> FakeErrorResponse:
        del url, kwargs
        return FakeErrorResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
        )
    )

    with pytest.raises(OpenShiftLightspeedApiError) as exc_info:
        client.query("Pod Pending이면?")

    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail
    assert "ols-user" in exc_info.value.detail


def test_lightspeed_client_reports_validation_error_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_post(url: str, **kwargs: Any) -> FakeValidationErrorResponse:
        del url, kwargs
        return FakeValidationErrorResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
        )
    )

    with pytest.raises(OpenShiftLightspeedApiError) as exc_info:
        client.query("Pod Pending이면?")

    assert exc_info.value.status_code == 422
    assert "body" in exc_info.value.detail
    assert "provider must be specified" in exc_info.value.detail


def test_lightspeed_client_reports_not_authorized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_post(url: str, **kwargs: Any) -> FakeErrorResponse:
        del url, kwargs
        return FakeErrorResponse()

    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)
    client = OpenShiftLightspeedClient(
        Settings(
            root_dir=tmp_path,
            openshift_lightspeed_base_url="https://lightspeed.example.test",
        )
    )

    result = client.check_authorized()

    assert result.authorized is False
    assert result.status_code == 403
    assert "Forbidden" in result.detail


def test_openshift_operation_question_detector() -> None:
    assert is_openshift_operation_question("Pod Pending 상태에서 무엇을 확인해야 해?")
    assert is_openshift_operation_question("oc get events 명령은 언제 써?")
    assert is_openshift_operation_question("포드가 대기 상태일 때 스케줄링 이벤트는 어디서 봐?")
    assert is_openshift_operation_question("네임스페이스 권한과 롤바인딩 확인 방법 알려줘")
    assert is_openshift_operation_question("사용자 권한은 어떤 명령으로 확인해?")
    assert is_openshift_operation_question("ServiceAccount가 어떤 권한을 갖는지 확인하려면?")
    assert is_openshift_operation_question("다른 사용자 기준으로 권한을 테스트하려면 oc auth can-i에 뭘 붙여?")
    assert is_openshift_operation_question("루트와 서비스 연결 상태를 확인하고 싶어")
    assert is_openshift_operation_question("클러스터 이벤트중 워닝만 필터링할수잇어?")
    assert is_openshift_operation_question("내 GIT 저장소를 파이프라인에 연결 기준으로 주의사항을 정리해줘")
    assert is_openshift_operation_question("git 저장소를 파이프라인에 연결하는 절차에서 흔한 실패지점은 뭐야?")
    assert is_openshift_operation_question("Pipelines as Code webhook 호출 실패 지점은 뭐야?")
    assert is_openshift_operation_question("Tekton PipelineRun이 생성되지 않으면 어디부터 확인해?")
    assert is_openshift_operation_question("Ingress 컨트롤러에 단일 NodePort 서비스 추가 내용을 초보자용 3단계로 다시 정리해줘")
    assert is_openshift_operation_question(
        "Operator 설치 후 CSV가 정상 전환되지 않을 때 Subscription, InstallPlan, ClusterServiceVersion 상태를 어떤 순서로 확인하나요?"
    )
    assert not is_openshift_operation_question("안녕 오늘 날씨 어때?")
    assert not is_openshift_operation_question("서비스 기획 회의 안건 정리해줘")
    assert not is_openshift_operation_question("내 Git 저장소 이름을 바꾸는 방법 알려줘")


def test_lightspeed_smoke_reports_disabled_when_endpoint_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENSHIFT_LIGHTSPEED_BASE_URL", raising=False)
    monkeypatch.delenv("OPENSHIFT_LIGHTSPEED_API_TOKEN", raising=False)

    exit_code = _run_lightspeed_smoke(
        SimpleNamespace(
            root_dir=tmp_path,
            query="Pod Pending이면?",
            conversation_id="",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["configured"] is False
    assert payload["status"] == "disabled"


def test_lightspeed_auth_smoke_reports_disabled_when_endpoint_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENSHIFT_LIGHTSPEED_BASE_URL", raising=False)
    monkeypatch.delenv("OPENSHIFT_LIGHTSPEED_API_TOKEN", raising=False)

    exit_code = _run_lightspeed_auth_smoke(SimpleNamespace(root_dir=tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["configured"] is False
    assert payload["status"] == "disabled"


def test_lightspeed_auth_smoke_calls_authorized_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeAuthOkResponse:
        calls.append({"url": url, **kwargs})
        return FakeAuthOkResponse()

    monkeypatch.setenv("OPENSHIFT_LIGHTSPEED_BASE_URL", "https://lightspeed.example.test")
    monkeypatch.setenv("OPENSHIFT_LIGHTSPEED_API_TOKEN", "token-value")
    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)

    exit_code = _run_lightspeed_auth_smoke(SimpleNamespace(root_dir=tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["configured"] is True
    assert payload["status"] == "success"
    assert payload["status_code"] == 200
    assert calls[0]["url"] == "https://lightspeed.example.test/authorized"


def test_lightspeed_auth_smoke_returns_three_when_forbidden(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_post(url: str, **kwargs: Any) -> FakeErrorResponse:
        del url, kwargs
        return FakeErrorResponse()

    monkeypatch.setenv("OPENSHIFT_LIGHTSPEED_BASE_URL", "https://lightspeed.example.test")
    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)

    exit_code = _run_lightspeed_auth_smoke(SimpleNamespace(root_dir=tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["status"] == "not_authorized"
    assert payload["status_code"] == 403
    assert "Forbidden" in payload["detail"]


def _print_payload(exit_code: int, payload: dict[str, Any]):
    def runner(args: Any) -> int:
        del args
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code

    return runner


def test_lightspeed_integration_smoke_reports_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "play_book_studio.cli._run_lightspeed_auth_smoke",
        _print_payload(2, {"status": "disabled"}),
    )

    exit_code = _run_lightspeed_integration_smoke(
        SimpleNamespace(
            root_dir=tmp_path,
            ui_base_url="http://pbs.example.test",
            query="Pod Pending이면?",
            conversation_id="",
            session_id="integration-smoke",
            timeout_seconds=3,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "disabled"
    assert payload["steps"]["auth"]["exit_code"] == 2


def test_lightspeed_integration_smoke_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "play_book_studio.cli._run_lightspeed_auth_smoke",
        _print_payload(0, {"status": "success"}),
    )
    monkeypatch.setattr(
        "play_book_studio.cli._run_lightspeed_smoke",
        _print_payload(0, {"status": "success", "answer_length": 10}),
    )
    monkeypatch.setattr(
        "play_book_studio.cli._run_lightspeed_chat_smoke",
        _print_payload(
            0,
            {
                "status": "success",
                "answer_source": "lightspeed_with_pbs_rag",
                "external_viewer_path": "/external/lightspeed/unit-test",
                "lightspeed_related_link_present": True,
            },
        ),
    )

    def fake_get(url: str, **kwargs: Any) -> FakeViewerResponse:
        del kwargs
        if url.endswith("/api/source-meta"):
            return FakeViewerResponse(
                {
                    "title": "OpenShift Lightspeed 공식 답변",
                    "boundary_badge": "Lightspeed",
                    "source_lane": "openshift_lightspeed",
                }
            )
        if url.endswith("/api/viewer-document"):
            return FakeViewerResponse(
                {
                    "html": (
                        "<h1>OpenShift Lightspeed 공식 답변</h1>"
                        "<span>Lightspeed</span>"
                    )
                }
            )
        return FakeViewerResponse({}, status_code=404)

    monkeypatch.setattr("requests.get", fake_get)

    exit_code = _run_lightspeed_integration_smoke(
        SimpleNamespace(
            root_dir=tmp_path,
            ui_base_url="http://pbs.example.test",
            query="Pod Pending이면?",
            conversation_id="",
            session_id="integration-smoke",
            timeout_seconds=3,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["steps"]["auth"]["exit_code"] == 0
    assert payload["steps"]["query"]["exit_code"] == 0
    assert payload["steps"]["chat"]["exit_code"] == 0
    assert payload["steps"]["viewer"]["source_meta_ready"] is True
    assert payload["steps"]["viewer"]["viewer_document_ready"] is True


def test_lightspeed_smoke_calls_configured_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setenv("OPENSHIFT_LIGHTSPEED_BASE_URL", "https://lightspeed.example.test")
    monkeypatch.setenv("OPENSHIFT_LIGHTSPEED_API_TOKEN", "token-value")
    monkeypatch.setattr("play_book_studio.integrations.lightspeed.requests.post", fake_post)

    exit_code = _run_lightspeed_smoke(
        SimpleNamespace(
            root_dir=tmp_path,
            query="Pod Pending이면?",
            conversation_id="smoke-1",
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["configured"] is True
    assert payload["status"] == "success"
    assert payload["answer_length"] > 0
    assert payload["referenced_document_count"] == 1
    assert calls[0]["url"] == "https://lightspeed.example.test/v1/query"
    assert calls[0]["json"]["conversation_id"] == "smoke-1"


def test_lightspeed_chat_smoke_reports_success_for_stream_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeStreamResponse:
        calls.append({"url": url, **kwargs})
        return FakeStreamResponse(
            [
                {"type": "trace", "step": "openshift_lightspeed", "status": "done"},
                {"type": "answer_delta", "delta": "답변"},
                {
                    "type": "result",
                    "payload": {
                        "answer": "답변: Lightspeed 답변입니다.",
                        "answer_source": "lightspeed_with_pbs_rag",
                        "pipeline_trace": {
                            "external_answer": {
                                "status": "used",
                                "viewer_path": "/external/lightspeed/unit-test",
                            },
                        },
                        "related_links": [
                            {
                                "href": "/external/lightspeed/unit-test",
                                "boundary_badge": "Lightspeed",
                                "source_lane": "openshift_lightspeed",
                            }
                        ],
                    },
                },
            ]
        )

    monkeypatch.setattr("requests.post", fake_post)

    exit_code = _run_lightspeed_chat_smoke(
        SimpleNamespace(
            ui_base_url="http://pbs.example.test",
            query="Pod Pending이면?",
            session_id="chat-smoke-1",
            timeout_seconds=3,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "success"
    assert payload["answer_source"] == "lightspeed_with_pbs_rag"
    assert payload["lightspeed_related_link_present"] is True
    assert calls[0]["url"] == "http://pbs.example.test/api/chat/stream"
    assert calls[0]["json"]["session_id"] == "chat-smoke-1"


def test_lightspeed_chat_smoke_returns_two_when_chat_did_not_use_lightspeed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_post(url: str, **kwargs: Any) -> FakeStreamResponse:
        del url, kwargs
        return FakeStreamResponse(
            [
                {
                    "type": "result",
                    "payload": {
                        "answer": "답변: PBS 내부 답변입니다.",
                        "answer_source": "pbs_rag",
                        "pipeline_trace": {},
                        "related_links": [],
                    },
                },
            ]
        )

    monkeypatch.setattr("requests.post", fake_post)

    exit_code = _run_lightspeed_chat_smoke(
        SimpleNamespace(
            ui_base_url="http://pbs.example.test",
            query="Pod Pending이면?",
            session_id="chat-smoke-2",
            timeout_seconds=3,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "not_lightspeed"
    assert payload["answer_source"] == "pbs_rag"
