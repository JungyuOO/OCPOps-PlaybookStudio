"""데이터상황실 전용 집계 payload."""

from __future__ import annotations

import subprocess
import json
import urllib.error
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path

from play_book_studio.chat_modes import chat_mode_contract
from play_book_studio.app.data_control_room_buckets import (
    _build_approved_wiki_runtime_book_bucket,
    _build_buyer_packet_bundle_bucket,
    _build_gold_candidate_book_bucket,
    _build_navigation_backlog_bucket,
    _build_product_gate_bucket,
    _build_product_rehearsal_summary,
    _build_release_candidate_freeze_summary,
    _build_wiki_usage_signal_bucket,
    _iso_now,
    _safe_int,
    _safe_read_json,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.intake.artifact_bundle import iter_customer_pack_book_payload_paths
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.source_authority import COMMUNITY_AUTHORITY, canonical_source_authority

from .customer_pack_read_boundary import customer_pack_draft_id_from_viewer_path, load_customer_pack_read_boundary
from .data_control_room_helpers import (
    _build_high_value_focus,
    _build_known_books_section,
    _build_source_of_truth_drift,
    _candidate_file_rows,
    _candidate_playbook_dirs,
    _grade_label,
    _is_gold_book,
    _job_payload,
    _job_report_path,
    _path_snapshot,
    _path_snapshot_for_optional,
    _resolve_report_path,
    _select_report_candidate,
    _simplify_book,
    _summarize_eval,
)
from .data_control_room_detail import load_customer_pack_private_chunk_rows
from .data_control_room_library import (
    DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES,
    DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
    _aggregate_corpus_books,
    _aggregate_playbooks,
    _attach_corpus_status,
    _apply_customer_pack_runtime_truth,
    _apply_viewer_path_fallback,
    _build_custom_document_bucket,
    _build_manual_book_library,
    _build_playbook_library,
    _derived_family_status,
)


def _book_customer_pack_draft_id(book: dict[str, object]) -> str:
    boundary_truth = str(book.get("boundary_truth") or "").strip()
    source_lane = str(book.get("source_lane") or "").strip()
    draft_id = str(book.get("draft_id") or "").strip()
    if draft_id:
        return draft_id.split("::", 1)[0]
    viewer_path = str(book.get("viewer_path") or "").strip()
    viewer_draft_id = customer_pack_draft_id_from_viewer_path(viewer_path)
    if viewer_draft_id:
        return viewer_draft_id
    if boundary_truth != "private_customer_pack_runtime" and source_lane != "customer_source_first_pack":
        return ""
    slug = str(book.get("book_slug") or "").strip()
    return slug.split("--", 1)[0].strip() if "--" in slug else ""


def _book_is_community_runtime(book: dict[str, object]) -> bool:
    return canonical_source_authority(book) == COMMUNITY_AUTHORITY


def _book_is_private_customer_runtime(book: dict[str, object]) -> bool:
    if _book_is_community_runtime(book):
        return False
    return (
        str(book.get("boundary_truth") or "").strip() == "private_customer_pack_runtime"
        or str(book.get("source_lane") or "").strip() == "customer_source_first_pack"
    )


def _filter_readable_customer_pack_books(
    books: list[dict[str, object]],
    *,
    readable_draft_ids: set[str],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for book in books:
        draft_id = _book_customer_pack_draft_id(book)
        if draft_id and draft_id not in readable_draft_ids:
            continue
        items.append(book)
    return items


def _path_fingerprint(path: Path | None) -> tuple[str, bool, int, int]:
    if path is None:
        return ("", False, 0, 0)
    target = Path(path).resolve()
    try:
        stat = target.stat()
    except FileNotFoundError:
        return (str(target), False, 0, 0)
    return (str(target), True, int(stat.st_mtime_ns), int(stat.st_size))


def _data_control_room_cache_fingerprint(root: Path) -> tuple[tuple[str, bool, int, int], ...]:
    settings = load_settings(root)
    gate_path = root / "reports" / "build_logs" / "foundry_runs" / "profiles" / "morning_gate" / "latest.json"
    promotion_report_paths = _llmwiki_promotion_report_paths(root)
    validation_loop_report_paths = _llmwiki_validation_loop_report_paths(root)
    role_rehearsal_report_paths = _role_rehearsal_report_paths(root)
    contextual_enrichment_report_paths = _llmwiki_contextual_enrichment_report_paths(root)
    custom_material_dir = root / ".P_docs" / "01_검토대기_플레이북재료"
    custom_material_files = sorted(path for path in custom_material_dir.rglob("*") if path.is_file()) if custom_material_dir.exists() else []
    draft_store = CustomerPackDraftStore(root)
    draft_records = draft_store.list()
    watched_paths = [
        gate_path,
        root / ".git" / "HEAD",
        *promotion_report_paths,
        *validation_loop_report_paths,
        *role_rehearsal_report_paths,
        *contextual_enrichment_report_paths,
        root / ".P_docs" / "01_검토대기_플레이북재료",
        root / ".P_docs" / "_review_bucket_manifest.json",
        *custom_material_files,
        settings.source_manifest_path,
        settings.source_approval_report_path,
        settings.translation_lane_report_path,
        settings.retrieval_eval_report_path,
        settings.answer_eval_report_path,
        settings.ragas_eval_report_path,
        settings.runtime_report_path,
        settings.chunks_path,
        settings.customer_pack_books_dir,
        settings.customer_pack_corpus_dir,
        draft_store.drafts_dir,
        *[
            Path(str(getattr(record, "private_corpus_manifest_path", "") or "").strip())
            for record in draft_records
            if str(getattr(record, "private_corpus_manifest_path", "") or "").strip()
        ],
        *settings.playbook_book_dirs,
    ]
    fingerprints = [_path_fingerprint(path) for path in watched_paths]
    git_context = _current_git_context(root)
    git_signature = "|".join(
        [
            str(git_context.get("branch") or ""),
            str(git_context.get("head") or ""),
            str(bool(git_context.get("dirty_tracked_files"))),
        ]
    )
    fingerprints.append((f"git-state:{git_signature}", True, 0, len(git_signature)))
    runtime_dependency_signature = _runtime_dependency_fingerprint(root)
    fingerprints.append((f"runtime-deps:{runtime_dependency_signature}", True, 0, len(runtime_dependency_signature)))
    return tuple(fingerprints)


def _llmwiki_promotion_report_paths(root: Path) -> list[Path]:
    reports_dir = root / ".kugnusdocs" / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*llmwiki-promotion*.json"), key=lambda path: path.name)


def _latest_llmwiki_promotion_report_path(root: Path) -> Path | None:
    evidence_markers = (
        "artifact-manifest",
        "chat-matrix",
        "customer-master",
        "official-gold-gate",
        "runtime-maintenance",
        "runtime-report",
    )
    candidates: list[Path] = []
    for path in _llmwiki_promotion_report_paths(root):
        if any(marker in path.name for marker in evidence_markers):
            continue
        payload = _safe_read_json(path)
        summary = _dict_from(payload.get("summary"))
        is_top_level_report = bool(
            payload.get("ready_for_llmwiki_promotion") is not None
            or summary.get("ready_for_llmwiki_promotion") is not None
            or _dict_from(summary.get("contracts"))
        )
        if is_top_level_report:
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0)


def _llmwiki_validation_loop_report_paths(root: Path) -> list[Path]:
    reports_dir = root / ".kugnusdocs" / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*llmwiki-validation-loop*.json"), key=lambda path: path.name)


def _latest_llmwiki_validation_loop_report_path(root: Path) -> Path | None:
    candidates = _llmwiki_validation_loop_report_paths(root)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0)


def _role_rehearsal_report_paths(root: Path) -> list[Path]:
    reports_dir = root / ".kugnusdocs" / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*operator-learner-role-rehearsal*.json"), key=lambda path: path.name)


def _latest_role_rehearsal_report_path(root: Path) -> Path | None:
    candidates = _role_rehearsal_report_paths(root)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0)


def _llmwiki_evolution_gate_report_paths(root: Path) -> list[Path]:
    reports_dir = root / ".kugnusdocs" / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*llmwiki-evolution-gate*.json"), key=lambda path: path.name)


def _latest_llmwiki_evolution_gate_report_path(root: Path) -> Path | None:
    candidates = _llmwiki_evolution_gate_report_paths(root)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0)


def _llmwiki_contextual_enrichment_report_paths(root: Path) -> list[Path]:
    reports_dir = root / ".kugnusdocs" / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*llmwiki-contextual-enrichment-gate*.json"), key=lambda path: path.name)


def _latest_llmwiki_contextual_enrichment_report_path(root: Path) -> Path | None:
    candidates = _llmwiki_contextual_enrichment_report_paths(root)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns if path.exists() else 0)


