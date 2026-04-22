"""Gold dataset automation profiles and judge-oriented orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

from play_book_studio.app.runtime_report import write_runtime_report
from play_book_studio.config.settings import Settings
from play_book_studio.config.validation import build_validation_report

from .approval_report import (
    _bundle_status_by_slug,
    build_approved_manifest,
    build_corpus_gap_report,
    build_source_approval_report,
    build_translation_lane_report,
    write_approved_manifest,
)
from .curated_gold_batch import apply_all_curated_gold
from .data_quality import build_data_quality_report, playbook_reader_grade_failures
from .manifest import read_manifest
from .models import SourceManifestEntry
from .pipeline import ensure_manifest, run_ingestion_pipeline
from .runtime_catalog_library import materialize_runtime_corpus_from_playbooks
from .source_bundle import harvest_source_bundle
from .source_bundle_quality import build_source_bundle_quality_report
from .source_discovery import default_dossier_slugs
from .synthesis_lane import write_synthesis_lane_outputs
from .topic_playbooks import (
    DERIVED_PLAYBOOK_SOURCE_TYPES,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
    materialize_derived_playbooks,
)
from .translation_draft_generation import generate_translation_drafts
from .translation_gold_promotion import promote_translation_gold


JobRunner = Callable[[Settings, Path, str], dict[str, Any]]


@dataclass(frozen=True)
class FoundryProfile:
    profile_id: str
    name: str
    description: str
    cadence: str
    days: tuple[str, ...]
    time: str | None
    minute: int | None
    interval_hours: int | None
    jobs: tuple[str, ...]


def _routines_path(settings: Settings) -> Path:
    return settings.root_dir / "pipelines" / "foundry_routines.json"


def load_foundry_profiles(settings: Settings) -> dict[str, FoundryProfile]:
    payload = json.loads(_routines_path(settings).read_text(encoding="utf-8"))
    profiles: dict[str, FoundryProfile] = {}
    for item in payload.get("profiles", []):
        schedule = dict(item.get("schedule", {}))
        profile = FoundryProfile(
            profile_id=str(item["id"]),
            name=str(item["name"]),
            description=str(item["description"]),
            cadence=str(schedule["cadence"]),
            days=tuple(str(day) for day in schedule.get("days", [])),
            time=str(schedule["time"]) if "time" in schedule else None,
            minute=int(schedule["minute"]) if "minute" in schedule else None,
            interval_hours=(
                int(schedule["interval_hours"]) if "interval_hours" in schedule else None
            ),
            jobs=tuple(str(job) for job in item.get("jobs", [])),
        )
        profiles[profile.profile_id] = profile
    return profiles


def _job_specs(settings: Settings) -> dict[str, dict[str, Any]]:
    payload = json.loads(_routines_path(settings).read_text(encoding="utf-8"))
    return {
        str(job_id): dict(spec)
        for job_id, spec in dict(payload.get("jobs", {})).items()
    }


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _gold_manual_synthesis_entries(settings: Settings) -> list[Any]:
    entries = []
    for row in _read_jsonl_rows(settings.playbook_documents_path):
        source_metadata = dict(row.get("source_metadata", {}))
        if source_metadata.get("source_type") != "manual_synthesis":
            continue
        if str(row.get("translation_status", "")) != "approved_ko":
            continue
        if str(row.get("review_status", "")) != "approved":
            continue
        slug = str(row.get("book_slug", "")).strip()
        if not slug:
            continue
        anchor_map = dict(row.get("anchor_map", {}))
        viewer_path = ""
        if anchor_map:
            viewer_path = str(next(iter(anchor_map.values()), "")).split("#", 1)[0]
        if not viewer_path:
            viewer_path = settings.viewer_path_template.format(
                version=str(row.get("version") or settings.ocp_version),
                lang=str(row.get("locale") or settings.docs_language),
                slug=slug,
            )
        source_uri = str(row.get("source_uri") or "")
        translation_source_uri = str(row.get("translation_source_uri") or "")
        entries.append(
            SourceManifestEntry(
                product_slug="openshift_container_platform",
                ocp_version=str(row.get("version") or settings.ocp_version),
                docs_language=str(row.get("locale") or settings.docs_language),
                source_kind="html-single",
                book_slug=slug,
                title=str(row.get("title") or slug),
                index_url=source_uri,
                source_url=source_uri,
                resolved_source_url=source_uri,
                resolved_language=str(row.get("locale") or settings.docs_language),
                source_state="published_native",
                source_state_reason="preserved_manual_synthesis_from_gold_manualbook",
                catalog_source_label="curated gold manual synthesis",
                viewer_path=viewer_path,
                high_value=True,
                vendor_title=str(source_metadata.get("original_title") or row.get("title") or slug),
                content_status="approved_ko",
                citation_eligible=True,
                citation_block_reason="",
                viewer_strategy="internal_text",
                body_language_guess="ko",
                hangul_section_ratio=1.0,
                hangul_chunk_ratio=1.0,
                fallback_detected=False,
                source_fingerprint=str(row.get("translation_source_fingerprint") or source_uri),
                approval_status="approved",
                approval_notes="preserved approved manual_synthesis entry from gold manualbook",
                source_id=str(source_metadata.get("source_id") or f"manual_synthesis:{slug}"),
                source_lane=str(source_metadata.get("source_lane") or "applied_playbook"),
                source_type="manual_synthesis",
                source_collection=str(source_metadata.get("source_collection") or "core"),
                legal_notice_url=str(
                    row.get("legal_notice_url")
                    or source_metadata.get("legal_notice_url")
                    or ""
                ),
                original_title=str(source_metadata.get("original_title") or row.get("title") or slug),
                license_or_terms=str(source_metadata.get("license_or_terms") or ""),
                review_status="approved",
                trust_score=float(source_metadata.get("trust_score") or 1.0),
                verifiability=str(source_metadata.get("verifiability") or "anchor_backed"),
                updated_at=str(source_metadata.get("updated_at") or ""),
                translation_source_language=str(row.get("translation_source_language") or "en"),
                translation_target_language=str(row.get("locale") or settings.docs_language),
                translation_source_url=translation_source_uri,
                translation_source_fingerprint=str(row.get("translation_source_fingerprint") or ""),
                translation_stage=str(row.get("translation_stage") or "approved_ko"),
            )
        )
    return entries


def _date_slug() -> str:
    return datetime.now().date().isoformat()


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _job_report_path(report_root: Path, job_id: str) -> Path:
    job_dir = report_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir / f"{_timestamp_slug()}.json"


def _write_job_report(report_root: Path, job_id: str, payload: dict[str, Any]) -> Path:
    target = _job_report_path(report_root, job_id)
    _write_report(target, payload)
    _write_report(target.parent / "latest.json", payload)
    return target


def _profile_report_dir(report_root: Path, profile_id: str) -> Path:
    target = report_root / "profiles" / profile_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def _profile_delta_dir(report_root: Path, profile_id: str) -> Path:
    target = report_root / "deltas" / profile_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def _latest_profile_report_path(report_root: Path, profile_id: str) -> Path:
    return _profile_report_dir(report_root, profile_id) / "latest.json"


def foundry_report_root(settings: Settings) -> Path:
    return settings.root_dir / "reports" / "build_logs" / "foundry_runs"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _job_payload_from_run_report(report: dict[str, Any] | None, job_id: str) -> dict[str, Any]:
    if not report:
        return {}
    for item in report.get("job_results", []):
        if str(item.get("job_id", "")) == job_id:
            return dict(item.get("payload", {}))
    return {}


def _summary_count(payload: dict[str, Any], field_name: str) -> int:
    return int(dict(payload.get("summary", {})).get(field_name, 0))


def _approved_book_slugs(payload: dict[str, Any]) -> list[str]:
    slugs = []
    for slug in payload.get("approved_book_slugs", []):
        normalized = str(slug).strip()
        if normalized:
            slugs.append(normalized)
    return sorted(set(slugs))


def _queue_book_slugs(payload: dict[str, Any], field_name: str) -> list[str]:
    slugs: list[str] = []
    for item in payload.get(field_name, []):
        if isinstance(item, dict):
            slug = str(item.get("book_slug", "")).strip()
        else:
            slug = str(item).strip()
        if slug:
            slugs.append(slug)
    return sorted(set(slugs))


def build_foundry_delta(
    previous_report: dict[str, Any] | None,
    current_report: dict[str, Any],
) -> dict[str, Any]:
    current_synthesis = _job_payload_from_run_report(current_report, "synthesis_lane")
    previous_synthesis = _job_payload_from_run_report(previous_report, "synthesis_lane")
    current_approval = _job_payload_from_run_report(current_report, "source_approval")
    previous_approval = _job_payload_from_run_report(previous_report, "source_approval")
    current_quality = _job_payload_from_run_report(current_report, "source_bundle_quality")
    previous_quality = _job_payload_from_run_report(previous_report, "source_bundle_quality")

    current_translation_queue = _queue_book_slugs(current_synthesis, "translation_ready")
    previous_translation_queue = _queue_book_slugs(previous_synthesis, "translation_ready")
    current_manual_queue = _queue_book_slugs(current_synthesis, "manual_review_ready")
    previous_manual_queue = _queue_book_slugs(previous_synthesis, "manual_review_ready")
    current_approved = _approved_book_slugs(current_approval)
    previous_approved = _approved_book_slugs(previous_approval)

    summary_fields = (
        "approved_runtime_count",
        "translation_ready_count",
        "manual_review_ready_count",
    )
    counts = {
        field_name: {
            "before": _summary_count(previous_synthesis, field_name),
            "after": _summary_count(current_synthesis, field_name),
            "delta": _summary_count(current_synthesis, field_name)
            - _summary_count(previous_synthesis, field_name),
        }
        for field_name in summary_fields
    }
    high_value_before = int(dict(previous_approval.get("summary", {})).get("high_value_issue_count", 0))
    high_value_after = int(dict(current_approval.get("summary", {})).get("high_value_issue_count", 0))
    source_expansion_before = int(dict(previous_quality.get("counts", {})).get("source_expansion_needed", 0))
    source_expansion_after = int(dict(current_quality.get("counts", {})).get("source_expansion_needed", 0))

    previous_verdict = dict(previous_report.get("verdict", {})) if previous_report else {}
    current_verdict = dict(current_report.get("verdict", {}))
    return {
        "profile_id": str(current_report.get("profile", {}).get("id", "")),
        "has_previous_run": previous_report is not None,
        "previous_run_at": None if previous_report is None else previous_report.get("run_at"),
        "current_run_at": current_report.get("run_at"),
        "verdict_change": {
            "before": str(previous_verdict.get("status", "unknown")),
            "after": str(current_verdict.get("status", "unknown")),
            "changed": str(previous_verdict.get("status", "unknown"))
            != str(current_verdict.get("status", "unknown")),
        },
        "summary_deltas": {
            **counts,
            "high_value_issue_count": {
                "before": high_value_before,
                "after": high_value_after,
                "delta": high_value_after - high_value_before,
            },
            "source_expansion_needed_count": {
                "before": source_expansion_before,
                "after": source_expansion_after,
                "delta": source_expansion_after - source_expansion_before,
            },
        },
        "promoted_books": sorted(set(current_approved) - set(previous_approved)),
        "removed_books": sorted(set(previous_approved) - set(current_approved)),
        "translation_queue_added": sorted(
            set(current_translation_queue) - set(previous_translation_queue)
        ),
        "translation_queue_removed": sorted(
            set(previous_translation_queue) - set(current_translation_queue)
        ),
        "manual_review_added": sorted(set(current_manual_queue) - set(previous_manual_queue)),
        "manual_review_removed": sorted(set(previous_manual_queue) - set(current_manual_queue)),
    }


def retryable_foundry_reasons(report: dict[str, Any]) -> list[str]:
    retry_reasons: list[str] = []
    if any(item.get("status") != "ok" for item in report.get("job_results", [])):
        retry_reasons.append("job_error")

    verdict = dict(report.get("verdict", {}))
    for reason in verdict.get("reasons", []):
        normalized = str(reason)
        if normalized.startswith("jobs_failed"):
            retry_reasons.append(normalized)
        elif normalized.startswith("runtime_smoke_failed"):
            retry_reasons.append(normalized)
        elif normalized == "source_bundle_harvest_errors":
            retry_reasons.append(normalized)
    return sorted(set(retry_reasons))


def run_foundry_profile_with_retry(
    settings: Settings,
    profile_id: str,
    *,
    retries: int = 0,
    retry_delay_seconds: int = 300,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    attempts = max(1, retries + 1)
    last_report: dict[str, Any] | None = None
    retry_trace: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        last_report = run_foundry_profile(settings, profile_id)
        reasons = retryable_foundry_reasons(last_report)
        retry_trace.append(
            {
                "attempt": attempt,
                "report_path": last_report.get("report_path"),
                "retry_reasons": reasons,
            }
        )
        if attempt >= attempts or not reasons:
            break
        sleep_fn(float(retry_delay_seconds))

    assert last_report is not None
    last_report["retry"] = {
        "requested_retries": retries,
        "attempt_count": len(retry_trace),
        "retry_delay_seconds": retry_delay_seconds,
        "attempts": retry_trace,
    }
    report_path = Path(str(last_report["report_path"]))
    _write_report(report_path, last_report)
    profile_report_path = last_report.get("profile_report_path")
    if profile_report_path:
        _write_report(Path(str(profile_report_path)), last_report)
    profile_latest_path = last_report.get("profile_latest_report_path")
    if profile_latest_path:
        _write_report(Path(str(profile_latest_path)), last_report)
    return last_report


def _run_manifest_refresh(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    entries = ensure_manifest(settings, refresh=True)
    return {
        "summary": {
            "manifest_count": len(entries),
            "high_value_count": sum(1 for entry in entries if entry.high_value),
        },
        "output_targets": {
            "source_catalog_path": str(settings.source_catalog_path),
            "manifest_update_report_path": str(settings.source_manifest_update_report_path),
        },
    }


def _run_high_value_ingestion(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    log = run_ingestion_pipeline(
        settings,
        refresh_manifest=False,
        collect_subset="high-value",
        process_subset="high-value",
        skip_embeddings=True,
        skip_qdrant=True,
    )
    payload = log.to_dict()
    payload["output_targets"] = {
        "normalized_docs_path": str(settings.normalized_docs_path),
        "chunks_path": str(settings.chunks_path),
        "playbook_documents_path": str(settings.playbook_documents_path),
        "preprocessing_log_path": str(settings.preprocessing_log_path),
    }
    return payload


def _run_approved_runtime_rebuild(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    rebuild_settings = replace(settings, graph_backend="local")
    curated_gold_refresh = apply_all_curated_gold(
        rebuild_settings,
        refresh_synthesis_report=False,
        sync_qdrant=False,
    )
    log = run_ingestion_pipeline(
        rebuild_settings,
        refresh_manifest=False,
        collect_subset="all",
        process_subset="all",
        skip_embeddings=True,
        skip_qdrant=True,
    )
    payload = log.to_dict()
    payload["curated_gold_refresh"] = {
        "requested_count": int(dict(curated_gold_refresh.get("summary", {})).get("requested_count", 0) or 0),
        "promoted_count": int(dict(curated_gold_refresh.get("summary", {})).get("promoted_count", 0) or 0),
        "books": [
            str(item.get("book_slug") or "")
            for item in curated_gold_refresh.get("books", [])
            if isinstance(item, dict) and str(item.get("book_slug") or "").strip()
        ],
    }
    runtime_corpus = materialize_runtime_corpus_from_playbooks(
        rebuild_settings,
        sync_qdrant=True,
        recreate_qdrant=True,
    )
    payload["runtime_corpus_materialization"] = runtime_corpus
    payload["graph_build_backend"] = rebuild_settings.graph_backend
    payload["chunk_count"] = int(runtime_corpus.get("runtime_chunk_count", payload.get("chunk_count", 0)) or 0)
    payload["qdrant_upserted_count"] = int(
        runtime_corpus.get("qdrant_upserted_count", payload.get("qdrant_upserted_count", 0)) or 0
    )
    payload["output_targets"] = {
        "normalized_docs_path": str(settings.normalized_docs_path),
        "chunks_path": str(settings.chunks_path),
        "bm25_corpus_path": str(settings.bm25_corpus_path),
        "playbook_documents_path": str(settings.playbook_documents_path),
        "playbook_books_dir": str(settings.playbook_books_dir),
        "preprocessing_log_path": str(settings.preprocessing_log_path),
        "qdrant_collection": settings.qdrant_collection,
    }
    return payload


def _run_source_approval(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    derived_playbook_summary = materialize_derived_playbooks(settings)
    derived_family_statuses = {
        family: {
            "family": family,
            "count": int(
                dict(derived_playbook_summary.get("family_summaries", {}).get(family, {})).get(
                    "generated_count",
                    0,
                )
            ),
            "slugs": list(
                dict(derived_playbook_summary.get("family_summaries", {}).get(family, {})).get(
                    "generated_slugs",
                    [],
                )
            ),
            "status": (
                "materialized"
                if int(
                    dict(derived_playbook_summary.get("family_summaries", {}).get(family, {})).get(
                        "generated_count",
                        0,
                    )
                )
                > 0
                else "not_emitted"
            ),
        }
        for family in sorted(DERIVED_PLAYBOOK_SOURCE_TYPES)
    }
    topic_playbook_summary = dict(
        derived_playbook_summary.get("family_summaries", {}).get(
            TOPIC_PLAYBOOK_SOURCE_TYPE,
            {"generated_count": 0, "generated_slugs": []},
        )
    )
    operation_playbook_summary = dict(
        derived_playbook_summary.get("family_summaries", {}).get(
            OPERATION_PLAYBOOK_SOURCE_TYPE,
            {"generated_count": 0, "generated_slugs": []},
        )
    )
    troubleshooting_playbook_summary = dict(
        derived_playbook_summary.get("family_summaries", {}).get(
            TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
            {"generated_count": 0, "generated_slugs": []},
        )
    )
    policy_overlay_book_summary = dict(
        derived_playbook_summary.get("family_summaries", {}).get(
            POLICY_OVERLAY_BOOK_SOURCE_TYPE,
            {"generated_count": 0, "generated_slugs": []},
        )
    )
    synthesized_playbook_summary = dict(
        derived_playbook_summary.get("family_summaries", {}).get(
            SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
            {"generated_count": 0, "generated_slugs": []},
        )
    )
    approval_report = build_source_approval_report(settings)
    gap_report = build_corpus_gap_report(settings)
    translation_lane_report = build_translation_lane_report(settings)
    approved_entries = build_approved_manifest(settings)
    reader_grade_failure_slugs = set(playbook_reader_grade_failures(settings))
    approved_by_slug = {entry.book_slug: entry for entry in approved_entries}
    bundle_statuses = _bundle_status_by_slug(settings)
    for entry in _gold_manual_synthesis_entries(settings):
        if entry.book_slug in reader_grade_failure_slugs:
            continue
        bundle_content_status = str(
            dict(bundle_statuses.get(entry.book_slug, {})).get("content_status", "")
        ).strip()
        if bundle_content_status and bundle_content_status != "approved_ko":
            continue
        if entry.book_slug not in approved_by_slug:
            approved_by_slug[entry.book_slug] = entry
    if settings.source_manifest_path.exists():
        for entry in read_manifest(settings.source_manifest_path):
            if entry.book_slug in reader_grade_failure_slugs:
                continue
            if entry.book_slug in approved_by_slug:
                continue
            if entry.source_type != "manual_synthesis":
                continue
            if entry.approval_status != "approved":
                continue
            bundle_content_status = str(
                dict(bundle_statuses.get(entry.book_slug, {})).get("content_status", "")
            ).strip()
            if bundle_content_status and bundle_content_status != "approved_ko":
                continue
            approved_by_slug[entry.book_slug] = entry
    approved_entries = sorted(approved_by_slug.values(), key=lambda entry: entry.book_slug)
    write_approved_manifest(settings.source_manifest_path, approved_entries)

    approval_path = _write_job_report(report_dir, "source_approval_report", approval_report)
    gap_path = _write_job_report(report_dir, "high_value_gap_report", gap_report)
    translation_lane_path = _write_job_report(
        report_dir,
        "translation_lane_report",
        translation_lane_report,
    )

    return {
        "summary": approval_report["summary"],
        "gap_summary": approval_report["gap_summary"],
        "approved_manifest_count": len(approved_entries),
        "approved_book_slugs": [entry.book_slug for entry in approved_entries],
        "derived_playbook_summary": derived_playbook_summary,
        "derived_family_statuses": derived_family_statuses,
        "derived_playbook_count": int(derived_playbook_summary.get("generated_count", 0)),
        "topic_playbook_summary": topic_playbook_summary,
        "operation_playbook_summary": operation_playbook_summary,
        "troubleshooting_playbook_summary": troubleshooting_playbook_summary,
        "policy_overlay_book_summary": policy_overlay_book_summary,
        "synthesized_playbook_summary": synthesized_playbook_summary,
        "output_targets": {
            "approved_manifest_path": str(settings.source_manifest_path),
            "approval_report_path": str(approval_path),
            "gap_report_path": str(gap_path),
            "translation_lane_report_path": str(translation_lane_path),
            "playbook_documents_path": str(settings.playbook_documents_path),
            "playbook_books_dir": str(settings.playbook_books_dir),
        },
    }


def _run_source_bundle_harvest(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    slugs = default_dossier_slugs(settings)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for slug in slugs:
        try:
            manifest = harvest_source_bundle(settings, slug)
            results.append(
                {
                    "book_slug": slug,
                    "repo_artifact_count": len(manifest.get("repo_artifacts", [])),
                    "bundle_root": manifest.get("bundle_root"),
                    "issue_pr_candidates_path": manifest.get("issue_pr_candidates_path"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"book_slug": slug, "error": str(exc)})

    payload = {
        "summary": {
            "selected_count": len(slugs),
            "harvested_count": len(results),
            "error_count": len(errors),
        },
        "results": results,
        "errors": errors,
    }
    report_path = _write_job_report(report_dir, "source_bundle_batch", payload)
    payload["output_targets"] = {"report_path": str(report_path)}
    return payload


def _run_source_bundle_quality(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = build_source_bundle_quality_report(settings)
    report_path = _write_job_report(report_dir, "source_bundle_quality", payload)
    payload["output_targets"] = {"report_path": str(report_path)}
    return payload


def _run_synthesis_lane(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = write_synthesis_lane_outputs(settings)
    report_path = _write_job_report(report_dir, "synthesis_lane", payload)
    payload["output_targets"] = {
        **payload.get("output_targets", {}),
        "report_path": str(report_path),
    }
    return payload


def _run_translation_drafts(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = generate_translation_drafts(settings)
    report_path = _write_job_report(report_dir, "translation_draft_generation_report", payload)
    payload["draft_only"] = True
    payload["output_targets"] = {
        **payload.get("output_targets", {}),
        "report_path": str(report_path),
    }
    return payload


def _run_translation_gold_promotion(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = promote_translation_gold(
        settings,
        generate_first=False,
        refresh_synthesis_report=True,
        sync_qdrant=True,
    )
    report_path = _write_job_report(report_dir, "translation_gold_promotion_report", payload)
    payload["output_targets"] = {
        **payload.get("output_targets", {}),
        "report_path": str(report_path),
    }
    return payload


def _run_validation_gate(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = build_validation_report(
        settings,
        expected_process_subset="high-value",
        artifact_expectation_mode="runtime_baseline",
        include_qdrant_id_check=True,
    )
    report_path = _write_job_report(report_dir, "validation_report", payload)
    payload["output_targets"] = {"report_path": str(report_path)}
    return payload


def _run_data_quality_audit(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    payload = build_data_quality_report(settings)
    report_path = _write_job_report(report_dir, "data_quality_report", payload)
    payload["output_targets"] = {"report_path": str(report_path)}
    return payload


def _run_runtime_smoke(settings: Settings, report_dir: Path, _: str) -> dict[str, Any]:
    report_path, payload = write_runtime_report(
        settings.root_dir,
        output_path=_job_report_path(report_dir, "runtime_report"),
        sample=False,
    )
    _write_report(report_path.parent / "latest.json", payload)
    payload["output_targets"] = {"report_path": str(report_path)}
    return payload


JOB_RUNNERS: dict[str, JobRunner] = {
    "manifest_refresh": _run_manifest_refresh,
    "high_value_ingestion": _run_high_value_ingestion,
    "approved_runtime_rebuild": _run_approved_runtime_rebuild,
    "source_approval": _run_source_approval,
    "source_bundle_harvest": _run_source_bundle_harvest,
    "source_bundle_quality": _run_source_bundle_quality,
    "synthesis_lane": _run_synthesis_lane,
    "translation_drafts": _run_translation_drafts,
    "translation_gold_promotion": _run_translation_gold_promotion,
    "validation_gate": _run_validation_gate,
    "data_quality_audit": _run_data_quality_audit,
    "runtime_smoke": _run_runtime_smoke,
}


def build_release_verdict(job_results: list[dict[str, Any]]) -> dict[str, Any]:
    results_by_job = {str(item["job_id"]): item for item in job_results}
    reasons: list[str] = []

    failed_jobs = [item["job_id"] for item in job_results if item["status"] != "ok"]
    if failed_jobs:
        reasons.append("jobs_failed:" + ",".join(failed_jobs))
        return {
            "status": "blocked",
            "release_blocking": True,
            "reasons": reasons,
        }

    harvest_payload = dict(results_by_job.get("source_bundle_harvest", {}).get("payload", {}))
    if int(dict(harvest_payload.get("summary", {})).get("error_count", 0)) > 0:
        reasons.append("source_bundle_harvest_errors")

    quality_payload = dict(results_by_job.get("source_bundle_quality", {}).get("payload", {}))
    quality_counts = dict(quality_payload.get("counts", {}))
    if int(quality_counts.get("source_expansion_needed", 0)) > 0:
        reasons.append("source_expansion_needed")

    synthesis_payload = dict(results_by_job.get("synthesis_lane", {}).get("payload", {}))
    synthesis_summary = dict(synthesis_payload.get("summary", {}))
    translation_ready_count = int(synthesis_summary.get("translation_ready_count", 0))
    manual_review_ready_count = int(synthesis_summary.get("manual_review_ready_count", 0))
    if translation_ready_count > 0:
        reasons.append("translation_ready_remaining")
    if manual_review_ready_count > 0:
        reasons.append("manual_review_remaining")

    approval_payload = dict(results_by_job.get("source_approval", {}).get("payload", {}))
    approval_summary = dict(approval_payload.get("summary", {}))
    if int(approval_summary.get("high_value_issue_count", 0)) > 0:
        reasons.append("high_value_gaps_remaining")

    validation_payload = dict(results_by_job.get("validation_gate", {}).get("payload", {}))
    validation_checks = dict(validation_payload.get("checks", {}))
    required_validation_checks = (
        "raw_html_covers_expected_subset",
        "artifact_books_match_expected_subset",
        "chunks_have_unique_ids",
        "bm25_matches_chunks",
        "qdrant_matches_chunks_by_count",
        "required_keys_present",
        "manifest_metadata_complete",
        "normalized_metadata_complete",
        "chunk_metadata_complete",
        "playbook_metadata_complete",
        "parsed_lineage_complete",
        "security_boundary_complete",
        "no_empty_chunk_texts",
        "no_legal_notice_chunks",
    )
    failed_validation_checks = [
        check_name
        for check_name in required_validation_checks
        if validation_checks.get(check_name) is not True
    ]
    failed_validation_checks.extend(
        check_name
        for check_name in ("qdrant_matches_chunks_by_ids", "qdrant_books_match_chunks")
        if check_name in validation_checks and validation_checks.get(check_name) is False
    )
    if failed_validation_checks:
        reasons.append("validation_failed:" + ",".join(failed_validation_checks))

    data_quality_payload = dict(results_by_job.get("data_quality_audit", {}).get("payload", {}))
    data_quality_checks = dict(data_quality_payload.get("checks", {}))
    failed_data_quality_checks = [
        check_name
        for check_name, value in data_quality_checks.items()
        if value is False
    ]
    if failed_data_quality_checks:
        reasons.append("data_quality_failed:" + ",".join(failed_data_quality_checks))

    runtime_payload = dict(results_by_job.get("runtime_smoke", {}).get("payload", {}))
    runtime_probes = dict(runtime_payload.get("probes", {}))
    runtime_errors: list[str] = []
    local_ui = dict(runtime_probes.get("local_ui", {}))
    if local_ui:
        if "error" in local_ui or int(local_ui.get("health_status", 0) or 0) >= 400:
            runtime_errors.append("local_ui")
    llm = dict(runtime_probes.get("llm", {}))
    if llm and ("error" in llm or int(llm.get("models_status", 0) or 0) >= 400):
        runtime_errors.append("llm")
    embedding = dict(runtime_probes.get("embedding", {}))
    if embedding and "error" in embedding:
        runtime_errors.append("embedding")
    qdrant = dict(runtime_probes.get("qdrant", {}))
    if qdrant and ("error" in qdrant or not bool(qdrant.get("collection_present", True))):
        runtime_errors.append("qdrant")
    if runtime_errors:
        reasons.append("runtime_smoke_failed:" + ",".join(runtime_errors))

    if any(
        reason.startswith("source_expansion_needed") or reason.startswith("validation_failed")
        or reason.startswith("source_bundle_harvest_errors")
        or reason.startswith("data_quality_failed")
        or reason.startswith("runtime_smoke_failed")
        for reason in reasons
    ):
        status = "blocked"
    elif reasons:
        status = "needs_promotion"
    else:
        status = "release_ready"

    return {
        "status": status,
        "release_blocking": status != "release_ready",
        "reasons": reasons,
        "summary": {
            "approved_runtime_count": int(synthesis_summary.get("approved_runtime_count", 0)),
            "translation_ready_count": translation_ready_count,
            "manual_review_ready_count": manual_review_ready_count,
            "high_value_issue_count": int(approval_summary.get("high_value_issue_count", 0)),
            "source_expansion_needed_count": int(quality_counts.get("source_expansion_needed", 0)),
            "failed_validation_checks": failed_validation_checks,
            "failed_data_quality_checks": failed_data_quality_checks,
        },
    }


def run_foundry_profile(
    settings: Settings,
    profile_id: str,
) -> dict[str, Any]:
    profiles = load_foundry_profiles(settings)
    if profile_id not in profiles:
        raise KeyError(f"unknown foundry profile: {profile_id}")
    job_specs = _job_specs(settings)
    profile = profiles[profile_id]
    report_root = foundry_report_root(settings)
    report_root.mkdir(parents=True, exist_ok=True)
    previous_report = _load_json(_latest_profile_report_path(report_root, profile_id))

    job_results: list[dict[str, Any]] = []
    for job_id in profile.jobs:
        job_spec = dict(job_specs[job_id])
        runner = JOB_RUNNERS[job_id]
        try:
            payload = runner(settings, report_root, profile_id)
            job_result = {
                "job_id": job_id,
                "job_name": job_spec.get("name", job_id),
                "stage": job_spec.get("stage", ""),
                "status": "ok",
                "payload": payload,
            }
        except Exception as exc:  # noqa: BLE001
            job_result = {
                "job_id": job_id,
                "job_name": job_spec.get("name", job_id),
                "stage": job_spec.get("stage", ""),
                "status": "error",
                "payload": {"error": str(exc)},
            }
        audit_path = _write_job_report(report_root, job_id, job_result)
        job_result["audit_report_path"] = str(audit_path)
        job_results.append(job_result)
        if job_result["status"] == "error" and bool(job_spec.get("stop_on_failure", True)):
            break

    verdict = build_release_verdict(job_results)
    run_report = {
        "profile": {
            "id": profile.profile_id,
            "name": profile.name,
            "description": profile.description,
            "schedule": {
                "timezone": "Asia/Seoul",
                "cadence": profile.cadence,
                "days": list(profile.days),
                "time": profile.time,
                "minute": profile.minute,
                "interval_hours": profile.interval_hours,
            },
            "jobs": list(profile.jobs),
        },
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "job_results": job_results,
        "verdict": verdict,
    }
    run_report["delta"] = build_foundry_delta(previous_report, run_report)
    report_path = report_root / f"gold_foundry_{profile.profile_id}_{_timestamp_slug()}.json"
    profile_report_path = _profile_report_dir(report_root, profile.profile_id) / report_path.name
    delta_report_path = (
        _profile_delta_dir(report_root, profile.profile_id) / f"delta_{report_path.name}"
    )
    _write_report(report_path, run_report)
    _write_report(profile_report_path, run_report)
    _write_report(_latest_profile_report_path(report_root, profile.profile_id), run_report)
    _write_report(delta_report_path, run_report["delta"])
    _write_report(_profile_delta_dir(report_root, profile.profile_id) / "latest.json", run_report["delta"])
    run_report["report_path"] = str(report_path)
    run_report["profile_report_path"] = str(profile_report_path)
    run_report["profile_latest_report_path"] = str(_latest_profile_report_path(report_root, profile.profile_id))
    run_report["delta_report_path"] = str(delta_report_path)
    return run_report
