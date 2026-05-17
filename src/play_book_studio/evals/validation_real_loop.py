"""Run validation questions through the live service and compare afterward.

The live loop intentionally sends only the question to the service. Gold
answers are loaded only after service responses have been persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from play_book_studio.console_encoding import force_utf8_stdio
from play_book_studio.http.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL


QUESTION_KEYS = ("Question", "question", "query")
ANSWER_KEYS = ("answer", "Answer", "expected_answer")
TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/-]+|[가-힣]+")
COMMAND_RE = re.compile(
    r"(?m)^\s*((?:oc|kubectl|openshift-install|journalctl|systemctl|helm|curl)\b[^\n`]*)"
)
INLINE_COMMAND_RE = re.compile(
    r"`((?:oc|kubectl|openshift-install|journalctl|systemctl|helm|curl)\b[^`]*)`"
)
CITATION_RE = re.compile(r"\[\d+\]")
CODE_FENCE_RE = re.compile(r"```[^\n`]*\n|```")


@dataclass(frozen=True)
class BlindQuestionCase:
    case_id: str
    source_file: str
    source_index: int
    question: str


@dataclass(frozen=True)
class GoldAnswerCase:
    case_id: str
    answer: str


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("cases") or payload.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"Unsupported validation JSON shape: {path}")


def load_blind_question_cases(root_dir: Path, pattern: str) -> list[BlindQuestionCase]:
    cases: list[BlindQuestionCase] = []
    for path in sorted(root_dir.glob(pattern)):
        if path.name == "real_loop.json":
            continue
        for index, row in enumerate(_load_json_rows(path)):
            question = _first_text(row, QUESTION_KEYS)
            if not question:
                continue
            rel_path = path.relative_to(root_dir).as_posix()
            cases.append(
                BlindQuestionCase(
                    case_id=f"{path.stem}:{index + 1:04d}",
                    source_file=rel_path,
                    source_index=index,
                    question=question,
                )
            )
    return cases


def load_gold_answer_cases(root_dir: Path, pattern: str) -> dict[str, GoldAnswerCase]:
    answers: dict[str, GoldAnswerCase] = {}
    for path in sorted(root_dir.glob(pattern)):
        if path.name == "real_loop.json":
            continue
        for index, row in enumerate(_load_json_rows(path)):
            answer = _first_text(row, ANSWER_KEYS)
            if not answer:
                continue
            answers[f"{path.stem}:{index + 1:04d}"] = GoldAnswerCase(
                case_id=f"{path.stem}:{index + 1:04d}",
                answer=answer,
            )
    return answers


def _request_timeout(timeout_seconds: float) -> float | None:
    return None if timeout_seconds <= 0 else timeout_seconds


def _post_chat(base_url: str, query: str, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
    payload = {"query": query}
    request = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=_request_timeout(timeout_seconds)) as response:  # noqa: S310 - operator-supplied service URL
        body = response.read().decode("utf-8")
        parsed = json.loads(body) if body.strip() else {}
        if not isinstance(parsed, dict):
            parsed = {"raw": parsed}
        return response.status, parsed


def _post_chat_stream(base_url: str, query: str, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
    payload = {"query": query}
    request = Request(
        f"{base_url.rstrip('/')}/api/chat/stream",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    answer_parts: list[str] = []
    with urlopen(request, timeout=_request_timeout(timeout_seconds)) as response:  # noqa: S310 - operator-supplied service URL
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            events.append(event)
            if event.get("type") == "answer_delta":
                answer_parts.append(str(event.get("delta") or ""))
            if event.get("type") == "result" and isinstance(event.get("payload"), dict):
                payload = dict(event["payload"])
                payload.setdefault("answer", "".join(answer_parts))
                payload["_stream_events"] = events
                return response.status, payload
            if event.get("type") == "error":
                return response.status, {
                    "answer": "".join(answer_parts),
                    "response_kind": "error",
                    "warnings": [str(event.get("error") or "stream error")],
                    "_stream_events": events,
                }
    return response.status, {
        "answer": "".join(answer_parts),
        "response_kind": "stream_incomplete",
        "warnings": ["stream ended without result event"],
        "_stream_events": events,
    }


def _compact_trace(payload: dict[str, Any]) -> dict[str, Any]:
    retrieval_trace = payload.get("retrieval_trace")
    pipeline_trace = payload.get("pipeline_trace")
    compact: dict[str, Any] = {}
    if isinstance(retrieval_trace, dict):
        compact["retrieval_route"] = str(retrieval_trace.get("route") or "")
        compact["metadata_filter_fallback"] = bool(retrieval_trace.get("metadata_filter_fallback"))
        compact["warnings"] = list(retrieval_trace.get("warnings") or [])[:5]
    if isinstance(pipeline_trace, dict):
        timings = pipeline_trace.get("timings_ms")
        if isinstance(timings, dict):
            compact["timings_ms"] = {
                str(key): round(float(value), 1)
                for key, value in timings.items()
                if isinstance(value, int | float)
            }
    stream_events = payload.get("_stream_events")
    if isinstance(stream_events, list):
        compact["stream_event_count"] = len(stream_events)
        compact["stream_steps"] = [
            str(event.get("step") or event.get("type") or "")
            for event in stream_events
            if isinstance(event, dict)
        ][:30]
    return compact


def run_service_loop(
    cases: list[BlindQuestionCase],
    *,
    base_url: str,
    timeout_seconds: float,
    stream: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        result: dict[str, Any] = {
            "case_id": case.case_id,
            "source_file": case.source_file,
            "source_index": case.source_index,
            "question": case.question,
            "question_sha256_16": _stable_hash(case.question),
            "request": {
                "path": "/api/chat/stream" if stream else "/api/chat",
                "payload_keys": ["query"],
            },
        }
        try:
            if stream:
                status_code, payload = _post_chat_stream(base_url, case.question, timeout_seconds)
            else:
                status_code, payload = _post_chat(base_url, case.question, timeout_seconds)
            result.update(
                {
                    "status": "ok" if status_code < 400 else "http_error",
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "answer": str(payload.get("answer") or ""),
                    "response_kind": str(payload.get("response_kind") or ""),
                    "warnings": list(payload.get("warnings") or [])[:10],
                    "citations_count": len(payload.get("citations") or []),
                    "trace": _compact_trace(payload),
                }
            )
        except HTTPError as exc:
            result.update(
                {
                    "status": "http_error",
                    "status_code": exc.code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "answer": "",
                    "error": exc.read().decode("utf-8", errors="replace")[:1000],
                }
            )
        except (TimeoutError, URLError, OSError, json.JSONDecodeError) as exc:
            result.update(
                {
                    "status": "error",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "answer": "",
                    "error": str(exc),
                }
            )
        results.append(result)
    return results


def _normalize_text(text: str) -> str:
    cleaned = CODE_FENCE_RE.sub(" ", text)
    cleaned = CITATION_RE.sub(" ", cleaned)
    return " ".join(cleaned.lower().split())


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(_normalize_text(text)) if len(token.strip()) > 1}


def _commands(text: str) -> set[str]:
    commands = {" ".join(match.group(1).lower().split()) for match in COMMAND_RE.finditer(text)}
    commands.update(" ".join(match.group(1).lower().split()) for match in INLINE_COMMAND_RE.finditer(text))
    return {command for command in commands if command}


def _command_family(command: str) -> str:
    lowered = " ".join(command.lower().split())
    if lowered.startswith("oc adm certificate approve"):
        return "oc_adm_certificate_approve"
    if lowered.startswith("oc adm must-gather"):
        return "oc_adm_must_gather"
    if lowered.startswith("oc adm upgrade"):
        return "oc_adm_upgrade"
    if lowered.startswith("oc new-project"):
        return "oc_new_project"
    if lowered.startswith("oc new-app"):
        return "oc_new_app"
    if lowered.startswith("oc api-resources"):
        return "oc_api_resources"
    if lowered.startswith("oc project"):
        return "oc_project"
    if lowered.startswith("oc status"):
        return "oc_status"
    if lowered.startswith("oc logs"):
        return "oc_logs"
    if lowered.startswith("oc get"):
        return "oc_get"
    if lowered.startswith("oc describe"):
        return "oc_describe"
    if lowered.startswith("oc create"):
        return "oc_create"
    if lowered.startswith("oc delete"):
        return "oc_delete"
    if lowered.startswith("oc patch"):
        return "oc_patch"
    if lowered.startswith("oc edit"):
        return "oc_edit"
    if lowered.startswith("oc label"):
        return "oc_label"
    if lowered.startswith("oc debug"):
        return "oc_debug"
    if lowered.startswith("oc image extract"):
        return "oc_image_extract"
    if lowered.startswith("oc import-image"):
        return "oc_import_image"
    if lowered.startswith("oc tag"):
        return "oc_tag"
    if lowered.startswith("kubectl"):
        return "kubectl"
    if lowered.startswith("ccoctl"):
        return "ccoctl"
    return "_".join(lowered.split()[:2]) if lowered else ""


def _command_families(commands: set[str]) -> set[str]:
    return {family for command in commands if (family := _command_family(command))}


def _f1(expected: set[str], actual: set[str]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    overlap = len(expected & actual)
    if overlap == 0:
        return 0.0
    precision = overlap / len(actual)
    recall = overlap / len(expected)
    return (2 * precision * recall) / (precision + recall)


def _char_similarity(expected: str, actual: str) -> float:
    expected_norm = _normalize_text(expected)
    actual_norm = _normalize_text(actual)
    if not expected_norm and not actual_norm:
        return 1.0
    if not expected_norm or not actual_norm:
        return 0.0
    expected_chars = set(expected_norm)
    actual_chars = set(actual_norm)
    return len(expected_chars & actual_chars) / len(expected_chars | actual_chars)


def compare_answer_similarity(expected: str, actual: str) -> dict[str, Any]:
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    expected_commands = _commands(expected)
    actual_commands = _commands(actual)
    token_f1 = _f1(expected_tokens, actual_tokens)
    char_similarity = _char_similarity(expected, actual)
    command_f1 = _f1(expected_commands, actual_commands)
    if expected_commands:
        score = (0.45 * token_f1) + (0.25 * char_similarity) + (0.30 * command_f1)
    else:
        score = (0.65 * token_f1) + (0.35 * char_similarity)
    score = round(score, 4)
    return {
        "score": score,
        "verdict": "pass" if score >= 0.62 else "review",
        "metrics": {
            "token_f1": round(token_f1, 4),
            "char_similarity": round(char_similarity, 4),
            "command_f1": round(command_f1, 4),
            "expected_token_count": len(expected_tokens),
            "actual_token_count": len(actual_tokens),
            "expected_command_count": len(expected_commands),
            "actual_command_count": len(actual_commands),
        },
    }


def evaluate_answer_quality(
    *,
    question: str,
    expected: str,
    actual: str,
    response_kind: str,
    service_status: str = "",
) -> dict[str, Any]:
    expected_commands = _commands(expected)
    actual_commands = _commands(actual)
    expected_families = _command_families(expected_commands)
    actual_families = _command_families(actual_commands)
    question_tokens = _tokens(question)
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    expected_topic_overlap = _f1(expected_tokens, actual_tokens)
    missing_families = sorted(expected_families - actual_families)
    matched_families = sorted(expected_families & actual_families)
    reasons: list[str] = []

    if service_status and service_status != "ok":
        reasons.append("service_error")
    if response_kind == "smalltalk" and question_tokens:
        reasons.append("smalltalk_route")
    if response_kind == "no_answer":
        reasons.append("no_answer")
    if response_kind == "clarification":
        reasons.append("clarification_route")
    if response_kind == "error":
        reasons.append("answer_error")
    if not actual.strip():
        reasons.append("empty_answer")
    if expected_families and missing_families:
        reasons.append("missing_command_family")
    if expected_families and actual_families and not matched_families:
        reasons.append("command_drift")
    if expected_topic_overlap < 0.18 and actual.strip():
        reasons.append("weak_topic_overlap")

    if not reasons:
        verdict = "pass"
    elif set(reasons) <= {"missing_command_family", "weak_topic_overlap"} and actual.strip():
        verdict = "partial"
    else:
        verdict = "fail"

    return {
        "verdict": verdict,
        "failure_reasons": reasons,
        "expected_commands": sorted(expected_commands),
        "actual_commands": sorted(actual_commands),
        "expected_command_families": sorted(expected_families),
        "actual_command_families": sorted(actual_families),
        "matched_command_families": matched_families,
        "missing_command_families": missing_families,
        "metrics": {
            "topic_token_f1": round(expected_topic_overlap, 4),
        },
    }


def build_validation_report(
    service_results: list[dict[str, Any]],
    gold_answers: dict[str, GoldAnswerCase],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for result in service_results:
        case_id = str(result.get("case_id") or "")
        gold = gold_answers.get(case_id)
        actual = str(result.get("answer") or "")
        if gold is None:
            similarity = {
                "score": 0.0,
                "verdict": "missing_gold",
                "metrics": {},
            }
            quality = {
                "verdict": "missing_gold",
                "failure_reasons": ["missing_gold"],
            }
        else:
            similarity = compare_answer_similarity(gold.answer, actual)
            quality = evaluate_answer_quality(
                question=str(result.get("question") or ""),
                expected=gold.answer,
                actual=actual,
                response_kind=str(result.get("response_kind") or ""),
                service_status=str(result.get("status") or ""),
            )
        rows.append(
            {
                "case_id": case_id,
                "source_file": result.get("source_file"),
                "source_index": result.get("source_index"),
                "question_sha256_16": result.get("question_sha256_16"),
                "actual_answer_present": bool(actual.strip()),
                "expected_answer_present": gold is not None,
                "service_status": result.get("status"),
                "response_kind": result.get("response_kind"),
                "similarity": similarity,
                "quality": quality,
            }
        )
    compared = [row for row in rows if row["expected_answer_present"]]
    pass_count = sum(1 for row in compared if row["similarity"].get("verdict") == "pass")
    quality_pass_count = sum(1 for row in compared if row["quality"].get("verdict") == "pass")
    quality_partial_count = sum(1 for row in compared if row["quality"].get("verdict") == "partial")
    quality_fail_count = sum(1 for row in compared if row["quality"].get("verdict") == "fail")
    failure_reason_counts: dict[str, int] = {}
    for row in compared:
        for reason in row["quality"].get("failure_reasons") or []:
            failure_reason_counts[str(reason)] = failure_reason_counts.get(str(reason), 0) + 1
    answered_count = sum(1 for row in rows if row["actual_answer_present"])
    avg_score = (
        sum(float(row["similarity"].get("score") or 0.0) for row in compared) / len(compared)
        if compared
        else 0.0
    )
    return {
        "compared_at": _now(),
        "summary": {
            "total": len(rows),
            "answered": answered_count,
            "compared": len(compared),
            "passed": pass_count,
            "review": len(compared) - pass_count,
            "answer_present_rate": round(answered_count / len(rows), 4) if rows else 0.0,
            "similarity_pass_rate": round(pass_count / len(compared), 4) if compared else 0.0,
            "avg_similarity_score": round(avg_score, 4),
            "quality_passed": quality_pass_count,
            "quality_partial": quality_partial_count,
            "quality_failed": quality_fail_count,
            "quality_pass_rate": round(quality_pass_count / len(compared), 4) if compared else 0.0,
            "failure_reason_counts": failure_reason_counts,
        },
        "results": rows,
    }


def write_real_loop(
    root_dir: Path,
    *,
    pattern: str,
    output_path: Path,
    base_url: str,
    timeout_seconds: float,
    limit: int,
    start_index: int = 1,
    replace_selected: bool = False,
    skip_service: bool,
    stream: bool = True,
    resume: bool = False,
) -> dict[str, Any]:
    all_cases = load_blind_question_cases(root_dir, pattern)
    start_offset = max(start_index, 1) - 1
    selected_cases = all_cases[start_offset:]
    if limit > 0:
        selected_cases = selected_cases[:limit]
    selected_ids = {case.case_id for case in selected_cases}
    service_results: list[dict[str, Any]] = []
    if resume and output_path.is_file():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict) and isinstance(previous.get("service_results"), list):
            service_results = [
                row for row in previous["service_results"]
                if isinstance(row, dict) and str(row.get("case_id") or "")
            ]
            if replace_selected:
                service_results = [
                    row for row in service_results if str(row.get("case_id") or "") not in selected_ids
                ]
    completed_ids = {str(row.get("case_id") or "") for row in service_results}
    pending_cases = [case for case in selected_cases if case.case_id not in completed_ids]
    all_case_ids = {case.case_id for case in all_cases}
    completed_case_ids = completed_ids & all_case_ids
    payload = {
        "generated_at": _now(),
        "base_url": base_url,
        "input_pattern": pattern,
        "selected_range": {
            "start_index": max(start_index, 1),
            "limit": limit,
            "selected_count": len(selected_cases),
            "replace_selected": replace_selected,
        },
        "service_payload_contract": {
            "gold_answer_loaded_during_service_loop": False,
            "request_payload_keys": ["query"],
            "endpoint": "/api/chat/stream" if stream else "/api/chat",
        },
        "summary": {
            "question_count": len(all_cases),
            "service_result_count": len(service_results),
            "pending_count": len(all_cases) - len(completed_case_ids),
            "batch_pending_count": len(pending_cases),
            "partial": len(all_cases) > len(completed_case_ids),
        },
        "service_results": service_results,
        "validation": {
            "compared_at": "",
            "summary": {
                "total": 0,
                "answered": 0,
                "compared": 0,
                "passed": 0,
                "review": 0,
                "answer_present_rate": 0.0,
                "similarity_pass_rate": 0.0,
                "avg_similarity_score": 0.0,
            },
            "results": [],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if skip_service:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        for case in pending_cases:
            service_results.extend(
                run_service_loop([case], base_url=base_url, timeout_seconds=timeout_seconds, stream=stream)
            )
            payload["summary"]["service_result_count"] = len(service_results)  # type: ignore[index]
            completed_case_ids = {
                str(row.get("case_id") or "") for row in service_results
            } & all_case_ids
            payload["summary"]["pending_count"] = len(all_cases) - len(completed_case_ids)  # type: ignore[index]
            payload["summary"]["batch_pending_count"] = len(pending_cases) - sum(  # type: ignore[index]
                1 for case in pending_cases if case.case_id in completed_case_ids
            )
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            latest = service_results[-1]
            print(
                json.dumps(
                    {
                        "progress": f"{len(completed_case_ids)}/{len(all_cases)}",
                        "batch_progress": f"{sum(1 for case in selected_cases if case.case_id in completed_case_ids)}/{len(selected_cases)}",
                        "case_id": latest.get("case_id"),
                        "status": latest.get("status"),
                        "answered": bool(str(latest.get("answer") or "").strip()),
                        "duration_ms": latest.get("duration_ms"),
                        "output": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    gold_answers = load_gold_answer_cases(root_dir, pattern)
    completed_case_ids = {str(row.get("case_id") or "") for row in service_results} & all_case_ids
    payload["summary"]["pending_count"] = len(all_cases) - len(completed_case_ids)  # type: ignore[index]
    payload["summary"]["batch_pending_count"] = 0  # type: ignore[index]
    payload["summary"]["partial"] = len(all_cases) > len(completed_case_ids)  # type: ignore[index]
    payload["validation"] = build_validation_report(service_results, gold_answers)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def reanalyze_existing_output(
    root_dir: Path,
    *,
    pattern: str,
    output_path: Path,
) -> dict[str, Any]:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Unsupported output JSON shape: {output_path}")
    service_results = payload.get("service_results")
    if not isinstance(service_results, list):
        raise ValueError(f"Missing service_results in {output_path}")
    typed_results = [row for row in service_results if isinstance(row, dict)]
    gold_answers = load_gold_answer_cases(root_dir, pattern)
    payload["validation"] = build_validation_report(typed_results, gold_answers)
    payload.setdefault("summary", {})
    if isinstance(payload["summary"], dict):
        payload["summary"]["service_result_count"] = len(typed_results)
        payload["summary"]["pending_count"] = 0
        payload["summary"]["batch_pending_count"] = 0
        payload["summary"]["partial"] = False
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run validation/ocp_*.json questions through /api/chat.")
    parser.add_argument("--root-dir", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--pattern", default="validation/ocp_*.json", help="Glob for validation input JSON files.")
    parser.add_argument("--output", default="validation/real_loop.json", help="Output JSON path.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_PLAYBOOK_UI_BASE_URL.replace("127.0.0.1", "localhost"),
        help="Running PlayBook Studio base URL.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="Per-request timeout. Use 0 to wait without a socket timeout.")
    parser.add_argument("--limit", type=int, default=0, help="Limit case count. 0 means all.")
    parser.add_argument("--start-index", type=int, default=1, help="1-based case index to start from after sorting input files.")
    parser.add_argument(
        "--replace-selected",
        action="store_true",
        help="When resuming, drop existing rows in the selected range before running them again.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Use /api/chat instead of the UI-style /api/chat/stream endpoint.",
    )
    parser.add_argument(
        "--skip-service",
        action="store_true",
        help="Only verify file loading/report shape without calling the service.",
    )
    parser.add_argument(
        "--reanalyze-existing",
        action="store_true",
        help="Do not call the service; rebuild validation metrics for the existing output file.",
    )
    parser.add_argument("--resume", action="store_true", help="Keep completed rows in the output file and run only missing cases.")
    return parser.parse_args()


def main() -> int:
    force_utf8_stdio()
    args = _parse_args()
    root_dir = Path(args.root_dir).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root_dir / output
    if bool(args.reanalyze_existing):
        payload = reanalyze_existing_output(root_dir, pattern=str(args.pattern), output_path=output)
        summary = payload.get("validation", {}).get("summary", {})
        print(
            json.dumps(
                {
                    "output": str(output),
                    "question_count": payload.get("summary", {}).get("question_count"),
                    "service_result_count": payload.get("summary", {}).get("service_result_count"),
                    "validation": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    payload = write_real_loop(
        root_dir,
        pattern=str(args.pattern),
        output_path=output,
        base_url=str(args.base_url),
        timeout_seconds=float(args.timeout_seconds),
        limit=int(args.limit),
        start_index=int(args.start_index),
        replace_selected=bool(args.replace_selected),
        skip_service=bool(args.skip_service),
        stream=not bool(args.no_stream),
        resume=bool(args.resume),
    )
    summary = payload.get("validation", {}).get("summary", {})
    print(
        json.dumps(
            {
                "output": str(output),
                "question_count": payload.get("summary", {}).get("question_count"),
                "service_result_count": payload.get("summary", {}).get("service_result_count"),
                "validation": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
