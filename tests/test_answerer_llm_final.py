import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.config.settings import Settings
from play_book_studio.integrations.lightspeed import OpenShiftLightspeedResult
from play_book_studio.retrieval.models import RetrievalHit, RetrievalResult, SessionContext


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


class CustomerUploadRetriever:
    def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        del kwargs
        hit = RetrievalHit(
            chunk_id="ci-webhook",
            book_slug="uploaded-documents",
            chapter="CI 순서",
            section="Webhook 설정",
            anchor="ci-webhook",
            source_url="uploads/sources/ci.pdf",
            viewer_path="/uploads/documents/11111111-1111-1111-1111-111111111111/index.html#ci-webhook",
            text=(
                "고객 CI 순서 문서에서는 GitHub Webhook Payload URL에 smee URL을 넣고, "
                "Webhook secret을 OpenShift 쪽 secret과 맞추도록 설명합니다."
            ),
            source="hybrid",
            raw_score=0.98,
            fused_score=0.98,
            section_path=("CI 순서", "Webhook 설정"),
            chunk_type="procedure",
            source_lane="user_upload",
            source_type="uploaded_document",
            source_collection="uploads",
            review_status="private",
            semantic_role="uploaded_document",
            block_kinds=("text", "image"),
            component_scores={"bm25_score": 0.98},
            source_scope="user_upload",
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


class HanbitUploadRetriever:
    def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        del kwargs
        hit = RetrievalHit(
            chunk_id="hanbit-pipelinerun-check",
            book_slug="uploaded-documents",
            chapter="한빛리테일 OCP 운영 준비 현황 및 CI/CD 연결 기준",
            section="PipelineRun이 생성되지 않을 때 고객사 기준 점검 순서",
            anchor="hanbit-pipelinerun-check",
            source_url="uploads/sources/hanbit.pdf",
            viewer_path="/uploads/documents/ac6d5577-50f4-43fa-acc1-f77f4b235626/index.html#hanbit-pipelinerun-check",
            text=(
                "한빛리테일 운영자료 기준으로 PipelineRun이 생성되지 않으면 GitHub Webhook "
                "Delivery와 Payload URL, smee.io 릴레이 상태, OpenShift Secret 일치 여부를 "
                "먼저 확인합니다. Repository 이름 hanbit-payments-api-repository namespace ci-pipelines "
                "기준으로 Repository CR과 PipelineRun을 확인합니다. Pipelines as Code controller는 "
                "openshift-pipelines namespace의 로그를 확인합니다."
            ),
            source="hybrid",
            raw_score=0.99,
            fused_score=0.99,
            section_path=(
                "한빛리테일 OCP 운영 준비 현황 및 CI/CD 연결 기준",
                "PipelineRun이 생성되지 않을 때 고객사 기준 점검 순서",
            ),
            chunk_type="procedure",
            source_lane="user_upload",
            source_type="uploaded_document",
            source_collection="uploads",
            review_status="private",
            semantic_role="uploaded_document",
            block_kinds=("text",),
            component_scores={"bm25_score": 0.99},
            source_scope="user_upload",
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


class ConsoleRetriever:
    def retrieve(self, query: str, **kwargs: Any) -> RetrievalResult:
        del kwargs
        hit = RetrievalHit(
            chunk_id="web-console-workloads",
            book_slug="web_console",
            chapter="Web console",
            section="웹 콘솔에서 프로젝트와 워크로드 보기",
            anchor="web-console-workloads",
            source_url="https://docs.example.test/web-console",
            viewer_path="/docs/ocp/4.20/ko/web_console/index.html#web-console-workloads",
            text="Use the OpenShift web console to select projects and view workloads and applications.",
            source="hybrid",
            raw_score=0.95,
            fused_score=0.95,
            chunk_type="reference",
            source_collection="core",
            review_status="approved",
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


class ConsoleLlmClient(FakeLlmClient):
    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        del kwargs
        self.calls.append(messages)
        return "답변: 웹 콘솔에서 프로젝트를 선택한 뒤 Workloads 영역에서 워크로드와 애플리케이션을 확인합니다 [1]."


class HanbitLlmClient(FakeLlmClient):
    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        del kwargs
        self.calls.append(messages)
        return (
            "답변: 한빛리테일 운영자료 기준으로는 PipelineRun이 보이지 않을 때 먼저 GitHub Webhook "
            "Delivery와 Payload URL이 맞는지 확인하고, smee.io 릴레이와 OpenShift Secret 값이 "
            "서로 일치하는지 순서대로 점검합니다 [1]."
        )


class CustomerContextLlmClient(FakeLlmClient):
    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        del kwargs
        self.calls.append(messages)
        return (
            "답변: OpenShift 공식 기준으로는 PipelineRun 생성 주체와 이벤트를 먼저 확인하고, "
            "고객 문서 기준으로는 GitHub Webhook Payload URL, smee.io relay, Webhook secret을 "
            "같이 점검해야 합니다 [1]."
        )


class PlaceholderCustomerContextLlmClient(FakeLlmClient):
    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        del kwargs
        self.calls.append(messages)
        return (
            "답변: 한빛리테일 기준으로는 PipelineRun과 Repository CR을 먼저 확인해야 합니다 [1].\n\n"
            "1. PipelineRun 확인: `oc get pipelinerun -n <namespace>`로 생성 여부를 봅니다.\n"
            "2. Repository CR 확인: `oc get repository -n <namespace>`로 Webhook 연결 객체를 봅니다.\n"
            "3. 상세 확인: `oc describe repository <name> -n <namespace>`로 이벤트를 확인합니다.\n\n"
            "```bash\noc get pipelinerun -n <namespace>\n```"
        )


class FakeLightspeedClient:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, query: str, **kwargs: Any) -> OpenShiftLightspeedResult:
        del kwargs
        self.calls.append(query)
        return OpenShiftLightspeedResult(
            answer=(
                "Pod 또는 PVC가 Pending 상태이면 Events에서 scheduling 또는 binding 실패 사유를 "
                "먼저 확인하고, 리소스 request와 quota 조건을 비교합니다."
            ),
            referenced_documents=[{"title": "OpenShift troubleshooting"}],
        )


class CustomerContextDenialLightspeedClient:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, query: str, **kwargs: Any) -> OpenShiftLightspeedResult:
        del kwargs
        self.calls.append(query)
        return OpenShiftLightspeedResult(
            answer=(
                "죄송하지만, 현재 제가 접근할 수 있는 정보에는 '한빛 리테일'의 운영 자료가 "
                "포함되어 있지 않습니다. 자료를 주시면 분석해 드리겠습니다."
            ),
            referenced_documents=[{"title": "OpenShift Lightspeed overview"}],
        )


class ToolNameThenCliLightspeedClient:
    is_configured = True

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query(self, query: str, **kwargs: Any) -> OpenShiftLightspeedResult:
        request_profile = str(kwargs.get("request_profile") or "console_parity")
        self.calls.append({"query": query, "request_profile": request_profile})
        if request_profile == "operator_cli_quality":
            return OpenShiftLightspeedResult(
                answer=(
                    "먼저 `oc describe pod <pod_name> -n <namespace>`로 Events 섹션을 확인하고, "
                    "`oc get events -n <namespace> --sort-by='.lastTimestamp'`로 네임스페이스 이벤트를 봅니다. "
                    "이후 `oc logs <pod_name> -n <namespace>`로 로그를 확인합니다."
                ),
                request_metadata={"request_profile": "operator_cli_quality", "payload_keys": ["query", "system_prompt"]},
                quality={
                    "internal_tool_names": [],
                    "internal_tool_name_count": 0,
                    "cli_command_count": 3,
                    "cli_command_samples": ["oc describe pod", "oc get events", "oc logs"],
                    "passes_operator_cli_quality": True,
                },
            )
        return OpenShiftLightspeedResult(
            answer="먼저 `events_list`로 이벤트를 보고 `pods_log`로 로그를 확인합니다.",
            request_metadata={"request_profile": "console_parity", "payload_keys": ["query"]},
            quality={
                "internal_tool_names": ["events_list", "pods_log"],
                "internal_tool_name_count": 2,
                "cli_command_count": 0,
                "cli_command_samples": [],
                "passes_operator_cli_quality": False,
            },
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


def test_web_console_locator_is_not_blocked_as_command_query(tmp_path: Path) -> None:
    llm = ConsoleLlmClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=ConsoleRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
    )

    result = answerer.answer("OpenShift 웹 콘솔에서 프로젝트와 워크로드를 확인하려면 어디를 봐야 해?")

    assert llm.calls
    assert result.response_kind == "rag"
    assert result.citations[0].book_slug == "web_console"
    assert "insufficient command grounding coverage" not in result.warnings
    assert not any(
        event.get("step") == "grounding_guard" and event.get("status") == "error"
        for event in result.pipeline_trace["events"]
    )


def test_openshift_lightspeed_answer_is_returned_without_pbs_llm_rewrite(tmp_path: Path) -> None:
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
    assert not llm.calls
    assert "LLM 최종 답변입니다" not in result.answer
    assert "Events에서 scheduling 또는 binding 실패 사유" in result.answer
    assert "[1]" in result.answer
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert steps.index("openshift_lightspeed") < steps.index("retrieval")
    assert "lightspeed_answer_passthrough" in steps


def test_openshift_lightspeed_query_normalizes_common_korean_typo(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer("클러스터 이벤트중 워닝만 필터링할수잇어?")

    assert lightspeed.calls == ["클러스터 이벤트중 워닝만 필터링할수있어?"]
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["normalized_query"] == "클러스터 이벤트중 워닝만 필터링할수있어?"
    assert not llm.calls


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


def test_lightspeed_quality_retry_replaces_internal_tool_name_answer(tmp_path: Path) -> None:
    lightspeed = ToolNameThenCliLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=FakeLlmClient(),  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer("이벤트와 로그는 어떤 명령으로 먼저 확인해?")

    assert lightspeed.calls == [
        {"query": "이벤트와 로그는 어떤 명령으로 먼저 확인해?", "request_profile": "console_parity"},
        {"query": "이벤트와 로그는 어떤 명령으로 먼저 확인해?", "request_profile": "operator_cli_quality"},
    ]
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    external_answer = result.pipeline_trace["external_answer"]
    assert external_answer["request_profile"] == "operator_cli_quality"
    assert external_answer["quality"]["passes_operator_cli_quality"] is True
    assert external_answer["quality_retry"]["initial_quality"]["internal_tool_name_count"] == 2
    assert "events_list" not in result.answer
    assert "pods_log" not in result.answer
    assert "oc describe pod" in result.answer
    assert "oc logs" in result.answer


def test_lvmcluster_storage_cr_question_calls_lightspeed(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    query = "LVMCluster CR을 CLI로 생성할 때 storageClass와 deviceSelector는 어떻게 지정하나요?"
    result = answerer.answer(query)

    assert lightspeed.calls == [query]
    assert not llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "used"


def test_lightspeed_is_not_skipped_when_source_scope_is_explicitly_restricted(tmp_path: Path) -> None:
    llm = FakeLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer(
        "PVC가 Pending이면 무엇을 먼저 확인해야 해?",
        context=SessionContext(enabled_source_scopes=["user_upload"]),
    )

    assert lightspeed.calls == ["PVC가 Pending이면 무엇을 먼저 확인해야 해?"]
    assert not llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "used"
    assert "Events에서 scheduling 또는 binding 실패 사유" in result.answer


def test_lightspeed_success_records_customer_upload_context_bridge(tmp_path: Path) -> None:
    llm = CustomerContextLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=CustomerUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer("OpenShift PipelineRun이 안 뜨면 어디부터 확인해?")

    assert lightspeed.calls == ["OpenShift PipelineRun이 안 뜨면 어디부터 확인해?"]
    assert llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    context_bridge = result.pipeline_trace["external_answer"]["context_bridge"]
    assert context_bridge["customer_context_applied"] is True
    assert context_bridge["customer_context_citation_count"] == 1
    assert context_bridge["bridge_label"] == "OpenShift Lightspeed + Customer Context"
    assert result.pipeline_trace["external_answer"]["customer_context_synthesis"]["status"] == "used"
    assert result.citations[0].viewer_path.startswith("/uploads/documents/")
    assert "Webhook Payload URL" in result.answer
    user_prompt = llm.calls[0][-1]["content"]
    assert "OpenShift Lightspeed 공식 답변:" in user_prompt
    assert "GitHub Webhook Payload URL" in user_prompt
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert "customer_context_bridge" in steps
    assert "lightspeed_customer_context_synthesis" in steps
    assert "lightspeed_answer_passthrough" not in steps


def test_lightspeed_customer_context_denial_uses_available_upload_context(tmp_path: Path) -> None:
    llm = HanbitLlmClient()
    lightspeed = CustomerContextDenialLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=HanbitUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    query = "그럼 한빛 리테일의 운영자료 기준으로 답해줄 수 있어?"
    result = answerer.answer(
        query,
        context=SessionContext(
            current_topic="OpenShift PipelineRun이 생성되지 않을 때 점검 순서",
            open_entities=["PipelineRun", "GitHub Webhook", "OpenShift"],
        ),
    )

    assert len(lightspeed.calls) == 1
    assert "OpenShift PipelineRun이 생성되지 않을 때 점검 순서" in lightspeed.calls[0]
    assert query in lightspeed.calls[0]
    assert "PBS 고객/업로드 운영자료 context" in lightspeed.calls[0]
    assert "PipelineRun이 생성되지 않을 때 고객사 기준 점검 순서" in lightspeed.calls[0]
    assert llm.calls
    assert result.pipeline_trace["answer_source"] == "pbs_rag"
    external_answer = result.pipeline_trace["external_answer"]
    assert external_answer["status"] == "ignored_customer_context_denial"
    assert external_answer["original_status"] == "used"
    assert external_answer["customer_context_sent_to_lightspeed"] is True
    assert external_answer["customer_context_prefetch"]["status"] == "used"
    assert external_answer["customer_context_synthesis"]["status"] == "used"
    assert result.citations[0].source_scope == "user_upload"
    assert "한빛리테일 운영자료 기준" in result.answer
    assert "접근할 수 있는 정보" not in result.answer
    user_prompt = llm.calls[0][-1]["content"]
    assert "OpenShift Lightspeed 공식 답변:" not in user_prompt
    assert "접근할 수 있는 정보" not in user_prompt
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert "customer_context_synthesis" in steps
    assert "lightspeed_answer_passthrough" not in steps


def test_pipeline_user_upload_follow_up_calls_lightspeed(tmp_path: Path) -> None:
    llm = CustomerContextLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=CustomerUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    query = "내 GIT 저장소를 파이프라인에 연결 기준으로 주의사항을 정리해줘"
    result = answerer.answer(
        query,
        context=SessionContext(
            active_document_id="11111111-1111-1111-1111-111111111111",
            enabled_source_scopes=["user_upload"],
        ),
    )

    assert len(lightspeed.calls) == 1
    assert query in lightspeed.calls[0]
    assert "PBS 고객/업로드 운영자료 context" in lightspeed.calls[0]
    assert "GitHub Webhook Payload URL" in lightspeed.calls[0]
    assert llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert result.pipeline_trace["external_answer"]["status"] == "used"
    assert result.pipeline_trace["external_answer"]["customer_context_sent_to_lightspeed"] is True
    assert result.pipeline_trace["external_answer"]["context_bridge"]["customer_context_applied"] is True
    assert result.pipeline_trace["external_answer"]["customer_context_synthesis"]["status"] == "used"
    assert result.citations[0].source_scope == "user_upload"


def test_customer_context_only_follow_up_calls_lightspeed_with_upload_context(tmp_path: Path) -> None:
    llm = CustomerContextLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=HanbitUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    query = "한빛리테일 기준으로 설명가능?"
    result = answerer.answer(
        query,
        context=SessionContext(
            current_topic="OpenShift PipelineRun이 생성되지 않을 때 점검 순서",
            open_entities=["PipelineRun", "GitHub Webhook", "OpenShift"],
        ),
    )

    assert len(lightspeed.calls) == 1
    assert "OpenShift PipelineRun이 생성되지 않을 때 점검 순서" in lightspeed.calls[0]
    assert "후속 질문: 한빛리테일 기준으로 설명가능?" in lightspeed.calls[0]
    assert "PBS 고객/업로드 운영자료 context" in lightspeed.calls[0]
    assert "PipelineRun이 생성되지 않을 때 고객사 기준 점검 순서" in lightspeed.calls[0]
    assert llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    external_answer = result.pipeline_trace["external_answer"]
    assert external_answer["status"] == "used"
    assert external_answer["routing_reason"] == "contextual_openshift_follow_up"
    assert external_answer["query_augmented"] is True
    assert external_answer["customer_context_sent_to_lightspeed"] is True
    assert external_answer["customer_context_prefetch"]["status"] == "used"
    assert external_answer["context_bridge"]["customer_context_applied"] is True
    assert external_answer["customer_context_synthesis"]["status"] == "used"
    assert result.citations[0].source_scope == "user_upload"


def test_customer_context_commands_are_concretized_for_copy_paste(tmp_path: Path) -> None:
    llm = PlaceholderCustomerContextLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=HanbitUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer(
        "한빛리테일 기준으로 PipelineRun 안뜰 때 뭐부터 확인해?",
        context=SessionContext(
            current_topic="OpenShift PipelineRun이 생성되지 않을 때 점검 순서",
            open_entities=["PipelineRun", "Repository CR", "OpenShift"],
        ),
    )

    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    assert "`oc get pipelinerun -n <namespace>`" not in result.answer
    assert "`oc get repository -n <namespace>`" not in result.answer
    assert "`oc describe repository <name> -n <namespace>`" not in result.answer
    assert "`oc get pipelinerun -n ci-pipelines`" not in result.answer
    assert "`oc get repository -n ci-pipelines`" not in result.answer
    assert "제공된 근거에는 실행 명령이나 예시 코드가 명시되어 있지 않습니다" not in result.answer
    assert "```bash\n# PipelineRun 리소스 생성 여부 확인\noc get pipelinerun -n ci-pipelines\n```" in result.answer
    assert "```bash\n# Repository CR 목록 확인\noc get repository -n ci-pipelines\n```" in result.answer
    assert (
        "```bash\n# Repository CR 상세 확인\n"
        "oc describe repository hanbit-payments-api-repository -n ci-pipelines\n```"
    ) in result.answer
    external_answer = result.pipeline_trace["external_answer"]
    assert external_answer["customer_context_values"]["pipeline_namespace"] == "ci-pipelines"
    assert external_answer["customer_context_values"]["repository_name"] == "hanbit-payments-api-repository"
    assert external_answer["customer_context_command_cards"]["command_card_count"] >= 3


def test_contextual_pipeline_troubleshooting_follow_up_calls_lightspeed(tmp_path: Path) -> None:
    llm = CustomerContextLlmClient()
    lightspeed = FakeLightspeedClient()
    answerer = ChatAnswerer(
        Settings(root_dir=tmp_path),
        retriever=CustomerUploadRetriever(),  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        lightspeed_client=lightspeed,  # type: ignore[arg-type]
    )

    result = answerer.answer(
        "흔한 실패지점은 뭐야?",
        context=SessionContext(
            current_topic="CI 순서 > 내 GIT저장소를 파이프라인에 연결",
            open_entities=["파이프라인", "Git 저장소", "Webhook"],
            active_document_id="11111111-1111-1111-1111-111111111111",
            enabled_source_scopes=["user_upload"],
        ),
    )

    assert len(lightspeed.calls) == 1
    assert "CI 순서 > 내 GIT저장소를 파이프라인에 연결" in lightspeed.calls[0]
    assert "후속 질문: 흔한 실패지점은 뭐야?" in lightspeed.calls[0]
    assert llm.calls
    assert result.pipeline_trace["answer_source"] == "lightspeed_with_pbs_rag"
    external_answer = result.pipeline_trace["external_answer"]
    assert external_answer["status"] == "used"
    assert external_answer["routing_reason"] == "contextual_openshift_follow_up"
    assert external_answer["query_augmented"] is True
    assert external_answer["context_bridge"]["customer_context_applied"] is True
    assert external_answer["customer_context_synthesis"]["status"] == "used"
    assert result.citations[0].source_scope == "user_upload"


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
    assert not llm.calls
    assert "FailedScheduling" in result.answer
    assert "[1]" in result.answer
    steps = [event.get("step") for event in result.pipeline_trace["events"]]
    assert steps.index("openshift_lightspeed") < steps.index("retrieval")
    assert "lightspeed_answer_passthrough" in steps
