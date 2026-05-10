from __future__ import annotations

from play_book_studio.answering.context import assemble_context
from play_book_studio.answering.answerer import _is_low_confidence_retrieval
from play_book_studio.answering.answer_text_commands import build_grounded_command_guide_answer
from play_book_studio.answering.answer_text_commands import strip_ungrounded_code_blocks
from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.http.presenters import _citation_display_payload
from play_book_studio.http.session_flow import suggest_follow_up_questions
from play_book_studio.http.sessions import ChatSession
from play_book_studio.evals.studio_live_smoke import SmokeCase, _validate_case
from play_book_studio.retrieval.intent_detectors import has_command_request
from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.query_terms import normalize_query
from play_book_studio.retrieval.scoring import fuse_ranked_hits


def _hit(
    chunk_id: str,
    *,
    text: str,
    cli_commands: tuple[str, ...] = (),
    chunk_type: str = "reference",
    book_slug: str = "test-book",
    section: str = "Test Section",
    raw_score: float = 1.0,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="Test",
        section=section,
        anchor=chunk_id,
        source_url="",
        viewer_path=f"/docs/{chunk_id}",
        text=text,
        source="bm25",
        raw_score=raw_score,
        fused_score=raw_score,
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


def test_command_context_selects_cli_profile_commands_instead_of_clarifying() -> None:
    query = "\ub124\uc784\uc2a4\ud398\uc774\uc2a4 \ud655\uc778\ud558\ub294 \uba85\ub839\uc5b4\uac00 \ubb50\uc57c?"
    concept_hit = _hit(
        "concept",
        text="A namespace scopes resources, but this paragraph has no command.",
        book_slug="security_and_compliance",
        raw_score=0.20,
    )
    cli_hit = _hit(
        "cli-profile",
        text=(
            "CLI profiles show the current context namespace. "
            "[CODE language=\"shell-session\"] $ oc config view [/CODE] "
            "[CODE language=\"shell-session\"] $ oc project [/CODE]"
        ),
        cli_commands=("oc config view", "oc project"),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.4.2. CLI profile manual configuration",
        raw_score=0.18,
    )

    bundle = assemble_context([concept_hit, cli_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "cli-profile"
    assert "oc config view" in bundle.citations[0].cli_commands


def test_current_project_command_context_prefers_view_over_set_context() -> None:
    query = (
        "\ud604\uc7ac \ud130\ubbf8\ub110\uc774 \uc5b4\ub290 \ud504\ub85c\uc81d\ud2b8\ub098 "
        "namespace\ub97c \ubcf4\uace0 \uc788\ub294\uc9c0 \ud655\uc778\ud558\ub294 \uba85\ub839\uc740?"
    )
    set_context_hit = _hit(
        "set-context",
        text=(
            "CLI profile manual configuration. "
            "[CODE language=\"shell-session\"] $ oc config set-context `oc config current-context` "
            "--namespace=<project_name> [/CODE]"
        ),
        cli_commands=("oc config set-context `oc config current-context` --namespace=<project_name>",),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.4.2. CLI profile manual configuration",
        raw_score=0.30,
    )
    view_project_hit = _hit(
        "view-project",
        text=(
            "현재 프로젝트 보기. 아래 명령을 사용하여 현재 프로젝트를 봅니다. "
            "[CODE language=\"shell\"] oc project [/CODE]"
        ),
        cli_commands=("oc project",),
        chunk_type="command",
        book_slug="cli_tools",
        section="2.1.5.5. 현재 프로젝트 보기",
        raw_score=0.20,
    )

    bundle = assemble_context([set_context_hit, view_project_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "view-project"


def test_namespace_command_query_expands_toward_cli_profile_docs() -> None:
    normalized = normalize_query(
        "\ub124\uc784\uc2a4\ud398\uc774\uc2a4 \ud655\uc778\ud558\ub294 \uba85\ub839\uc5b4\uac00 \ubb50\uc57c?"
    )

    assert "현재 프로젝트 보기" in normalized
    assert "oc project" in normalized
    assert "config view" in normalized


def test_install_guidance_context_selects_bootstrap_wait_command() -> None:
    query = "bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?"
    overview_hit = _hit(
        "overview",
        text="The bootstrap process prepares initial cluster services.",
        book_slug="installation_overview",
        raw_score=0.20,
    )
    wait_hit = _hit(
        "bootstrap-wait",
        text=(
            "Waiting for the bootstrap process to complete. "
            "[CODE language=\"shell-session\"] "
            "$ ./openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info "
            "[/CODE]"
        ),
        chunk_type="procedure",
        book_slug="installing_on_any_platform",
        section="1.14. Waiting for the bootstrap process to complete",
        raw_score=0.18,
    )

    bundle = assemble_context([overview_hit, wait_hit], query=query, max_chunks=4)

    assert bundle.citations
    assert bundle.citations[0].chunk_id == "bootstrap-wait"
    assert any("openshift-install" in command for command in bundle.citations[0].cli_commands)


def test_bootstrap_guidance_query_expands_toward_wait_doc() -> None:
    normalized = normalize_query(
        "bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?"
    )

    assert "Waiting" in normalized
    assert "process" in normalized
    assert "complete" in normalized
    assert "wait-for bootstrap-complete" in normalized


def test_low_confidence_guard_allows_bootstrap_wait_grounding() -> None:
    citation = _citation(
        excerpt="Use openshift-install wait-for bootstrap-complete to monitor bootstrap.",
        cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
    )

    assert not _is_low_confidence_retrieval(
        query="bootstrap \uae30\ub2e4\ub9ac\ub294 \ub2e8\uacc4\uc5d0\uc11c \ubb58 \ud655\uc778\ud574\uc57c \ud574?",
        citations=[citation],
        selected_hits=[{"fused_score": 0.03, "pre_rerank_fused_score": 0.02, "vector_score": 0.02}],
    )


def test_strip_ungrounded_code_blocks_does_not_claim_no_commands_when_citation_has_command() -> None:
    citation = _citation(
        excerpt="Use openshift-install wait-for bootstrap-complete to monitor bootstrap.",
        cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
    )

    cleaned = strip_ungrounded_code_blocks(
        "답변\n\n```text\nINFO Waiting for API...\n```",
        citations=[citation],
    )

    assert "제공된 근거에는 실행 명령" not in cleaned


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


def test_follow_up_questions_rotate_from_citation_seed_and_stay_grounded() -> None:
    first = AnswerResult(
        query="현재 프로젝트 확인 명령은?",
        mode="chat",
        answer="답변: `oc project` [1].",
        rewritten_query="현재 프로젝트 확인 명령은?",
        response_kind="rag",
        citations=[_citation(cli_commands=("oc project",), excerpt="현재 프로젝트 보기")],
        cited_indices=[1],
    )
    second = AnswerResult(
        query="bootstrap 기다리는 단계에서 뭘 확인해야 해?",
        mode="chat",
        answer="답변: `openshift-install wait-for bootstrap-complete` [1].",
        rewritten_query="bootstrap 기다리는 단계에서 뭘 확인해야 해?",
        response_kind="rag",
        citations=[
            _citation(
                excerpt="Waiting for the bootstrap process to complete.",
                cli_commands=("openshift-install --dir <installation_directory> wait-for bootstrap-complete --log-level=info",),
            )
        ],
        cited_indices=[1],
    )

    first_suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s1"), result=first)
    second_suggestions = suggest_follow_up_questions(session=ChatSession(session_id="s2"), result=second)

    assert first_suggestions
    assert second_suggestions
    assert first_suggestions != second_suggestions
    assert any("oc project" in suggestion or "namespace" in suggestion for suggestion in first_suggestions)
    assert any("bootstrap" in suggestion or "openshift-install" in suggestion for suggestion in second_suggestions)


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
