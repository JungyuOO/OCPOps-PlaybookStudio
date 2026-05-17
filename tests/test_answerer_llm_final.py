from pathlib import Path
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.config.settings import Settings
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
