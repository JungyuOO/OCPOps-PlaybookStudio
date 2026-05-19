from __future__ import annotations

from play_book_studio.retrieval.alias_table import expand_with_aliases, load_alias_table


def test_expand_with_aliases_appends_canonical_terms():
    table = {"pod 중단 예산": ["poddisruptionbudget"], "모든 프로젝트": ["--all-namespaces"]}
    expanded = expand_with_aliases("모든 프로젝트에서 pod 중단 예산 확인", table)
    assert "poddisruptionbudget" in expanded
    assert "--all-namespaces" in expanded
    assert "모든 프로젝트에서 pod 중단 예산 확인" in expanded


def test_expand_with_aliases_no_match_returns_query_unchanged():
    assert expand_with_aliases("관련 없는 질문", {"로그인": ["login"]}) == "관련 없는 질문"


def test_load_alias_table_reads_packaged_toml():
    table = load_alias_table()
    assert "로그인" in table
