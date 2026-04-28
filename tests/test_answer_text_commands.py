from play_book_studio.answering.answer_text_commands import (
    build_grounded_command_guide_answer,
    shape_crash_loop_troubleshooting,
    strip_ungrounded_code_blocks,
)
from play_book_studio.answering.citations import finalize_citations
from play_book_studio.answering.models import Citation


def test_grounded_command_guide_includes_verification_hints() -> None:
    citation = Citation(
        index=1,
        chunk_id="installation_overview--runtimes",
        book_slug="installation_overview",
        section="4.4.3. Runtimes",
        anchor="runtimes",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtimes",
        excerpt="Runtimes 절차에서는 노드와 머신 상태를 확인합니다.",
        cli_commands=("oc get nodes", "oc get machines -A"),
        verification_hints=("노드가 Ready 상태인지 확인", "Machine이 Running 상태인지 확인"),
    )

    answer = build_grounded_command_guide_answer(
        query="Runtimes 절차 명령 알려줘",
        citations=[citation],
    )

    assert answer is not None
    assert "oc get nodes" in answer
    finalized, _, _ = finalize_citations(answer, [citation])
    assert (
        "실행 후에는 노드가 Ready 상태인지 확인; Machine이 Running 상태인지 확인 기준으로 결과를 확인하세요. [1]"
        in finalized
    )


def test_finalize_citations_places_period_before_citation_marker() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="installation_overview",
        section="Runtimes",
        anchor="runtimes",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtimes",
        excerpt="",
    )

    finalized, _, _ = finalize_citations("답변: 아래 명령으로 진행하면 됩니다 [1].", [citation])

    assert finalized == "답변: 아래 명령으로 진행하면 됩니다. [1]"


def test_finalize_citations_normalizes_korean_particle_spacing() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: HPA 는 15 초마다 Pod 의 지표를 확인합니다 [1].",
        [citation],
    )

    assert finalized == "답변: HPA는 15초마다 Pod의 지표를 확인합니다. [1]"


def test_finalize_citations_separates_adjacent_citation_from_next_sentence() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: HPA는 Pod 에 지표를 확인합니다. [1]이 과정에서 설정을 확인합니다 [1].",
        [citation],
    )

    assert "Pod에" in finalized
    assert "[1] 이 과정" in finalized
    assert finalized.endswith("확인합니다. [1]")


def test_finalize_citations_preserves_section_numbers_and_sentence_spacing() -> None:
    citation = Citation(
        index=1,
        chunk_id="c1",
        book_slug="nodes",
        section="HPA",
        anchor="hpa",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/nodes/index.html#hpa",
        excerpt="",
    )

    finalized, _, _ = finalize_citations(
        "답변: 5.1.4. 절차입니다 [1]. HPA는 `metrics.k8s.io` 를 사용합니다.이때 Pod 에 requests가 필요합니다 [1].",
        [citation],
    )

    assert "5.1.4." in finalized
    assert "`metrics.k8s.io`를" in finalized
    assert "합니다. 이때 Pod에" in finalized


def test_shape_crash_loop_troubleshooting_returns_actionable_steps() -> None:
    citation = Citation(
        index=1,
        chunk_id="support--crashloop",
        book_slug="support",
        section="애플리케이션 진단 데이터 수집",
        anchor="diagnostic",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/support/index.html#diagnostic",
        excerpt="CrashLoopBackOff 상태에서는 describe와 logs로 진단 데이터를 수집합니다.",
        cli_commands=("oc describe pod/my-app-1-akdlg", "oc logs -f pod/my-app-1-akdlg"),
        verification_hints=("oc describe pod/my-app-1-akdlg", "oc logs -f pod/my-app-1-akdlg"),
    )

    answer = shape_crash_loop_troubleshooting(
        "답변: 먼저 문서를 여세요. [1]",
        query="CrashLoopBackOff는 어디부터 봐야해?",
        citations=[citation],
    )
    finalized, _, _ = finalize_citations(answer, [citation])

    assert "CrashLoopBackOff" in finalized
    assert "oc describe pod/my-app-1-akdlg" in finalized
    assert "oc logs -f pod/my-app-1-akdlg" in finalized
    assert "문서를 여세요" not in finalized


def test_strip_ungrounded_code_blocks_when_citation_has_no_commands() -> None:
    citation = Citation(
        index=1,
        chunk_id="runtime",
        book_slug="installation_overview",
        section="Runtimes",
        anchor="runtime",
        source_url="",
        viewer_path="/docs/ocp/4.20/ko/installation_overview/index.html#runtime",
        excerpt="CRI-O를 사용하여 런타임을 관리합니다.",
    )

    answer = strip_ungrounded_code_blocks(
        "답변: 먼저 확인합니다. [1]\n\n```bash\ncrio inspect <container-id>\n```",
        citations=[citation],
    )

    assert "crio inspect" not in answer
    assert "제공된 근거에는 실행 명령이나 예시 코드가 명시되어 있지 않습니다." in answer
