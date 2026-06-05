import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.config.settings import Settings
from play_book_studio.integrations.lightspeed import OpenShiftLightspeedResult
from play_book_studio.retrieval.models import RetrievalHit, RetrievalResult


class FakeRetriever:
    def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        del kwargs
        hit = RetrievalHit(
            chunk_id="storage-pvc",
            book_slug="storage",
            chapter="Storage",
            section="PVC Pending troubleshooting",
            anchor="pvc-pending",
            source_url="https://docs.example.test/storage",
            viewer_path="/docs/ocp/4.20/ko/storage/index.html#pvc-pending",
            text=(
                "PVC가 Pending 상태이면 먼저 PVC 목록을 확인하고 이벤트를 확인합니다.\n"
                "```shell\n$ oc get pvc\n$ oc describe pvc <pvc-name>\n```"
            ),
            source="hybrid",
            raw_score=0.95,
            fused_score=0.95,
            chunk_type="troubleshooting",
            source_collection="core",
            review_status="approved",
            cli_commands=("oc get pvc", "oc describe pvc <pvc-name>"),
            error_strings=("Pending",),
            k8s_objects=("PVC", "StorageClass"),
            component_scores={"bm25_score": 0.95},
        )
        return RetrievalResult(
            query=query,
            normalized_query=query,
            rewritten_query=query,
            top_k=5,
            candidate_k=10,
            context={},
            hits=[hit],
            trace={"route": "rag"},
        )


class WeakCommandRetriever:
    def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        del kwargs
        hit = RetrievalHit(
            chunk_id="weak-architecture",
            book_slug="architecture",
            chapter="Architecture",
            section="Architecture overview",
            anchor="overview",
            source_url="https://docs.example.test/architecture",
            viewer_path="/docs/ocp/4.20/ko/architecture/index.html#overview",
            text="OpenShift architecture overview only.",
            source="hybrid",
            raw_score=0.3,
            fused_score=0.3,
            chunk_type="reference",
            source_collection="core",
            review_status="approved",
            component_scores={"bm25_score": 0.3},
        )
        return RetrievalResult(
            query=query,
            normalized_query=query,
            rewritten_query=query,
            top_k=5,
            candidate_k=10,
            context={},
            hits=[hit],
            trace={"route": "rag"},
        )


class FakeLlmClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        del kwargs
        self.calls.append(messages)
        return (
            "답변: LLM 최종 답변입니다. PVC가 원하는 상태인지 먼저 목록에서 확인하고, "
            "Pending이면 같은 PVC의 이벤트를 describe로 좁혀서 StorageClass나 바인딩 오류를 확인하세요 [1].\n\n"
            "```bash\noc get pvc\noc describe pvc <pvc-name>\n```"
            "\n\n출력에서 STATUS와 Events를 같이 보면 다음 조치 대상을 빠르게 좁힐 수 있습니다 [1]."
        )

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "preferred_provider": "fake",
            "last_provider": "fake",
            "last_fallback_used": False,
            "last_attempted_providers": ["fake"],
        }


class FakeLightspeedClient:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, query: str) -> OpenShiftLightspeedResult:
        self.calls.append(query)
        return OpenShiftLightspeedResult(
            answer=(
                "Pod 또는 PVC가 Pending 상태이면 Events에서 scheduling 또는 binding 실패 사유를 "
                "먼저 확인하고, 리소스 request와 quota 조건을 비교합니다."
            ),
            referenced_documents=[{"title": "OpenShift troubleshooting"}],
        )


class LocalLightspeedHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        self.__class__.calls.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "payload": payload,
            }
        )
        if self.path != "/v1/query":
            self.send_response(404)
            self.end_headers()
            return
        response = {
            "response": (
                "Pod Pending 상태에서는 Events의 FailedScheduling 여부와 "
                "request, quota, node allocatable 값을 먼저 확인합니다."
            ),
            "conversation_id": "conv-local-1",
            "referenced_documents": [{"title": "OpenShift pod troubleshooting"}],
            "truncated": False,
            "input_tokens": 10,
            "output_tokens": 20,
        }
        raw = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _start_local_lightspeed_server() -> tuple[ThreadingHTTPServer, str]:
    LocalLightspeedHandler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalLightspeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_grounded_command_answer_is_rewritten_by_answer_llm(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
    )

    result = answerer.answer("PVC 상태 확인 명령 알려줘")

    assert llm.calls
    assert result.response_kind == "rag"
    assert "LLM 최종 답변입니다" in result.answer
    prompt_text = "\n".join(message["content"] for message in llm.calls[0])
    assert "Grounded answer draft for final LLM rewrite" not in prompt_text
    assert "oc get pvc" in prompt_text
    assert not any(event.get("step") == "deterministic_draft" for event in result.pipeline_trace["events"])
    assert any(event.get("step") == "llm_runtime" for event in result.pipeline_trace["events"])


