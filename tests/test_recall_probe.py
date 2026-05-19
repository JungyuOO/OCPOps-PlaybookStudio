from __future__ import annotations

from play_book_studio.evals.recall_probe import (
    hit_matches_case,
    probe_case,
    rank_in_hits,
    summarize_probe_results,
)
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


class _FakeBM25:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=10):
        return self._hits[:top_k]


class _FakeVector:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=10, query_filter=None):
        return self._hits[:top_k]


def test_probe_case_reports_per_stage_ranks():
    target = _hit("pdb", section="Pod 중단 예산", cli_commands=("oc get poddisruptionbudget",))
    noise = _hit("noise", section="기타")
    case = {"id": "pdb", "query": "pod 중단 예산", "expect_command": "oc get poddisruptionbudget"}

    result = probe_case(
        bm25_index=_FakeBM25([noise, target]),
        vector_retriever=_FakeVector([target]),
        case=case,
        candidate_k=40,
    )

    assert result["bm25_rank"] == 2
    assert result["vector_rank"] == 1
    assert result["rrf_rank"] == 1
    assert result["pass_at_8"] is True


def test_summarize_probe_results_computes_recall_at_k():
    results = [
        {"id": "a", "rrf_rank": 1, "pass_at_8": True, "pass_at_20": True},
        {"id": "b", "rrf_rank": 12, "pass_at_8": False, "pass_at_20": True},
        {"id": "c", "rrf_rank": None, "pass_at_8": False, "pass_at_20": False},
    ]
    summary = summarize_probe_results(results)
    assert summary["case_count"] == 3
    assert summary["recall_at_8"] == round(1 / 3, 4)
    assert summary["recall_at_20"] == round(2 / 3, 4)
