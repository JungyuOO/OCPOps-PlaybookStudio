# answer eval 케이스를 실행하고 통과율 요약을 만드는 평가 로직.
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from play_book_studio.answering.answerer import ChatAnswerer
from play_book_studio.retrieval.models import SessionContext


HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
ANSWER_PREFIX_RE = re.compile(r"^\s*답변:")
CLARIFICATION_RE = re.compile(
    r"(불명확|모호|어느 .*말씀|어떤 .*말씀|무슨 .*말씀|확인해 주시겠|알고 싶으신가요|말씀하시는 건가요|의미하시는 건가요|\?$)"
)
NO_ANSWER_RE = re.compile(
    r"(근거에 .*없습니다|근거가 없습니다|정보가 없습니다|답변할 수 없습니다|답할 수 없습니다|찾을 수 없습니다|포함되어 있지 않습니다)"
)


def _normalize_for_contains(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _ordered_unique_books(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        book_slug = str(row.get("book_slug", "")).strip()
        if not book_slug or book_slug in seen:
            continue
        seen.add(book_slug)
        ordered.append(book_slug)
    return ordered


def evaluate_case(
    answerer: ChatAnswerer,
    case: dict[str, Any],
    *,
    top_k: int,
    candidate_k: int,
    max_context_chunks: int,
) -> dict[str, Any]:
    context = SessionContext.from_dict(case.get("context"))
    result = answerer.answer(
        str(case["query"]),
        mode=str(case.get("mode", "ops")),
        context=context,
        top_k=top_k,
        candidate_k=candidate_k,
        max_context_chunks=max_context_chunks,
    )

    cited_books = [
        citation.book_slug
        for citation in result.citations
        if citation.index in set(result.cited_indices)
    ]
    final_citations = [citation.to_dict() for citation in result.citations]
    expected_books = list(case.get("expected_book_slugs", []))
    forbidden_books = list(case.get("forbidden_book_slugs", []))
    must_include_terms = [str(term) for term in case.get("must_include_terms", [])]
    must_not_include_terms = [str(term) for term in case.get("must_not_include_terms", [])]
    expected_book_set = set(expected_books)
    forbidden_book_set = set(forbidden_books)
    clarification_expected = bool(case.get("clarification_expected", False))
    no_answer_expected = bool(case.get("no_answer_expected", False))

    has_answer = bool(result.answer.strip())
    has_korean = bool(HANGUL_RE.search(result.answer))
    answer_format_valid = bool(ANSWER_PREFIX_RE.search(result.answer))
    has_inline_citations = bool(result.cited_indices)
    citation_indices_valid = all(
        1 <= index <= len(result.citations) for index in result.cited_indices
    )
    clarification_detected = bool(CLARIFICATION_RE.search(result.answer))
    no_answer_detected = bool(NO_ANSWER_RE.search(result.answer))
    assertive_answer_detected = (
        has_answer and not clarification_detected and not no_answer_detected
    )
    normalized_answer = _normalize_for_contains(result.answer)
    missing_required_terms = [
        term for term in must_include_terms if _normalize_for_contains(term) not in normalized_answer
    ]
    forbidden_answer_terms = [
        term for term in must_not_include_terms if _normalize_for_contains(term) in normalized_answer
    ]
    must_include_pass = not missing_required_terms
    must_exclude_pass = not forbidden_answer_terms

    cited_expected_book = any(book_slug in expected_book_set for book_slug in cited_books)
    unexpected_cited_books = [
        book_slug for book_slug in cited_books if book_slug not in expected_book_set
    ]
    forbidden_cited_books = [
        book_slug for book_slug in cited_books if book_slug in forbidden_book_set
    ]
    has_unexpected_citation = bool(unexpected_cited_books or forbidden_cited_books)
    citation_precision = (
        round(
            sum(int(book_slug in expected_book_set) for book_slug in cited_books)
            / max(len(cited_books), 1),
            4,
        )
        if cited_books
        else 0.0
    )

    clarification_needed_but_answered = clarification_expected and assertive_answer_detected
    no_evidence_but_asserted = no_answer_expected and assertive_answer_detected

    standard_pass = all(
        [
            not clarification_expected,
            not no_answer_expected,
            has_answer,
            has_korean,
            answer_format_valid,
            has_inline_citations,
            citation_indices_valid,
            cited_expected_book,
            not result.warnings,
            not forbidden_cited_books,
            must_include_pass,
            must_exclude_pass,
        ]
    )
    clarification_pass = all(
        [
            clarification_expected,
            has_answer,
            has_korean,
            answer_format_valid,
            clarification_detected,
            not forbidden_cited_books,
            must_include_pass,
            must_exclude_pass,
        ]
    )
    no_answer_pass = all(
        [
            no_answer_expected,
            has_answer,
            has_korean,
            answer_format_valid,
            no_answer_detected,
            not cited_books,
            not forbidden_cited_books,
            must_include_pass,
            must_exclude_pass,
        ]
    )
    pass_all = standard_pass or clarification_pass or no_answer_pass

    retrieved_rows = list(result.retrieval_trace.get("bm25", [])) + list(
        result.retrieval_trace.get("vector", [])
    )
    retrieved_books = _ordered_unique_books(retrieved_rows)

    return {
        "id": case.get("id"),
        "mode": case.get("mode", "ops"),
        "query_type": case.get("query_type", "ops"),
        "failure_bucket_hint": str(case.get("failure_bucket_hint", "")).strip(),
        "question": case["query"],
        "query": case["query"],
        "expected_book_slugs": expected_books,
        "forbidden_book_slugs": forbidden_books,
        "must_include_terms": must_include_terms,
        "must_not_include_terms": must_not_include_terms,
        "clarification_expected": clarification_expected,
        "no_answer_expected": no_answer_expected,
        "rewritten_query": result.rewritten_query,
        "retrieved_books": retrieved_books,
        "has_answer": has_answer,
        "has_korean": has_korean,
        "answer_format_valid": answer_format_valid,
        "has_inline_citations": has_inline_citations,
        "citation_indices_valid": citation_indices_valid,
        "clarification_detected": clarification_detected,
        "no_answer_detected": no_answer_detected,
        "clarification_needed_but_answered": clarification_needed_but_answered,
        "no_evidence_but_asserted": no_evidence_but_asserted,
        "must_include_pass": must_include_pass,
        "must_exclude_pass": must_exclude_pass,
        "missing_required_terms": missing_required_terms,
        "forbidden_answer_terms": forbidden_answer_terms,
        "cited_expected_book": cited_expected_book,
        "unexpected_cited_books": unexpected_cited_books,
        "forbidden_cited_books": forbidden_cited_books,
        "has_unexpected_citation": has_unexpected_citation,
        "strict_expected_only": not unexpected_cited_books and not forbidden_cited_books,
        "citation_precision": citation_precision,
        "warning_free": not result.warnings,
        "pass": pass_all,
        "cited_indices": result.cited_indices,
        "cited_books": cited_books,
        "warnings": result.warnings,
        "answer": result.answer,
        "answer_text": result.answer,
        "final_citations": final_citations,
        "citations": final_citations,
        "quality_flags": _quality_flags(
            passed=pass_all,
            has_unexpected_citation=has_unexpected_citation,
            warnings=list(result.warnings),
        ),
    }


def _rate(bucket: list[dict[str, Any]], key: str) -> float:
    total = len(bucket)
    if total == 0:
        return 0.0
    return round(sum(int(item[key]) for item in bucket) / total, 4)


def _conditional_rate(
    bucket: list[dict[str, Any]],
    *,
    condition_key: str,
    value_key: str,
) -> float:
    conditioned = [item for item in bucket if item.get(condition_key)]
    if not conditioned:
        return 0.0
    return round(sum(int(item[value_key]) for item in conditioned) / len(conditioned), 4)


def _classify_failure_root_cause(detail: dict[str, Any]) -> tuple[str, str]:
    warnings = [str(item) for item in detail.get("warnings", [])]
    if any("outside OCP corpus" in warning for warning in warnings):
        return ("policy-overlay", "query or product scope fell outside the active OCP corpus boundary")
    if detail.get("clarification_needed_but_answered"):
        return ("generation", "clarification gate missed and the answer overcommitted")
    if detail.get("no_evidence_but_asserted"):
        return ("generation", "no-answer case still produced an asserted answer")
    expected_books = set(detail.get("expected_book_slugs", []))
    retrieved_books = set(detail.get("retrieved_books", []))
    cited_books = set(detail.get("cited_books", []))
    if expected_books and not retrieved_books:
        return ("retrieval", "retriever returned no candidate books for an answerable case")
    if expected_books and not (retrieved_books & expected_books):
        return ("retrieval", "retriever missed the expected playbook family")
    if detail.get("forbidden_cited_books") or detail.get("unexpected_cited_books"):
        return ("provenance", "answer cited the wrong playbook family or extra provenance")
    if expected_books and (retrieved_books & expected_books) and not (cited_books & expected_books):
        return ("provenance", "retrieval found the right family but final citations did not preserve it")
    if detail.get("missing_required_terms") or detail.get("forbidden_answer_terms"):
        return ("generation", "answer text violated the required or forbidden term contract")
    return ("generation", "answer quality failed after retrieval without a provenance miss")


def _quality_flags(*, passed: bool, has_unexpected_citation: bool, warnings: list[str]) -> list[str]:
    flags: list[str] = []
    if passed and has_unexpected_citation:
        flags.append("provenance_noise")
    if warnings:
        flags.append("warning_present")
    return flags


def summarize_case_results(details: list[dict[str, Any]]) -> dict[str, Any]:
    by_query_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for detail in details:
        by_query_type[str(detail.get("query_type", "unknown"))].append(detail)
        by_mode[str(detail.get("mode", "unknown"))].append(detail)

    def bucket_stats(bucket: list[dict[str, Any]]) -> dict[str, float]:
        return {
            "case_count": len(bucket),
            "answer_present_rate": _rate(bucket, "has_answer"),
            "korean_answer_rate": _rate(bucket, "has_korean"),
            "answer_format_rate": _rate(bucket, "answer_format_valid"),
            "inline_citation_rate": _rate(bucket, "has_inline_citations"),
            "citation_valid_rate": _rate(bucket, "citation_indices_valid"),
            "expected_citation_rate": _rate(bucket, "cited_expected_book"),
            "unexpected_citation_rate": _rate(bucket, "has_unexpected_citation"),
            "strict_expected_only_rate": _rate(bucket, "strict_expected_only"),
            "pass_with_provenance_noise_rate": round(
                sum(
                    int(
                        bool(item.get("pass"))
                        and bool(item.get("has_unexpected_citation"))
                    )
                    for item in bucket
                )
                / max(len(bucket), 1),
                4,
            ),
            "avg_citation_precision": round(
                sum(float(item.get("citation_precision", 0.0)) for item in bucket)
                / max(len(bucket), 1),
                4,
            ),
            "clarification_needed_but_answered_rate": _conditional_rate(
                bucket,
                condition_key="clarification_expected",
                value_key="clarification_needed_but_answered",
            ),
            "no_evidence_but_asserted_rate": _conditional_rate(
                bucket,
                condition_key="no_answer_expected",
                value_key="no_evidence_but_asserted",
            ),
            "must_include_rate": _rate(bucket, "must_include_pass"),
            "must_exclude_rate": _rate(bucket, "must_exclude_pass"),
            "warning_free_rate": _rate(bucket, "warning_free"),
            "pass_rate": _rate(bucket, "pass"),
        }

    failures: list[dict[str, Any]] = []
    root_cause_counts: dict[str, int] = defaultdict(int)
    for detail in details:
        if detail["pass"]:
            continue
        root_cause_tag, root_cause_reason = _classify_failure_root_cause(detail)
        root_cause_counts[root_cause_tag] += 1
        failures.append(
            {
            "id": detail.get("id"),
            "mode": detail.get("mode"),
            "query_type": detail.get("query_type"),
            "failure_bucket_hint": detail.get("failure_bucket_hint", ""),
            "root_cause_tag": root_cause_tag,
            "root_cause_reason": root_cause_reason,
            "question": detail["question"],
            "rewritten_query": detail.get("rewritten_query", ""),
            "expected_book_slugs": detail["expected_book_slugs"],
            "forbidden_book_slugs": detail.get("forbidden_book_slugs", []),
            "must_include_terms": detail.get("must_include_terms", []),
            "must_not_include_terms": detail.get("must_not_include_terms", []),
            "clarification_expected": detail.get("clarification_expected", False),
            "no_answer_expected": detail.get("no_answer_expected", False),
            "retrieved_books": detail.get("retrieved_books", []),
            "cited_books": detail["cited_books"],
            "unexpected_cited_books": detail.get("unexpected_cited_books", []),
            "forbidden_cited_books": detail.get("forbidden_cited_books", []),
            "missing_required_terms": detail.get("missing_required_terms", []),
            "forbidden_answer_terms": detail.get("forbidden_answer_terms", []),
            "citation_precision": detail.get("citation_precision", 0.0),
            "cited_indices": detail.get("cited_indices", []),
            "warnings": detail.get("warnings", []),
            "answer_text": detail.get("answer_text", ""),
            "final_citations": detail.get("final_citations", []),
        }
        )

    provenance_noise_case_ids = [
        str(detail.get("id", ""))
        for detail in details
        if detail.get("pass") and detail.get("has_unexpected_citation")
    ]
    if failures:
        assessment_status = "insufficient"
        assessment_reason = "real-world cases still fail under the active answer contract"
    elif provenance_noise_case_ids:
        assessment_status = "sufficient_with_provenance_noise"
        assessment_reason = "answer contract passes, but some passing cases still cite extra provenance"
    else:
        assessment_status = "sufficient"
        assessment_reason = "real-world cases pass cleanly under the active answer contract"

    return {
        "case_count": len(details),
        "overall": bucket_stats(details),
        "by_query_type": {
            query_type: bucket_stats(bucket)
            for query_type, bucket in sorted(by_query_type.items())
        },
        "by_mode": {
            mode: bucket_stats(bucket)
            for mode, bucket in sorted(by_mode.items())
        },
        "failures": failures,
        "realworld_assessment": {
            "status": assessment_status,
            "reason": assessment_reason,
            "failed_case_count": len(failures),
            "root_cause_counts": dict(sorted(root_cause_counts.items())),
            "provenance_noise_case_ids": provenance_noise_case_ids,
        },
    }
