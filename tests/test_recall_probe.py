from __future__ import annotations

from play_book_studio.evals.recall_probe import hit_matches_case, rank_in_hits
from play_book_studio.retrieval.models import RetrievalHit


def _hit(chunk_id, *, book_slug="nodes", section="", cli_commands=(), text=""):
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="",
        section=section,
        anchor="",
        source_url="",
        viewer_path="",
        text=text,
        source="bm25",
        raw_score=1.0,
        cli_commands=tuple(cli_commands),
    )


def test_hit_matches_case_by_command():
    case = {"expect_command": "oc get poddisruptionbudget"}
    assert hit_matches_case(_hit("c1", cli_commands=("oc get poddisruptionbudget --all-namespaces",)), case)
    assert not hit_matches_case(_hit("c2", cli_commands=("oc get pods",)), case)


def test_hit_matches_case_by_section_contains():
    case = {"expect_section_contains": "중단 예산"}
    assert hit_matches_case(_hit("c1", section="Pod 중단 예산"), case)
    assert not hit_matches_case(_hit("c2", section="노드 상태"), case)


def test_rank_in_hits_returns_one_based_rank_or_none():
    case = {"expect_command": "oc get nodes"}
    hits = [_hit("a"), _hit("b", cli_commands=("oc get nodes",)), _hit("c")]
    assert rank_in_hits(hits, case) == 2
    assert rank_in_hits([_hit("x")], case) is None
