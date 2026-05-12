from __future__ import annotations

from play_book_studio.evals.sanity import summarize_results


def test_must_clarify_cases_do_not_lower_expected_retrieval_hit_rate() -> None:
    summary = summarize_results(
        [
            {
                "id": "ops-001",
                "category": "ops",
                "mode": "ops",
                "query": "etcd 백업은 어떻게 하나?",
                "expected_book_slugs": ["etcd"],
                "forbidden_book_slugs": [],
                "expected_hit_at_1": True,
                "expected_hit_at_3": True,
                "expected_hit_at_5": True,
                "forbidden_hit_at_1": False,
                "forbidden_hit_at_3": False,
                "forbidden_hit_at_5": False,
                "rewritten_query": "etcd 백업",
                "top_book_slugs": ["etcd"],
                "must_clarify": False,
                "must_refuse": False,
                "trace": {"warnings": []},
            },
            {
                "id": "ambiguous-001",
                "category": "ambiguous",
                "mode": "ops",
                "query": "로그는 어디서 봐?",
                "expected_book_slugs": ["logging"],
                "forbidden_book_slugs": [],
                "expected_hit_at_1": False,
                "expected_hit_at_3": False,
                "expected_hit_at_5": False,
                "forbidden_hit_at_1": False,
                "forbidden_hit_at_3": False,
                "forbidden_hit_at_5": False,
                "rewritten_query": "로그",
                "top_book_slugs": ["nodes"],
                "must_clarify": True,
                "must_refuse": False,
                "trace": {"warnings": []},
            },
        ]
    )

    assert summary["overall"]["case_count"] == 2
    assert summary["overall"]["expected_case_count"] == 1
    assert summary["overall"]["clarify_case_count"] == 1
    assert summary["overall"]["expected_hit_at_3"] == 1.0
    assert summary["misses"] == []