def _git_text(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _current_git_context(root: Path) -> dict[str, object]:
    dirty = bool(_git_text(root, "status", "--porcelain", "--untracked-files=no"))
    return {
        "branch": _git_text(root, "branch", "--show-current"),
        "head": _git_text(root, "rev-parse", "HEAD"),
        "dirty_tracked_files": dirty,
        "dirty_tracked_latest_mtime_ns": _dirty_tracked_latest_mtime_ns(root),
    }


def _dirty_tracked_latest_mtime_ns(root: Path) -> int:
    latest = 0
    status_text = _git_text(root, "status", "--porcelain", "--untracked-files=no")
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path_text = line[3:].strip().strip('"')
        if " -> " in path_text:
            path_text = path_text.rsplit(" -> ", 1)[1].strip().strip('"')
        if not path_text:
            continue
        path = root / path_text
        try:
            latest = max(latest, int(path.stat().st_mtime_ns))
        except OSError:
            continue
    return latest


def _dict_from(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _list_from(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _promotion_contract(report: dict[str, object], key: str) -> dict[str, object]:
    summary = _dict_from(report.get("summary"))
    contracts = _dict_from(summary.get("contracts"))
    contract = _dict_from(contracts.get(key))
    if contract:
        return contract
    return _dict_from(report.get(key))


def _promotion_contract_ok(report: dict[str, object], key: str) -> bool:
    contract = _promotion_contract(report, key)
    return bool(contract.get("ok"))


def _chat_matrix_total(chat_matrix: dict[str, object]) -> tuple[int, int]:
    requirements = _dict_from(chat_matrix.get("runtime_requirements"))
    llm_pass = _safe_int(requirements.get("llm_live_pass_count"))
    llm_total = _safe_int(requirements.get("llm_live_total"))
    vector_pass = _safe_int(requirements.get("vector_live_pass_count"))
    vector_total = _safe_int(requirements.get("vector_live_total"))
    return llm_pass + vector_pass, llm_total + vector_total


def _build_llmwiki_promotion_control_status(root: Path) -> dict[str, object]:
    report_path = _latest_llmwiki_promotion_report_path(root)
    current_git = _current_git_context(root)
    if report_path is None:
        return {
            "status": "missing",
            "ready": False,
            "report_ready": False,
            "failures": ["llmwiki promotion report is missing"],
            "selected_report": {
                "path": "",
                "exists": False,
                "generated_at": "",
                "git": {},
                "current_git": current_git,
                "head_matches_current": False,
                "stale": True,
            },
            "contracts": {},
            "metrics": {},
            "evidence": {},
            "commands": {},
            "mode_contract": chat_mode_contract(),
        }

    report = _safe_read_json(report_path)
    report_git = _dict_from(report.get("git"))
    current_head = str(current_git.get("head") or "").strip()
    report_head = str(report_git.get("head") or "").strip()
    head_matches_current = bool(current_head and report_head and current_head == report_head)
    report_mtime_ns = int(report_path.stat().st_mtime_ns if report_path.exists() else 0)
    dirty_after_report = _safe_int(current_git.get("dirty_tracked_latest_mtime_ns")) > report_mtime_ns
    stale = not head_matches_current or dirty_after_report
    summary = _dict_from(report.get("summary"))
    raw_failures = _list_from(summary.get("failures")) or _list_from(report.get("failures"))
    report_status = str(report.get("status") or summary.get("status") or "unknown")
    report_ready = bool(report.get("ready_for_llmwiki_promotion") or summary.get("ready_for_llmwiki_promotion"))
    official_gold = _promotion_contract(report, "official_gold")
    official_metrics = _dict_from(official_gold.get("metrics"))
    customer_master = _promotion_contract(report, "customer_master")
    customer_validation = _dict_from(customer_master.get("validation"))
    runtime_report = _promotion_contract(report, "runtime_report")
    runtime_maintenance = _promotion_contract(report, "runtime_maintenance")
    chat_matrix = _promotion_contract(report, "chat_matrix")
    chat_pass, chat_total = _chat_matrix_total(chat_matrix)
    status = "stale" if stale else report_status
    failures = [str(item) for item in raw_failures if str(item).strip()]
    if stale:
        failures = [
            *failures,
            "llmwiki promotion report is stale for the current checkout",
        ]
    return {
        "status": status,
        "ready": bool(report_ready and not stale and report_status == "ok"),
        "report_ready": report_ready,
        "failures": failures,
        "selected_report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "generated_at": str(report.get("generated_at") or ""),
            "git": report_git,
            "current_git": current_git,
            "head_matches_current": head_matches_current,
            "dirty_after_report": dirty_after_report,
            "stale": stale,
        },
        "contracts": {
            "official_gold": official_gold,
            "customer_master": customer_master,
            "runtime_report": runtime_report,
            "runtime_maintenance": runtime_maintenance,
            "chat_matrix": chat_matrix,
        },
        "metrics": {
            "official_chunks_count": _safe_int(official_metrics.get("chunks_count")),
            "official_bm25_count": _safe_int(official_metrics.get("bm25_count")),
            "official_code_blocks": _safe_int(official_metrics.get("code_blocks")),
            "official_inline_figures": _safe_int(official_metrics.get("playbook_figure_blocks")),
            "official_figure_sidecar_count": _safe_int(official_metrics.get("figure_sidecar_count")),
            "official_figure_matched_section_count": _safe_int(official_metrics.get("figure_matched_section_count")),
            "official_figure_missing_relation_count": _safe_int(official_metrics.get("figure_missing_relation_count")),
            "official_bm25_metadata_missing_row_count": _safe_int(official_metrics.get("bm25_metadata_missing_row_count")),
            "official_ko_localization_failing_book_count": _safe_int(official_metrics.get("ko_localization_failing_book_count")),
            "official_ko_localization_book_count": _safe_int(official_metrics.get("ko_localization_book_count")),
            "official_ko_localization_status": str(official_metrics.get("ko_localization_status") or ""),
            "customer_master_source_count": _safe_int(customer_master.get("source_count")),
            "customer_master_section_count": _safe_int(customer_master.get("section_count")),
            "customer_master_chunk_count": _safe_int(customer_master.get("chunk_count")),
            "customer_master_coverage_ratio": customer_validation.get("source_coverage_ratio"),
            "chat_live_pass_count": chat_pass,
            "chat_live_total": chat_total,
        },
        "status_rail": [
            {
                "key": "promotion",
                "label": "Promotion",
                "status": status,
                "ready": bool(report_ready and not stale and report_status == "ok"),
                "detail": "promotion report / current HEAD",
                "count": 1 if report_ready else 0,
                "total": 1,
            },
            {
                "key": "official",
                "label": "Official",
                "status": "ready" if _promotion_contract_ok(report, "official_gold") else "blocked",
                "ready": _promotion_contract_ok(report, "official_gold"),
                "detail": f"{_safe_int(official_metrics.get('chunks_count')):,} chunks / {_safe_int(official_metrics.get('code_blocks')):,} code blocks",
                "count": _safe_int(official_metrics.get("chunks_count")),
                "total": _safe_int(official_metrics.get("bm25_count")),
            },
            {
                "key": "customer",
                "label": "Customer",
                "status": "ready" if _promotion_contract_ok(report, "customer_master") else "blocked",
                "ready": _promotion_contract_ok(report, "customer_master"),
                "detail": f"{_safe_int(customer_master.get('source_count'))} PPT sources / {_safe_int(customer_master.get('section_count'))} master sections",
                "count": _safe_int(customer_master.get("source_count")),
                "total": _safe_int(customer_master.get("source_count")),
            },
            {
                "key": "runtime",
                "label": "Runtime",
                "status": "ready" if _promotion_contract_ok(report, "runtime_report") and _promotion_contract_ok(report, "runtime_maintenance") else "blocked",
                "ready": _promotion_contract_ok(report, "runtime_report") and _promotion_contract_ok(report, "runtime_maintenance"),
                "detail": "LLM / Embedder / Vector smoke",
                "count": int(_promotion_contract_ok(report, "runtime_report")) + int(_promotion_contract_ok(report, "runtime_maintenance")),
                "total": 2,
            },
            {
                "key": "chat",
                "label": "Chat",
                "status": "ready" if _promotion_contract_ok(report, "chat_matrix") else "blocked",
                "ready": _promotion_contract_ok(report, "chat_matrix"),
                "detail": f"{chat_pass}/{chat_total} live LLM/vector checks",
                "count": chat_pass,
                "total": chat_total,
            },
        ],
        "evidence": _dict_from(report.get("evidence")),
        "commands": _dict_from(report.get("commands")),
        "mode_contract": chat_mode_contract(),
    }


def _build_llmwiki_validation_loop_control_status(root: Path) -> dict[str, object]:
    report_path = _latest_llmwiki_validation_loop_report_path(root)
    current_git = _current_git_context(root)
    if report_path is None:
        return {
            "status": "missing",
            "ready": False,
            "failures": ["llmwiki validation loop report is missing"],
            "selected_report": {
                "path": "",
                "exists": False,
                "generated_at": "",
                "git": {},
                "current_git": current_git,
                "head_matches_current": False,
                "stale": True,
            },
            "surya_policy": {
                "required_for_llmwiki_runtime": False,
                "status": "offline_allowed",
            },
            "acceptance": {},
            "metrics": {},
            "commands": {},
        }

    report = _safe_read_json(report_path)
    report_git = _dict_from(report.get("git"))
    current_head = str(current_git.get("head") or "").strip()
    report_head = str(report_git.get("head") or "").strip()
    head_matches_current = bool(current_head and report_head and current_head == report_head)
    report_mtime_ns = int(report_path.stat().st_mtime_ns if report_path.exists() else 0)
    dirty_after_report = _safe_int(current_git.get("dirty_tracked_latest_mtime_ns")) > report_mtime_ns
    stale = not head_matches_current or dirty_after_report
    acceptance = _dict_from(report.get("acceptance"))
    failures = [
        str(item)
        for item in _list_from(acceptance.get("failures")) or _list_from(report.get("failures"))
        if str(item).strip()
    ]
    if stale:
        failures.append("llmwiki validation loop report is stale for the current checkout")
    report_status = str(report.get("status") or "unknown")
    ready = bool(report.get("ready")) and report_status == "ok" and not stale
    metrics = _dict_from(acceptance.get("metrics"))
    return {
        "status": "stale" if stale else report_status,
        "ready": ready,
        "failures": failures,
        "selected_report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "generated_at": str(report.get("generated_at") or ""),
            "git": report_git,
            "current_git": current_git,
            "head_matches_current": head_matches_current,
            "dirty_after_report": dirty_after_report,
            "stale": stale,
        },
        "surya_policy": _dict_from(report.get("surya_policy")),
        "acceptance": acceptance,
        "metrics": {
            "completed_iterations": _safe_int(report.get("completed_iterations")),
            "requested_iterations": _safe_int(report.get("requested_iterations")),
            "official_chunks": _safe_int(metrics.get("official_chunks")),
            "official_code_blocks": _safe_int(metrics.get("official_code_blocks")),
            "official_figures": _safe_int(metrics.get("official_figures")),
            "customer_sources": _safe_int(metrics.get("customer_sources")),
            "customer_sections": _safe_int(metrics.get("customer_sections")),
            "chat_live_pass_count": _safe_int(metrics.get("chat_live_pass_count")),
            "chat_live_total": _safe_int(metrics.get("chat_live_total")),
        },
        "commands": _dict_from(report.get("commands")),
    }


def _build_llmwiki_evolution_gate_control_status(root: Path) -> dict[str, object]:
    report_path = _latest_llmwiki_evolution_gate_report_path(root)
    current_git = _current_git_context(root)
    if report_path is None:
        return {
            "status": "missing",
            "ready": False,
            "failures": ["llmwiki evolution gate report is missing"],
            "selected_report": {
                "path": "",
                "exists": False,
                "generated_at": "",
                "git": {},
                "current_git": current_git,
                "head_matches_current": False,
                "stale": True,
            },
            "checks": {},
            "metrics": {},
        }
    report = _safe_read_json(report_path)
    report_git = _dict_from(report.get("git"))
    current_head = str(current_git.get("head") or "").strip()
    report_head = str(report_git.get("head") or "").strip()
    head_matches_current = bool(current_head and report_head and current_head == report_head)
    report_mtime_ns = int(report_path.stat().st_mtime_ns if report_path.exists() else 0)
    dirty_after_report = _safe_int(current_git.get("dirty_tracked_latest_mtime_ns")) > report_mtime_ns
    stale = not head_matches_current or dirty_after_report
    status = "stale" if stale else str(report.get("status") or "unknown")
    failures = [str(item) for item in _list_from(report.get("failures")) if str(item).strip()]
    if stale:
        failures.append("llmwiki evolution gate report is stale for the current checkout")
    quality = _dict_from(report.get("retrieval_quality_critic"))
    backwrite = _dict_from(report.get("wiki_backwrite_candidate"))
    anti_rot = _dict_from(report.get("wiki_lint_anti_rot"))
    return {
        "status": status,
        "ready": bool(report.get("ready") and not stale and report.get("status") == "ok"),
        "failures": failures,
        "selected_report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "generated_at": str(report.get("generated_at") or ""),
            "git": report_git,
            "current_git": current_git,
            "head_matches_current": head_matches_current,
            "dirty_after_report": dirty_after_report,
            "stale": stale,
        },
        "checks": _dict_from(report.get("checks")),
        "metrics": {
            "quality_blockers": _safe_int(quality.get("blocker_count")),
            "quality_warnings": _safe_int(quality.get("warning_count")),
            "backwrite_candidates": _safe_int(backwrite.get("candidate_count")),
            "anti_rot_blockers": _safe_int(anti_rot.get("blocker_count")),
            "anti_rot_warnings": _safe_int(anti_rot.get("warning_count")),
        },
    }


