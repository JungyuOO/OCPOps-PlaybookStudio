from __future__ import annotations

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.evals.answer_eval import evaluate_case


class _FakeAnswerer:
    def __init__(self, result: AnswerResult) -> None:
        self.result = result

    def answer(self, *_args, **_kwargs) -> AnswerResult:
        return self.result


def _citation(*, excerpt: str = "oc adm top nodes") -> Citation:
    return Citation(
        index=1,
        chunk_id="support-top-nodes",
        book_slug="support",
        section="노드 사용량 확인",
        anchor="top-nodes",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/support/index.html#top-nodes",
        excerpt=excerpt,
        cli_commands=("oc adm top nodes",),
        verification_hints=("oc adm top nodes",),
    )


def test_answer_eval_requires_expected_citation_terms() -> None:
    result = AnswerResult(
        query="노드 사용량 확인",
        mode="ops",
        answer="답변: `oc adm top nodes` 명령으로 확인합니다. [1]",
        rewritten_query="노드 사용량 확인",
        citations=[_citation()],
        cited_indices=[1],
    )

    detail = evaluate_case(
        _FakeAnswerer(result),
        {
            "id": "top-nodes",
            "query": "노드 사용량 확인",
            "expected_book_slugs": ["support"],
            "must_include_terms": ["oc adm top nodes"],
            "expected_citation_terms": ["oc adm top nodes"],
        },
        top_k=5,
        candidate_k=10,
        max_context_chunks=3,
    )

    assert detail["pass"] is True
    assert detail["citation_terms_pass"] is True


def test_answer_eval_flags_wrong_citation_chunk_even_when_answer_text_matches() -> None:
    result = AnswerResult(
        query="노드 사용량 확인",
        mode="ops",
        answer="답변: `oc adm top nodes` 명령으로 확인합니다. [1]",
        rewritten_query="노드 사용량 확인",
        citations=[_citation(excerpt="oc get pods -A")],
        cited_indices=[1],
    )

    detail = evaluate_case(
        _FakeAnswerer(result),
        {
            "id": "top-nodes",
            "query": "노드 사용량 확인",
            "expected_book_slugs": ["support"],
            "must_include_terms": ["oc adm top nodes"],
            "expected_citation_terms": ["oc adm top nodes"],
            "forbidden_citation_terms": ["oc get pods -A"],
        },
        top_k=5,
        candidate_k=10,
        max_context_chunks=3,
    )

    assert detail["pass"] is False
    assert detail["citation_forbidden_terms_pass"] is False
    assert detail["forbidden_citation_term_hits"] == ["oc get pods -A"]
