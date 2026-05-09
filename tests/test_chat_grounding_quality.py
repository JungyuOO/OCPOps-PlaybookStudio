from __future__ import annotations

from play_book_studio.answering.answer_text_commands import build_grounded_command_guide_answer
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.http.presenters import _citation_display_payload
from play_book_studio.http.session_flow import suggest_follow_up_questions
from play_book_studio.http.sessions import ChatSession
from play_book_studio.evals.studio_live_smoke import SmokeCase, _validate_case
from play_book_studio.retrieval.intent_detectors import has_command_request
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.scoring import fuse_ranked_hits


def _hit(
    chunk_id: str,
    *,
    text: str,
    cli_commands: tuple[str, ...] = (),
    chunk_type: str = "reference",
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug="test-book",
        chapter="Test",
        section="Test Section",
        anchor=chunk_id,
        source_url="",
        viewer_path=f"/docs/{chunk_id}",
        text=text,
        source="bm25",
        raw_score=1.0,
        chunk_type=chunk_type,
        cli_commands=cli_commands,
    )


def _citation(
    *,
    excerpt: str = "Namespace and project commands.",
    cli_commands: tuple[str, ...] = ("oc get namespaces", "oc project -q"),
) -> Citation:
    return Citation(
        index=1,
        chunk_id="namespace-commands",
        book_slug="applications",
        section="Namespaces and projects",
        anchor="namespaces",
        source_url="",
        viewer_path="/docs/namespaces",
        excerpt=excerpt,
        cli_commands=cli_commands,
    )


def test_korean_command_lookup_is_detected_without_fixed_answer() -> None:
    assert has_command_request("네임스페이스 확인하는 명령어가 뭐야?")


def test_command_lookup_boosts_command_bearing_chunks() -> None:
    concept_hit = _hit(
        "concept",
        text="A namespace provides a scope for resources.",
    )
    command_hit = _hit(
        "command",
        text="Use oc get namespaces to list namespaces.",
        cli_commands=("oc get namespaces",),
        chunk_type="procedure",
    )

    hits = fuse_ranked_hits(
        "네임스페이스 확인하는 명령어가 뭐야?",
        {"bm25": [concept_hit, command_hit]},
        context=SessionContext(),
        top_k=2,
    )

    assert hits[0].chunk_id == "command"
    assert "command_intent_cli_commands_boost" in hits[0].component_scores


def test_namespace_command_answer_is_built_from_citation_commands() -> None:
    answer = build_grounded_command_guide_answer(
        query="네임스페이스 확인하는 명령어가 뭐야?",
        citations=[_citation()],
    )

    assert answer is not None
    assert "oc get namespaces" in answer
    assert "oc project -q" in answer


def test_follow_up_questions_are_grounded_in_citation_commands() -> None:
    result = AnswerResult(
        query="네임스페이스 확인하는 명령어가 뭐야?",
        mode="chat",
        answer="답변: `oc get namespaces`를 사용하세요 [1].",
        rewritten_query="네임스페이스 확인하는 명령어가 뭐야?",
        response_kind="rag",
        citations=[_citation()],
        cited_indices=[1],
    )

    suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s1"), result=result)

    assert suggestions
    assert any("oc get namespaces" in suggestion for suggestion in suggestions)
    assert all("문서" not in suggestion for suggestion in suggestions[:1])


def test_citation_display_payload_strips_code_markup() -> None:
    payload = _citation_display_payload(
        _citation(
            excerpt='[CODE language="shell-session" caption="Monitor"] $ oc get namespaces [/CODE]',
            cli_commands=("oc get namespaces",),
        )
    )

    assert "[CODE" not in payload["excerpt"]
    assert "[/CODE" not in payload["excerpt"]
    assert "oc get namespaces" in payload["excerpt"]
    assert payload["command_preview"] == ["oc get namespaces"]


def test_live_smoke_flags_command_answers_without_grounded_command() -> None:
    detail = _validate_case(
        SmokeCase(case_id="command-missing", query="네임스페이스 확인하는 명령어가 뭐야?"),
        200,
        [
            {"type": "answer_delta"},
            {
                "type": "result",
                "payload": {
                    "answer": "답변: 관련 문서를 먼저 확인하세요 [1].",
                    "response_kind": "rag",
                    "warnings": [],
                    "cited_indices": [1],
                    "suggested_queries": [],
                    "citations": [
                        {
                            "index": 1,
                            "book_slug": "applications",
                            "section": "Namespaces",
                            "viewer_path": "/docs/namespaces",
                            "excerpt": "Namespace overview.",
                            "cli_commands": [],
                        }
                    ],
                },
            },
        ],
        "",
    )

    assert "command_query_missing_grounded_command" in detail["failures"]


def test_live_smoke_flags_raw_code_markup_in_citation_preview() -> None:
    detail = _validate_case(
        SmokeCase(case_id="raw-code", query="네임스페이스 확인하는 명령어가 뭐야?"),
        200,
        [
            {"type": "answer_delta"},
            {
                "type": "result",
                "payload": {
                    "answer": "답변: 아래 명령을 사용하세요 [1].\n\n```bash\noc get namespaces\n```",
                    "response_kind": "rag",
                    "warnings": [],
                    "cited_indices": [1],
                    "suggested_queries": ["`oc get namespaces` 결과에서 무엇을 확인해야 해?"],
                    "citations": [
                        {
                            "index": 1,
                            "book_slug": "applications",
                            "section": "Namespaces",
                            "viewer_path": "/docs/namespaces",
                            "excerpt": "[CODE] oc get namespaces [/CODE]",
                            "cli_commands": ["oc get namespaces"],
                        }
                    ],
                },
            },
        ],
        "",
    )

    assert "citation_raw_code_markup" in detail["failures"]