def _build_llmwiki_contextual_enrichment_control_status(root: Path) -> dict[str, object]:
    report_path = _latest_llmwiki_contextual_enrichment_report_path(root)
    current_git = _current_git_context(root)
    if report_path is None:
        return {
            "status": "missing",
            "ready": False,
            "failures": ["llmwiki contextual enrichment gate report is missing"],
            "selected_report": {
                "path": "",
                "exists": False,
                "generated_at": "",
                "git": {},
                "current_git": current_git,
                "head_matches_current": False,
                "stale": True,
            },
            "checks": {},
            "metrics": {},
        }
    report = _safe_read_json(report_path)
    report_git = _dict_from(report.get("git"))
    current_head = str(current_git.get("head") or "").strip()
    report_head = str(report_git.get("head") or "").strip()
    head_matches_current = bool(current_head and report_head and current_head == report_head)
    report_mtime_ns = int(report_path.stat().st_mtime_ns if report_path.exists() else 0)
    dirty_after_report = _safe_int(current_git.get("dirty_tracked_latest_mtime_ns")) > report_mtime_ns
    stale = not head_matches_current or dirty_after_report
    status = "stale" if stale else str(report.get("status") or "unknown")
    failures = [str(item) for item in _list_from(report.get("failures")) if str(item).strip()]
    if stale:
        failures.append("llmwiki contextual enrichment gate report is stale for the current checkout")
    coverage = _dict_from(report.get("coverage"))
    total = _dict_from(coverage.get("total"))
    recall_fixture = _dict_from(report.get("recall_fixture"))
    return {
        "status": status,
        "ready": bool(report.get("ready") and not stale and report.get("status") == "ok"),
        "failures": failures,
        "selected_report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "generated_at": str(report.get("generated_at") or ""),
            "git": report_git,
            "current_git": current_git,
            "head_matches_current": head_matches_current,
            "dirty_after_report": dirty_after_report,
            "stale": stale,
        },
        "checks": _dict_from(report.get("checks")),
        "metrics": {
            "row_count": _safe_int(total.get("row_count")),
            "runtime_contextual_count": _safe_int(total.get("runtime_contextual_count")),
            "persisted_contextual_count": _safe_int(total.get("persisted_contextual_count")),
            "contextual_prefix_count": _safe_int(total.get("contextual_prefix_count")),
            "contextual_heading_path_count": _safe_int(total.get("contextual_heading_path_count")),
            "recall_fixture_improved": bool(recall_fixture.get("improved")),
        },
    }


def _role_rehearsal_git_context(report: dict[str, object]) -> dict[str, object]:
    report_git = _dict_from(report.get("git"))
    if report_git:
        return report_git
    return {
        "branch": str(report.get("branch") or ""),
        "head": str(report.get("head") or ""),
    }


def _probe_qdrant_dependency(root: Path, *, timeout: float = 1.5) -> dict[str, object]:
    settings = load_settings(root)
    url = f"{settings.qdrant_url.rstrip('/')}/collections"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 0) or 0)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "id": "qdrant",
            "ready": False,
            "status": "down",
            "url": url,
            "collection": settings.qdrant_collection,
            "collections": [],
            "error": str(exc),
        }
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return {
            "id": "qdrant",
            "ready": False,
            "status": "bad_json",
            "url": url,
            "collection": settings.qdrant_collection,
            "collections": [],
            "http_status": status_code,
            "error": str(exc),
        }
    result = payload.get("result") if isinstance(payload, dict) else {}
    rows = result.get("collections") if isinstance(result, dict) else []
    collections = [
        str(item.get("name") or "").strip()
        for item in rows
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    collection_ready = settings.qdrant_collection in collections
    return {
        "id": "qdrant",
        "ready": status_code < 400 and collection_ready,
        "status": "ok" if status_code < 400 and collection_ready else "missing_collection",
        "url": url,
        "collection": settings.qdrant_collection,
        "collections": collections,
        "http_status": status_code,
        "error": "" if collection_ready else f"missing collection: {settings.qdrant_collection}",
    }


def _runtime_dependency_fingerprint(root: Path) -> str:
    qdrant = _probe_qdrant_dependency(root, timeout=0.5)
    return "|".join(
        [
            "qdrant",
            str(qdrant.get("status") or ""),
            str(bool(qdrant.get("ready"))),
            str(qdrant.get("collection") or ""),
            str(qdrant.get("error") or "")[:120],
        ]
    )


def _build_runtime_dependency_status(root: Path) -> dict[str, object]:
    qdrant = _probe_qdrant_dependency(root)
    checks = [qdrant]
    failures = [
        f"{check.get('id')}: {check.get('error') or check.get('status')}"
        for check in checks
        if not bool(check.get("ready"))
    ]
    ready = not failures
    return {
        "status": "ok" if ready else "blocked",
        "ready": ready,
        "failures": failures,
        "checks": checks,
        "qdrant": qdrant,
    }


def _build_role_rehearsal_control_status(root: Path) -> dict[str, object]:
    report_path = _latest_role_rehearsal_report_path(root)
    current_git = _current_git_context(root)
    empty_roles = {
        "operator_a": {"pass": 0, "total": 0, "ready": False},
        "learner_b": {"pass": 0, "total": 0, "ready": False},
    }
    if report_path is None:
        return {
            "status": "missing",
            "ready": False,
            "pass_count": 0,
            "total": 0,
            "roles": empty_roles,
            "acceptance": {},
            "failures": ["operator/learner role rehearsal report is missing"],
            "selected_report": {
                "path": "",
                "exists": False,
                "generated_at": "",
                "git": {},
                "current_git": current_git,
                "head_matches_current": False,
                "stale": True,
            },
            "results": [],
        }

    report = _safe_read_json(report_path)
    report_git = _role_rehearsal_git_context(report)
    current_head = str(current_git.get("head") or "").strip()
    report_head = str(report_git.get("head") or "").strip()
    head_matches_current = bool(current_head and report_head and current_head == report_head)
    report_mtime_ns = int(report_path.stat().st_mtime_ns if report_path.exists() else 0)
    dirty_after_report = _safe_int(current_git.get("dirty_tracked_latest_mtime_ns")) > report_mtime_ns
    stale = not head_matches_current or dirty_after_report
    report_status = str(report.get("status") or "unknown").strip()
    pass_count = _safe_int(report.get("pass_count"))
    total = _safe_int(report.get("total"))
    raw_roles = _dict_from(report.get("roles"))
    acceptance = _dict_from(report.get("acceptance"))
    roles: dict[str, object] = {}
    failures = [str(item) for item in _list_from(report.get("failures")) if str(item).strip()]
    for role_id in ("operator_a", "learner_b"):
        role_payload = _dict_from(raw_roles.get(role_id))
        role_pass = _safe_int(role_payload.get("pass"))
        role_total = _safe_int(role_payload.get("total"))
        role_ready = role_total > 0 and role_pass == role_total
        roles[role_id] = {
            "pass": role_pass,
            "total": role_total,
            "ready": role_ready,
            "acceptance": str(acceptance.get(role_id) or ""),
        }
        if not role_ready:
            failures.append(f"{role_id} role rehearsal is incomplete ({role_pass}/{role_total})")
    results: list[dict[str, object]] = []
    for result in _list_from(report.get("results")):
        if not isinstance(result, dict):
            continue
        result_pass = bool(result.get("pass"))
        result_id = str(result.get("id") or "").strip()
        role_id = str(result.get("role") or "").strip()
        results.append(
            {
                "id": result_id,
                "role": role_id,
                "goal": str(result.get("goal") or ""),
                "pass": result_pass,
                "status": str(result.get("status") or ""),
                "response_kind": str(result.get("response_kind") or ""),
                "collections": [str(item) for item in _list_from(result.get("collections"))],
                "books": [str(item) for item in _list_from(result.get("books"))],
                "citation_count": _safe_int(result.get("citation_count")),
            }
        )
        if not result_pass:
            failures.append(f"{role_id or 'unknown'}::{result_id or 'unknown'} failed role rehearsal")
    if total <= 0:
        failures.append("role rehearsal total case count is zero")
    if pass_count != total:
        failures.append(f"role rehearsal pass count mismatch ({pass_count}/{total})")
    if report_status != "ok":
        failures.append(f"role rehearsal report status is {report_status or 'unknown'}")
    if stale:
        failures.append("operator/learner role rehearsal report is stale for the current checkout")
    status = "stale" if stale else report_status
    ready = status == "ok" and pass_count == total and total > 0 and not failures
    return {
        "status": status,
        "ready": ready,
        "pass_count": pass_count,
        "total": total,
        "roles": roles,
        "acceptance": acceptance,
        "failures": failures,
        "selected_report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "generated_at": str(report.get("generated_at") or ""),
            "git": report_git,
            "current_git": current_git,
            "head_matches_current": head_matches_current,
            "dirty_after_report": dirty_after_report,
            "stale": stale,
        },
        "results": results,
    }


