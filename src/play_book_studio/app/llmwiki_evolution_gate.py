from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any


DOC_LOCATOR_ONLY_RE = re.compile(r"문서를 여는 것이 맞습니다")
NO_ANSWER_RE = re.compile(r"\bno_answer\b|답변할 수 없습니다|답할 수 없습니다")
GENERIC_GUIDE_RE = re.compile(r"일반적인 가이드|구체적인 근거 없이|근거가 없습니다")
NO_EVIDENCE_RE = re.compile(r"포함되어 있지 않습니다|찾을 수 없습니다|정보가 없습니다")
SESSION_RECAP_RE = re.compile(r"지금까지|배운 내용|체크리스트|학습 플랜|요약|정리")
UNRELATED_COMMAND_RULES: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
    (
        re.compile(r"보고|증거|정리"),
        re.compile(r"oc adm prune builds|must-gather --image=.*compliance", re.IGNORECASE),
        "reporting_or_evidence_query_contains_unrelated_build_or_compliance_command",
    ),
)


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git_value(root_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_refs(root_dir: Path) -> dict[str, str]:
    return {
        "branch": _git_value(root_dir, "branch", "--show-current"),
        "head": _git_value(root_dir, "rev-parse", "HEAD"),
        "base_ref": "origin/main",
        "base_sha": _git_value(root_dir, "merge-base", "HEAD", "origin/main"),
    }


def _reports_dir(root_dir: Path) -> Path:
    return root_dir / ".kugnusdocs" / "reports"


def _dated_report_path(root_dir: Path, name: str) -> Path:
    return _reports_dir(root_dir) / f"{date.today().isoformat()}-{name}.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _answer_text(row: dict[str, Any]) -> str:
    return str(row.get("answer_preview") or row.get("answer") or "")


def _row_id(row: dict[str, Any], fallback: int) -> str:
    return str(row.get("id") or row.get("turn") or fallback)


def _has_no_evidence_phrase(answer: str) -> bool:
    return bool(NO_EVIDENCE_RE.search(answer))


def _unrelated_command_findings(row: dict[str, Any], *, source: str, fallback: int) -> list[dict[str, Any]]:
    query = str(row.get("query") or "")
    answer = _answer_text(row)
    findings: list[dict[str, Any]] = []
    for query_re, answer_re, code in UNRELATED_COMMAND_RULES:
        if query_re.search(query) and answer_re.search(answer):
            findings.append(
                {
                    "severity": "blocker",
                    "code": code,
                    "source": source,
                    "id": _row_id(row, fallback),
                    "query": query,
                    "answer_excerpt": answer[:300],
                }
            )
    return findings


def _quality_findings_for_row(row: dict[str, Any], *, source: str, fallback: int) -> list[dict[str, Any]]:
    answer = _answer_text(row)
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    findings: list[dict[str, Any]] = []
    if not bool(row.get("pass")):
        findings.append(
            {
                "severity": "blocker",
                "code": "case_or_turn_failed_existing_contract",
                "source": source,
                "id": _row_id(row, fallback),
                "failed_checks": [key for key, value in checks.items() if not bool(value)],
            }
        )
    if DOC_LOCATOR_ONLY_RE.search(answer) or checks.get("not_doc_locator_only") is False:
        findings.append(
            {
                "severity": "blocker",
                "code": "doc_locator_only_answer",
                "source": source,
                "id": _row_id(row, fallback),
            }
        )
    if NO_ANSWER_RE.search(answer) or str(row.get("response_kind") or "") == "no_answer":
        findings.append(
            {
                "severity": "blocker",
                "code": "no_answer",
                "source": source,
                "id": _row_id(row, fallback),
            }
        )
    if GENERIC_GUIDE_RE.search(answer) and _safe_int(row.get("citation_count")) <= 0:
        findings.append(
            {
                "severity": "blocker",
                "code": "generic_guide_without_citation",
                "source": source,
                "id": _row_id(row, fallback),
            }
        )
    if _safe_int(row.get("citation_count")) <= 0 and checks.get("min_citations") is False:
        findings.append(
            {
                "severity": "blocker",
                "code": "missing_citation",
                "source": source,
                "id": _row_id(row, fallback),
            }
        )
    if checks.get("expected_collections") is False or checks.get("expected_books") is False:
        findings.append(
            {
                "severity": "blocker",
                "code": "citation_scope_mismatch",
                "source": source,
                "id": _row_id(row, fallback),
                "collections": row.get("collections", []),
                "books": row.get("books", []),
            }
        )
    if SESSION_RECAP_RE.search(str(row.get("query") or "")) and _has_no_evidence_phrase(answer):
        findings.append(
            {
                "severity": "warning",
                "code": "recap_contains_missing_evidence_phrase",
                "source": source,
                "id": _row_id(row, fallback),
            }
        )
    findings.extend(_unrelated_command_findings(row, source=source, fallback=fallback))
    return findings


def _answer_variety_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        role = str(row.get("role") or "unknown")
        by_role.setdefault(role, []).append(row)
    findings: list[dict[str, Any]] = []
    for role, items in sorted(by_role.items()):
        if len(items) < 5:
            continue
        normalized = {
            re.sub(r"\s+", " ", _answer_text(item).strip().lower())[:360]
            for item in items
            if _answer_text(item).strip()
        }
        ratio = len(normalized) / max(1, len(items))
        if ratio < 0.45:
            findings.append(
                {
                    "severity": "warning",
                    "code": "low_answer_variety",
                    "role": role,
                    "unique_ratio": round(ratio, 3),
                    "unique_count": len(normalized),
                    "total": len(items),
                }
            )
    return findings


def build_retrieval_quality_critic(
    *,
    chat_matrix: dict[str, Any],
    role_continuity: dict[str, Any],
) -> dict[str, Any]:
    chat_results = _list_dicts(chat_matrix.get("results"))
    role_results = _list_dicts(role_continuity.get("results"))
    findings: list[dict[str, Any]] = []
    if not chat_matrix:
        findings.append({"severity": "blocker", "code": "chat_matrix_report_missing"})
    if not role_continuity:
        findings.append({"severity": "blocker", "code": "role_continuity_report_missing"})
    if chat_matrix and chat_matrix.get("status") != "ok":
        findings.append({"severity": "blocker", "code": "chat_matrix_status_not_ok"})
    if role_continuity and role_continuity.get("status") != "ok":
        findings.append({"severity": "blocker", "code": "role_continuity_status_not_ok"})

    for index, row in enumerate(chat_results, start=1):
        findings.extend(_quality_findings_for_row(row, source="chat_matrix", fallback=index))
    for index, row in enumerate(role_results, start=1):
        findings.extend(_quality_findings_for_row(row, source="role_continuity", fallback=index))
    findings.extend(_answer_variety_findings(role_results))

    blocker_count = sum(1 for item in findings if item.get("severity") == "blocker")
    warning_count = sum(1 for item in findings if item.get("severity") == "warning")
    checks = {
        "chat_matrix_loaded": bool(chat_matrix),
        "role_continuity_loaded": bool(role_continuity),
        "chat_matrix_status_ok": chat_matrix.get("status") == "ok" if chat_matrix else False,
        "role_continuity_status_ok": role_continuity.get("status") == "ok" if role_continuity else False,
        "chat_matrix_all_pass": _safe_int(chat_matrix.get("pass_count")) == _safe_int(chat_matrix.get("total"))
        and _safe_int(chat_matrix.get("total")) > 0,
        "role_continuity_all_pass": _safe_int(role_continuity.get("pass_count")) == _safe_int(role_continuity.get("total"))
        and _safe_int(role_continuity.get("total")) >= 20,
        "no_blocking_quality_findings": blocker_count == 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "findings": findings,
        "metrics": {
            "chat_matrix_cases": len(chat_results),
            "role_continuity_turns": len(role_results),
        },
    }


def _candidate_id(*, source: str, row: dict[str, Any], fallback: int) -> str:
    seed = f"{source}|{_row_id(row, fallback)}|{row.get('query') or ''}|{_answer_text(row)[:160]}"
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _candidate_from_row(*, row: dict[str, Any], source: str, fallback: int) -> dict[str, Any] | None:
    answer = _answer_text(row).strip()
    query = str(row.get("query") or "").strip()
    if not answer or _safe_int(row.get("citation_count")) <= 0:
        return None
    if DOC_LOCATOR_ONLY_RE.search(answer) or NO_ANSWER_RE.search(answer):
        return None
    collections = [str(item) for item in (row.get("collections") or []) if str(item).strip()]
    books = [str(item) for item in (row.get("books") or []) if str(item).strip()]
    cited_indices = [item for item in (row.get("cited_indices") or []) if str(item).strip()]
    if not (collections or books):
        return None
    return {
        "candidate_id": _candidate_id(source=source, row=row, fallback=fallback),
        "source_report": source,
        "source_id": _row_id(row, fallback),
        "role": str(row.get("role") or ""),
        "query": query,
        "title": query[:80] or f"{source} synthesis {fallback}",
        "answer_excerpt": answer[:1000],
        "provenance": {
            "collections": collections,
            "books": books,
            "cited_indices": cited_indices,
            "citation_count": _safe_int(row.get("citation_count")),
        },
        "promotion_state": "candidate_only_requires_review",
    }


def build_wiki_backwrite_candidates(
    *,
    chat_matrix: dict[str, Any],
    role_continuity: dict[str, Any],
    limit: int = 12,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for source, payload in (("chat_matrix", chat_matrix), ("role_continuity", role_continuity)):
        for index, row in enumerate(_list_dicts(payload.get("results")), start=1):
            candidate = _candidate_from_row(row=row, source=source, fallback=index)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    invalid = [
        item["candidate_id"]
        for item in candidates
        if not item.get("query")
        or not item.get("answer_excerpt")
        or not (item.get("provenance") or {}).get("citation_count")
    ]
    checks = {
        "candidate_count_positive": len(candidates) > 0,
        "all_candidates_have_provenance": not invalid,
        "candidate_only_not_auto_promoted": all(
            item.get("promotion_state") == "candidate_only_requires_review" for item in candidates
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "candidate_count": len(candidates),
        "invalid_candidate_ids": invalid,
        "candidates": candidates,
    }


def build_wiki_lint_anti_rot(
    *,
    root: Path,
    evidence_paths: dict[str, Path],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    head = _git_value(root, "rev-parse", "HEAD")
    findings: list[dict[str, Any]] = []
    for name, path in evidence_paths.items():
        payload = _read_json(path)
        if not payload:
            findings.append({"severity": "blocker", "code": "evidence_missing_or_unreadable", "name": name, "path": str(path)})
            continue
        report_head = str(payload.get("head") or (payload.get("git") or {}).get("head") or "")
        if report_head and head and report_head != head:
            findings.append(
                {
                    "severity": "blocker",
                    "code": "stale_evidence_head",
                    "name": name,
                    "path": str(path),
                    "report_head": report_head,
                    "current_head": head,
                }
            )
    for candidate in candidates:
        provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
        if not provenance.get("citation_count") or not (provenance.get("books") or provenance.get("collections")):
            findings.append(
                {
                    "severity": "blocker",
                    "code": "candidate_without_source_provenance",
                    "candidate_id": candidate.get("candidate_id"),
                }
            )
        if not candidate.get("query"):
            findings.append(
                {
                    "severity": "warning",
                    "code": "candidate_orphan_without_query",
                    "candidate_id": candidate.get("candidate_id"),
                }
            )
    blocker_count = sum(1 for item in findings if item.get("severity") == "blocker")
    warning_count = sum(1 for item in findings if item.get("severity") == "warning")
    checks = {
        "evidence_files_readable": all(_read_json(path) for path in evidence_paths.values()),
        "evidence_heads_current": blocker_count == 0,
        "candidate_provenance_clean": not any(item.get("code") == "candidate_without_source_provenance" for item in findings),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "findings": findings,
    }


def build_llmwiki_evolution_gate(
    root_dir: str | Path,
    *,
    chat_matrix_report_path: str | Path | None = None,
    role_continuity_report_path: str | Path | None = None,
    promotion_report_path: str | Path | None = None,
    validation_loop_report_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(root_dir).resolve()
    chat_path = Path(chat_matrix_report_path) if chat_matrix_report_path else _dated_report_path(root, "llmwiki-promotion-chat-matrix")
    role_path = Path(role_continuity_report_path) if role_continuity_report_path else _dated_report_path(root, "role-continuity-rehearsal")
    promotion_path = Path(promotion_report_path) if promotion_report_path else _dated_report_path(root, "llmwiki-promotion-report")
    loop_path = Path(validation_loop_report_path) if validation_loop_report_path else _dated_report_path(root, "llmwiki-validation-loop")
    chat_matrix = _read_json(chat_path)
    role_continuity = _read_json(role_path)

    quality = build_retrieval_quality_critic(chat_matrix=chat_matrix, role_continuity=role_continuity)
    backwrite = build_wiki_backwrite_candidates(chat_matrix=chat_matrix, role_continuity=role_continuity)
    evidence_paths = {
        "chat_matrix": chat_path,
        "role_continuity": role_path,
        "promotion": promotion_path,
        "validation_loop": loop_path,
    }
    anti_rot = build_wiki_lint_anti_rot(
        root=root,
        evidence_paths=evidence_paths,
        candidates=backwrite.get("candidates", []),
    )
    checks = {
        "retrieval_quality_critic_ready": bool(quality.get("ok")),
        "wiki_backwrite_candidate_ready": bool(backwrite.get("ok")),
        "wiki_lint_anti_rot_ready": bool(anti_rot.get("ok")),
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "generated_at": _iso_timestamp(),
        "git": _git_refs(root),
        "goal": "beyond_rag_llmwiki_p0_evolution_gate",
        "status": "ok" if not failures else "fail",
        "ready": not failures,
        "checks": checks,
        "failures": failures,
        "retrieval_quality_critic": quality,
        "wiki_backwrite_candidate": backwrite,
        "wiki_lint_anti_rot": anti_rot,
        "next_lanes": [
            "contextual_chunk_enrichment",
            "raptor_summary_tree",
            "graphrag_community_reports",
            "crag_self_rag_retrieval_critic",
        ],
        "evidence": {name: str(path) for name, path in evidence_paths.items()},
    }


def write_llmwiki_evolution_gate_report(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    chat_matrix_report_path: str | Path | None = None,
    role_continuity_report_path: str | Path | None = None,
    promotion_report_path: str | Path | None = None,
    validation_loop_report_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir).resolve()
    payload = build_llmwiki_evolution_gate(
        root,
        chat_matrix_report_path=chat_matrix_report_path,
        role_continuity_report_path=role_continuity_report_path,
        promotion_report_path=promotion_report_path,
        validation_loop_report_path=validation_loop_report_path,
    )
    output = Path(output_path) if output_path else _dated_report_path(root, "llmwiki-evolution-gate")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, payload
