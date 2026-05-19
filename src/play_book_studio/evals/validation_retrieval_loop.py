"""Run validation questions through retrieval only.

This intentionally avoids answer generation. It checks whether retrieved
documents contain the command and topic evidence present in the gold answer.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import load_settings
from play_book_studio.console_encoding import force_utf8_stdio
from play_book_studio.evals.validation_real_loop import (
    load_blind_question_cases,
    load_gold_answer_cases,
)
from play_book_studio.answering.query_intents import build_intent_profile
from play_book_studio.retrieval.retriever import ChatRetriever


TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/-]+|[\uac00-\ud7a3]+")
COMMAND_RE = re.compile(r"(?:oc|kubectl|openshift-install|journalctl|systemctl|helm|curl)\b[^\n`]*")
STOP_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "you",
    "this",
    "that",
    "아래",
    "명령",
    "사용",
    "확인",
    "리소스",
    "상태",
    "정상",
    "실행",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        token = raw.strip("-_./:")
        if len(token) < 2 or token in STOP_TOKENS:
            continue
        tokens.append(token)
    return tokens


def _commands(text: str) -> list[str]:
    commands: list[str] = []
    for raw in COMMAND_RE.findall(text):
        command = re.sub(r"\s+", " ", raw).strip(" .")
        if command and command not in commands:
            commands.append(command)
    return commands


def _command_family(command: str) -> str:
    parts = command.split()
    if not parts:
        return ""
    if len(parts) >= 3 and parts[0] in {"oc", "kubectl"}:
        return " ".join(parts[:3])
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return parts[0]


def _normalize_command(command: str) -> str:
    command = command.lower()
    command = re.sub(r"<[^>]+>", " ", command)
    command = re.sub(r"\{[^}]+\}", " ", command)
    command = re.sub(r"['\"`\\]", " ", command)
    command = re.sub(r"[^a-z0-9_.:/-]+", " ", command)
    return re.sub(r"\s+", " ", command).strip()


def _command_terms(command: str) -> set[str]:
    terms = set(_normalize_command(command).split())
    return {term for term in terms if len(term) > 1 and term not in {"oc", "kubectl", "get", "create", "apply"}}


def _commands_match(expected: str, retrieved: str) -> bool:
    expected_norm = _normalize_command(expected)
    retrieved_norm = _normalize_command(retrieved)
    if not expected_norm or not retrieved_norm:
        return False
    if expected_norm in retrieved_norm or retrieved_norm in expected_norm:
        return True
    expected_parts = expected_norm.split()
    retrieved_parts = retrieved_norm.split()
    if len(expected_parts) >= 2 and expected_parts[:2] == retrieved_parts[:2]:
        expected_terms = _command_terms(expected_norm)
        retrieved_terms = _command_terms(retrieved_norm)
        if not expected_terms:
            return True
        return bool(expected_terms & retrieved_terms)
    return False


def _hit_text(hit: Any) -> str:
    parts = [
        getattr(hit, "book_slug", ""),
        getattr(hit, "chapter", ""),
        getattr(hit, "section", ""),
        getattr(hit, "heading_title", ""),
        getattr(hit, "text", ""),
        " ".join(getattr(hit, "cli_commands", ()) or ()),
        " ".join(getattr(hit, "k8s_objects", ()) or ()),
        " ".join(getattr(hit, "operator_names", ()) or ()),
    ]
    return "\n".join(str(part) for part in parts if part)


def _overlap_score(gold_text: str, retrieved_text: str) -> dict[str, Any]:
    gold_counts = Counter(_tokens(gold_text))
    retrieved_tokens = set(_tokens(retrieved_text))
    if not gold_counts:
        return {"score": 0.0, "hits": [], "gold_token_count": 0}
    weighted_total = sum(gold_counts.values())
    weighted_hits = sum(count for token, count in gold_counts.items() if token in retrieved_tokens)
    hits = [token for token in gold_counts if token in retrieved_tokens]
    return {
        "score": round(weighted_hits / max(1, weighted_total), 4),
        "hits": hits[:30],
        "gold_token_count": len(gold_counts),
    }


def _command_score(gold_answer: str, retrieved_text: str) -> dict[str, Any]:
    gold_commands = _commands(gold_answer)
    retrieved_commands = _commands(retrieved_text)
    gold_families = {_command_family(command) for command in gold_commands if _command_family(command)}
    retrieved_families = {_command_family(command) for command in retrieved_commands if _command_family(command)}
    matched = sorted(gold_families & retrieved_families)
    fuzzy_matched = sorted(
        {
            expected
            for expected in gold_commands
            if any(_commands_match(expected, retrieved) for retrieved in retrieved_commands)
        }
    )
    if not gold_families:
        return {
            "expected": [],
            "retrieved": retrieved_commands[:20],
            "matched_families": [],
            "matched_commands": [],
            "pass": True,
        }
    return {
        "expected": gold_commands,
        "retrieved": retrieved_commands[:20],
        "matched_families": matched,
        "matched_commands": fuzzy_matched,
        "pass": bool(matched or fuzzy_matched),
    }


def _term_in_text(term: str, text: str) -> bool:
    term = re.sub(r"\s+", " ", (term or "").strip().lower())
    if not term:
        return False
    text = (text or "").lower()
    if term in text:
        return True
    tokens = [
        token
        for token in re.split(r"[^a-z0-9_.:/-]+", re.sub(r"<[^>]+>|\{[^}]+\}|\[[^\]]+\]", " ", term))
        if len(token) > 1 and token not in {"oc", "kubectl", "get", "create", "apply"}
    ]
    return bool(tokens) and all(token in text for token in tokens)


def _intent_evidence_score(question: str, retrieved_text: str) -> dict[str, Any]:
    profile = build_intent_profile(question)
    primary_matches = [command for command in profile.primary_commands if _term_in_text(command, retrieved_text)]
    evidence_matches = [term for term in profile.evidence_terms if _term_in_text(term, retrieved_text)]
    has_profile = bool(profile.intent != "unknown" and profile.confidence >= 0.7)
    return {
        "intent": profile.intent,
        "target_object": profile.target_object,
        "task": profile.task,
        "confidence": profile.confidence,
        "primary_command_matches": primary_matches,
        "evidence_matches": evidence_matches,
        "pass": bool(not has_profile or primary_matches or len(evidence_matches) >= 2),
    }


def _evaluate_case(
    retriever: ChatRetriever,
    *,
    case: Any,
    gold_answer: str,
    top_k: int,
    candidate_k: int,
    use_vector: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = retriever.retrieve(
        case.question,
        top_k=top_k,
        candidate_k=candidate_k,
        use_vector=use_vector,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    hit_texts = [_hit_text(hit) for hit in result.hits]
    retrieved_text = "\n\n".join(hit_texts)
    overlap = _overlap_score(gold_answer, retrieved_text)
    command = _command_score(gold_answer, retrieved_text)
    intent_evidence = _intent_evidence_score(case.question, retrieved_text)
    top_hits = [
        {
            "chunk_id": hit.chunk_id,
            "book_slug": hit.book_slug,
            "section": hit.section,
            "anchor": hit.anchor,
            "viewer_path": hit.viewer_path,
            "score": round(float(hit.fused_score or hit.raw_score or 0.0), 6),
            "cli_commands": list(hit.cli_commands),
            "k8s_objects": list(hit.k8s_objects),
            "operator_names": list(hit.operator_names),
        }
        for hit in result.hits
    ]
    pass_threshold = 0.18 if command["expected"] else 0.22
    passed = bool(command["pass"] and intent_evidence["pass"] and overlap["score"] >= pass_threshold)
    partial = bool(command["pass"] or intent_evidence["pass"] or overlap["score"] >= pass_threshold)
    trace = result.trace or {}
    reranker = trace.get("reranker") or {}
    return {
        "case_id": case.case_id,
        "source_file": case.source_file,
        "source_index": case.source_index,
        "question": case.question,
        "duration_ms": duration_ms,
        "passed": passed,
        "partial": partial and not passed,
        "overlap": overlap,
        "command": command,
        "intent_evidence": intent_evidence,
        "rewritten_query": result.rewritten_query,
        "top_hits": top_hits,
        "reranker": {
            "enabled": bool(reranker.get("enabled", False)),
            "mode": str(reranker.get("mode", "")),
            "decision_reason": str(reranker.get("decision_reason", "")),
            "applied": bool(reranker.get("applied", False)),
            "candidate_budget": reranker.get("candidate_budget", 0),
        },
        "timings_ms": trace.get("timings_ms", {}),
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row["passed"])
    partial = sum(1 for row in results if row["partial"])
    failed = total - passed - partial
    command_cases = [row for row in results if row["command"]["expected"]]
    command_passed = sum(1 for row in command_cases if row["command"]["pass"])
    intent_checked = [row for row in results if row.get("intent_evidence", {}).get("confidence", 0.0) >= 0.7]
    intent_passed = sum(1 for row in intent_checked if row.get("intent_evidence", {}).get("pass"))
    durations = [float(row["duration_ms"]) for row in results]
    reranker_modes = Counter(str(row.get("reranker", {}).get("mode", "")) for row in results)
    return {
        "total": total,
        "passed": passed,
        "partial": partial,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "pass_or_partial_rate": round((passed + partial) / total, 4) if total else 0.0,
        "command_case_count": len(command_cases),
        "command_pass_rate": round(command_passed / len(command_cases), 4) if command_cases else 1.0,
        "intent_case_count": len(intent_checked),
        "intent_pass_rate": round(intent_passed / len(intent_checked), 4) if intent_checked else 1.0,
        "avg_duration_ms": round(sum(durations) / total, 1) if total else 0.0,
        "max_duration_ms": round(max(durations), 1) if durations else 0.0,
        "reranker_modes": dict(reranker_modes),
    }


def reanalyze_existing(args: argparse.Namespace) -> dict[str, Any]:
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(args.root_dir).resolve() / output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    for row in payload.get("results", []):
        retrieved_text = "\n\n".join(
            "\n".join(
                [
                    str(hit.get("book_slug", "")),
                    str(hit.get("section", "")),
                    " ".join(hit.get("cli_commands") or []),
                    " ".join(hit.get("k8s_objects") or []),
                    " ".join(hit.get("operator_names") or []),
                ]
            )
            for hit in row.get("top_hits", [])
            if isinstance(hit, dict)
        )
        expected = "\n".join(row.get("command", {}).get("expected") or [])
        command = _command_score(expected, retrieved_text)
        row["command"] = {
            **row.get("command", {}),
            "matched_families": command["matched_families"],
            "matched_commands": command["matched_commands"],
            "pass": command["pass"],
        }
        row["intent_evidence"] = _intent_evidence_score(row.get("question", ""), retrieved_text)
        pass_threshold = 0.18 if row["command"].get("expected") else 0.22
        row["passed"] = bool(
            row["command"]["pass"]
            and row["intent_evidence"]["pass"]
            and row.get("overlap", {}).get("score", 0.0) >= pass_threshold
        )
        row["partial"] = bool(
            not row["passed"]
            and (
                row["command"]["pass"]
                or row["intent_evidence"]["pass"]
                or row.get("overlap", {}).get("score", 0.0) >= pass_threshold
            )
        )
    payload["reanalyzed_at"] = _now()
    payload["summary"] = _summary(payload.get("results", []))
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    root_dir = Path(args.root_dir).resolve()
    settings = load_settings(root_dir)
    if args.database_url.strip():
        settings = replace(settings, database_url=args.database_url.strip())
    retriever = ChatRetriever.from_settings(settings, enable_reranker=bool(args.enable_reranker))
    cases = load_blind_question_cases(root_dir, args.pattern)
    gold_answers = load_gold_answer_cases(root_dir, args.pattern)
    requested_case_ids = {case_id.strip() for case_id in args.case_id if case_id.strip()}
    if requested_case_ids:
        cases = [
            case
            for case in cases
            if case.case_id in requested_case_ids
            or case.case_id.rsplit(":", 1)[-1] in requested_case_ids
        ]
    if args.start_index > 1:
        cases = cases[args.start_index - 1 :]
    if args.limit > 0:
        cases = cases[: args.limit]

    results: list[dict[str, Any]] = []
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = root_dir / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for index, case in enumerate(cases, start=1):
        gold = gold_answers.get(case.case_id)
        if gold is None:
            continue
        row = _evaluate_case(
            retriever,
            case=case,
            gold_answer=gold.answer,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            use_vector=not args.no_vector,
        )
        results.append(row)
        print(
            json.dumps(
                {
                    "progress": f"{index}/{len(cases)}",
                    "case_id": case.case_id,
                    "passed": row["passed"],
                    "partial": row["partial"],
                    "overlap": row["overlap"]["score"],
                    "command_pass": row["command"]["pass"],
                    "duration_ms": row["duration_ms"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        payload = {
            "generated_at": _now(),
            "input_pattern": args.pattern,
            "top_k": args.top_k,
            "candidate_k": args.candidate_k,
            "use_vector": not args.no_vector,
            "enable_reranker": bool(args.enable_reranker),
            "summary": _summary(results),
            "results": results,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "generated_at": _now(),
        "input_pattern": args.pattern,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "use_vector": not args.no_vector,
        "enable_reranker": bool(args.enable_reranker),
        "summary": _summary(results),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run validation/ocp_*.json through retrieval only.")
    parser.add_argument("--root-dir", default=".")
    parser.add_argument("--pattern", default="validation/ocp_*.json")
    parser.add_argument("--output", default="validation/retrieval_loop.json")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=8)
    parser.add_argument("--no-vector", action="store_true")
    parser.add_argument("--enable-reranker", action="store_true")
    parser.add_argument("--reanalyze-existing", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    return parser


def main() -> int:
    force_utf8_stdio()
    args = build_parser().parse_args()
    payload = reanalyze_existing(args) if args.reanalyze_existing else run(args)
    print(json.dumps({"summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