def _rail_ready(llmwiki_promotion: dict[str, object], key: str) -> bool:
    for item in _list_from(llmwiki_promotion.get("status_rail")):
        if not isinstance(item, dict):
            continue
        if str(item.get("key") or "").strip() == key:
            return bool(item.get("ready"))
    return False


def _surface_status(*, ready: bool, watch: bool = False) -> str:
    if ready:
        return "ready"
    if watch:
        return "watch"
    return "blocked"


def _build_development_surface(
    *,
    surface_id: str,
    title: str,
    route: str,
    ready: bool,
    acceptance: str,
    evidence: list[str],
    next_action: str,
    blockers: list[str] | None = None,
    watch: bool = False,
    required: bool = True,
) -> dict[str, object]:
    normalized_blockers = [str(item) for item in blockers or [] if str(item).strip()]
    return {
        "id": surface_id,
        "title": title,
        "route": route,
        "owner_scope": "feat/dev-kugnus",
        "required": required,
        "ready": bool(ready),
        "status": _surface_status(ready=ready, watch=watch and not ready),
        "acceptance": acceptance,
        "evidence": evidence,
        "next_action": next_action,
        "blockers": normalized_blockers,
    }


def _build_development_control_status(
    *,
    llmwiki_promotion: dict[str, object],
    llmwiki_validation_loop: dict[str, object] | None = None,
    official_playbook_count: int,
    customer_playbook_count: int,
    user_corpus_chunk_count: int,
    custom_document_count: int,
    playable_asset_count: int,
    source_of_truth_drift: dict[str, object],
    product_rehearsal: dict[str, object],
    role_rehearsal: dict[str, object],
    runtime_dependencies: dict[str, object],
) -> dict[str, object]:
    validation_loop = _dict_from(llmwiki_validation_loop)
    metrics = _dict_from(llmwiki_promotion.get("metrics"))
    mode_contract = _dict_from(llmwiki_promotion.get("mode_contract"))
    mode_ids = {
        str(item.get("id") or "").strip()
        for item in _list_from(mode_contract.get("supported_modes"))
        if isinstance(item, dict)
    }
    selected_report = _dict_from(llmwiki_promotion.get("selected_report"))
    official_chunks = _safe_int(metrics.get("official_chunks_count"))
    official_code_blocks = _safe_int(metrics.get("official_code_blocks"))
    official_figures = _safe_int(metrics.get("official_inline_figures"))
    customer_sources = _safe_int(metrics.get("customer_master_source_count"))
    customer_sections = _safe_int(metrics.get("customer_master_section_count"))
    chat_pass_count = _safe_int(metrics.get("chat_live_pass_count"))
    chat_total = _safe_int(metrics.get("chat_live_total"))
    source_alignment = _dict_from(source_of_truth_drift.get("status_alignment"))
    drift_mismatches = [
        str(item)
        for item in _list_from(source_alignment.get("mismatches"))
        if str(item).strip()
    ]
    rehearsal_blockers = [
        str(item)
        for item in _list_from(product_rehearsal.get("blockers"))
        if str(item).strip()
    ]
    rehearsal_exists = bool(product_rehearsal.get("exists")) and str(product_rehearsal.get("status") or "").strip() != "missing"
    role_rehearsal_failures = [
        str(item)
        for item in _list_from(role_rehearsal.get("failures"))
        if str(item).strip()
    ]
    role_rehearsal_ready = bool(role_rehearsal.get("ready"))
    role_rehearsal_report = _dict_from(role_rehearsal.get("selected_report"))
    role_rehearsal_roles = _dict_from(role_rehearsal.get("roles"))
    operator_a_role = _dict_from(role_rehearsal_roles.get("operator_a"))
    learner_b_role = _dict_from(role_rehearsal_roles.get("learner_b"))
    role_rehearsal_pass_count = _safe_int(role_rehearsal.get("pass_count"))
    role_rehearsal_total = _safe_int(role_rehearsal.get("total"))
    runtime_dependency_failures = [
        str(item)
        for item in _list_from(runtime_dependencies.get("failures"))
        if str(item).strip()
    ]
    runtime_dependencies_ready = bool(runtime_dependencies.get("ready"))
    qdrant_dependency = _dict_from(runtime_dependencies.get("qdrant"))
    promotion_ready = bool(llmwiki_promotion.get("ready"))
    official_ready = _rail_ready(llmwiki_promotion, "official") and official_chunks > 0 and official_code_blocks > 0
    customer_ready = _rail_ready(llmwiki_promotion, "customer") and customer_sources > 0 and customer_sections > 0
    runtime_ready = _rail_ready(llmwiki_promotion, "runtime")
    chat_ready = _rail_ready(llmwiki_promotion, "chat") and {"learn", "ops"}.issubset(mode_ids) and chat_total > 0 and chat_pass_count == chat_total
    validation_loop_ready = bool(validation_loop.get("ready"))
    validation_loop_status = str(validation_loop.get("status") or "missing").strip()
    validation_loop_metrics = _dict_from(validation_loop.get("metrics"))
    validation_loop_failures = [
        str(item)
        for item in _list_from(validation_loop.get("failures"))
        if str(item).strip()
    ]
    surya_policy = _dict_from(validation_loop.get("surya_policy"))
    surya_required = bool(surya_policy.get("required_for_llmwiki_runtime"))
    viewer_ready = official_ready and official_playbook_count > 0 and official_figures > 0
    library_ready = customer_ready and customer_playbook_count > 0 and user_corpus_chunk_count > 0
    factory_ready = custom_document_count > 0 or customer_playbook_count > 0
    harness_ready = promotion_ready and runtime_ready and validation_loop_ready and role_rehearsal_ready and runtime_dependencies_ready and not drift_mismatches and not surya_required
    surfaces = [
        _build_development_surface(
            surface_id="control_tower",
            title="Control Tower",
            route="/playbook-library/control-tower",
            ready=promotion_ready,
            acceptance="현재 checkout의 promotion report가 stale 없이 전체 LLMWiki 상태를 대표한다.",
            evidence=[
                f"status={llmwiki_promotion.get('status') or 'unknown'}",
                "HEAD matched" if selected_report.get("head_matches_current") else "HEAD mismatch",
            ],
            next_action="report가 stale이면 llmwiki-promotion을 다시 실행한다.",
            blockers=[] if promotion_ready else [*map(str, _list_from(llmwiki_promotion.get("failures")))],
        ),
        _build_development_surface(
            surface_id="studio_chat",
            title="Studio Chat",
            route="/studio",
            ready=chat_ready,
            acceptance="챗봇은 학습/운영 2모드만 노출하고, 두 모드 모두 live LLM/vector 검증을 통과한다.",
            evidence=[
                f"modes={', '.join(sorted(mode_ids)) or 'missing'}",
                f"chat live={chat_pass_count}/{chat_total}",
            ],
            next_action="질문 유형별 회귀 matrix를 늘려 모드별 hallucination guard를 강화한다.",
            blockers=[] if chat_ready else ["learn/ops mode contract or live chat matrix is incomplete"],
        ),
        _build_development_surface(
            surface_id="runtime_dependencies",
            title="Runtime Dependencies",
            route="/playbook-library/control-tower",
            ready=runtime_dependencies_ready,
            acceptance="챗봇 검색 근거 레이어는 재부팅 후에도 Qdrant collection까지 살아 있어야 하며, down 상태를 숨기지 않는다.",
            evidence=[
                f"qdrant={qdrant_dependency.get('status') or 'unknown'}",
                f"collection={qdrant_dependency.get('collection') or 'missing'}",
                f"url={qdrant_dependency.get('url') or 'unknown'}",
            ],
            next_action="Qdrant가 down/missing이면 Docker Desktop과 qdrant 서비스를 복구한 뒤 role-rehearsal을 다시 실행한다.",
            blockers=runtime_dependency_failures,
        ),
        _build_development_surface(
            surface_id="role_rehearsal",
            title="Operator A / Learner B Rehearsal",
            route="/studio",
            ready=role_rehearsal_ready,
            acceptance="운영자A와 학습자B live rehearsal가 현재 checkout의 챗봇 답변, citation, 공식/고객 근거 계약을 통과한다.",
            evidence=[
                f"status={role_rehearsal.get('status') or 'missing'}",
                f"cases={role_rehearsal_pass_count}/{role_rehearsal_total}",
                f"operator_a={_safe_int(operator_a_role.get('pass'))}/{_safe_int(operator_a_role.get('total'))} · learner_b={_safe_int(learner_b_role.get('pass'))}/{_safe_int(learner_b_role.get('total'))}",
                "HEAD matched" if role_rehearsal_report.get("head_matches_current") else "HEAD mismatch",
            ],
            next_action="역할 리허설이 stale/fail이면 role-rehearsal을 재실행하고 실패 case를 제품 회귀 테스트로 고정한다.",
            blockers=role_rehearsal_failures,
        ),
        _build_development_surface(
            surface_id="official_manual_wiki",
            title="Official Manual Wiki",
            route="/docs/ocp/4.20/ko/cli_tools/index.html?page_mode=multi",
            ready=official_ready,
            acceptance="공식 매뉴얼은 chunks, code blocks, figures를 보존한 Gold source로 재생산된다.",
            evidence=[
                f"{official_chunks:,} chunks",
                f"{official_code_blocks:,} code blocks",
                f"{official_figures:,} figures",
            ],
            next_action="영문 잔류와 용어 사전 적용률을 gate에 추가한다.",
            blockers=[] if official_ready else ["official gold contract is not ready"],
        ),
        _build_development_surface(
            surface_id="customer_operating_books",
            title="Customer Operating Books",
            route="/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html?page_mode=multi",
            ready=library_ready,
            acceptance="고객 PPT는 master 운영북과 private corpus에 합류해 챗봇 근거로 쓰인다.",
            evidence=[
                f"{customer_sources:,} source docs",
                f"{customer_sections:,} master sections",
                f"{customer_playbook_count:,} customer books",
                f"{user_corpus_chunk_count:,} private chunks",
            ],
            next_action="고객 문서별 Q/A smoke를 promotion report에 더 촘촘히 편입한다.",
            blockers=[] if library_ready else ["customer master or private corpus is incomplete"],
        ),
        _build_development_surface(
            surface_id="wiki_viewer",
            title="Wiki Viewer",
            route="/studio",
            ready=viewer_ready,
            acceptance="viewer는 single/multi 모드에서 목차, inline figure, code block이 읽히는 책 경험을 제공한다.",
            evidence=[
                f"{official_playbook_count:,} official playbooks",
                f"{official_figures:,} inline figures",
            ],
            next_action="브라우저 screenshot smoke를 대표 문서별로 자동 저장한다.",
            blockers=[] if viewer_ready else ["viewer evidence is missing official playbooks or figures"],
        ),
        _build_development_surface(
            surface_id="book_factory_repository",
            title="Book Factory & Repository",
            route="/playbook-library/repository",
            ready=factory_ready,
            acceptance="공식/사용자 원천은 수집, 검토, viewer 합류까지 하나의 흐름으로 추적된다.",
            evidence=[
                f"{custom_document_count:,} custom documents",
                f"{playable_asset_count:,} playable assets",
            ],
            next_action="원천 요청 backlog와 materialization 결과를 같은 품질 gate로 연결한다.",
            blockers=[] if factory_ready else ["no custom/customer material is visible to the factory"],
            watch=not factory_ready,
            required=False,
        ),
        _build_development_surface(
            surface_id="automation_harness",
            title="Automation Harness",
            route="/playbook-library/control-tower",
            ready=harness_ready,
            acceptance="promotion, runtime, source-of-truth drift가 한 명령/한 report에서 판정된다.",
            evidence=[
                "runtime ready" if runtime_ready else "runtime blocked",
                f"validation loop={validation_loop_status}",
                f"{len(drift_mismatches)} drift mismatches",
            ],
            next_action="llmwiki-loop를 반복 실행해 실패 원인을 report에 남긴다.",
            blockers=(
                drift_mismatches
                if drift_mismatches
                else (
                    []
                    if harness_ready
                    else [
                        *(validation_loop_failures or []),
                        *(role_rehearsal_failures or []),
                        *(runtime_dependency_failures or []),
                        "promotion/runtime/validation loop/role rehearsal contract is not ready",
                    ]
                )
            ),
        ),
        _build_development_surface(
            surface_id="surya_optional_boundary",
            title="Surya Optional Boundary",
            route="/playbook-library/control-tower",
            ready=not surya_required,
            acceptance="Surya OCR는 신규 이미지/OCR fallback 보조장치이며 기존 LLMWiki 검색/챗봇/뷰어 런타임 필수 의존성이 아니다.",
            evidence=[
                f"surya={surya_policy.get('status') or 'offline_allowed'}",
                f"loop iterations={_safe_int(validation_loop_metrics.get('completed_iterations'))}",
            ],
            next_action="신규 스캔 PDF나 이미지-only 문서 작업 때만 Qwen OCR 또는 Surya fallback을 별도 점검한다.",
            blockers=[] if not surya_required else ["Surya is incorrectly marked as required for LLMWiki runtime"],
            required=False,
        ),
        _build_development_surface(
            surface_id="product_rehearsal",
            title="Product Rehearsal",
            route="/playbook-library/control-tower",
            ready=rehearsal_exists and not rehearsal_blockers,
            acceptance="제품 시나리오 rehearsal가 현재 상태를 반영하고 blocker를 숨기지 않는다.",
            evidence=[
                f"status={product_rehearsal.get('status') or 'missing'}",
                f"{len(rehearsal_blockers)} blockers",
            ],
            next_action="Control Tower 시나리오를 실제 사용자 흐름 기준으로 재정렬한다.",
            blockers=rehearsal_blockers,
            watch=not rehearsal_blockers,
            required=False,
        ),
    ]
    required_surfaces = [item for item in surfaces if bool(item.get("required", True))]
    required_ready_count = sum(1 for item in required_surfaces if bool(item.get("ready")))
    blocked_count = sum(1 for item in surfaces if item.get("status") == "blocked")
    watch_count = sum(1 for item in surfaces if item.get("status") == "watch")
    ready_count = sum(1 for item in surfaces if bool(item.get("ready")))
    overall_ready = required_ready_count == len(required_surfaces) and blocked_count == 0
    return {
        "status": "ready" if overall_ready else "blocked" if blocked_count else "watch",
        "ready": overall_ready,
        "summary": {
            "ready_count": ready_count,
            "surface_count": len(surfaces),
            "required_ready_count": required_ready_count,
            "required_surface_count": len(required_surfaces),
            "blocked_count": blocked_count,
            "watch_count": watch_count,
        },
        "scope": {
            "included": [
                "Studio",
                "Playbook Library",
                "Control Tower",
                "Wiki Viewer",
                "Book Factory",
                "Customer Operating Books",
                "Official Manual Pipeline",
                "Chatbot Runtime",
            ],
            "excluded": [
                {
                    "id": "ops_console",
                    "title": "Ops Console",
                    "reason": "다른 팀원 담당 lane이므로 feat/dev-kugnus 고도화 범위에서 제외",
                    "route": "/ops-console",
                }
            ],
        },
        "surfaces": surfaces,
        "verification_commands": [
            "python -m unittest tests.test_chat_modes_contract tests.test_data_control_room_llmwiki",
            "python run_local_runtime.py role-rehearsal --ui-base-url http://127.0.0.1:8876",
            "python -m play_book_studio.cli llmwiki-promotion --ui-base-url http://127.0.0.1:8876",
            "npm run build",
        ],
    }


