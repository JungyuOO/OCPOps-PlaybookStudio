from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from play_book_studio.evals.chat_performance_report import (
    DEFAULT_QUESTIONS_PATH,
    _load_question_cases,
    run_query,
)


DEFAULT_PLUS_QUESTIONS_PATH = Path(__file__).with_name("chat_benchmark_questions_plus100.jsonl")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_.:/-]+")
_COMMAND_RE = re.compile(
    r"\b(?:oc|kubectl|openshift-install|etcdctl)\s+[^\n`$]+",
    flags=re.IGNORECASE,
)
_BAD_ANSWER_MARKERS = (
    "문서를 찾을 수 없습니다",
    "문서에서 찾을 수 없습니다",
    "관련 문서를 찾지 못했습니다",
    "충분한 근거를 찾지 못했습니다",
    "현재 문서에서는 확인되지 않습니다",
)
_STRICT_WARNING_MARKERS = (
    "low retrieval confidence",
    "no context citations assembled",
    "answer indicates missing corpus coverage",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run parent chat cases, click generated follow-up questions, and grade grounded answerability."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--questions-file", default=str(DEFAULT_PLUS_QUESTIONS_PATH if DEFAULT_PLUS_QUESTIONS_PATH.exists() else DEFAULT_QUESTIONS_PATH))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", default="reports/chat_followup_quality_report.json")
    parser.add_argument("--route-kind", default="official")
    parser.add_argument("--mode", default="ops")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--followups-per-case", type=int, default=3)
    parser.add_argument(
        "--continue-on-infra-error",
        action="store_true",
        help="Keep running after transport/retrieval infrastructure errors. By default the report stops immediately.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _tokens(*parts: str) -> set[str]:
    values: set[str] = set()
    stop = {"어떻게", "무엇", "먼저", "확인", "방법", "상태", "알려줘", "어떤", "when", "what", "how"}
    for part in parts:
        for token in _TOKEN_RE.findall(str(part or "").lower()):
            cleaned = token.strip(" .,:;!?()[]{}<>`'\"")
            if len(cleaned) >= 2 and cleaned not in stop:
                values.add(cleaned)
    return values


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles if needle)


def _normalize_command_for_grade(value: str) -> str:
    normalized = re.sub(r"<[^>]+>|\{[^}]+\}|\[[^\]]+\]", " ", str(value or "").lower())
    normalized = normalized.replace("--all-namespaces", "-a")
    normalized = re.sub(r"\s+", " ", normalized).strip(" .,:;")
    aliases = (
        ("oc events", "oc get events"),
        ("oc get event ", "oc get events "),
        ("oc get events -a", "oc get events -a"),
        ("oc get co", "oc get clusteroperator"),
        ("oc get clusteroperators", "oc get clusteroperator"),
        ("oc get sub", "oc get subscription"),
        ("oc get subs", "oc get subscription"),
        ("oc get subscriptions", "oc get subscription"),
        ("oc get csvs", "oc get csv"),
        ("oc get clusterserviceversion", "oc get csv"),
        ("oc get clusterserviceversions", "oc get csv"),
        ("oc get pdb", "oc get poddisruptionbudget"),
        ("oc get pdbs", "oc get poddisruptionbudget"),
        ("oc get poddisruptionbudgets", "oc get poddisruptionbudget"),
        ("oc get endpointslices", "oc get endpointslice"),
        ("oc get sc", "oc get storageclass"),
        ("oc get storageclasses", "oc get storageclass"),
        ("oc get po", "oc get pods"),
        ("oc adm top pod", "oc adm top pods"),
    )
    padded = f"{normalized} "
    for source, target in aliases:
        if padded.startswith(f"{source} "):
            remainder = padded[len(source) :].strip()
            normalized = f"{target} {remainder}".strip()
            break
    return normalized


