from __future__ import annotations

from play_book_studio.evals.retrieval_gap_audit import build_retrieval_gap_audit


def test_retrieval_gap_audit_classifies_similar_document_and_near_tie() -> None:
    payload = {
        "retrieval_eval": {
            "suite.jsonl": {
                "details": [
                    {
                        "id": "case-1",
                        "query_type": "ops",
                        "query": "Pod pending order",
                        "expected_book_slugs": ["nodes", "support"],
                        "top_book_slugs": ["cli_tools", "support", "nodes"],
                        "top_source_scopes": ["official_docs", "official_docs", "official_docs"],
                        "top_hits": [
                            {"book_slug": "cli_tools", "score": 0.151},
                            {"book_slug": "support", "score": 0.149},
                        ],
                        "hybrid_top_book_slugs": ["support", "cli_tools"],
                        "reranked_top_book_slugs": ["cli_tools", "support"],
                    }
                ]
            }
        }
    }

    report = build_retrieval_gap_audit(payload)
    miss = report["miss_cases"][0]

    assert report["decision"] == "review"
    assert report["summary"]["book_hit@1"] == 0.0
    assert report["summary"]["book_hit@5"] == 1.0
    assert report["reason_counts"]["similar_document"] == 1
    assert report["reason_counts"]["near_tie"] == 1
    assert report["reason_counts"]["rerank_regression"] == 1
    assert miss["expected_rank"] == 2


def test_retrieval_gap_audit_fails_when_expected_book_is_absent_at5() -> None:
    payload = {
        "retrieval_eval": {
            "suite.jsonl": {
                "details": [
                    {
                        "id": "case-1",
                        "query": "Where is update preflight?",
                        "expected_book_slugs": ["updating_clusters"],
                        "top_book_slugs": ["machine_management", "support", "nodes", "cli_tools", "storage"],
                        "top_source_scopes": ["official_docs"] * 5,
                        "top_hits": [{"score": 0.20}],
                    }
                ]
            }
        }
    }

    report = build_retrieval_gap_audit(payload)

    assert report["decision"] == "fail"
    assert report["summary"]["book_miss@5_count"] == 1
    assert report["reason_counts"] == {"expected_book_absent_at5": 1}


def test_retrieval_gap_audit_keeps_scope_boundary_signal() -> None:
    payload = {
        "retrieval_eval": {
            "suite.jsonl": {
                "details": [
                    {
                        "id": "scope-1",
                        "query": "Only official docs",
                        "expected_book_slugs": [],
                        "expected_source_scopes": ["official_docs"],
                        "top_book_slugs": ["backup_and_restore"],
                        "top_source_scopes": ["official_docs"],
                    }
                ]
            }
        }
    }

    report = build_retrieval_gap_audit(payload)

    assert report["decision"] == "pass"
    assert report["summary"]["scope_hit@1"] == 1.0
    assert report["reason_counts"] == {}
    assert any(item["area"] == "source_scope_boundary" for item in report["recommendations"])


def test_retrieval_gap_audit_splits_baseline_and_regression_summaries() -> None:
    payload = {
        "retrieval_eval": {
            "retrieval_benchmark_cases.jsonl": {
                "details": [
                    {
                        "id": "base-clean",
                        "query": "etcd backup",
                        "expected_book_slugs": ["backup_and_restore"],
                        "expected_source_scopes": ["official_docs"],
                        "top_book_slugs": ["backup_and_restore"],
                        "top_source_scopes": ["official_docs"],
                    }
                ]
            },
            "retrieval_official_hit1_regression_cases.jsonl": {
                "details": [
                    {
                        "id": "regression-miss",
                        "query": "node drain",
                        "expected_book_slugs": ["nodes"],
                        "expected_source_scopes": ["official_docs"],
                        "top_book_slugs": ["support", "nodes"],
                        "top_source_scopes": ["official_docs", "official_docs"],
                    }
                ]
            },
        }
    }

    report = build_retrieval_gap_audit(payload)

    assert report["summary"]["book_hit@1"] == 0.5
    assert report["baseline_summary"]["book_hit@1"] == 1.0
    assert report["regression_summary"]["book_hit@1"] == 0.0
    assert report["regression_summary"]["book_hit@5"] == 1.0
