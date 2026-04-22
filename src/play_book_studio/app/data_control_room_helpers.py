"""data_control_room helper functions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from play_book_studio.app.data_control_room_buckets import _safe_int, _safe_read_json
from play_book_studio.config.settings import load_settings


def _path_snapshot(path: Path) -> dict[str, Any]:
    exists = path.exists()
    payload: dict[str, Any] = {"path": str(path), "exists": exists}
    if exists:
        try:
            stat = path.stat()
            payload["mtime"] = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
            if path.is_file():
                payload["size_bytes"] = stat.st_size
        except OSError:
            return payload
    return payload


def _path_snapshot_for_optional(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "exists": False}
    return _path_snapshot(path)


def _job_payload(report: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in report.get("job_results", []):
        if isinstance(job, dict) and str(job.get("job_id") or "") == job_id:
            payload = job.get("payload")
            return payload if isinstance(payload, dict) else {}
    return {}


def _job_report_path(report: dict[str, Any], job_id: str) -> str:
    for job in report.get("job_results", []):
        if isinstance(job, dict) and str(job.get("job_id") or "") == job_id:
            return str(job.get("audit_report_path") or "")
    return ""


def _resolve_report_path(candidate: str) -> Path | None:
    value = str(candidate or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def _report_count(report: dict[str, Any], *, summary_key: str, rows_key: str) -> int:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if isinstance(summary, dict) and summary_key in summary:
        return _safe_int(summary.get(summary_key))
    rows = report.get(rows_key)
    return len(rows) if isinstance(rows, list) else 0


def _select_report_candidate(
    *paths: Path | None,
    summary_key: str,
    rows_key: str,
    expected_count: int = 0,
) -> tuple[Path | None, dict[str, Any]]:
    candidates: list[tuple[tuple[int, int, int, float], Path, dict[str, Any]]] = []
    seen: set[Path] = set()
    for candidate_path in paths:
        if candidate_path is None:
            continue
        resolved = candidate_path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        payload = _safe_read_json(resolved)
        if not payload:
            continue
        primary_count = _report_count(payload, summary_key=summary_key, rows_key=rows_key)
        book_count = _report_count(payload, summary_key="book_count", rows_key="books")
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            mtime = 0.0
        score = (
            1 if expected_count > 0 and primary_count == expected_count else 0,
            1 if primary_count > 0 else 0,
            book_count,
            mtime,
        )
        candidates.append((score, resolved, payload))
    if not candidates:
        return None, {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, best_path, best_payload = candidates[0]
    return best_path, best_payload


def _grade_label(book: dict[str, Any]) -> str:
    content_status = str(book.get("content_status") or book.get("translation_status") or "").strip()
    approval_status = str(book.get("approval_status") or book.get("review_status") or "").strip()
    if content_status == "approved_ko" and approval_status == "approved":
        return "Gold"
    if content_status in {"approved_ko", "translated_ko_draft", "mixed"}:
        return "Silver"
    if approval_status in {"approved", "needs_review", "queued", "draft"}:
        return "Silver"
    return "Bronze"


def _is_gold_book(book: dict[str, Any]) -> bool:
    content_status = str(book.get("content_status") or "").strip()
    approval_status = str(book.get("approval_status") or book.get("review_status") or "").strip()
    return content_status == "approved_ko" and approval_status == "approved"


def _safe_read_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _candidate_file_rows(*paths: Path) -> tuple[Path | None, list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    selected_path: Path | None = None
    selected_rows: list[dict[str, Any]] = []
    for path in paths:
        if any(item.get("path") == str(path) for item in candidates):
            continue
        rows = _safe_read_jsonl(path)
        candidates.append({**_path_snapshot(path), "row_count": len(rows)})
        if selected_path is None and rows:
            selected_path = path
            selected_rows = rows
    if selected_path is None and candidates:
        selected_path = Path(candidates[0]["path"])
    return selected_path, selected_rows, candidates


def _candidate_playbook_dirs(*paths: Path, expected_count: int) -> tuple[Path | None, list[Path], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    selected_dir: Path | None = None
    selected_files: list[Path] = []
    for path in paths:
        if any(item.get("path") == str(path) for item in candidates):
            continue
        files = sorted(path.glob("*.json")) if path.exists() and path.is_dir() else []
        candidates.append({**_path_snapshot(path), "file_count": len(files)})
        if selected_dir is None and files and len(files) == expected_count:
            selected_dir = path
            selected_files = files
    if selected_dir is None:
        best = None
        best_files: list[Path] = []
        for candidate in candidates:
            path = Path(str(candidate["path"]))
            files = sorted(path.glob("*.json")) if path.exists() and path.is_dir() else []
            if len(files) > len(best_files):
                best = path
                best_files = files
        selected_dir = best
        selected_files = best_files
    return selected_dir, selected_files, candidates


def _summarize_eval(report: dict[str, Any], *, overall_key: str = "overall") -> dict[str, Any]:
    overall = report.get(overall_key) if isinstance(report.get(overall_key), dict) else {}
    payload: dict[str, Any] = {"exists": bool(report)}
    for key in (
        "case_count",
        "book_hit_at_1",
        "book_hit_at_3",
        "book_hit_at_5",
        "pass_rate",
        "avg_citation_precision",
        "answer_present_rate",
        "faithfulness",
        "answer_relevancy",
    ):
        value = overall.get(key)
        if value is not None:
            payload[key] = value
    return payload


def _build_high_value_focus(
    source_bundle_quality: dict[str, Any],
    *,
    known_books: dict[str, dict[str, Any]],
    manifest_by_slug: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bundles = source_bundle_quality.get("bundles") if isinstance(source_bundle_quality.get("bundles"), list) else []
    items: list[dict[str, Any]] = []
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        slug = str(bundle.get("book_slug") or "").strip()
        known = known_books.get(slug, {})
        manifest = manifest_by_slug.get(slug, {})
        items.append(
            {
                "book_slug": slug,
                "title": str(bundle.get("title") or known.get("title") or manifest.get("title") or slug),
                "grade": _grade_label(known) if known else _grade_label(manifest) if manifest else "Bronze",
                "content_status": str(bundle.get("content_status") or known.get("content_status") or manifest.get("content_status") or ""),
                "gap_lane": str(bundle.get("gap_lane") or known.get("gap_lane") or manifest.get("gap_lane") or ""),
                "promotion_strategy": str(bundle.get("promotion_strategy") or ""),
                "readiness": str(bundle.get("readiness") or ""),
                "ko_fallback_banner": bool(bundle.get("ko_fallback_banner") or False),
                "manifest_approved": bool(bundle.get("manifest_approved") or False),
                "has_en_html": bool(bundle.get("has_en_html") or False),
                "repo_artifact_count": int(bundle.get("repo_artifact_count") or 0),
                "exact_issue_pr_count": int(bundle.get("exact_issue_pr_count") or 0),
                "related_issue_pr_count": int(bundle.get("related_issue_pr_count") or 0),
                "recommended_action": str(bundle.get("recommended_action") or ""),
            }
        )
    if not items:
        for book in known_books.values():
            if not bool(book.get("high_value")):
                continue
            items.append(
                {
                    "book_slug": str(book.get("book_slug") or ""),
                    "title": str(book.get("title") or ""),
                    "grade": _grade_label(book),
                    "content_status": str(book.get("content_status") or ""),
                    "gap_lane": str(book.get("gap_lane") or ""),
                    "promotion_strategy": "",
                    "readiness": str(book.get("grade") or ""),
                    "ko_fallback_banner": bool(book.get("fallback_detected") or False),
                    "manifest_approved": str(book.get("approval_status") or "") == "approved",
                    "has_en_html": bool(book.get("source_url") or ""),
                    "repo_artifact_count": int(book.get("chunk_count") or 0),
                    "exact_issue_pr_count": 0,
                    "related_issue_pr_count": 0,
                    "recommended_action": str(book.get("gap_action") or ""),
                }
            )
    return {
        "count": len(items),
        "books": sorted(items, key=lambda item: (str(item.get("readiness") or ""), str(item.get("book_slug") or ""))),
        "ready_count": sum(1 for item in items if str(item.get("readiness") or "") == "already_promoted"),
        "manifest_approved_count": sum(1 for item in items if bool(item.get("manifest_approved"))),
    }


def _build_source_of_truth_drift(
    *,
    gate_report: dict[str, Any],
    source_approval_report: dict[str, Any],
    translation_lane_report: dict[str, Any],
    manifest_path: Path,
    selected_chunks_path: Path | None,
    chunk_candidates: list[dict[str, Any]],
    selected_playbook_dir: Path | None,
    playbook_candidates: list[dict[str, Any]],
    source_approval_report_path: Path | None,
    translation_lane_path: Path | None,
) -> dict[str, Any]:
    gate_verdict = gate_report.get("verdict") if isinstance(gate_report.get("verdict"), dict) else {}
    gate_summary = gate_verdict.get("summary") if isinstance(gate_verdict.get("summary"), dict) else {}
    source_summary = source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {}
    translation_summary = translation_lane_report.get("summary") if isinstance(translation_lane_report.get("summary"), dict) else {}
    chunk_existing = [candidate for candidate in chunk_candidates if bool(candidate.get("exists"))]
    playbook_existing = [candidate for candidate in playbook_candidates if bool(candidate.get("exists"))]
    chunk_drift = len(chunk_existing) > 1
    playbook_drift = len(playbook_existing) > 1
    manifest_drift = not manifest_path.exists()
    mismatches: list[str] = []
    if int(gate_summary.get("approved_runtime_count") or 0) != int(source_summary.get("approved_ko_count") or 0):
        mismatches.append("gate_approved_runtime_count_vs_source_approval_approved_ko_count")
    if int(translation_summary.get("active_queue_count") or 0) != len(translation_lane_report.get("active_queue") or []):
        mismatches.append("translation_lane_active_queue_count_vs_payload")
    return {
        "canonical_grade_source": {
            "name": "source_approval_report",
            "path": str(source_approval_report_path or ""),
            "exists": bool(source_approval_report_path and source_approval_report_path.exists()),
            "rule": "Source approval report is the grade authority for approved_ko / translated_ko_draft / blocked classification.",
            "derived_views": ["known_books", "gold_books", "summary.gate.approved_runtime_count"],
            "summary": source_summary,
        },
        "storage_drift": {
            "manifest": {"path": str(manifest_path), "exists": manifest_path.exists(), "selected": str(manifest_path)},
            "chunks": {"selected_path": str(selected_chunks_path or ""), "candidates": chunk_existing, "drift_detected": chunk_drift},
            "playbooks": {"selected_dir": str(selected_playbook_dir or ""), "candidates": playbook_existing, "drift_detected": playbook_drift},
            "report_paths": {"source_approval_report": str(source_approval_report_path or ""), "translation_lane_report": str(translation_lane_path or "")},
            "drift_detected": manifest_drift or chunk_drift or playbook_drift or bool(mismatches),
        },
        "status_alignment": {
            "gate_status": str(gate_verdict.get("status") or "unknown"),
            "approved_runtime_count": int(gate_summary.get("approved_runtime_count") or 0),
            "approved_ko_count": int(source_summary.get("approved_ko_count") or 0),
            "active_queue_count": int(translation_summary.get("active_queue_count") or 0),
            "mismatches": mismatches,
        },
    }


def _simplify_book(book: dict[str, Any]) -> dict[str, Any]:
    translation_lane = book.get("translation_lane") if isinstance(book.get("translation_lane"), dict) else {}
    reader_grade = book.get("manualbook_reader_grade") if isinstance(book.get("manualbook_reader_grade"), dict) else {}
    return {
        "book_slug": str(book.get("book_slug") or ""),
        "title": str(book.get("title") or book.get("vendor_title") or ""),
        "grade": _grade_label(book),
        "content_status": str(book.get("content_status") or ""),
        "approval_status": str(book.get("approval_status") or ""),
        "review_status": str(book.get("review_status") or ""),
        "source_type": str(book.get("source_type") or ""),
        "source_lane": str(book.get("source_lane") or ""),
        "high_value": bool(book.get("high_value")),
        "fallback_detected": bool(book.get("fallback_detected")),
        "chunk_count": int(book.get("chunk_count") or 0),
        "section_count": int(book.get("section_count") or 0),
        "viewer_path": str(book.get("viewer_path") or ""),
        "source_url": str(book.get("source_url") or ""),
        "updated_at": str(book.get("updated_at") or ""),
        "manualbook_reader_grade_failed": bool(book.get("manualbook_reader_grade_failed")),
        "manualbook_reader_grade": reader_grade,
        "runtime_eligible": bool(translation_lane.get("runtime_eligible")),
        "citation_eligible": bool(book.get("citation_eligible")),
        "gap_lane": str(book.get("gap_lane") or ""),
        "gap_action": str(book.get("gap_action") or ""),
        "approval_state": str(book.get("approval_state") or ""),
        "publication_state": str(book.get("publication_state") or ""),
        "parser_backend": str(book.get("parser_backend") or ""),
        "boundary_truth": str(book.get("boundary_truth") or ""),
        "runtime_truth_label": str(book.get("runtime_truth_label") or ""),
        "boundary_badge": str(book.get("boundary_badge") or ""),
    }


def _build_known_books_section(
    source_books: list[dict[str, Any]],
    *,
    manifest_by_slug: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    known_books = [_simplify_book(book) for book in source_books if isinstance(book, dict)]
    for book in known_books:
        slug = str(book.get("book_slug") or "").strip()
        manifest = manifest_by_slug.get(slug, {})
        if not book.get("source_url"):
            book["source_url"] = str(manifest.get("source_url") or manifest.get("resolved_source_url") or "")
        if not book.get("viewer_path"):
            book["viewer_path"] = str(manifest.get("viewer_path") or "")
    return known_books


__all__ = [
    "_build_high_value_focus",
    "_build_known_books_section",
    "_build_source_of_truth_drift",
    "_candidate_file_rows",
    "_candidate_playbook_dirs",
    "_grade_label",
    "_is_gold_book",
    "_job_payload",
    "_job_report_path",
    "_path_snapshot",
    "_path_snapshot_for_optional",
    "_resolve_report_path",
    "_select_report_candidate",
    "_simplify_book",
    "_summarize_eval",
]