def _command_matches_expected(searchable: str, expected_command: str) -> bool:
    expected = _normalize_command_for_grade(expected_command)
    if not expected:
        return False
    normalized_text = _normalize_command_for_grade(searchable)
    if expected in normalized_text:
        return True
    if expected.startswith("oc get events") and "oc events" in normalized_text:
        return True
    if expected.startswith("oc logs") and "oc logs" in normalized_text:
        return True
    if expected.startswith("oc adm node-logs") and "oc adm node-logs" in normalized_text:
        return True
    if expected.startswith("oc get pods") and "oc get pods" in normalized_text:
        return True
    if expected.startswith("oc auth can-i") and "oc auth can-i" in normalized_text:
        return True
    if expected.startswith("oc patch") and "oc patch" in normalized_text:
        return True
    if expected.startswith("cluster-backup.sh") and "cluster-backup.sh" in normalized_text:
        return True
    tokens = [
        token
        for token in re.split(r"[^a-z0-9_.-]+", expected)
        if len(token) >= 2 and token not in {"name", "namespace", "operator", "resource", "verb"}
    ]
    return len(tokens) >= 2 and all(token in normalized_text for token in tokens)


def _contains_expected_command(text: str, expected_commands: list[str]) -> bool:
    return any(_command_matches_expected(text, command) for command in expected_commands)


def _extract_commands(*parts: str) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for match in _COMMAND_RE.findall(str(part or "")):
            cleaned = re.sub(r"\s+", " ", match).strip(" .,:;")
            lowered = cleaned.lower()
            if lowered and lowered not in seen:
                seen.add(lowered)
                commands.append(cleaned)
    return commands


def _citations_text(item: dict[str, Any]) -> str:
    citations = item.get("citations") if isinstance(item.get("citations"), list) else []
    return " ".join(
        " ".join(
            str(citation.get(key) or "")
            for key in ("book_slug", "section", "source_url")
            if isinstance(citation, dict)
        )
        for citation in citations
        if isinstance(citation, dict)
    )


def _citation_books(item: dict[str, Any]) -> set[str]:
    citations = item.get("citations") if isinstance(item.get("citations"), list) else []
    return {
        str(citation.get("book_slug") or "").strip().lower()
        for citation in citations
        if isinstance(citation, dict) and str(citation.get("book_slug") or "").strip()
    }


def _expected_from_case(case: dict[str, Any]) -> dict[str, list[str]]:
    query = str(case.get("query") or "").lower()
    expected = {
        "commands": [str(v) for v in case.get("expected_commands", []) if str(v).strip()],
        "books": [str(v) for v in case.get("expected_books_any", []) if str(v).strip()],
        "objects": [str(v) for v in case.get("expected_objects", []) if str(v).strip()],
        "domains": [str(v) for v in case.get("expected_domains", []) if str(v).strip()],
    }
    rules: list[tuple[tuple[str, ...], dict[str, list[str]]]] = [
        (("로그인", "login"), {"commands": ["oc login", "oc whoami"], "books": ["authentication_and_authorization", "cli_tools"]}),
        (("node", "노드"), {"commands": ["oc get nodes", "oc describe node"], "books": ["nodes", "support"], "objects": ["node"]}),
        (("pod 중단 예산", "pdb", "poddisruptionbudget"), {"commands": ["oc get poddisruptionbudget", "oc get pdb"], "objects": ["poddisruptionbudget"]}),
        (("crashloopbackoff",), {"commands": ["oc logs", "oc describe pod"], "objects": ["pod"]}),
        (("pvc", "persistentvolumeclaim"), {"commands": ["oc get pvc", "oc describe pvc"], "books": ["storage"], "objects": ["pvc"]}),
        (("route", "라우트"), {"commands": ["oc get route", "oc describe route"], "books": ["ingress_and_load_balancing"], "objects": ["route"]}),
        (("clusteroperator", "cluster operator"), {"commands": ["oc get clusteroperator", "oc get co"], "objects": ["clusteroperator"]}),
        (("이벤트", "event"), {"commands": ["oc get events"], "objects": ["event"]}),
        (("버전", "version"), {"commands": ["oc version", "oc get clusterversion"], "objects": ["clusterversion"]}),
        (("endpointslice",), {"commands": ["oc get endpointslice"], "objects": ["endpointslice"]}),
        (("ingresscontroller",), {"commands": ["oc get ingresscontroller"], "books": ["ingress_and_load_balancing"], "objects": ["ingresscontroller"]}),
        (("serviceaccount", "service account"), {"commands": ["oc auth can-i", "oc get serviceaccount"], "books": ["authentication_and_authorization"], "objects": ["serviceaccount"]}),
        (("installplan",), {"commands": ["oc get installplan", "oc patch installplan"], "books": ["operators"], "objects": ["installplan"]}),
        (("operator",), {"commands": ["oc get csv", "oc get subscription"], "books": ["operators"], "objects": ["operator"]}),
        (("storageclass",), {"commands": ["oc get storageclass"], "books": ["storage"], "objects": ["storageclass"]}),
        (("prometheus", "alertmanager", "알람", "메트릭", "monitoring"), {"books": ["monitoring"], "objects": ["prometheus", "alertmanager"]}),
        (("must-gather",), {"commands": ["oc adm must-gather"], "books": ["support"]}),
        (("etcd",), {"commands": ["oc get pods", "cluster-backup.sh"], "books": ["etcd", "backup_and_restore"], "objects": ["etcd"]}),
    ]
    for needles, additions in rules:
        if any(needle in query for needle in needles):
            for key, values in additions.items():
                for value in values:
                    if value not in expected[key]:
                        expected[key].append(value)
    return expected


