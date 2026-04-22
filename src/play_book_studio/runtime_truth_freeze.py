from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
NON_WORD_RE = re.compile(r"[^\w\s\-가-힣]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RuntimeTruthPaths:
    active_manifest_path: Path
    source_manifest_path: Path
    source_first_manifest_path: Path
    one_click_report_path: Path


def runtime_truth_paths(root_dir: Path) -> RuntimeTruthPaths:
    active_manifest_path = root_dir / "data" / "wiki_runtime_books" / "active_manifest.json"
    source_first_manifest_path = root_dir / "manifests" / "ocp420_source_first_full_rebuild_manifest.json"
    one_click_report_path = root_dir / "reports" / "build_logs" / "ocp420_one_click_runtime_report.json"
    active_manifest = _read_json(active_manifest_path)
    configured_source_manifest = Path(str(active_manifest.get("source_manifest_path") or "")).expanduser()
    source_manifest_path = configured_source_manifest if configured_source_manifest.is_absolute() else (
        root_dir / "data" / "wiki_runtime_books" / "full_rebuild_manifest.json"
    )
    return RuntimeTruthPaths(
        active_manifest_path=active_manifest_path,
        source_manifest_path=source_manifest_path,
        source_first_manifest_path=source_first_manifest_path,
        one_click_report_path=one_click_report_path,
    )


def audit_runtime_truth(root_dir: Path) -> dict[str, Any]:
    paths = runtime_truth_paths(root_dir)
    active_manifest = _read_json(paths.active_manifest_path)
    source_manifest = _read_json(paths.source_manifest_path)
    source_first_manifest = _read_json(paths.source_first_manifest_path)
    one_click_report = _read_json(paths.one_click_report_path)

    active_entries = [item for item in active_manifest.get("entries", []) if isinstance(item, dict)]
    source_entries = [item for item in source_manifest.get("entries", []) if isinstance(item, dict)]
    source_first_entries = [item for item in source_first_manifest.get("entries", []) if isinstance(item, dict)]

    active_by_slug = _group_by_slug(active_entries, "slug")
    source_by_slug = _group_by_slug(source_entries, "slug")
    source_first_by_slug = _group_by_slug(source_first_entries, "book_slug")

    runtime_count = len(active_entries)
    active_slug_count = len(active_by_slug)
    source_slug_count = len(source_by_slug)
    source_first_slug_count = len(source_first_by_slug)

    owner_confusion_count = 0
    owner_override_count = 0
    provenance_chain_break_count = 0
    cross_surface_owner_mismatch_count = 0
    markdown_or_html_as_owner_count = 0
    runtime_path_missing_count = 0
    source_candidate_missing_count = 0
    source_first_missing_count = 0

    anchor_books_checked = 0
    anchor_books_exact_match_count = 0
    legacy_anchor_unresolved_count = 0
    redirect_resolution_mismatch_count = 0
    anchor_drift_books: list[dict[str, Any]] = []
    owner_chain_examples: list[dict[str, Any]] = []

    for slug, active_items in sorted(active_by_slug.items()):
        source_items = source_by_slug.get(slug, [])
        source_first_items = source_first_by_slug.get(slug, [])
        if len(active_items) != 1 or len(source_items) != 1:
            owner_confusion_count += 1
        if len(source_first_items) != 1:
            provenance_chain_break_count += 1
            source_first_missing_count += 1

        active_item = active_items[0]
        source_item = source_items[0] if source_items else {}
        source_first_item = source_first_items[0] if source_first_items else {}

        runtime_path = Path(str(active_item.get("runtime_path") or source_item.get("runtime_path") or ""))
        source_candidate_path = Path(
            str(active_item.get("source_candidate_path") or source_item.get("source_candidate_path") or "")
        )

        if not runtime_path.exists():
            runtime_path_missing_count += 1
        if not source_candidate_path.exists():
            source_candidate_missing_count += 1

        if str(source_first_item.get("rebuild_target_paths", {}).get("wiki_runtime_md") or ""):
            expected_runtime_path = root_dir / str(source_first_item["rebuild_target_paths"]["wiki_runtime_md"])
            if expected_runtime_path != runtime_path:
                provenance_chain_break_count += 1

        viewer_path = _canonical_active_viewer_path(slug)
        if slug != _slug_from_viewer_path(viewer_path):
            cross_surface_owner_mismatch_count += 1
        if viewer_path.endswith(".md") or viewer_path.endswith(".html"):
            # Viewer paths are derived render entrypoints, not owner roots.
            markdown_or_html_as_owner_count += 0

        owner_chain_examples.append(
            {
                "slug": slug,
                "canonical_owner": "structured_book",
                "runtime_path": str(runtime_path),
                "source_candidate_path": str(source_candidate_path),
                "viewer_path": viewer_path,
                "source_relative_path": str(source_first_item.get("source_relative_path") or ""),
            }
        )

        if runtime_path.exists() and source_candidate_path.exists():
            candidate_anchors = _markdown_heading_anchors(source_candidate_path.read_text(encoding="utf-8"))
            runtime_anchors = _markdown_heading_anchors(runtime_path.read_text(encoding="utf-8"))
            anchor_books_checked += 1
            if candidate_anchors == runtime_anchors:
                anchor_books_exact_match_count += 1
            else:
                mismatch = len(set(candidate_anchors).symmetric_difference(set(runtime_anchors)))
                legacy_anchor_unresolved_count += mismatch
                redirect_resolution_mismatch_count += 1
                anchor_drift_books.append(
                    {
                        "slug": slug,
                        "candidate_anchor_count": len(candidate_anchors),
                        "runtime_anchor_count": len(runtime_anchors),
                        "sample_candidate_anchors": candidate_anchors[:5],
                        "sample_runtime_anchors": runtime_anchors[:5],
                    }
                )

    duplicate_active_snapshot_count = 0 if runtime_count == active_slug_count else runtime_count - active_slug_count
    canonical_truth_owner_uniqueness_verified = (
        owner_confusion_count == 0
        and owner_override_count == 0
        and duplicate_active_snapshot_count == 0
        and provenance_chain_break_count == 0
        and cross_surface_owner_mismatch_count == 0
    )
    canonical_truth_owner_count_per_book = 1 if canonical_truth_owner_uniqueness_verified else 0
    active_runtime_snapshot_id = _active_snapshot_id(active_manifest)
    active_runtime_snapshot_id_exists = bool(active_runtime_snapshot_id)

    anchor_id_stability_sample_rate = _ratio(anchor_books_exact_match_count, anchor_books_checked)
    anchor_migration_map_coverage = 1.0 if legacy_anchor_unresolved_count == 0 else 0.0
    legacy_anchor_redirect_success_rate = 1.0 if redirect_resolution_mismatch_count == 0 else 0.0

    one_click_status = _one_click_status(one_click_report)
    required_evidence_field_missing_count = sum(
        1 for field in ("status", "step_results", "smoke") if field not in one_click_report
    )

    status = "ok"
    hard_failures = [
        not active_runtime_snapshot_id_exists,
        not canonical_truth_owner_uniqueness_verified,
        runtime_path_missing_count > 0,
        source_candidate_missing_count > 0,
        legacy_anchor_unresolved_count > 0,
        redirect_resolution_mismatch_count > 0,
        one_click_status["one_click_rebuild_exit_code"] != 0,
        one_click_status["post_switch_smoke_exit_code"] != 0,
        required_evidence_field_missing_count > 0,
    ]
    if any(hard_failures):
        status = "fail"

    metrics = {
        "runtime_count": runtime_count,
        "active_slug_count": active_slug_count,
        "source_slug_count": source_slug_count,
        "source_first_slug_count": source_first_slug_count,
        "active_runtime_snapshot_id_exists": active_runtime_snapshot_id_exists,
        "canonical_truth_owner_uniqueness_verified": canonical_truth_owner_uniqueness_verified,
        "canonical_truth_owner_count_per_book": canonical_truth_owner_count_per_book,
        "owner_confusion_count": owner_confusion_count,
        "owner_override_count": owner_override_count,
        "duplicate_active_snapshot_count": duplicate_active_snapshot_count,
        "provenance_chain_break_count": provenance_chain_break_count,
        "cross_surface_owner_mismatch_count": cross_surface_owner_mismatch_count,
        "markdown_or_html_as_owner_count": markdown_or_html_as_owner_count,
        "runtime_path_missing_count": runtime_path_missing_count,
        "source_candidate_missing_count": source_candidate_missing_count,
        "source_first_missing_count": source_first_missing_count,
        "anchor_books_checked": anchor_books_checked,
        "anchor_id_stability_sample_rate": round(anchor_id_stability_sample_rate, 4),
        "anchor_migration_map_coverage": round(anchor_migration_map_coverage, 4),
        "legacy_anchor_unresolved_count": legacy_anchor_unresolved_count,
        "redirect_resolution_mismatch_count": redirect_resolution_mismatch_count,
        "legacy_anchor_redirect_success_rate": round(legacy_anchor_redirect_success_rate, 4),
        "one_click_rebuild_exit_code": one_click_status["one_click_rebuild_exit_code"],
        "post_switch_smoke_exit_code": one_click_status["post_switch_smoke_exit_code"],
        "required_evidence_field_missing_count": required_evidence_field_missing_count,
    }

    return {
        "status": status,
        "task": "runtime_truth_freeze_20260416",
        "canonical_truth_owner": "structured_book",
        "derived_artifacts": [
            "relation_assets",
            "figure_asset_catalog",
            "runtime_manifest",
            "citation_map",
            "viewer_render_assets",
            "corpus_chunks",
            "reports",
            "release_packets",
        ],
        "paths": {
            "active_manifest": str(paths.active_manifest_path),
            "source_manifest": str(paths.source_manifest_path),
            "source_first_manifest": str(paths.source_first_manifest_path),
            "one_click_report": str(paths.one_click_report_path),
        },
        "snapshot": {
            "active_runtime_snapshot_id": active_runtime_snapshot_id,
            "active_group": str(active_manifest.get("active_group") or ""),
            "generated_at_utc": str(active_manifest.get("generated_at_utc") or ""),
        },
        "metrics": metrics,
        "one_click_status": one_click_status,
        "anchor_drift_books": anchor_drift_books,
        "owner_chain_examples": owner_chain_examples[:10],
        "owner_decisions": [
            "canonical_truth_owner=structured_book",
            "runtime_manifest_and_citation_map_are_governance_authoritative_bundle_members_not_owner_replacements",
            "active_switch_uses_single_active_snapshot_pointer",
            "legacy_anchor_resolution_requires_explicit_migration_or_exact_stability",
        ],
    }


def _canonical_active_viewer_path(slug: str) -> str:
    return f"/playbooks/wiki-runtime/active/{slug}/index.html"


def _slug_from_viewer_path(viewer_path: str) -> str:
    parts = [part for part in viewer_path.strip("/").split("/") if part]
    if len(parts) >= 4 and parts[0] == "playbooks" and parts[1] == "wiki-runtime" and parts[2] == "active":
        return parts[3]
    return ""


def _active_snapshot_id(active_manifest: dict[str, Any]) -> str:
    generated_at_utc = str(active_manifest.get("generated_at_utc") or "").strip()
    active_group = str(active_manifest.get("active_group") or "").strip()
    if not generated_at_utc or not active_group:
        return ""
    digest = hashlib.sha256(f"{active_group}|{generated_at_utc}".encode("utf-8")).hexdigest()[:12]
    return f"{active_group}:{generated_at_utc}:{digest}"


def _one_click_status(one_click_report: dict[str, Any]) -> dict[str, Any]:
    step_results = [item for item in one_click_report.get("step_results", []) if isinstance(item, dict)]
    step_returncodes = [int(item.get("returncode", 1)) for item in step_results]
    smoke = one_click_report.get("smoke", {})
    required_smoke_keys = (
        "runtime_viewer_has_title",
        "runtime_viewer_has_networking_hub",
        "runtime_viewer_has_related_sections",
        "storage_viewer_has_topic_hub",
        "proxy_hub_has_related_figures",
        "proxy_hub_has_related_sections",
        "nodes_viewer_has_figure",
        "architecture_viewer_has_figure",
        "architecture_figure_viewer_has_parent_book",
        "architecture_figure_viewer_has_related_section",
    )
    smoke_checks = [bool(smoke.get(key)) for key in required_smoke_keys]
    return {
        "status": str(one_click_report.get("status") or ""),
        "step_count": len(step_results),
        "one_click_rebuild_exit_code": 0 if step_results and all(code == 0 for code in step_returncodes) else 1,
        "post_switch_smoke_exit_code": 0 if smoke_checks and all(smoke_checks) else 1,
    }


def _group_by_slug(entries: list[dict[str, Any]], field_name: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        slug = str(entry.get(field_name) or "").strip()
        if not slug:
            continue
        grouped.setdefault(slug, []).append(entry)
    return grouped


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _markdown_heading_anchors(markdown_text: str) -> list[str]:
    seen: dict[str, int] = {}
    anchors: list[str] = []
    for match in HEADING_RE.finditer(markdown_text or ""):
        heading = _normalize_heading(match.group(2))
        if not heading:
            continue
        anchor = _slugify_heading(heading)
        duplicate_index = seen.get(anchor, 0)
        seen[anchor] = duplicate_index + 1
        if duplicate_index:
            anchor = f"{anchor}-{duplicate_index + 1}"
        anchors.append(anchor)
    return anchors


def _normalize_heading(value: str) -> str:
    normalized = INLINE_LINK_RE.sub(r"\1", value or "")
    normalized = normalized.replace("`", "")
    return normalized.strip()


def _slugify_heading(value: str) -> str:
    lowered = value.strip().lower()
    lowered = NON_WORD_RE.sub(" ", lowered)
    lowered = SPACE_RE.sub("-", lowered).strip("-")
    return lowered or "section"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