@lru_cache(maxsize=8)
def _build_data_control_room_payload_cached(
    root_dir: str,
    fingerprint: tuple[tuple[str, bool, int, int], ...],
) -> dict[str, object]:
    del fingerprint
    return _build_data_control_room_payload_uncached(Path(root_dir))


def build_data_control_room_payload(root_dir: str | Path) -> dict[str, object]:
    root = Path(root_dir).resolve()
    fingerprint = _data_control_room_cache_fingerprint(root)
    return _build_data_control_room_payload_cached(str(root), fingerprint)


def _build_data_control_room_payload_uncached(root_dir: str | Path) -> dict[str, object]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    gate_path = root / "reports" / "build_logs" / "foundry_runs" / "profiles" / "morning_gate" / "latest.json"
    gate_report = _safe_read_json(gate_path)
    verdict = gate_report.get("verdict") if isinstance(gate_report.get("verdict"), dict) else {}
    verdict_summary = verdict.get("summary") if isinstance(verdict.get("summary"), dict) else {}
    manifest = _safe_read_json(settings.source_manifest_path)
    manifest_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    manifest_by_slug = {str(entry.get("book_slug") or "").strip(): entry for entry in manifest_entries if isinstance(entry, dict) and str(entry.get("book_slug") or "").strip()}
    manifest_slugs = set(manifest_by_slug)
    expected_approved_runtime_count = len(manifest_by_slug)
    source_approval_payload = _job_payload(gate_report, "source_approval")
    gate_source_approval_report_path = _resolve_report_path(str(((source_approval_payload.get("output_targets") or {}).get("approval_report_path")) or _job_report_path(gate_report, "source_approval")))
    source_approval_report_path, source_approval_report = _select_report_candidate(gate_source_approval_report_path, settings.source_approval_report_path, summary_key="approved_ko_count", rows_key="books", expected_count=expected_approved_runtime_count)
    source_summary = source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {}
    source_book_count = _safe_int(source_summary.get("book_count") or len(source_approval_report.get("books") or []))
    selected_approved_runtime_count = _safe_int(source_summary.get("approved_ko_count") or verdict_summary.get("approved_runtime_count") or expected_approved_runtime_count)
    gate_translation_lane_path = _resolve_report_path(str(((source_approval_payload.get("output_targets") or {}).get("translation_lane_report_path")) or _job_report_path(gate_report, "synthesis_lane")))
    if source_approval_report_path is not None:
        translation_lane_path, translation_lane_report = _select_report_candidate(gate_translation_lane_path, settings.translation_lane_report_path, summary_key="active_queue_count", rows_key="active_queue", expected_count=max(source_book_count - selected_approved_runtime_count, 0))
    else:
        translation_lane_path, translation_lane_report = None, {}
    source_bundle_quality_payload = _job_payload(gate_report, "source_bundle_quality")
    retrieval_report = _safe_read_json(settings.retrieval_eval_report_path)
    answer_report = _safe_read_json(settings.answer_eval_report_path)
    ragas_report = _safe_read_json(settings.ragas_eval_report_path)
    runtime_report = _safe_read_json(settings.runtime_report_path)
    runtime_smoke_payload = _job_payload(gate_report, "runtime_smoke")
    source_books = source_approval_report.get("books") if isinstance(source_approval_report.get("books"), list) else []
    known_books = {str(book.get("book_slug") or "").strip(): book for book in source_books if isinstance(book, dict) and str(book.get("book_slug") or "").strip()}
    active_queue = translation_lane_report.get("active_queue") if isinstance(translation_lane_report.get("active_queue"), list) else []
    known_book_rows = _build_known_books_section(source_books, manifest_by_slug=manifest_by_slug)
    active_queue_rows = [_simplify_book(book) for book in active_queue if isinstance(book, dict)]
    high_value_focus = _build_high_value_focus(source_bundle_quality_payload, known_books=known_books, manifest_by_slug=manifest_by_slug)
    selected_chunks_path, chunk_rows, chunk_candidates = _candidate_file_rows(settings.chunks_path, settings.chunks_path)
    selected_playbook_dir, playbook_files, playbook_candidates = _candidate_playbook_dirs(*settings.playbook_book_dirs, expected_count=len(manifest_by_slug))
    customer_pack_files = iter_customer_pack_book_payload_paths(settings.customer_pack_books_dir)
    all_customer_pack_draft_records = {
        record.draft_id: record
        for record in CustomerPackDraftStore(root).list()
        if str(record.draft_id or "").strip()
    }
    customer_pack_read_boundaries = {
        draft_id: load_customer_pack_read_boundary(root, draft_id)
        for draft_id in sorted(all_customer_pack_draft_records)
    }
    readable_customer_pack_draft_ids = {
        draft_id
        for draft_id, summary in customer_pack_read_boundaries.items()
        if bool(summary.get("read_allowed", False))
    }
    customer_pack_draft_records = {
        draft_id: record
        for draft_id, record in all_customer_pack_draft_records.items()
        if draft_id in readable_customer_pack_draft_ids
    }
    customer_pack_corpus_rows = load_customer_pack_private_chunk_rows(root, draft_records_by_id=customer_pack_draft_records)
    all_playbook_files: list[Path] = []
    seen_playbook_paths: set[str] = set()
    for path in [*playbook_files, *customer_pack_files]:
        normalized_path = str(path)
        if normalized_path not in seen_playbook_paths:
            seen_playbook_paths.add(normalized_path)
            all_playbook_files.append(path)
    corpus_books = _aggregate_corpus_books(chunk_rows, manifest_by_slug=manifest_by_slug, known_books=known_books, grade_label=_grade_label)
    manualbooks = _aggregate_playbooks(all_playbook_files, manifest_by_slug=manifest_by_slug, known_books=known_books, grade_label=_grade_label, safe_read_json=_safe_read_json)
    manualbooks = _apply_customer_pack_runtime_truth(manualbooks, draft_records_by_id=customer_pack_draft_records)
    manualbooks = _filter_readable_customer_pack_books(
        manualbooks,
        readable_draft_ids=readable_customer_pack_draft_ids,
    )
    user_library_corpus_books = _aggregate_corpus_books(customer_pack_corpus_rows, manifest_by_slug={}, known_books={}, grade_label=_grade_label)
    user_library_corpus_books = _apply_customer_pack_runtime_truth(user_library_corpus_books, draft_records_by_id=customer_pack_draft_records)
    combined_corpus_by_slug = {
        str(book.get("book_slug") or "").strip(): book
        for book in [*corpus_books, *user_library_corpus_books]
        if str(book.get("book_slug") or "").strip()
    }
    for book in user_library_corpus_books:
        draft_id = str(book.get("draft_id") or "").strip()
        if not draft_id:
            continue
        primary_viewer_path = f"/playbooks/customer-packs/{draft_id}/index.html"
        book_viewer_path = str(book.get("viewer_path") or "").split("#", 1)[0].strip()
        if draft_id not in combined_corpus_by_slug or book_viewer_path == primary_viewer_path:
            combined_corpus_by_slug[draft_id] = book
    manualbooks = _attach_corpus_status(manualbooks, corpus_by_slug=combined_corpus_by_slug)
    community_source_runtime_books = _apply_viewer_path_fallback(
        [book for book in manualbooks if _book_is_community_runtime(book)],
        root=root,
    )
    private_customer_manualbooks = [
        book for book in manualbooks if not _book_is_community_runtime(book)
    ]
    derived_playbook_family_statuses = {
        family: _derived_family_status(
            family,
            [
                book
                for book in private_customer_manualbooks
                if str(book.get("source_type") or "").strip() == family
            ],
        )
        for family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    derived_playbooks = [book for family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES for book in derived_playbook_family_statuses[family]["books"]]
    core_corpus_books = [book for book in corpus_books if str(book.get("book_slug") or "").strip() in manifest_slugs]
    extra_corpus_books = [book for book in corpus_books if str(book.get("book_slug") or "").strip() not in manifest_slugs]
    topic_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[TOPIC_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    operation_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[OPERATION_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    troubleshooting_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    policy_overlay_books = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[POLICY_OVERLAY_BOOK_SOURCE_TYPE]["books"]), root=root)
    synthesized_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    core_manualbooks = [book for book in private_customer_manualbooks if str(book.get("source_type") or "").strip() not in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET and str(book.get("book_slug") or "").strip() in manifest_slugs]
    extra_manualbooks = [book for book in private_customer_manualbooks if str(book.get("source_type") or "").strip() not in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET and str(book.get("book_slug") or "").strip() not in manifest_slugs]
    user_library_books = _apply_viewer_path_fallback([book for book in extra_manualbooks if _book_is_private_customer_runtime(book)], root=root)
    customer_pack_runtime_books = _apply_viewer_path_fallback([book for book in private_customer_manualbooks if _book_is_private_customer_runtime(book)], root=root)
    user_library_corpus_chunk_count = sum(int(book.get("chunk_count") or 0) for book in user_library_corpus_books)
    grade_breakdown_counter = Counter(_grade_label(book) for book in source_books)
    gold_books = [_simplify_book(book) for slug in manifest_by_slug for book in [known_books.get(slug)] if isinstance(book, dict) and _is_gold_book(book)]
    materialized_corpus_slugs = {str(row.get("book_slug") or "").strip() for row in chunk_rows if str(row.get("book_slug") or "").strip()}
    materialized_core_corpus_slugs = materialized_corpus_slugs & manifest_slugs
    extra_materialized_corpus_slugs = materialized_corpus_slugs - manifest_slugs
    materialized_topic_playbook_slugs = set(derived_playbook_family_statuses[TOPIC_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_operation_playbook_slugs = set(derived_playbook_family_statuses[OPERATION_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_troubleshooting_playbook_slugs = set(derived_playbook_family_statuses[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_policy_overlay_book_slugs = set(derived_playbook_family_statuses[POLICY_OVERLAY_BOOK_SOURCE_TYPE]["slugs"])
    materialized_synthesized_playbook_slugs = set(derived_playbook_family_statuses[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_derived_playbook_slugs = materialized_topic_playbook_slugs | materialized_operation_playbook_slugs | materialized_troubleshooting_playbook_slugs | materialized_policy_overlay_book_slugs | materialized_synthesized_playbook_slugs
    materialized_manualbook_slugs = {
        str(book.get("book_slug") or "").strip()
        for book in manualbooks
        if str(book.get("book_slug") or "").strip()
        and str(book.get("source_type") or "").strip() not in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET
    }
    materialized_core_manualbook_slugs = materialized_manualbook_slugs & manifest_slugs
    extra_materialized_manualbook_slugs = materialized_manualbook_slugs - manifest_slugs
    buyer_scope = source_bundle_quality_payload.get("buyer_scope") if isinstance(source_bundle_quality_payload.get("buyer_scope"), dict) else {}
    raw_manual_count = int(buyer_scope.get("raw_manual_count") or len(manifest_by_slug))
    playable_asset_count = (
        len(core_manualbooks)
        + len(extra_manualbooks)
        + len(derived_playbooks)
        + len(community_source_runtime_books)
    )
    playable_asset_multiplication = {
        "raw_manual_count": raw_manual_count,
        "playable_asset_count": playable_asset_count,
        "delta_vs_raw_manual_count": playable_asset_count - raw_manual_count,
        "ratio_vs_raw_manual_count": round(playable_asset_count / raw_manual_count, 4) if raw_manual_count > 0 else 0.0,
    }
    manual_book_library = _build_manual_book_library(core_manualbooks, extra_manualbooks)
    playbook_library = _build_playbook_library(derived_playbook_family_statuses)
    custom_documents = _build_custom_document_bucket(root)
    gold_candidate_books = _build_gold_candidate_book_bucket(root)
    approved_wiki_runtime_books = _build_approved_wiki_runtime_book_bucket(root, translation_lane_report=translation_lane_report)
    navigation_backlog = _build_navigation_backlog_bucket(root)
    wiki_usage_signals = _build_wiki_usage_signal_bucket(root)
    product_gate = _build_product_gate_bucket(root)
    product_rehearsal = _build_product_rehearsal_summary(root)
    role_rehearsal = _build_role_rehearsal_control_status(root)
    runtime_dependencies = _build_runtime_dependency_status(root)
    buyer_packet_bundle = _build_buyer_packet_bundle_bucket(root)
    release_candidate_freeze = _build_release_candidate_freeze_summary(root)
    llmwiki_promotion = _build_llmwiki_promotion_control_status(root)
    llmwiki_validation_loop = _build_llmwiki_validation_loop_control_status(root)
    llmwiki_evolution_gate = _build_llmwiki_evolution_gate_control_status(root)
    llmwiki_contextual_enrichment = _build_llmwiki_contextual_enrichment_control_status(root)
    chunk_candidate_counts = {candidate["row_count"] for candidate in chunk_candidates if candidate.get("exists")}
    playbook_candidate_counts = {candidate["file_count"] for candidate in playbook_candidates if candidate.get("exists")}
    canonical_grade_source = {
        "name": "source_approval_report",
        "path": str(source_approval_report_path or ""),
        "exists": bool(source_approval_report_path and source_approval_report_path.exists()),
        "rule": "Source approval report is the canonical grade source. Release grade is normalized to Gold / Silver / Bronze while raw workflow states remain in content_status, review_status, and translation_status.",
        "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {},
    }
    source_of_truth_drift = _build_source_of_truth_drift(
        gate_report=gate_report,
        source_approval_report=source_approval_report,
        translation_lane_report=translation_lane_report,
        manifest_path=settings.source_manifest_path,
        selected_chunks_path=selected_chunks_path,
        chunk_candidates=chunk_candidates,
        selected_playbook_dir=selected_playbook_dir,
        playbook_candidates=playbook_candidates,
        source_approval_report_path=source_approval_report_path,
        translation_lane_path=translation_lane_path,
    )
    answer_overall = answer_report.get("overall") if isinstance(answer_report.get("overall"), dict) else {}
    ragas_overall = ragas_report.get("overall") if isinstance(ragas_report.get("overall"), dict) else {}
    runtime_app = runtime_report.get("app") if isinstance(runtime_report.get("app"), dict) else {}
    runtime_runtime = runtime_report.get("runtime") if isinstance(runtime_report.get("runtime"), dict) else {}
    runtime_probes = runtime_report.get("probes") if isinstance(runtime_report.get("probes"), dict) else {}
    role_rehearsal_report_path_text = str(
        _dict_from(role_rehearsal.get("selected_report")).get("path") or ""
    ).strip()
    report_paths = {
        "gate": str(gate_path),
        "source_approval": str(source_approval_report_path or ""),
        "translation_lane": str(translation_lane_path or ""),
        "retrieval_eval": str(settings.retrieval_eval_report_path),
        "answer_eval": str(settings.answer_eval_report_path),
        "ragas_eval": str(settings.ragas_eval_report_path),
        "runtime": str(settings.runtime_report_path),
        "role_rehearsal": role_rehearsal_report_path_text,
        "llmwiki_evolution_gate": str(_dict_from(llmwiki_evolution_gate.get("selected_report")).get("path") or ""),
        "llmwiki_contextual_enrichment": str(
            _dict_from(llmwiki_contextual_enrichment.get("selected_report")).get("path") or ""
        ),
    }
    report_snapshots = {
        "morning_gate": _path_snapshot(gate_path),
        "source_approval": _path_snapshot_for_optional(source_approval_report_path),
        "translation_lane": _path_snapshot_for_optional(translation_lane_path),
        "retrieval_eval": _path_snapshot(settings.retrieval_eval_report_path),
        "answer_eval": _path_snapshot(settings.answer_eval_report_path),
        "ragas_eval": _path_snapshot(settings.ragas_eval_report_path),
        "runtime_report": _path_snapshot(settings.runtime_report_path),
        "role_rehearsal": _path_snapshot_for_optional(
            Path(role_rehearsal_report_path_text) if role_rehearsal_report_path_text else None
        ),
        "llmwiki_evolution_gate": _path_snapshot_for_optional(
            Path(str(_dict_from(llmwiki_evolution_gate.get("selected_report")).get("path") or ""))
            if str(_dict_from(llmwiki_evolution_gate.get("selected_report")).get("path") or "").strip()
            else None
        ),
        "llmwiki_contextual_enrichment": _path_snapshot_for_optional(
            Path(str(_dict_from(llmwiki_contextual_enrichment.get("selected_report")).get("path") or ""))
            if str(_dict_from(llmwiki_contextual_enrichment.get("selected_report")).get("path") or "").strip()
            else None
        ),
    }
    development_control = _build_development_control_status(
        llmwiki_promotion=llmwiki_promotion,
        llmwiki_validation_loop=llmwiki_validation_loop,
        official_playbook_count=len(core_manualbooks),
        customer_playbook_count=len(customer_pack_runtime_books),
        user_corpus_chunk_count=user_library_corpus_chunk_count,
        custom_document_count=int(custom_documents.get("source_count") or len(custom_documents.get("books") or [])),
        playable_asset_count=playable_asset_count,
        source_of_truth_drift=source_of_truth_drift,
        product_rehearsal=product_rehearsal,
        role_rehearsal=role_rehearsal,
        runtime_dependencies=runtime_dependencies,
    )
    return {
        "generated_at": _iso_now(),
        "active_pack": {
            "app_id": settings.app_id,
            "app_label": settings.app_label,
            "pack_id": settings.active_pack_id,
            "pack_label": settings.active_pack_label,
            "ocp_version": settings.ocp_version,
            "docs_language": settings.docs_language,
            "viewer_path_prefix": settings.viewer_path_prefix,
        },
        "summary": {
            "gate_status": str(verdict.get("status") or "unknown"),
            "release_blocking": bool(verdict.get("release_blocking")),
            "approved_runtime_count": selected_approved_runtime_count,
            "known_book_count": int(source_approval_report.get("summary", {}).get("book_count") or len(source_books)),
            "gold_book_count": len(gold_books),
            "known_books_count": len(known_book_rows),
            "queue_count": len(active_queue_rows),
            "active_queue_count": len(active_queue_rows),
            "high_value_focus_count": int(high_value_focus.get("count") or 0),
            "blocked_count": int(source_approval_report.get("summary", {}).get("blocked_count") or 0),
            "raw_manual_count": raw_manual_count,
            "chunk_count": len(chunk_rows),
            "corpus_book_count": len(materialized_core_corpus_slugs),
            "core_corpus_book_count": len(materialized_core_corpus_slugs),
            "manualbook_count": len(materialized_core_manualbook_slugs),
            "core_manualbook_count": len(materialized_core_manualbook_slugs),
            "customer_pack_runtime_book_count": len(customer_pack_runtime_books),
            "community_source_runtime_book_count": len(community_source_runtime_books),
            "user_library_book_count": len(user_library_books),
            "user_library_corpus_book_count": len(user_library_corpus_books),
            "user_library_corpus_chunk_count": user_library_corpus_chunk_count,
            "custom_document_count": int(custom_documents.get("source_count") or len(custom_documents.get("books") or [])),
            "custom_document_slot_count": int(custom_documents.get("slot_count") or len(custom_documents.get("books") or [])),
            "gold_candidate_book_count": len(gold_candidate_books.get("books") or []),
            "approved_wiki_runtime_book_count": len(approved_wiki_runtime_books.get("books") or []),
            "wiki_navigation_backlog_count": len(navigation_backlog.get("books") or []),
            "wiki_usage_signal_count": len(wiki_usage_signals.get("books") or []),
            "product_gate_count": len(product_gate.get("books") or []),
            "buyer_packet_bundle_count": len(buyer_packet_bundle.get("books") or []),
            "release_candidate_freeze_ready": bool(release_candidate_freeze.get("exists")),
            "llmwiki_promotion_ready": bool(llmwiki_promotion.get("ready")),
            "llmwiki_promotion_status": str(llmwiki_promotion.get("status") or "unknown"),
            "llmwiki_promotion_report_stale": bool((_dict_from(llmwiki_promotion.get("selected_report"))).get("stale")),
            "llmwiki_promotion_failure_count": len(_list_from(llmwiki_promotion.get("failures"))),
            "llmwiki_validation_loop_ready": bool(llmwiki_validation_loop.get("ready")),
            "llmwiki_validation_loop_status": str(llmwiki_validation_loop.get("status") or "unknown"),
            "llmwiki_validation_loop_failure_count": len(_list_from(llmwiki_validation_loop.get("failures"))),
            "llmwiki_evolution_gate_ready": bool(llmwiki_evolution_gate.get("ready")),
            "llmwiki_evolution_gate_status": str(llmwiki_evolution_gate.get("status") or "unknown"),
            "llmwiki_evolution_gate_failure_count": len(_list_from(llmwiki_evolution_gate.get("failures"))),
            "llmwiki_evolution_backwrite_candidate_count": _safe_int(
                _dict_from(llmwiki_evolution_gate.get("metrics")).get("backwrite_candidates")
            ),
            "llmwiki_evolution_quality_blocker_count": _safe_int(
                _dict_from(llmwiki_evolution_gate.get("metrics")).get("quality_blockers")
            ),
            "llmwiki_contextual_enrichment_ready": bool(llmwiki_contextual_enrichment.get("ready")),
            "llmwiki_contextual_enrichment_status": str(
                llmwiki_contextual_enrichment.get("status") or "unknown"
            ),
            "llmwiki_contextual_enrichment_failure_count": len(
                _list_from(llmwiki_contextual_enrichment.get("failures"))
            ),
            "llmwiki_contextual_enrichment_row_count": _safe_int(
                _dict_from(llmwiki_contextual_enrichment.get("metrics")).get("row_count")
            ),
            "role_rehearsal_ready": bool(role_rehearsal.get("ready")),
            "role_rehearsal_status": str(role_rehearsal.get("status") or "unknown"),
            "role_rehearsal_pass_count": _safe_int(role_rehearsal.get("pass_count")),
            "role_rehearsal_total": _safe_int(role_rehearsal.get("total")),
            "role_rehearsal_failure_count": len(_list_from(role_rehearsal.get("failures"))),
            "runtime_dependencies_ready": bool(runtime_dependencies.get("ready")),
            "runtime_dependencies_status": str(runtime_dependencies.get("status") or "unknown"),
            "runtime_dependencies_failure_count": len(_list_from(runtime_dependencies.get("failures"))),
            "development_control_status": str(development_control.get("status") or "unknown"),
            "development_control_ready": bool(development_control.get("ready")),
            "official_gold_ok": _promotion_contract_ok({"summary": {"contracts": _dict_from(llmwiki_promotion.get("contracts"))}}, "official_gold"),
            "customer_master_ok": _promotion_contract_ok({"summary": {"contracts": _dict_from(llmwiki_promotion.get("contracts"))}}, "customer_master"),
            "runtime_live_ok": _promotion_contract_ok({"summary": {"contracts": _dict_from(llmwiki_promotion.get("contracts"))}}, "runtime_report"),
            "runtime_maintenance_ok": _promotion_contract_ok({"summary": {"contracts": _dict_from(llmwiki_promotion.get("contracts"))}}, "runtime_maintenance"),
            "chat_matrix_ok": _promotion_contract_ok({"summary": {"contracts": _dict_from(llmwiki_promotion.get("contracts"))}}, "chat_matrix"),
            "product_gate_pass_rate": product_rehearsal.get("critical_scenario_pass_rate"),
            "topic_playbook_count": len(topic_playbooks),
            "operation_playbook_count": len(operation_playbooks),
            "troubleshooting_playbook_count": len(troubleshooting_playbooks),
            "policy_overlay_book_count": len(policy_overlay_books),
            "synthesized_playbook_count": len(synthesized_playbooks),
            "derived_playbook_count": len(derived_playbooks),
            "playable_asset_count": playable_asset_count,
            "extra_corpus_book_count": len(extra_materialized_corpus_slugs),
            "extra_manualbook_count": len(extra_materialized_manualbook_slugs),
            "retrieval_hit_at_1": retrieval_report.get("overall", {}).get("book_hit_at_1"),
            "answer_pass_rate": answer_overall.get("pass_rate"),
            "citation_precision": answer_overall.get("avg_citation_precision"),
            "ragas_faithfulness": ragas_overall.get("faithfulness"),
            "canonical_grade_source": canonical_grade_source["name"],
        },
        "gate": {
            "path": str(gate_path),
            "run_at": str(gate_report.get("run_at") or ""),
            "status": str(verdict.get("status") or "unknown"),
            "release_blocking": bool(verdict.get("release_blocking")),
            "reasons": list(verdict.get("reasons") or []),
            "summary": {
                "approved_runtime_count": int(verdict_summary.get("approved_runtime_count") or len(manifest_by_slug)),
                "translation_ready_count": int(verdict_summary.get("translation_ready_count") or 0),
                "manual_review_ready_count": int(verdict_summary.get("manual_review_ready_count") or 0),
                "high_value_issue_count": int(verdict_summary.get("high_value_issue_count") or 0),
                "source_expansion_needed_count": int(verdict_summary.get("source_expansion_needed_count") or 0),
                "failed_validation_checks": list(verdict_summary.get("failed_validation_checks") or []),
                "failed_data_quality_checks": list(verdict_summary.get("failed_data_quality_checks") or []),
            },
        },
        "grading": {
            "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {},
            "grade_breakdown": [{"grade": grade, "count": count} for grade, count in sorted(grade_breakdown_counter.items(), key=lambda item: (-item[1], item[0]))],
            "gold_books": gold_books,
            "queue_books": active_queue_rows,
        },
        "evaluations": {
            "retrieval": {**_summarize_eval(retrieval_report), "path": str(settings.retrieval_eval_report_path)},
            "answer": {**_summarize_eval(answer_report), "path": str(settings.answer_eval_report_path)},
            "ragas": {**_summarize_eval(ragas_report), "path": str(settings.ragas_eval_report_path)},
            "runtime": {"path": str(settings.runtime_report_path), "app": runtime_app, "runtime": runtime_runtime, "probes": runtime_probes, "latest_smoke": runtime_smoke_payload},
        },
        "source_of_truth": {
            "artifacts_dir": str(settings.artifacts_dir),
            "manifest": _path_snapshot(settings.source_manifest_path),
            "chunks": {"selected_path": str(selected_chunks_path) if selected_chunks_path else "", "candidates": chunk_candidates, "drift_detected": len(chunk_candidate_counts) > 1},
            "playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "candidates": playbook_candidates, "drift_detected": len(playbook_candidate_counts) > 1},
        },
        "canonical_grade_source": canonical_grade_source,
        "source_of_truth_drift": source_of_truth_drift,
        "corpus": {"selected_path": str(selected_chunks_path) if selected_chunks_path else "", "books": core_corpus_books},
        "manualbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": core_manualbooks},
        "customer_pack_runtime_books": {"selected_dir": str(settings.customer_pack_books_dir.resolve()), "books": customer_pack_runtime_books},
        "community_source_runtime_books": {"selected_dir": str(settings.customer_pack_books_dir.resolve()), "books": community_source_runtime_books},
        "user_library_books": {"selected_dir": str(settings.customer_pack_books_dir.resolve()), "books": user_library_books},
        "user_library_corpus": {"selected_dir": str(settings.customer_pack_corpus_dir.resolve()), "books": user_library_corpus_books},
        "custom_documents": custom_documents,
        "gold_candidate_books": gold_candidate_books,
        "approved_wiki_runtime_books": approved_wiki_runtime_books,
        "wiki_navigation_backlog": navigation_backlog,
        "wiki_usage_signals": wiki_usage_signals,
        "product_gate": product_gate,
        "buyer_packet_bundle": buyer_packet_bundle,
        "release_candidate_freeze": release_candidate_freeze,
        "product_rehearsal": product_rehearsal,
        "role_rehearsal": role_rehearsal,
        "runtime_dependencies": runtime_dependencies,
        "llmwiki_promotion": llmwiki_promotion,
        "llmwiki_validation_loop": llmwiki_validation_loop,
        "llmwiki_evolution_gate": llmwiki_evolution_gate,
        "llmwiki_contextual_enrichment": llmwiki_contextual_enrichment,
        "development_control": development_control,
        "manual_book_library": manual_book_library,
        "topic_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": topic_playbooks},
        "operation_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": operation_playbooks},
        "troubleshooting_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": troubleshooting_playbooks},
        "policy_overlay_books": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": policy_overlay_books},
        "synthesized_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": synthesized_playbooks},
        "derived_playbook_families": derived_playbook_family_statuses,
        "playbook_library": playbook_library,
        "materialization": {
            "manifest_book_count": len(manifest_by_slug),
            "gold_book_count": len(gold_books),
            "corpus_book_count": len(core_corpus_books),
            "core_corpus_book_count": len(core_corpus_books),
            "manualbook_book_count": len(core_manualbooks),
            "core_manualbook_book_count": len(core_manualbooks),
            "customer_pack_runtime_book_count": len(customer_pack_runtime_books),
            "community_source_runtime_book_count": len(community_source_runtime_books),
            "user_library_book_count": len(user_library_books),
            "user_library_corpus_book_count": len(user_library_corpus_books),
            "user_library_corpus_chunk_count": user_library_corpus_chunk_count,
            "custom_document_count": int(custom_documents.get("source_count") or len(custom_documents.get("books") or [])),
            "custom_document_slot_count": int(custom_documents.get("slot_count") or len(custom_documents.get("books") or [])),
            "topic_playbook_book_count": len(topic_playbooks),
            "operation_playbook_book_count": len(operation_playbooks),
            "troubleshooting_playbook_book_count": len(troubleshooting_playbooks),
            "policy_overlay_book_book_count": len(policy_overlay_books),
            "synthesized_playbook_book_count": len(synthesized_playbooks),
            "derived_playbook_book_count": len(derived_playbooks),
            "playable_asset_count": playable_asset_count,
            "playable_asset_multiplication": playable_asset_multiplication,
            "extra_corpus_book_count": len(extra_corpus_books),
            "extra_manualbook_book_count": len(extra_manualbooks),
            "materialized_corpus_book_count": len(materialized_core_corpus_slugs),
            "materialized_manualbook_book_count": len(materialized_core_manualbook_slugs),
            "materialized_topic_playbook_count": len(materialized_topic_playbook_slugs),
            "materialized_operation_playbook_count": len(materialized_operation_playbook_slugs),
            "materialized_troubleshooting_playbook_count": len(materialized_troubleshooting_playbook_slugs),
            "materialized_policy_overlay_book_count": len(materialized_policy_overlay_book_slugs),
            "materialized_synthesized_playbook_count": len(materialized_synthesized_playbook_slugs),
            "materialized_derived_playbook_count": len(materialized_derived_playbook_slugs),
            "extra_corpus_books": sorted(extra_materialized_corpus_slugs),
            "extra_manualbook_books": sorted(extra_materialized_manualbook_slugs),
            "missing_corpus_books": sorted(manifest_slugs - materialized_core_corpus_slugs),
            "missing_manualbook_books": sorted(manifest_slugs - materialized_core_manualbook_slugs),
            "logical_counts_match": len(manifest_by_slug) == len(core_corpus_books) == len(core_manualbooks),
            "counts_match": len(manifest_by_slug) == len(gold_books) == len(materialized_core_corpus_slugs) == len(materialized_core_manualbook_slugs),
        },
        "known_books": known_book_rows,
        "active_queue": active_queue_rows,
        "high_value_focus": high_value_focus,
        "report_paths": report_paths,
        "gold_books": gold_books,
        "corpus_book_status": core_corpus_books,
        "extra_corpus_book_status": extra_corpus_books,
        "manualbook_status": core_manualbooks,
        "extra_manualbook_status": extra_manualbooks,
        "user_library_corpus_status": user_library_corpus_books,
        "topic_playbook_status": topic_playbooks,
        "operation_playbook_status": operation_playbooks,
        "troubleshooting_playbook_status": troubleshooting_playbooks,
        "policy_overlay_book_status": policy_overlay_books,
        "synthesized_playbook_status": synthesized_playbooks,
        "recent_report_paths": report_snapshots,
        "reports": {
            "gate": {"status": str(verdict.get("status") or "unknown"), "summary": verdict_summary},
            "source_approval": {"path": str(source_approval_report_path or ""), "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {}},
            "translation_lane": {"path": str(translation_lane_path or ""), "summary": translation_lane_report.get("summary") if isinstance(translation_lane_report.get("summary"), dict) else {}},
            "retrieval": _summarize_eval(retrieval_report),
            "answer": _summarize_eval(answer_report),
            "ragas": _summarize_eval(ragas_report),
            "runtime": runtime_smoke_payload,
        },
    }


__all__ = ["build_data_control_room_payload"]
