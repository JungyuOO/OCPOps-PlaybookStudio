"""Live Studio chat smoke checks against the running HTTP service.

This is intentionally stdlib-only so it can run in the app container or from
the host without adding evaluation dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SECTION_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
LOW_CONFIDENCE_RE = re.compile(r"(low retrieval confidence|점수가 낮|정확히 맞물리는 점수가 낮)", re.IGNORECASE)
FENCED_CODE_RE = re.compile(r"```[^\n`]*\n([\s\S]*?)```")


@dataclass(frozen=True)
class SmokeCase:
    case_id: str
    query: str
    route_kind: str = ""
    source: str = ""
    mode: str = "ops"
    learning_index: int | None = None
    learning_category_key: str = ""
    learning_category_label: str = ""
    learning_target_book_slug: str = ""
    learning_target_title: str = ""
    learning_target_viewer_path: str = ""
    parent_id: str = ""


def _http_json(base_url: str, path: str, params: dict[str, str] | None = None) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(url, timeout=30) as response:  # noqa: S310 - local smoke target by operator input
        return json.loads(response.read().decode("utf-8"))


def _post_stream(base_url: str, path: str, payload: dict[str, Any]) -> tuple[int, list[dict[str, Any]], str]:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:  # noqa: S310 - local smoke target by operator input
        raw = response.read().decode("utf-8")
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return response.status, events, raw


def _post_studio_chat_stream(base_url: str, case: SmokeCase, session_id: str) -> tuple[int, list[dict[str, Any]], str]:
    if case.route_kind == "course":
        return _post_stream(
            base_url,
            "/api/v1/course/chat/stream",
            {
                "message": case.query,
                "session_id": session_id,
                "user_id": "studio-live-smoke",
            },
        )
    return _post_stream(base_url, "/api/chat/stream", _chat_payload(case, session_id))


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _starter_cases(base_url: str) -> tuple[list[SmokeCase], list[SmokeCase]]:
    payload = _http_json(base_url, "/api/studio/starter-questions", {"seed": "studio-live-smoke"})
    starters: list[SmokeCase] = []
    learning_sequence: list[SmokeCase] = []
    for group in payload.get("groups", []):
        if not isinstance(group, dict):
            continue
        for index, item in enumerate(group.get("questions") or []):
            if isinstance(item, dict):
                starters.append(_case_from_starter(item, f"starter:{group.get('key', 'group')}:{index}"))
    for index, item in enumerate(payload.get("learning_sequence") or []):
        if isinstance(item, dict):
            learning_sequence.append(_case_from_starter(item, f"learning-sequence:{index}"))
    return starters, learning_sequence


def _case_from_starter(item: dict[str, Any], case_id: str) -> SmokeCase:
    return SmokeCase(
        case_id=case_id,
        query=str(item.get("question") or "").strip(),
        route_kind=str(item.get("route_kind") or "").strip(),
        source=str(item.get("source") or "starter").strip(),
        mode="course" if str(item.get("route_kind") or "") == "course" else "ops",
        learning_index=item.get("learning_index") if isinstance(item.get("learning_index"), int) else None,
        learning_category_key=str(item.get("category_key") or "").strip(),
        learning_category_label=str(item.get("category_label") or "").strip(),
        learning_target_book_slug=str(item.get("target_book_slug") or "").strip(),
        learning_target_title=str(item.get("target_title") or "").strip(),
        learning_target_viewer_path=str(item.get("target_viewer_path") or "").strip(),
    )


def _manifest_cases(root_dir: Path, limit: int) -> list[SmokeCase]:
    paths = [
        root_dir / "manifests" / "pbs_chat_quality_cases.jsonl",
        root_dir / "manifests" / "pbs_chat_quality_extended_cases.jsonl",
        root_dir / "manifests" / "answer_eval_cases.jsonl",
        root_dir / "manifests" / "answer_eval_realworld_cases.jsonl",
    ]
    cases: list[SmokeCase] = []
    seen: set[str] = set()
    for path in paths:
        for row in _iter_jsonl(path):
            query = str(row.get("query") or "").strip()
            if not query or query in seen:
                continue
            if row.get("clarification_expected") or row.get("no_answer_expected"):
                continue
            seen.add(query)
            cases.append(
                SmokeCase(
                    case_id=f"manifest:{path.name}:{len(cases)}",
                    query=query,
                    route_kind="official",
                    source=str(path.relative_to(root_dir)),
                    mode=str(row.get("mode") or "ops"),
                )
            )
            if len(cases) >= limit:
                return cases
    return cases


def _chat_payload(case: SmokeCase, session_id: str) -> dict[str, Any]:
    return {
        "query": case.query,
        "session_id": session_id,
        "mode": case.mode,
        "route_kind": case.route_kind,
        "learning_index": case.learning_index,
        "learning_category_key": case.learning_category_key,
        "learning_category_label": case.learning_category_label,
        "learning_target_book_slug": case.learning_target_book_slug,
        "learning_target_title": case.learning_target_title,
        "learning_target_viewer_path": case.learning_target_viewer_path,
    }


def _code_blocks(answer: str) -> list[str]:
    return [match.group(1).strip() for match in FENCED_CODE_RE.finditer(answer or "") if match.group(1).strip()]


def _citation_text(citations: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for citation in citations:
        parts.append(str(citation.get("excerpt") or ""))
        parts.extend(str(command) for command in citation.get("cli_commands") or [])
    return "\n".join(parts).lower()


def _validate_case(case: SmokeCase, status: int, events: list[dict[str, Any]], raw: str) -> dict[str, Any]:
    result = next(
        (
            event.get("payload") or event.get("response")
            for event in events
            if event.get("type") == "result"
        ),
        None,
    )
    event_types = [str(event.get("type") or "") for event in events]
    failures: list[str] = []
    if status != 200:
        failures.append(f"http_status:{status}")
    if "answer_delta" not in event_types:
        failures.append("missing_answer_delta")
    if not isinstance(result, dict):
        return {
            "case_id": case.case_id,
            "query": case.query,
            "source": case.source,
            "pass": False,
            "failures": [*failures, "missing_result"],
            "raw_preview": raw[:500],
        }
    answer = str(result.get("answer") or "")
    warnings = [str(item) for item in result.get("warnings") or []]
    citations = [item for item in result.get("citations") or [] if isinstance(item, dict)]
    cited_indices = [int(index) for index in result.get("cited_indices") or [] if isinstance(index, int)]
    suggestions = [str(item).strip() for item in result.get("suggested_queries") or [] if str(item).strip()]
    if len(answer.strip()) < 40:
        failures.append("short_answer")
    if LOW_CONFIDENCE_RE.search(answer) or any(LOW_CONFIDENCE_RE.search(warning) for warning in warnings):
        failures.append("low_confidence_for_seeded_question")
    if result.get("response_kind") == "clarification" and case.route_kind in {"official", "learning", "course"}:
        failures.append("unexpected_clarification")
    if not citations and result.get("response_kind") == "rag":
        failures.append("missing_citations")
    if any(index < 1 or index > len(citations) for index in cited_indices):
        failures.append("invalid_citation_index")
    answer_cites_source = bool(re.search(r"\[\d+\]", answer))
    if citations and not cited_indices and case.route_kind != "course":
        failures.append("missing_inline_cited_indices")
    if citations and case.route_kind == "course" and not answer_cites_source:
        failures.append("missing_inline_citation_marker")
    for citation in citations:
        viewer_path = str(citation.get("viewer_path") or "")
        if not viewer_path:
            failures.append("citation_missing_viewer_path")
            break
    if any(SECTION_NUMBER_PREFIX_RE.search(suggestion) for suggestion in suggestions):
        failures.append("section_numbered_suggestion")
    blocks = _code_blocks(answer)
    citation_text = _citation_text(citations)
    if blocks and citations:
        command_grounded = any(
            block.lower() in citation_text or any(line.strip().lower() in citation_text for line in block.splitlines() if len(line.strip()) > 8)
            for block in blocks
        )
        if not command_grounded:
            failures.append("answer_code_not_visible_in_citations")
    return {
        "case_id": case.case_id,
        "parent_id": case.parent_id,
        "query": case.query,
        "source": case.source,
        "route_kind": case.route_kind,
        "response_kind": result.get("response_kind"),
        "event_types": sorted(set(event_types)),
        "answer_len": len(answer),
        "citation_count": len(citations),
        "cited_indices": cited_indices,
        "warning_count": len(warnings),
        "suggestion_count": len(suggestions),
        "failures": sorted(set(failures)),
        "pass": not failures,
        "answer_preview": answer[:260],
        "citation_preview": [
            {
                "index": citation.get("index"),
                "book_slug": citation.get("book_slug"),
                "section": citation.get("section"),
                "viewer_path": citation.get("viewer_path"),
                "cli_commands": citation.get("cli_commands") or [],
            }
            for citation in citations[:3]
        ],
        "suggested_queries": suggestions[:4],
    }


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    root_dir = Path(args.root_dir).resolve()
    starter_cases, learning_sequence = _starter_cases(args.base_url)
    manifest_cases = _manifest_cases(root_dir, max(0, args.manifest_limit))
    queue: list[SmokeCase] = [*starter_cases, *learning_sequence, *manifest_cases]
    if args.limit > 0:
        queue = queue[: args.limit]
    details: list[dict[str, Any]] = []
    seen_queries = {case.query for case in queue}
    started_at = time.time()
    index = 0
    while index < len(queue):
        if args.limit > 0 and index >= args.limit:
            break
        case = queue[index]
        index += 1
        session_id = f"studio-live-smoke-{int(started_at)}-{index}"
        try:
            status, events, raw = _post_studio_chat_stream(args.base_url, case, session_id)
            detail = _validate_case(case, status, events, raw)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            detail = {
                "case_id": case.case_id,
                "query": case.query,
                "source": case.source,
                "route_kind": case.route_kind,
                "pass": False,
                "failures": [f"request_error:{type(exc).__name__}"],
                "error": str(exc),
            }
        details.append(detail)
        if args.followups_per_case > 0 and detail.get("pass") is True:
            parent_id = str(detail.get("case_id") or "")
            for followup_index, suggestion in enumerate(detail.get("suggested_queries") or []):
                if followup_index >= args.followups_per_case:
                    break
                if suggestion in seen_queries:
                    continue
                seen_queries.add(suggestion)
                queue.append(
                    SmokeCase(
                        case_id=f"followup:{parent_id}:{followup_index}",
                        query=suggestion,
                        route_kind=case.route_kind,
                        source="suggested_query",
                        mode=case.mode,
                        parent_id=parent_id,
                    )
                )
    failed = [detail for detail in details if not detail.get("pass")]
    failure_counts: dict[str, int] = {}
    for detail in failed:
        for failure in detail.get("failures") or []:
            failure_counts[str(failure)] = failure_counts.get(str(failure), 0) + 1
    return {
        "schema": "studio_live_smoke_v1",
        "base_url": args.base_url,
        "case_count": len(details),
        "pass_count": len(details) - len(failed),
        "fail_count": len(failed),
        "pass_rate": round((len(details) - len(failed)) / max(len(details), 1), 4),
        "failure_counts": dict(sorted(failure_counts.items())),
        "duration_sec": round(time.time() - started_at, 3),
        "details": details,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live Studio chat smoke checks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--root-dir", default=".")
    parser.add_argument("--limit", type=int, default=80, help="Maximum total cases including follow-ups. Use 0 for all queued cases.")
    parser.add_argument("--manifest-limit", type=int, default=80)
    parser.add_argument("--followups-per-case", type=int, default=1)
    parser.add_argument("--report-path", default="reports/studio_live_smoke_report.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_smoke(args)
    output_path = Path(args.report_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("case_count", "pass_count", "fail_count", "pass_rate", "failure_counts", "duration_sec")}, ensure_ascii=False, indent=2))
    if report["fail_count"]:
        print(f"wrote failure report: {output_path}", file=sys.stderr)
        return 1
    print(f"wrote report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
