from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS_PATH = Path(__file__).with_name("chat_benchmark_questions.jsonl")
DEFAULT_QUERIES = (
    "ocp 로그인 어떻게 함",
    "모든 프로젝트에서 pod 중단 예산 확인 어떻게해?",
    "Node 상태는 어떤 명령으로 먼저 확인하나요?",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chat benchmark cases and collect stage timing evidence.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--questions-file", default=str(DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", default="reports/chat_performance_report.json")
    parser.add_argument("--route-kind", default="official")
    parser.add_argument("--mode", default="ops")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _decode_stream_line(raw_line: bytes) -> dict[str, Any] | None:
    text = raw_line.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    if text.startswith("data:"):
        text = text[5:].strip()
    if text == "[DONE]":
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"type": "decode_error", "raw": text}
    return payload if isinstance(payload, dict) else {"type": "unknown", "payload": payload}


def _stage_name(step: str) -> str:
    return {
        "request_received": "request received",
        "route_query": "route / intent routing",
        "normalize_query": "query normalization",
        "rewrite_query": "query signal extraction / expansion planning",
        "query_expansion": "embedding query generation",
        "bm25_search": "BM25 keyword retrieval",
        "vector_search": "parallel vector retrieval + Qdrant metadata filter",
        "fusion": "retrieval fusion / dedup",
        "graph_expand": "graph evidence expansion",
        "context_assembly": "LLM citation context assembly",
        "prompt_build": "LLM prompt build",
        "llm_generate": "answer generation",
        "llm_runtime": "LLM runtime accounting",
        "citation_finalize": "citation cleanup",
        "grounding_guard": "grounding guard",
        "pipeline_complete": "pipeline complete",
    }.get(step, step)


def _result_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("type") == "result" and isinstance(event.get("payload"), dict):
            return dict(event["payload"])
    return {}


def _answer_from_events(events: list[dict[str, Any]], result: dict[str, Any]) -> str:
    answer = str(result.get("answer") or "").strip()
    if answer:
        return answer
    return "".join(str(event.get("delta") or "") for event in events if event.get("type") == "answer_delta").strip()


def _first_delta_ms(events: list[dict[str, Any]]) -> float | None:
    for event in events:
        if event.get("type") == "answer_delta":
            value = event.get("received_ms")
            return float(value) if isinstance(value, int | float) else None
    return None


def _trace_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": event.get("step"),
            "stage": _stage_name(str(event.get("step") or "")),
            "label": event.get("label"),
            "status": event.get("status"),
            "detail": event.get("detail"),
            "timestamp_ms": event.get("timestamp_ms"),
            "duration_ms": event.get("duration_ms"),
            "received_ms": event.get("received_ms"),
            "meta": event.get("meta"),
        }
        for event in events
        if event.get("type") == "trace"
    ]


def _print_trace_event(event: dict[str, Any]) -> None:
    if event.get("type") != "trace":
        return
    step = str(event.get("step") or "")
    status = str(event.get("status") or "")
    duration = event.get("duration_ms")
    timestamp = event.get("timestamp_ms")
    duration_text = f"{float(duration) / 1000:.2f}s" if isinstance(duration, int | float) else "-"
    timestamp_text = f"{float(timestamp) / 1000:.2f}s" if isinstance(timestamp, int | float) else "-"
    print(f"  [{timestamp_text}] {status:7} {_stage_name(step)} ({step}) duration={duration_text}")
    detail = str(event.get("detail") or "")
    if detail:
        print(f"      detail: {detail[:260]}")


def _load_question_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    if args.queries:
        cases.extend(
            {
                "id": f"cli-{index:03d}",
                "category": "cli",
                "query": query,
                "route_kind": args.route_kind,
                "mode": args.mode,
            }
            for index, query in enumerate(args.queries, start=1)
        )
    else:
        path = Path(args.questions_file)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                row = json.loads(line)
                if isinstance(row, dict) and str(row.get("query") or "").strip():
                    cases.append(row)
    if not cases:
        cases.extend(
            {
                "id": f"default-{index:03d}",
                "category": "default",
                "query": query,
                "route_kind": args.route_kind,
                "mode": args.mode,
            }
            for index, query in enumerate(DEFAULT_QUERIES, start=1)
        )
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    return cases