def _grade_answer(item: dict[str, Any], case: dict[str, Any], *, role: str) -> dict[str, Any]:
    warnings = [str(value) for value in item.get("warnings") or []]
    answer = str(item.get("answer") or "")
    citation_text = _citations_text(item)
    searchable = " ".join((answer, citation_text)).lower()
    citations = item.get("citations") if isinstance(item.get("citations"), list) else []
    expected = _expected_from_case(case)
    reasons: list[str] = []

    if item.get("error"):
        reasons.append("request_error")
    if item.get("response_kind") != "rag":
        reasons.append(f"response_kind:{item.get('response_kind')}")
    if not citations:
        reasons.append("no_citations")
    for warning in warnings:
        if any(marker in warning.lower() for marker in _STRICT_WARNING_MARKERS):
            reasons.append(warning)
    if _contains_any(answer, list(_BAD_ANSWER_MARKERS)):
        reasons.append("missing_corpus_answer")

    expected_commands = expected.get("commands") or []
    expected_books = {book.lower() for book in expected.get("books") or []}
    expected_objects = expected.get("objects") or []
    actual_books = _citation_books(item)
    actual_commands = _extract_commands(answer, citation_text)

    command_match = not expected_commands or _contains_expected_command(searchable, expected_commands)
    book_match = not expected_books or bool(actual_books & expected_books)
    object_match = not expected_objects or _contains_any(searchable, expected_objects)

    if expected_commands and not command_match:
        reasons.append("missing_expected_command")
    if expected_books and not book_match:
        reasons.append("unexpected_citation_book")
    if expected_objects and not object_match:
        reasons.append("missing_expected_object")

    hard_fail = any(
        reason.startswith("response_kind:")
        or reason in {"request_error", "no_citations", "missing_corpus_answer", "missing_expected_command"}
        or reason in _STRICT_WARNING_MARKERS
        for reason in reasons
    )
    if hard_fail:
        grade = "fail"
    elif reasons:
        grade = "partial"
    else:
        grade = "pass"

    return {
        "role": role,
        "grade": grade,
        "reasons": reasons,
        "expected": expected,
        "actual": {
            "books": sorted(actual_books),
            "commands": actual_commands,
            "warnings": warnings,
        },
    }


