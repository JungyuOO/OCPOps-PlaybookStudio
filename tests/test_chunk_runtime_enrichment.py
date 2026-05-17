from __future__ import annotations

from types import SimpleNamespace

import play_book_studio.ingestion.chunking as chunking_module
from play_book_studio.ingestion.chunk_question_candidates import build_chunk_question_candidates
from play_book_studio.ingestion.chunking import chunk_sections
from play_book_studio.ingestion.models import NormalizedSection


class _FakeTokenCounter:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def count(self, text: str) -> int:
        return max(1, len(text.split()))


class _FakeQuestionLlm:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def generate(self, messages, *, max_tokens=None):  # noqa: ANN001
        del max_tokens
        self.messages.append(messages)
        return (
            '{"starter_question_candidates":["Pod 상태는 어디서 먼저 확인하면 될까요?",'
            '"Pod 문제를 좁히려면 어떤 명령부터 보면 될까요?"],'
            '"followup_question_candidates":["oc describe pod 결과에서는 무엇을 봐야 할까요?"]}'
        )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        embedding_model="dragonkue/bge-m3-ko",
        chunk_size=120,
        chunk_overlap=0,
        question_candidate_llm_client=_FakeQuestionLlm(),
    )


def test_chunk_sections_emit_parent_and_leaf_runtime_metadata(monkeypatch) -> None:
    monkeypatch.setattr(chunking_module, "TokenCounter", _FakeTokenCounter)
    section = NormalizedSection(
        book_slug="applications",
        book_title="Applications",
        heading="Pod 상태 확인",
        section_level=2,
        section_path=["Applications", "Pod 상태 확인"],
        anchor="pod-status",
        source_url="https://docs.example/pods",
        viewer_path="/docs/pods",
        text="\n\n".join(
            [
                "Pod가 Running인지 확인하려면 먼저 현재 namespace의 Pod 목록을 봅니다.",
                "[CODE]oc get pods -n pbs-test[/CODE]",
                "자세한 이벤트와 컨테이너 상태는 describe 결과에서 확인합니다.",
                "[CODE]oc describe pod example -n pbs-test[/CODE]",
            ]
        ),
        semantic_role="procedure",
        block_kinds=("paragraph", "code"),
        cli_commands=("oc get pods -n pbs-test", "oc describe pod example -n pbs-test"),
        k8s_objects=("Pod",),
    )

    chunks = chunk_sections([section], _settings())

    leaves = [chunk for chunk in chunks if chunk.chunk_role == "leaf"]
    parents = [chunk for chunk in chunks if chunk.chunk_role == "parent"]
    assert leaves
    assert len(parents) == 1
    parent = parents[0]
    assert parent.child_chunk_ids == tuple(chunk.chunk_id for chunk in leaves)
    assert all(chunk.parent_chunk_id == parent.chunk_id for chunk in leaves)
    assert parent.starter_question_candidates
    assert parent.followup_question_candidates
    assert parent.question_candidates_version == 2
    assert all(not chunk.starter_question_candidates for chunk in leaves)
    assert all(not chunk.followup_question_candidates for chunk in leaves)


def test_navigation_only_sections_are_flagged_before_indexing(monkeypatch) -> None:
    monkeypatch.setattr(chunking_module, "TokenCounter", _FakeTokenCounter)
    section = NormalizedSection(
        book_slug="overview",
        book_title="Overview",
        heading="관련 문서",
        section_level=2,
        section_path=["Overview", "관련 문서"],
        anchor="related-docs",
        source_url="https://docs.example/overview",
        viewer_path="/docs/overview",
        text="관련 문서\nOpen document\nClose",
        semantic_role="reference",
        block_kinds=("reference",),
    )

    chunks = chunk_sections([section], _settings())

    leaf = next(chunk for chunk in chunks if chunk.chunk_role == "leaf")
    parent = next(chunk for chunk in chunks if chunk.chunk_role == "parent")
    assert leaf.navigation_only is True
    assert parent.navigation_only is False


def test_chunk_question_candidates_are_generated_by_llm_from_chunk_content() -> None:
    llm = _FakeQuestionLlm()
    candidates = build_chunk_question_candidates(
        {
            "heading": "Deployment YAML 작성",
            "text": "Deployment 매니페스트를 작성하고 replicas와 selector를 확인합니다.",
            "cli_commands": ["oc apply -f deployment.yaml"],
            "k8s_objects": ["Deployment"],
        },
        llm_client=llm,
    )

    starter = candidates["starter_question_candidates"]
    followup = candidates["followup_question_candidates"]
    prompt_text = "\n".join(message["content"] for message in llm.messages[0])
    assert "Deployment YAML 작성" in prompt_text
    assert "oc apply -f deployment.yaml" in prompt_text
    assert starter == [
        "Pod 상태는 어디서 먼저 확인하면 될까요?",
        "Pod 문제를 좁히려면 어떤 명령부터 보면 될까요?",
    ]
    assert followup == ["oc describe pod 결과에서는 무엇을 봐야 할까요?"]


def test_chunk_question_candidates_without_llm_do_not_template_questions() -> None:
    candidates = build_chunk_question_candidates(
        {
            "heading": "Service Route 연결",
            "text": "Service와 Route 연결을 설명합니다.",
            "k8s_objects": ["Service", "Route"],
        }
    )

    assert candidates == {"starter_question_candidates": [], "followup_question_candidates": []}
