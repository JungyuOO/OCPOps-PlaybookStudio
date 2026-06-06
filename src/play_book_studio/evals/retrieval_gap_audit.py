"""Summarize retrieval hit@1 gaps from a RAG foundation audit payload."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    return []


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _contains_expected(top_values: list[str], expected_values: list[str], *, limit: int) -> bool:
    if not expected_values:
        return False
    expected = set(expected_values)
    return any(value in expected for value in top_values[:limit])


def _first_expected_rank(top_values: list[str], expected_values: list[str]) -> int:
    expected = set(expected_values)
    for index, value in enumerate(top_values, start=1):
        if value in expected:
            return index
    return 0


def _top_hit_score(case: dict[str, Any], rank: int) -> float:
    hits = case.get("top_hits") if isinstance(case.get("top_hits"), list) else []
    if rank <= 0 or rank > len(hits):
        return 0.0
    hit = hits[rank - 1]
    if not isinstance(hit, dict):
        return 0.0
    try:
        return float(hit.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _case_summary(case: dict[str, Any], *, suite_name: str) -> dict[str, Any]:
    expected_books = _string_list(case.get("expected_book_slugs"))
    expected_scopes = _string_list(case.get("expected_source_scopes"))
    top_books = _string_list(case.get("top_book_slugs"))
    top_scopes = _string_list(case.get("top_source_scopes"))
    bm25_books = _string_list(case.get("bm25_top_book_slugs"))
    vector_books = _string_list(case.get("vector_top_book_slugs"))
    hybrid_books = _string_list(case.get("hybrid_top_book_slugs"))
    reranked_books = _string_list(case.get("reranked_top_book_slugs"))
    top1_book_hit = _contains_expected(top_books, expected_books, limit=1) if expected_books else True
    top3_book_hit = _contains_expected(top_books, expected_books, limit=3) if expected_books else True
    top5_book_hit = _contains_expected(top_books, expected_books, limit=5) if expected_books else True
    top1_scope_hit = _contains_expected(top_scopes, expected_scopes, limit=1) if expected_scopes else True
    top5_scope_hit = _contains_expected(top_scopes, expected_scopes, limit=5) if expected_scopes else True
    expected_rank = _first_expected_rank(top_books, expected_books) if expected_books else 0
    expected_score = _top_hit_score(case, expected_rank)
    top_score = _top_hit_score(case, 1)
    score_margin = round(top_score - expected_score, 6) if expected_rank else 0.0

    reasons: list[str] = []
    if expected_books and not top1_book_hit:
        if top5_book_hit:
            reasons.append("similar_document")
        else:
            reasons.append("expected_book_absent_at5")
        if (
            _contains_expected(hybrid_books, expected_books, limit=1)
            and not _contains_expected(reranked_books, expected_books, limit=1)
        ):
            reasons.append("rerank_regression")
        if expected_rank and score_margin <= 0.015:
            reasons.append("near_tie")
    if expected_scopes and not top1_scope_hit:
        reasons.append("source_scope_miss")
    if expected_scopes and top1_scope_hit and not top5_scope_hit:
        reasons.append("source_scope_unstable")
    if not reasons:
        reasons.append("clean")

    return {
        "suite": suite_name,
        "id": str(case.get("id") or ""),
        "query_type": str(case.get("query_type") or ""),
        "query": str(case.get("query") or ""),
        "expected_book_slugs": expected_books,
        "expected_source_scopes": expected_scopes,
        "top_book_slugs": top_books[:5],
        "top_source_scopes": top_scopes[:5],
        "top1_book_hit": top1_book_hit,
        "top3_book_hit": top3_book_hit,
        "top5_book_hit": top5_book_hit,
        "top1_scope_hit": top1_scope_hit,
        "top5_scope_hit": top5_scope_hit,
        "expected_rank": expected_rank,
        "top_score": top_score,
        "expected_score": expected_score,
        "score_margin": score_margin,
        "bm25_top_book_slugs": bm25_books[:5],
        "vector_top_book_slugs": vector_books[:5],
        "hybrid_top_book_slugs": hybrid_books[:5],
        "reranked_top_book_slugs": reranked_books[:5],
        "graph_signal_tag": str(case.get("graph_signal_tag") or ""),
        "graph_signal_reason": str(case.get("graph_signal_reason") or ""),
        "reasons": reasons,
    }


def build_retrieval_gap_audit(audit_payload: dict[str, Any]) -> dict[str, Any]:
    retrieval_eval = audit_payload.get("retrieval_eval") if isinstance(audit_payload.get("retrieval_eval"), dict) else {}
    case_reports: list[dict[str, Any]] = []
    suite_summaries: dict[str, dict[str, Any]] = {}
    for suite_name, suite_payload in retrieval_eval.items():
        if not isinstance(suite_payload, dict):
            continue
        details = [item for item in suite_payload.get("details") or [] if isinstance(item, dict)]
        reports = [_case_summary(case, suite_name=suite_name) for case in details]
        case_reports.extend(reports)
        book_cases = [case for case in reports if case.get("expected_book_slugs")]
        scope_cases = [case for case in reports if case.get("expected_source_scopes")]
        suite_summaries[str(suite_name)] = _summarize_cases(book_cases=book_cases, scope_cases=scope_cases)

    book_cases = [case for case in case_reports if case.get("expected_book_slugs")]
    scope_cases = [case for case in case_reports if case.get("expected_source_scopes")]
    baseline_cases = [case for case in book_cases if not _is_regression_suite(str(case.get("suite") or ""))]
    baseline_scope_cases = [case for case in scope_cases if not _is_regression_suite(str(case.get("suite") or ""))]
    regression_cases = [case for case in book_cases if _is_regression_suite(str(case.get("suite") or ""))]
    regression_scope_cases = [case for case in scope_cases if _is_regression_suite(str(case.get("suite") or ""))]
    global_summary = _summarize_cases(book_cases=book_cases, scope_cases=scope_cases)
    baseline_summary = _summarize_cases(book_cases=baseline_cases, scope_cases=baseline_scope_cases)
    regression_summary = _summarize_cases(book_cases=regression_cases, scope_cases=regression_scope_cases)
    miss_cases = [
        case
        for case in case_reports
        if ("clean" not in case.get("reasons", []))
    ]
    reason_counts: Counter[str] = Counter()
    for case in miss_cases:
        for reason in case.get("reasons") or []:
            if reason != "clean":
                reason_counts[str(reason)] += 1

    decision = "pass"
    if global_summary["book_case_count"] and global_summary["book_hit@1"] < 0.8:
        decision = "review"
    if global_summary["book_case_count"] and global_summary["book_hit@5"] < 0.95:
        decision = "fail"

    return {
        "schema": "pbs_retrieval_gap_audit_v1",
        "generated_at": _now(),
        "decision": decision,
        "summary": global_summary,
        "baseline_summary": baseline_summary,
        "regression_summary": regression_summary,
        "suite_summaries": suite_summaries,
        "reason_counts": dict(sorted(reason_counts.items())),
        "miss_cases": sorted(
            miss_cases,
            key=lambda case: (
                0 if "expected_book_absent_at5" in case.get("reasons", []) else 1,
                0 if "rerank_regression" in case.get("reasons", []) else 1,
                int(case.get("expected_rank") or 99) or 99,
                str(case.get("suite") or ""),
                str(case.get("id") or ""),
            ),
        ),
        "recommendations": _recommendations(global_summary, reason_counts),
    }


def _is_regression_suite(suite_name: str) -> bool:
    return "regression" in suite_name.casefold()


def _summarize_cases(*, book_cases: list[dict[str, Any]], scope_cases: list[dict[str, Any]]) -> dict[str, Any]:
    book_total = len(book_cases)
    scope_total = len(scope_cases)
    return {
        "book_case_count": book_total,
        "book_hit@1": _ratio(sum(1 for case in book_cases if case.get("top1_book_hit")), book_total),
        "book_hit@3": _ratio(sum(1 for case in book_cases if case.get("top3_book_hit")), book_total),
        "book_hit@5": _ratio(sum(1 for case in book_cases if case.get("top5_book_hit")), book_total),
        "book_miss@1_count": sum(1 for case in book_cases if not case.get("top1_book_hit")),
        "book_miss@5_count": sum(1 for case in book_cases if not case.get("top5_book_hit")),
        "scope_case_count": scope_total,
        "scope_hit@1": _ratio(sum(1 for case in scope_cases if case.get("top1_scope_hit")), scope_total),
        "scope_hit@5": _ratio(sum(1 for case in scope_cases if case.get("top5_scope_hit")), scope_total),
        "scope_miss@1_count": sum(1 for case in scope_cases if not case.get("top1_scope_hit")),
    }


def _recommendations(summary: dict[str, Any], reason_counts: Counter[str]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if reason_counts.get("similar_document", 0):
        recommendations.append(
            {
                "area": "book_intent_prior",
                "priority": "P0",
                "detail": (
                    "Expected manuals are present in top-5 but often lose rank 1. Add query-intent/book priors "
                    "and section-level tie breakers before changing the corpus."
                ),
            }
        )
    if reason_counts.get("near_tie", 0):
        recommendations.append(
            {
                "area": "score_tie_breaking",
                "priority": "P0",
                "detail": (
                    "Several misses have very small score margins. Prefer exact heading/query-term overlap, "
                    "procedure sections, and non-navigation chunks when scores are near-tied."
                ),
            }
        )
    if reason_counts.get("rerank_regression", 0):
        recommendations.append(
            {
                "area": "reranker_guardrail",
                "priority": "P1",
                "detail": (
                    "Hybrid rank had an expected manual first but reranking moved it down. Add a regression test "
                    "for those cases and inspect reranker features before tuning weights globally."
                ),
            }
        )
    if reason_counts.get("expected_book_absent_at5", 0):
        recommendations.append(
            {
                "area": "candidate_recall",
                "priority": "P1",
                "detail": "Some expected manuals are absent from top-5. Expand lexical aliases or query rewrites for these topics.",
            }
        )
    if summary.get("scope_case_count") and summary.get("scope_hit@1") == 1.0:
        recommendations.append(
            {
                "area": "source_scope_boundary",
                "priority": "keep",
                "detail": "Source-scope routing is currently stable; keep this as a guard while improving book-level rank.",
            }
        )
    return recommendations


def write_markdown_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    baseline = payload.get("baseline_summary") if isinstance(payload.get("baseline_summary"), dict) else {}
    regression = payload.get("regression_summary") if isinstance(payload.get("regression_summary"), dict) else {}
    lines = [
        "# Retrieval Gap Audit",
        "",
        f"- Schema: `{payload.get('schema')}`",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Book cases: `{summary.get('book_case_count')}`",
        f"- Book hit@1/hit@3/hit@5: `{summary.get('book_hit@1')}` / `{summary.get('book_hit@3')}` / `{summary.get('book_hit@5')}`",
        f"- Book miss@1/miss@5: `{summary.get('book_miss@1_count')}` / `{summary.get('book_miss@5_count')}`",
        f"- Scope cases hit@1/hit@5: `{summary.get('scope_hit@1')}` / `{summary.get('scope_hit@5')}`",
        f"- Baseline book hit@1/hit@5: `{baseline.get('book_hit@1')}` / `{baseline.get('book_hit@5')}`",
        f"- Regression book hit@1/hit@5: `{regression.get('book_hit@1')}` / `{regression.get('book_hit@5')}`",
        "",
        "## Reason Counts",
        "",
    ]
    for reason, count in sorted((payload.get("reason_counts") or {}).items()):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## Recommendations", ""])
    for item in payload.get("recommendations") or []:
        if isinstance(item, dict):
            lines.append(f"- `{item.get('priority')}` `{item.get('area')}`: {item.get('detail')}")
    lines.extend(["", "## Miss Cases", ""])
    for case in (payload.get("miss_cases") or [])[:30]:
        if isinstance(case, dict):
            lines.append(
                f"- `{case.get('suite')}` `{case.get('id')}` rank `{case.get('expected_rank')}` "
                f"reasons `{', '.join(case.get('reasons') or [])}`: {case.get('query')}"
            )
            lines.append(
                f"  top: `{', '.join(case.get('top_book_slugs') or [])}`; "
                f"expected: `{', '.join(case.get('expected_book_slugs') or [])}`"
            )
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_audit(*, input_path: Path, output_json: Path | None = None, output_md: Path | None = None) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"audit JSON root must be an object: {input_path}")
    report = build_retrieval_gap_audit(payload)
    report["input_path"] = str(input_path)
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        write_markdown_report(report, output_md)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit retrieval hit@1 gaps from a foundation audit JSON file.")
    parser.add_argument("--input", required=True, type=Path, help="Path to rag_foundation_audit audit.json")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = run_audit(
        input_path=args.input,
        output_json=args.output_json,
        output_md=args.output_md,
    )
    print(
        json.dumps(
            {
                "decision": payload.get("decision"),
                "summary": payload.get("summary"),
                "reason_counts": payload.get("reason_counts"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if str(payload.get("decision")) in {"pass", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