def _infra_error(item: dict[str, Any]) -> str:
    if item.get("error"):
        return str(item.get("error") or "request_error")
    for event in item.get("trace_events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("status") != "error":
            continue
        step = str(event.get("step") or "")
        detail = str(event.get("detail") or "")
        if step in {"vector_search", "bm25_search", "graph_expand", "retrieval"}:
            return f"{step}: {detail}"
        if "RemoteDisconnected" in detail or "Connection aborted" in detail:
            return f"{step or 'trace'}: {detail}"
    return ""


def _grade_followup_relation(parent: dict[str, Any], child: dict[str, Any], suggestion: str) -> dict[str, Any]:
    parent_text = " ".join((str(parent.get("query") or ""), str(parent.get("answer") or ""), _citations_text(parent)))
    child_text = " ".join((suggestion, str(child.get("answer") or ""), _citations_text(child)))
    parent_tokens = _tokens(parent_text)
    suggestion_tokens = _tokens(suggestion)
    child_tokens = _tokens(child_text)
    shared_with_suggestion = sorted(parent_tokens & suggestion_tokens)
    shared_with_child = sorted(parent_tokens & child_tokens)
    parent_books = _citation_books(parent)
    child_books = _citation_books(child)
    parent_commands = {cmd.lower() for cmd in _extract_commands(str(parent.get("answer") or ""), _citations_text(parent))}
    child_commands = {cmd.lower() for cmd in _extract_commands(str(child.get("answer") or ""), _citations_text(child), suggestion)}
    same_book = bool(parent_books & child_books)
    same_command_family = bool(parent_commands & child_commands)
    relation_pass = bool(shared_with_suggestion[:1]) and (same_book or same_command_family or len(shared_with_child) >= 2)
    return {
        "grade": "pass" if relation_pass else "fail",
        "same_book": same_book,
        "same_command_family": same_command_family,
        "shared_suggestion_tokens": shared_with_suggestion[:12],
        "shared_child_tokens": shared_with_child[:12],
        "parent_books": sorted(parent_books),
        "child_books": sorted(child_books),
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    parent_grades: dict[str, int] = {}
    child_grades: dict[str, int] = {}
    relation_grades: dict[str, int] = {}
    total_suggestions = 0
    parents_with_suggestions = 0
    infra_errors = 0
    for row in results:
        if row.get("infra_error"):
            infra_errors += 1
        parent_grade = str(row.get("parent_grade", {}).get("grade") or "unknown")
        parent_grades[parent_grade] = parent_grades.get(parent_grade, 0) + 1
        followups = row.get("followups") if isinstance(row.get("followups"), list) else []
        if followups:
            parents_with_suggestions += 1
        total_suggestions += len(followups)
        for followup in followups:
            child_grade = str(followup.get("child_grade", {}).get("grade") or "unknown")
            relation_grade = str(followup.get("relation_grade", {}).get("grade") or "unknown")
            child_grades[child_grade] = child_grades.get(child_grade, 0) + 1
            relation_grades[relation_grade] = relation_grades.get(relation_grade, 0) + 1
    return {
        "parent_grades": parent_grades,
        "child_grades": child_grades,
        "relation_grades": relation_grades,
        "parent_count": len(results),
        "infra_errors": infra_errors,
        "parents_with_suggestions": parents_with_suggestions,
        "suggestion_display_rate": round(parents_with_suggestions / len(results), 4) if results else 0.0,
        "total_suggestions": total_suggestions,
        "avg_suggestions_per_parent": round(total_suggestions / len(results), 3) if results else 0.0,
        "followup_answer_pass_rate": round(child_grades.get("pass", 0) / total_suggestions, 4) if total_suggestions else 0.0,
        "followup_relation_pass_rate": round(relation_grades.get("pass", 0) / total_suggestions, 4) if total_suggestions else 0.0,
    }


def _write_markdown(report: dict[str, Any], output_path: Path) -> None:
    summary = report.get("summary") or {}
    lines = [
        "# Chat Follow-up Quality Report",
        "",
        f"- Base URL: `{report.get('base_url')}`",
        f"- Questions file: `{report.get('questions_file')}`",
        f"- Parent count: `{summary.get('parent_count')}`",
        f"- Suggestion display rate: `{summary.get('suggestion_display_rate')}`",
        f"- Follow-up answer pass rate: `{summary.get('followup_answer_pass_rate')}`",
        f"- Follow-up relation pass rate: `{summary.get('followup_relation_pass_rate')}`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    for row in report.get("results") or []:
        lines.extend(
            [
                f"## {row.get('id')} - {row.get('query')}",
                "",
                f"- Parent grade: `{row.get('parent_grade', {}).get('grade')}`",
                f"- Parent reasons: `{', '.join(row.get('parent_grade', {}).get('reasons') or [])}`",
                f"- Suggested count: `{len(row.get('followups') or [])}`",
                "",
            ]
        )
        for followup in row.get("followups") or []:
            lines.extend(
                [
                    f"### Suggestion: {followup.get('suggestion')}",
                    "",
                    f"- Child grade: `{followup.get('child_grade', {}).get('grade')}`",
                    f"- Child reasons: `{', '.join(followup.get('child_grade', {}).get('reasons') or [])}`",
                    f"- Relation grade: `{followup.get('relation_grade', {}).get('grade')}`",
                    f"- Child response kind: `{followup.get('child', {}).get('response_kind')}`",
                    "",
                ]
            )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    cases = _load_question_cases(args)
    verbose = not args.quiet
    results: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        session_id = f"followup-quality-{index:03d}-{int(time.time())}"
        parent = run_query(
            args.base_url,
            case,
            timeout=args.timeout,
            index=index,
            default_route_kind=args.route_kind,
            default_mode=args.mode,
            verbose=verbose,
            session_id=session_id,
        )
        parent_grade = _grade_answer(parent, case, role="parent")
        infra_error = _infra_error(parent)
        suggestions = [
            str(value).strip()
            for value in parent.get("suggested_queries") or []
            if str(value).strip()
        ][: max(args.followups_per_case, 0)]
        row = {
            "id": parent.get("id"),
            "category": parent.get("category"),
            "query": parent.get("query"),
            "parent": parent,
            "parent_grade": parent_grade,
            "infra_error": infra_error,
            "followups": [],
        }
        if infra_error:
            if verbose:
                print(f"  infra_error={infra_error}")
            results.append(row)
            if not args.continue_on_infra_error:
                break
            continue
        if verbose:
            print(f"  parent_grade={parent_grade['grade']} reasons={parent_grade['reasons']}")
            print(f"  testing_followups={len(suggestions)}")

        for offset, suggestion in enumerate(suggestions, start=1):
            child_case = {
                "id": f"{parent.get('id')}-followup-{offset:02d}",
                "category": f"{parent.get('category')}:followup",
                "query": suggestion,
                "route_kind": parent.get("route_kind") or args.route_kind,
                "mode": parent.get("mode") or args.mode,
            }
            child = run_query(
                args.base_url,
                child_case,
                timeout=args.timeout,
                index=index * 1000 + offset,
                default_route_kind=args.route_kind,
                default_mode=args.mode,
                verbose=verbose,
                session_id=session_id,
            )
            child_grade = _grade_answer(child, child_case, role="followup")
            relation_grade = _grade_followup_relation(parent, child, suggestion)
            row["followups"].append(
                {
                    "suggestion": suggestion,
                    "child": child,
                    "child_grade": child_grade,
                    "relation_grade": relation_grade,
                }
            )
            if verbose:
                print(
                    "  followup_grade="
                    f"{child_grade['grade']} relation={relation_grade['grade']} "
                    f"suggestion={suggestion}"
                )
        results.append(row)

    report = {
        "base_url": args.base_url,
        "questions_file": args.questions_file,
        "generated_at_epoch": round(time.time(), 3),
        "followups_per_case": args.followups_per_case,
        "summary": _summary(results),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report, output_path.with_suffix(".md"))
    print(f"\nreport_json={output_path}")
    print(f"report_md={output_path.with_suffix('.md')}")
    print("summary=" + json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