def _post_stream_events(
    base_url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    started_at: float,
    verbose: bool,
) -> list[dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            event = _decode_stream_line(raw_line)
            if event is None:
                continue
            event["received_ms"] = round((time.perf_counter() - started_at) * 1000, 1)
            events.append(event)
            if verbose:
                _print_trace_event(event)
    return events


def _vector_pass_summary(vector_runtime: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subquery in vector_runtime.get("subqueries") or []:
        if not isinstance(subquery, dict):
            continue
        rows.append(
            {
                "query": subquery.get("query"),
                "metadata_filter_pass": subquery.get("metadata_filter_pass"),
                "hit_count": subquery.get("hit_count"),
                "top_score": subquery.get("top_score"),
                "embedding_ms": subquery.get("embedding_ms"),
                "qdrant_ms": subquery.get("qdrant_ms"),
                "hydrate_ms": subquery.get("hydrate_ms"),
                "metadata_filter": subquery.get("metadata_filter"),
                "filter_passes": subquery.get("filter_passes") or [],
            }
        )
    return rows


def run_query(
    base_url: str,
    case: dict[str, Any],
    *,
    timeout: float,
    index: int,
    default_route_kind: str,
    default_mode: str,
    verbose: bool,
) -> dict[str, Any]:
    query = str(case.get("query") or "").strip()
    case_id = str(case.get("id") or f"case-{index:03d}")
    category = str(case.get("category") or "")
    route_kind = str(case.get("route_kind") or default_route_kind)
    mode = str(case.get("mode") or default_mode)
    payload = {
        "message": query,
        "query": query,
        "route_kind": route_kind,
        "mode": mode,
        "session_id": f"perf-{index:03d}",
    }
    if verbose:
        print(f"\n[{index:03d}] {case_id} category={category or '-'} route={route_kind} mode={mode}")
        print(f"  question: {query}")
    started_at = time.perf_counter()
    events = _post_stream_events(base_url, payload, timeout=timeout, started_at=started_at, verbose=verbose)
    total_ms = round((time.perf_counter() - started_at) * 1000, 1)
    result = _result_payload(events)
    retrieval_trace = result.get("retrieval_trace") if isinstance(result.get("retrieval_trace"), dict) else {}
    pipeline_trace = result.get("pipeline_trace") if isinstance(result.get("pipeline_trace"), dict) else {}
    citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    vector_runtime = retrieval_trace.get("vector_runtime") if isinstance(retrieval_trace.get("vector_runtime"), dict) else {}
    item = {
        "id": case_id,
        "category": category,
        "query": query,
        "route_kind": route_kind,
        "mode": mode,
        "total_ms": total_ms,
        "first_delta_ms": _first_delta_ms(events),
        "response_kind": result.get("response_kind"),
        "answer": _answer_from_events(events, result),
        "warnings": result.get("warnings") or [],
        "stage_timings_ms": {
            "retrieval": retrieval_trace.get("timings_ms") or {},
            "pipeline": pipeline_trace.get("timings_ms") or {},
        },
        "llm_runtime": pipeline_trace.get("llm") or {},
        "query_signal_debug": retrieval_trace.get("query_signal_debug") or {},
        "vector_runtime": vector_runtime,
        "vector_pass_summary": _vector_pass_summary(vector_runtime),
        "reranker": retrieval_trace.get("reranker") or {},
        "citations": [
            {
                "index": citation.get("index"),
                "book_slug": citation.get("book_slug"),
                "section": citation.get("section"),
                "source_url": citation.get("source_url"),
            }
            for citation in citations
            if isinstance(citation, dict)
        ],
        "trace_events": _trace_events(events),
    }
    if verbose:
        _print_result_summary(item)
    return item


def _print_result_summary(item: dict[str, Any]) -> None:
    total = float(item.get("total_ms") or 0.0) / 1000
    first_delta = float(item.get("first_delta_ms") or 0.0) / 1000
    print(f"  total={total:.2f}s first_delta={first_delta:.2f}s kind={item.get('response_kind')}")
    retrieval = item.get("stage_timings_ms", {}).get("retrieval", {})
    if isinstance(retrieval, dict):
        parts = ", ".join(f"{key}={float(value) / 1000:.2f}s" for key, value in retrieval.items())
        print(f"  retrieval: {parts}")
    vector_runtime = item.get("vector_runtime") if isinstance(item.get("vector_runtime"), dict) else {}
    query_signal_debug = item.get("query_signal_debug") if isinstance(item.get("query_signal_debug"), dict) else {}
    if query_signal_debug:
        print(f"  query_signal: mode={query_signal_debug.get('mode')} llm_enabled={query_signal_debug.get('llm_enabled')}")
        timings = query_signal_debug.get("timings_ms") if isinstance(query_signal_debug.get("timings_ms"), dict) else {}
        if timings:
            parts = ", ".join(f"{key}={float(value) / 1000:.2f}s" for key, value in timings.items())
            print(f"  query_signal timings: {parts}")
        timeline = query_signal_debug.get("timeline_ms") if isinstance(query_signal_debug.get("timeline_ms"), dict) else {}
        if timeline:
            print("  query_signal timeline:")
            for key, value in timeline.items():
                print(f"    +{float(value) / 1000:.3f}s {key}")
        request = query_signal_debug.get("request") if isinstance(query_signal_debug.get("request"), dict) else {}
        if request:
            print(
                "  query_signal request: "
                f"messages={request.get('message_count')} prompt_chars={request.get('prompt_chars')} "
                f"max_tokens={request.get('max_tokens')}"
            )
        query_signal_http = query_signal_debug.get("llm_http_debug") if isinstance(query_signal_debug.get("llm_http_debug"), dict) else {}
        if query_signal_http:
            print("  query_signal llm_http_debug:")
            print(json.dumps(query_signal_http, ensure_ascii=False, indent=2))
        messages = query_signal_debug.get("messages") if isinstance(query_signal_debug.get("messages"), list) else []
        if messages:
            print("  query_signal messages:")
            for index, message in enumerate(messages, start=1):
                print(f"    [{index}] role={message.get('role')}")
                print(str(message.get("content") or ""))
        raw_response = str(query_signal_debug.get("raw_response") or "")
        if raw_response:
            print("  query_signal raw_response:")
            print(raw_response)
        parsed_payload = query_signal_debug.get("parsed_payload")
        if parsed_payload:
            print("  query_signal parsed_payload:")
            print(json.dumps(parsed_payload, ensure_ascii=False, indent=2))
        validated_plan = query_signal_debug.get("validated_plan")
        if validated_plan:
            print("  query_signal validated_plan:")
            print(json.dumps(validated_plan, ensure_ascii=False, indent=2))
    llm_runtime = item.get("llm_runtime") if isinstance(item.get("llm_runtime"), dict) else {}
    if llm_runtime:
        print(
            "  answer_llm: "
            f"provider={llm_runtime.get('last_provider') or llm_runtime.get('preferred_provider')} "
            f"round_trip={float(llm_runtime.get('provider_round_trip_ms') or 0.0) / 1000:.2f}s "
            f"post_process={float(llm_runtime.get('post_process_ms') or 0.0) / 1000:.3f}s"
        )
        answer_http = llm_runtime.get("last_http_debug") if isinstance(llm_runtime.get("last_http_debug"), dict) else {}
        if answer_http:
            print("  answer_llm llm_http_debug:")
            print(json.dumps(answer_http, ensure_ascii=False, indent=2))
    print(
        "  vector: "
        f"parallel={vector_runtime.get('parallel_enabled')} workers={vector_runtime.get('parallel_workers')} "
        f"subqueries={vector_runtime.get('subquery_count')}"
    )
    for subquery in item.get("vector_pass_summary") or []:
        print(
            "    - "
            f"filter_pass={subquery.get('metadata_filter_pass')} "
            f"hits={subquery.get('hit_count')} "
            f"embed={float(subquery.get('embedding_ms') or 0.0) / 1000:.2f}s "
            f"qdrant={float(subquery.get('qdrant_ms') or 0.0) / 1000:.2f}s "
            f"hydrate={float(subquery.get('hydrate_ms') or 0.0) / 1000:.2f}s"
        )
        print(f"      query: {str(subquery.get('query') or '')[:180]}")
    citations = [
        f"{citation.get('book_slug')}::{citation.get('section')}"
        for citation in item.get("citations", [])
        if isinstance(citation, dict)
    ]
    if citations:
        print(f"  citations: {citations[:4]}")
    answer = str(item.get("answer") or "").replace("\n", " ").strip()
    print(f"  answer: {answer[:320]}")


def _write_markdown(report: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Chat Performance Report",
        "",
        f"- Base URL: `{report['base_url']}`",
        f"- Generated at: `{report['generated_at_epoch']}`",
        f"- Case count: `{len(report['results'])}`",
        "",
    ]
    for item in report["results"]:
        lines.extend(
            [
                f"## {item.get('id')} - {item.get('query')}",
                "",
            ]
        )
        if item.get("error"):
            lines.extend([f"- Error: `{item['error']}`", ""])
            continue
        lines.extend(
            [
                f"- Category: `{item.get('category')}`",
                f"- Total: `{float(item.get('total_ms') or 0.0) / 1000:.2f}s`",
                f"- First answer delta: `{float(item.get('first_delta_ms') or 0.0) / 1000:.2f}s`",
                f"- Response kind: `{item.get('response_kind')}`",
                f"- Warnings: `{', '.join(item.get('warnings') or [])}`",
                "",
                "### Stage timings",
                "",
            ]
        )
        for group, timings in item.get("stage_timings_ms", {}).items():
            if isinstance(timings, dict):
                lines.append(f"- {group}: " + ", ".join(f"{key}={float(value) / 1000:.2f}s" for key, value in timings.items()))
        query_signal_debug = item.get("query_signal_debug") if isinstance(item.get("query_signal_debug"), dict) else {}
        if query_signal_debug:
            lines.extend(["", "### Query signal debug", ""])
            lines.append("```json")
            lines.append(json.dumps(query_signal_debug, ensure_ascii=False, indent=2))
            lines.append("```")
        llm_runtime = item.get("llm_runtime") if isinstance(item.get("llm_runtime"), dict) else {}
        if llm_runtime:
            lines.extend(["", "### Answer LLM runtime", ""])
            lines.append("```json")
            lines.append(json.dumps(llm_runtime, ensure_ascii=False, indent=2))
            lines.append("```")
        lines.extend(["", "### Vector passes", ""])
        for row in item.get("vector_pass_summary") or []:
            lines.append(
                "- "
                f"pass={row.get('metadata_filter_pass')} "
                f"hits={row.get('hit_count')} "
                f"qdrant={float(row.get('qdrant_ms') or 0.0) / 1000:.2f}s "
                f"query={row.get('query')}"
            )
        answer = str(item.get("answer") or "").strip()
        lines.extend(["", "### Answer", "", answer[:2000] or "(empty)", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    cases = _load_question_cases(args)
    results: list[dict[str, Any]] = []
    verbose = not args.quiet
    for index, case in enumerate(cases, start=1):
        try:
            results.append(
                run_query(
                    args.base_url,
                    case,
                    timeout=args.timeout,
                    index=index,
                    default_route_kind=args.route_kind,
                    default_mode=args.mode,
                    verbose=verbose,
                )
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error_item = {
                "id": str(case.get("id") or f"case-{index:03d}"),
                "category": str(case.get("category") or ""),
                "query": str(case.get("query") or ""),
                "error": str(exc),
            }
            if verbose:
                print(f"\n[{index:03d}] {error_item['id']} ERROR: {exc}")
            results.append(error_item)
    report = {
        "base_url": args.base_url,
        "questions_file": args.questions_file,
        "generated_at_epoch": round(time.time(), 3),
        "target_total_seconds": 19.9,
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report, output_path.with_suffix(".md"))
    print(f"\nreport_json={output_path}")
    print(f"report_md={output_path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
