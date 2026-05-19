"""Run repository-scoped RAG checks against user-uploaded documents."""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


DEFAULT_CASES = "spec/v0.1.4/user_upload_eval/user-upload-rag-50-cases.json"
DEFAULT_OUTPUT = "spec/v0.1.4/user_upload_eval/user-upload-rag-results.json"
DEFAULT_BASE_URL = "http://127.0.0.1:5173"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    topic: str
    question: str
    expected_source_keywords: tuple[str, ...]
    required_answer_terms: tuple[str, ...]
    min_citations: int
    min_answer_chars: int
    require_upload_citation: bool


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _compact_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _text_blob(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text_blob(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_text_blob(item) for item in value)
    return _compact_space(value)


def _load_cases(path: Path) -> tuple[dict[str, Any], list[EvalCase]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"case file must be a JSON object: {path}")
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError(f"case file must contain a cases list: {path}")
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(raw_cases, start=1):
        if not isinstance(row, dict):
            continue
        case_id = _compact_space(row.get("id")) or f"case-{index:03d}"
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        question = _compact_space(row.get("question"))
        if not question:
            raise ValueError(f"case {case_id} has an empty question")
        cases.append(
            EvalCase(
                case_id=case_id,
                topic=_compact_space(row.get("topic")),
                question=question,
                expected_source_keywords=tuple(str(item) for item in row.get("expected_source_keywords") or []),
                required_answer_terms=tuple(str(item) for item in row.get("required_answer_terms") or []),
                min_citations=int(row.get("min_citations") or defaults.get("min_citations") or 1),
                min_answer_chars=int(row.get("min_answer_chars") or defaults.get("min_answer_chars") or 80),
                require_upload_citation=bool(
                    row.get("require_upload_citation", defaults.get("require_upload_citation", True))
                ),
            )
        )
    return payload, cases


def _request_json(
    session: requests.Session,
    *,
    method: str,
    url: str,
    timeout_seconds: float,
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.request(method, url, json=json_payload, timeout=None if timeout_seconds <= 0 else timeout_seconds)
    response.raise_for_status()
    parsed = response.json()
    if not isinstance(parsed, dict):
        return {"raw": parsed}
    return parsed


def _repository_upload_doc_count(repository: dict[str, Any]) -> int:
    documents = repository.get("documents")
    if not isinstance(documents, list):
        return 0
    return sum(1 for doc in documents if isinstance(doc, dict) and str(doc.get("source_scope") or "") == "user_upload")


def _resolve_repository(
    session: requests.Session,
    *,
    base_url: str,
    repository_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = _request_json(
        session,
        method="GET",
        url=f"{base_url.rstrip('/')}/api/repositories/documents",
        timeout_seconds=timeout_seconds,
    )
    repositories = [repo for repo in payload.get("repositories") or [] if isinstance(repo, dict)]
    if repository_id:
        for repo in repositories:
            if str(repo.get("repository_id") or "") == repository_id:
                return repo
        raise ValueError(f"repository_id not found in /api/repositories/documents: {repository_id}")
    user_repositories = [repo for repo in repositories if _repository_upload_doc_count(repo) > 0]
    if not user_repositories:
        raise ValueError("No repository with user_upload documents was returned by /api/repositories/documents.")
    user_repositories.sort(
        key=lambda repo: (
            str(repo.get("slug") or "") != "personal-uploads",
            str(repo.get("repository_kind") or "") != "personal",
            -_repository_upload_doc_count(repo),
        )
    )
    return user_repositories[0]


def _citation_is_user_upload(citation: dict[str, Any]) -> bool:
    blob = _text_blob(
        {
            "book_slug": citation.get("book_slug"),
            "source_url": citation.get("source_url"),
            "viewer_path": citation.get("viewer_path"),
            "href": citation.get("href"),
            "semantic_role": citation.get("semantic_role"),
        }
    )
    return bool(
        "uploaded-documents" in blob
        or "uploaded_document" in blob
        or "/uploads/" in blob
        or "uploads/" in blob
    )


def _citation_blob(citation: dict[str, Any]) -> str:
    return _text_blob(
        {
            "book_slug": citation.get("book_slug"),
            "section": citation.get("section"),
            "source_url": citation.get("source_url"),
            "viewer_path": citation.get("viewer_path"),
            "href": citation.get("href"),
            "source_label": citation.get("source_label"),
            "section_path": citation.get("section_path"),
            "excerpt": citation.get("excerpt"),
        }
    )


def _score_case(case: EvalCase, payload: dict[str, Any]) -> dict[str, Any]:
    answer = str(payload.get("answer") or "")
    citations = [item for item in payload.get("citations") or [] if isinstance(item, dict)]
    citation_text = " ".join(_citation_blob(item) for item in citations)
    combined_text = f"{answer} {citation_text}"
    upload_citations = [item for item in citations if _citation_is_user_upload(item)]
    non_upload_citations = [item for item in citations if not _citation_is_user_upload(item)]
    missing_terms = [term for term in case.required_answer_terms if term and not _contains(answer, term)]
    missing_source_keywords = [
        keyword for keyword in case.expected_source_keywords if keyword and not _contains(citation_text, keyword)
    ]
    failure_reasons: list[str] = []
    if len(answer.strip()) < case.min_answer_chars:
        failure_reasons.append("answer_too_short")
    if str(payload.get("response_kind") or "") in {"", "smalltalk", "no_answer", "clarification", "error"}:
        failure_reasons.append(f"bad_response_kind:{payload.get('response_kind') or 'empty'}")
    if len(citations) < case.min_citations:
        failure_reasons.append("not_enough_citations")
    if case.require_upload_citation and not upload_citations:
        failure_reasons.append("no_user_upload_citation")
    if non_upload_citations:
        failure_reasons.append("non_upload_citation_present")
    if missing_terms:
        failure_reasons.append("missing_required_answer_terms")
    if case.expected_source_keywords and len(missing_source_keywords) == len(case.expected_source_keywords):
        failure_reasons.append("expected_source_not_cited")
    return {
        "verdict": "pass" if not failure_reasons else "review",
        "failure_reasons": failure_reasons,
        "answer_chars": len(answer.strip()),
        "response_kind": str(payload.get("response_kind") or ""),
        "citations_count": len(citations),
        "upload_citations_count": len(upload_citations),
        "non_upload_citations_count": len(non_upload_citations),
        "missing_required_answer_terms": missing_terms,
        "missing_source_keywords": missing_source_keywords,
        "citation_sources": [
            {
                "index": item.get("index"),
                "book_slug": item.get("book_slug"),
                "source_url": item.get("source_url"),
                "viewer_path": item.get("viewer_path"),
                "section": item.get("section"),
                "is_user_upload": _citation_is_user_upload(item),
            }
            for item in citations
        ],
        "answer_preview": re.sub(r"\s+", " ", answer.strip())[:500],
        "combined_text_matched": bool(combined_text.strip()),
    }


def _run_case(
    session: requests.Session,
    case: EvalCase,
    *,
    base_url: str,
    repository_id: str,
    timeout_seconds: float,
    suite_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    chat_payload = {
        "query": case.question,
        "session_id": f"{suite_id}-{case.case_id}-{uuid.uuid4().hex[:8]}",
        "mode": "ops",
        "active_repository_id": repository_id,
        "active_document_id": "",
    }
    result: dict[str, Any] = {
        "case_id": case.case_id,
        "topic": case.topic,
        "question": case.question,
        "request": {
            "path": "/api/chat",
            "active_repository_id": repository_id,
            "active_document_id": "",
        },
    }
    try:
        payload = _request_json(
            session,
            method="POST",
            url=f"{base_url.rstrip('/')}/api/chat",
            timeout_seconds=timeout_seconds,
            json_payload=chat_payload,
        )
        result.update(
            {
                "status": "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "response": {
                    "answer": str(payload.get("answer") or ""),
                    "response_kind": str(payload.get("response_kind") or ""),
                    "warnings": list(payload.get("warnings") or [])[:10],
                    "rewritten_query": str(payload.get("rewritten_query") or ""),
                },
                "evaluation": _score_case(case, payload),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result.update(
            {
                "status": "error",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": str(exc),
                "evaluation": {
                    "verdict": "review",
                    "failure_reasons": ["request_error"],
                },
            }
        )
    return result


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    ok_count = sum(1 for item in results if item.get("status") == "ok")
    pass_count = sum(1 for item in results if item.get("evaluation", {}).get("verdict") == "pass")
    reason_counts: dict[str, int] = {}
    for item in results:
        for reason in item.get("evaluation", {}).get("failure_reasons") or []:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    return {
        "total": total,
        "ok": ok_count,
        "pass": pass_count,
        "review": total - pass_count,
        "pass_rate": round(pass_count / total, 4) if total else 0.0,
        "reason_counts": reason_counts,
    }


def _write_markdown_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# User Upload RAG Eval",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- base_url: {payload.get('base_url')}",
        f"- repository: {payload.get('repository', {}).get('title')} ({payload.get('repository', {}).get('repository_id')})",
        f"- document_count: {payload.get('repository', {}).get('document_count')}",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    for key in ("total", "ok", "pass", "review", "pass_rate"):
        lines.append(f"- {key}: {summary.get(key)}")
    reason_counts = summary.get("reason_counts") if isinstance(summary.get("reason_counts"), dict) else {}
    if reason_counts:
        lines.extend(["", "## Review Reasons", ""])
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
            lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Cases", ""])
    for row in payload.get("results") or []:
        evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
        lines.append(
            f"- `{row.get('case_id')}` {evaluation.get('verdict')} "
            f"({row.get('duration_ms')} ms): {row.get('question')}"
        )
        reasons = evaluation.get("failure_reasons") if isinstance(evaluation.get("failure_reasons"), list) else []
        if reasons:
            lines.append(f"  - reasons: {', '.join(str(reason) for reason in reasons)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_eval(
    *,
    cases_path: Path,
    output_path: Path,
    base_url: str,
    repository_id: str,
    limit: int,
    start_index: int,
    timeout_seconds: float,
    x_user: str,
    resume: bool,
) -> dict[str, Any]:
    suite, cases = _load_cases(cases_path)
    selected = cases[max(start_index, 1) - 1:]
    if limit > 0:
        selected = selected[:limit]
    selected_case_ids = {case.case_id for case in selected}
    previous_results: list[dict[str, Any]] = []
    if resume and output_path.is_file():
        try:
            previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_payload = {}
        if isinstance(previous_payload, dict) and isinstance(previous_payload.get("results"), list):
            previous_results = [
                row
                for row in previous_payload["results"]
                if isinstance(row, dict) and str(row.get("case_id") or "") in selected_case_ids
            ]
    completed_case_ids = {str(row.get("case_id") or "") for row in previous_results}
    pending_cases = [case for case in selected if case.case_id not in completed_case_ids]
    session = requests.Session()
    if x_user:
        session.headers.update({"X-User": x_user})
    repository = _resolve_repository(
        session,
        base_url=base_url,
        repository_id=repository_id,
        timeout_seconds=timeout_seconds,
    )
    resolved_repository_id = str(repository.get("repository_id") or "")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "generated_at": _now(),
        "suite": {
            "suite_id": suite.get("suite_id"),
            "title": suite.get("title"),
            "case_count": len(cases),
            "selected_count": len(selected),
            "pending_count": len(pending_cases),
            "start_index": max(start_index, 1),
            "limit": limit,
            "resume": resume,
        },
        "base_url": base_url,
        "repository": {
            "repository_id": resolved_repository_id,
            "slug": repository.get("slug"),
            "title": repository.get("title"),
            "repository_kind": repository.get("repository_kind"),
            "visibility": repository.get("visibility"),
            "owner_user_id": repository.get("owner_user_id"),
            "document_count": _repository_upload_doc_count(repository),
            "documents": [
                {
                    "document_source_id": doc.get("document_source_id"),
                    "title": doc.get("title"),
                    "filename": doc.get("filename"),
                    "chunk_count": doc.get("chunk_count"),
                    "indexed_chunk_count": doc.get("indexed_chunk_count"),
                    "source_scope": doc.get("source_scope"),
                    "visibility": doc.get("visibility"),
                }
                for doc in repository.get("documents") or []
                if isinstance(doc, dict) and str(doc.get("source_scope") or "") == "user_upload"
            ],
        },
        "summary": _summary([]),
        "results": previous_results,
    }
    payload["summary"] = _summary(payload["results"])
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in pending_cases:
        row = _run_case(
            session,
            case,
            base_url=base_url,
            repository_id=resolved_repository_id,
            timeout_seconds=timeout_seconds,
            suite_id=str(suite.get("suite_id") or "user-upload-rag"),
        )
        payload["results"].append(row)
        payload["summary"] = _summary(payload["results"])
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "progress": f"{len(payload['results'])}/{len(selected)}",
                    "case_id": row.get("case_id"),
                    "status": row.get("status"),
                    "verdict": row.get("evaluation", {}).get("verdict"),
                    "duration_ms": row.get("duration_ms"),
                    "output": str(output_path),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    markdown_path = output_path.with_suffix(".md")
    _write_markdown_report(markdown_path, payload)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate RAG answers against the user-upload repository.")
    parser.add_argument("--cases", default=DEFAULT_CASES, help="Path to the 50-question JSON case file.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write JSON results.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Running PlayBook Studio UI/API base URL.")
    parser.add_argument("--repository-id", default="", help="Repository id to test. Defaults to the user upload repository.")
    parser.add_argument("--limit", type=int, default=0, help="Limit case count. 0 means all selected cases.")
    parser.add_argument("--start-index", type=int, default=1, help="1-based start index after case-file order.")
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="Per-request timeout. Use 0 for no timeout.")
    parser.add_argument("--x-user", default="", help="Optional X-User header when testing a browser-created private owner.")
    parser.add_argument("--resume", action="store_true", help="Skip case ids already present in the output file.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = run_eval(
        cases_path=Path(args.cases).resolve(),
        output_path=Path(args.output).resolve(),
        base_url=str(args.base_url),
        repository_id=str(args.repository_id or ""),
        limit=int(args.limit),
        start_index=int(args.start_index),
        timeout_seconds=float(args.timeout_seconds),
        x_user=str(args.x_user or ""),
        resume=bool(args.resume),
    )
    print(json.dumps({"output": str(Path(args.output).resolve()), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
