# retrieval benchmark 결과를 카테고리/모드별 수치로 요약하는 helper.
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _rate(matched: int, total: int) -> float:
    return round(matched / max(total, 1), 4)


def summarize_results(
    details: list[dict[str, Any]],
    *,
    top_k: int,
    candidate_k: int,
) -> dict[str, Any]:
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mode_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    warning_count = 0

    for detail in details:
        category_groups[str(detail["category"])].append(detail)
        mode_groups[str(detail["mode"])].append(detail)
        warning_count += len(detail.get("warnings", []))

    def build_bucket(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(bucket)
        return {
            "case_count": total,
            "hit_at_1": _rate(sum(int(item["matched_at_1"]) for item in bucket), total),
            "hit_at_3": _rate(sum(int(item["matched_at_3"]) for item in bucket), total),
            "hit_at_5": _rate(sum(int(item["matched_at_5"]) for item in bucket), total),
        }

    return {
        "case_count": len(details),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "warning_count": warning_count,
        "overall": build_bucket(details),
        "by_category": {
            key: build_bucket(bucket)
            for key, bucket in sorted(category_groups.items())
        },
        "by_mode": {
            key: build_bucket(bucket)
            for key, bucket in sorted(mode_groups.items())
        },
        "details": details,
    }
