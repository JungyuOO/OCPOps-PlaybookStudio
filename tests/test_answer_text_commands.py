from __future__ import annotations

from play_book_studio.answering.answer_text_commands import (
    has_sufficient_command_grounding,
    strip_ungrounded_code_blocks,
)
from play_book_studio.answering.citations import finalize_citations
from play_book_studio.answering.models import Citation


def _citation(**overrides) -> Citation:
    values = {
        "index": 1,
        "chunk_id": "c1",
        "book_slug": "storage",
        "section": "PVC status",
        "anchor": "pvc",
        "source_url": "",
        "viewer_path": "/docs/storage#pvc",
        "excerpt": "Use oc get pvc and oc describe pvc <pvc-name> to inspect PVC status.",
        "cli_commands": ("oc get pvc", "oc describe pvc <pvc-name>"),
    }
    values.update(overrides)
    return Citation(**values)


def test_finalize_citations_places_period_before_citation_marker() -> None:
    finalized, _, _ = finalize_citations("답변: 아래 명령으로 확인합니다[1].", [_citation()])

    assert finalized.startswith("답변:")
    assert "[1]" in finalized


def test_has_sufficient_command_grounding_requires_command_evidence_for_command_query() -> None:
    assert has_sufficient_command_grounding(query="PVC 확인 명령 알려줘", citations=[_citation()])
    assert not has_sufficient_command_grounding(
        query="PVC 확인 명령 알려줘",
        citations=[_citation(cli_commands=(), excerpt="PVC 상태를 문서에서 설명합니다.")],
    )


def test_strip_ungrounded_code_blocks_keeps_grounded_command() -> None:
    answer = strip_ungrounded_code_blocks(
        "답변: 먼저 확인합니다 [1].\n\n```bash\noc describe pvc <pvc-name>\n```",
        citations=[_citation()],
    )

    assert "oc describe pvc <pvc-name>" in answer


def test_strip_ungrounded_code_blocks_removes_command_not_in_citations() -> None:
    answer = strip_ungrounded_code_blocks(
        "답변: 먼저 확인합니다 [1].\n\n```bash\noc delete pvc <pvc-name>\n```",
        citations=[_citation()],
    )

    assert "oc delete pvc" not in answer


def test_strip_ungrounded_code_blocks_explains_when_no_command_evidence_exists() -> None:
    answer = strip_ungrounded_code_blocks(
        "답변: 먼저 확인합니다 [1].\n\n```bash\noc get pods\n```",
        citations=[_citation(cli_commands=(), excerpt="PVC 상태 설명만 있습니다.")],
    )

    assert "oc get pods" not in answer
    assert "제공된 근거에는 실행 명령이나 예시 코드가 명시되어 있지 않습니다." in answer
