# 최소 retrieval 품질 게이트를 돌리는 sanity 평가 로직.
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _hit_at_k(top_book_slugs: list[str], expected_book_slugs: list[str], k: int) -> bool:
    expected = set(expected_book_slugs)
    if not expected:
        return False
    return any(book_slug in expected for book_slug in top_book_slugs[:k])


def _forbidden_at_k(top_book_slugs: list[str], forbidden_book_slugs: list[str], k: int) -> bool:
    forbidden = set(forbidden_book_slugs)
    if not forbidden:
        return False
    return any(book_slug in forbidden for book_slug in top_book_slugs[:k])


def evaluate_case(
    retriever: ChatRetriever,
    case: dict[str, Any],
    *,
    top_k: int,
    candidate_k: int,
    use_vector: bool = True,
) -> dict[str, Any]:
    context = SessionContext.from_dict(case.get("context"))
    result = retriever.retrieve(
        str(case["query"]),
        context=context,
        top_k=top_k,
        candidate_k=candidate_k,
        use_vector=use_vector,
    )

    top_books = [hit.book_slug for hit in result.hits]
    expected_books = list(case.get("expected_book_slugs", []))
    forbidden_books = list(case.get("forbidden_book_slugs", []))

    return {
        "id": case.get("id"),
        "category": case.get("category", "uncategorized"),
        "mode": case.get("mode", "ops"),
        "query_type": case.get("query_type", case.get("category", "unknown")),
        "query": case["query"],
        "context": context.to_dict(),
        "must_clarify": bool(case.get("must_clarify", False)),
        "must_refuse": bool(case.get("must_refuse", False)),
        "expected_book_slugs": expected_books,
        "forbidden_book_slugs": forbidden_books,
        "rewritten_query": result.rewritten_query,
        "normalized_query": result.normalized_query,
        "top_book_slugs": top_books,
        "expected_hit_at_1": _hit_at_k(top_books, expected_books, 1),
        "expected_hit_at_3": _hit_at_k(top_books, expected_books, 3),
        "expected_hit_at_5": _hit_at_k(top_books, expected_books, 5),
        "forbidden_hit_at_1": _forbidden_at_k(top_books, forbidden_books, 1),
        "forbidden_hit_at_3": _forbidden_at_k(top_books, forbidden_books, 3),
        "forbidden_hit_at_5": _forbidden_at_k(top_books, forbidden_books, 5),
        "top_hits": [
            {
                "book_slug": hit.book_slug,
                "section": hit.section,
                "viewer_path": hit.viewer_path,
                "score": round(hit.fused_score, 6),
            }
            for hit in result.hits
        ],
        "trace": {
            "warnings": result.trace.get("warnings", []),
            "bm25_top_books": [item["book_slug"] for item in result.trace.get("bm25", [])[:5]],
            "vector_top_books": [item["book_slug"] for item in result.trace.get("vector", [])[:5]],
        },
    }


def summarize_results(details: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for detail in details:
        by_category[str(detail["category"])].append(detail)
        by_mode[str(detail["mode"])].append(detail)

    def build_bucket(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(bucket)
        if total == 0:
            return {
                "case_count": 0,
                "expected_hit_at_1": 0.0,
                "expected_hit_at_3": 0.0,
                "expected_hit_at_5": 0.0,
                "forbidden_free_at_1": 0.0,
                "forbidden_free_at_3": 0.0,
                "forbidden_free_at_5": 0.0,
                "warning_free_rate": 0.0,
            }

        expected_cases = [item for item in bucket if item.get("expected_book_slugs")]
        expected_total = len(expected_cases)
        warning_free = sum(1 for item in bucket if not item.get("trace", {}).get("warnings"))

        def expected_rate(key: str) -> float:
            if expected_total == 0:
                return 0.0
            return round(sum(int(item[key]) for item in expected_cases) / expected_total, 4)

        return {
            "case_count": total,
            "expected_case_count": expected_total,
            "clarify_case_count": sum(int(item.get("must_clarify", False)) for item in bucket),
            "refuse_case_count": sum(int(item.get("must_refuse", False)) for item in bucket),
            "expected_hit_at_1": expected_rate("expected_hit_at_1"),
            "expected_hit_at_3": expected_rate("expected_hit_at_3"),
            "expected_hit_at_5": expected_rate("expected_hit_at_5"),
            "forbidden_free_at_1": round(
                sum(int(not item["forbidden_hit_at_1"]) for item in bucket) / total,
                4,
            ),
            "forbidden_free_at_3": round(
                sum(int(not item["forbidden_hit_at_3"]) for item in bucket) / total,
                4,
            ),
            "forbidden_free_at_5": round(
                sum(int(not item["forbidden_hit_at_5"]) for item in bucket) / total,
                4,
            ),
            "warning_free_rate": round(warning_free / total, 4),
        }

    misses = [
        {
            "id": item["id"],
            "category": item["category"],
            "query": item["query"],
            "expected_book_slugs": item["expected_book_slugs"],
            "forbidden_book_slugs": item["forbidden_book_slugs"],
            "rewritten_query": item["rewritten_query"],
            "top_book_slugs": item["top_book_slugs"],
            "warnings": item["trace"]["warnings"],
        }
        for item in details
        if (item.get("expected_book_slugs") and not item["expected_hit_at_5"]) or item["forbidden_hit_at_3"]
    ]

    return {
        "case_count": len(details),
        "overall": build_bucket(details),
        "by_category": {
            category: build_bucket(bucket)
            for category, bucket in sorted(by_category.items())
        },
        "by_mode": {
            mode: build_bucket(bucket)
            for mode, bucket in sorted(by_mode.items())
        },
        "misses": misses,
        "details": details,
    }
