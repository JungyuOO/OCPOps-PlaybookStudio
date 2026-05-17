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


def _settings() -> SimpleNamespace:
    return SimpleNamespace(embedding_model="dragonkue/bge-m3-ko", chunk_size=120, chunk_overlap=0)


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
                "Pod가 Running인지 확인하려면 먼저 현재 네임스페이스의 Pod 목록을 봅니다.",
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
    assert leaves[0].followup_question_candidates


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


def test_chunk_question_candidates_are_derived_from_chunk_content() -> None:
    candidates = build_chunk_question_candidates(
        {
            "heading": "Deployment YAML 작성",
            "text": "Deployment 매니페스트를 작성하고 replicas와 selector를 확인합니다.",
            "cli_commands": ["oc apply -f deployment.yaml"],
            "k8s_objects": ["Deployment"],
        }
    )

    starter = candidates["starter_question_candidates"]
    followup = candidates["followup_question_candidates"]
    assert starter
    assert any("Deployment" in question or "Deployment YAML" in question for question in starter)
    assert any("oc apply -f deployment.yaml" in question for question in followup)
    all_questions = starter + followup
    assert all("처음에는 무엇부터" not in question for question in all_questions)
    assert all("어떤 명령어부터 쓰면 돼" not in question for question in all_questions)
    assert all("어디서 확인하면 돼" not in question for question in all_questions)