def test_openshift_lightspeed_answer_is_used_as_pbs_answer_material(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer("PVC가 Pending이면 무엇을 먼저 확인해야 해?")

    assert lightspeed.calls == ["PVC가 Pending이면 무엇을 먼저 확인해야 해?"]
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "used"
    assert result.citations
    prompt_text = "\n".join(message["content"] for message in llm.calls[0])
    assert "OpenShift Lightspeed 공식 답변" in prompt_text
    assert "citation은 PBS 근거 번호만 사용하세요" in prompt_text
    assert "Events에서 scheduling 또는 binding 실패 사유" in prompt_text
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert steps.index("openshift_lightspeed") < steps.index("retrieval")


def test_lightspeed_success_is_not_blocked_by_pbs_rbac_grounding_guard(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer("특정 namespace에서 pods delete 권한이 있는지 어떻게 확인해?")

    assert lightspeed.calls == ["특정 namespace에서 pods delete 권한이 있는지 어떻게 확인해?"]
    assert result.response_kind == "rag"
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert not any(
        event.get("step") == "grounding_guard" and event.get("status") == "error"
        for event in result.pipeline_trace["events"]
    )


def test_lightspeed_disabled_note_survives_grounding_blocked_path(tmp_path: Path) -> None:
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=WeakCommandRetriever(),  # type: ignore[arg-type]
        llm_client=FakeLlmClient(),  # type: ignore[arg-type]
    )

    result = answerer.answer("oc delete pod 명령을 알려줘")

    assert result.response_kind == "no_answer"
    assert "OpenShift Lightspeed 연결이 설정되지 않아 현재 PBS 내부 근거로 답변합니다." in result.answer
    assert "현재 Playbook Library에 해당 자료가 없습니다" in result.answer
    assert result.pipeline_trace["answer_source"] == "pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "disabled"


def test_answerer_calls_configured_lightspeed_http_endpoint_before_pbs_retrieval(tmp_path: Path) -> None:
    server, base_url = _start_local_lightspeed_server()
    try:
        llm = FakeLlmClient()
        answerer = ChatAnswerer(
            Settings(
                root_dir=tmp_path,
                openshift_lightspeed_base_url=base_url,
                openshift_lightspeed_api_token="unit-token",
            ),
            retriever=FakeRetriever(),  # type: ignore[arg-type]
            llm_client=llm,  # type: ignore[arg-type]
        )

        result = answerer.answer("Pod Pending 상태면 무엇을 먼저 확인해야 해?")
    finally:
        server.shutdown()
        server.server_close()

    assert LocalLightspeedHandler.calls
    assert LocalLightspeedHandler.calls[0]["path"] == "/v1/query"
    assert LocalLightspeedHandler.calls[0]["authorization"] == "Bearer unit-token"
    assert LocalLightspeedHandler.calls[0]["payload"]["query"] == "Pod Pending 상태면 무엇을 먼저 확인해야 해?"
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "used"
    assert result.pipeline_trace["external_answer"]["conversation_id"] == "conv-local-1"
    assert result.pipeline_trace["external_answer"]["input_tokens"] == 10
    assert result.pipeline_trace["external_answer"]["output_tokens"] == 20
    assert result.pipeline_trace["external_answer"]["viewer_path"].startswith("/external/lightspeed/")
    artifact_path = (
        tmp_path
        / "artifacts"
        / "external_answers"
        / "lightspeed"
        / f"{result.pipeline_trace['external_answer']['artifact_id']}.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["conversation_id"] == "conv-local-1"
    assert artifact["input_tokens"] == 10
    assert artifact["output_tokens"] == 20
    prompt_text = "\n".join(message["content"] for message in llm.calls[0])
    assert "FailedScheduling" in prompt_text
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert steps.index("openshift_lightspeed") < steps.index("retrieval")
