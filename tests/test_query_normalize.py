from __future__ import annotations

from play_book_studio.retrieval.query_normalize import normalize_query


def test_normalize_query_trims_and_collapses_whitespace():
    assert normalize_query("  노드   상태   확인  ") == "노드 상태 확인 node status oc get nodes"


def test_normalize_query_appends_alias_terms():
    out = normalize_query("모든 프로젝트에서 pod 중단 예산 확인")
    assert "poddisruptionbudget" in out
    assert "--all-namespaces" in out


def test_normalize_query_returns_single_string_no_fanout():
    assert isinstance(normalize_query("ocp 로그인 어떻게 함"), str)
