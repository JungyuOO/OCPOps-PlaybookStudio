"""source bundle readiness를 번역/수동검토 산출물 큐로 승격한다."""

from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.config.settings import Settings

from .data_quality import playbook_reader_grade_failures
from .manifest import read_manifest, runtime_catalog_entries, write_manifest
from .models import CONTENT_STATUS_TRANSLATED_KO_DRAFT, SourceManifestEntry
from .source_bundle_quality import build_source_bundle_quality_report
from .topic_playbooks import (
    DERIVED_PLAYBOOK_SOURCE_TYPES,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
)

REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES = tuple(sorted(DERIVED_PLAYBOOK_SOURCE_TYPES))


def _entry_identity(entry: SourceManifestEntry) -> tuple[str, str, str, str]:
    return (
        entry.ocp_version,
        entry.docs_language,
        entry.source_kind,
        entry.book_slug,
    )


def _safe_read_manifest(path: Path) -> list[SourceManifestEntry]:
    if not path.exists():
        return []
    return read_manifest(path)


def _bundle_root(settings: Settings, slug: str) -> Path:
    return settings.bronze_dir / "source_bundles" / slug


def _bundle_dossier(settings: Settings, slug: str) -> dict[str, object]:
    path = _bundle_root(settings, slug) / "dossier.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_translation_entry(
    entry: SourceManifestEntry,
    *,
    readiness_row: dict[str, object],
    dossier: dict[str, object],
) -> SourceManifestEntry:
    payload = entry.to_dict()
    official_docs = dict(dossier.get("official_docs", {}))
    official_en = dict(official_docs.get("en", {}))
    source_url = str(official_en.get("url") or entry.translation_source_url or entry.resolved_source_url or entry.source_url)
    source_language = (
        entry.translation_source_language
        or entry.resolved_language
        or ("en" if bool(readiness_row.get("ko_fallback_banner", False)) else entry.docs_language)
        or "en"
    ).strip() or "en"
    if source_language == "ko":
        source_language = "en"
    payload.update(
        {
            "content_status": CONTENT_STATUS_TRANSLATED_KO_DRAFT,
            "citation_eligible": False,
            "citation_block_reason": "translated Korean draft requires review before citation",
            "approval_status": "needs_review",
            "approval_notes": "synthesis lane promoted from translation_ready bronze bundle",
            "resolved_language": source_language,
            "source_lane": "official_en_fallback" if bool(readiness_row.get("ko_fallback_banner", False)) else (entry.source_lane or "official_ko"),
            "translation_source_language": source_language,
            "translation_target_language": "ko",
            "translation_source_url": source_url,
            "translation_source_fingerprint": entry.translation_source_fingerprint or entry.source_fingerprint,
            "translation_stage": CONTENT_STATUS_TRANSLATED_KO_DRAFT,
        }
    )
    return SourceManifestEntry(**payload)


def build_synthesis_lane(settings: Settings) -> dict[str, object]:
    quality_report = build_source_bundle_quality_report(settings)
    reader_grade_failures = playbook_reader_grade_failures(settings)
    reader_grade_failure_slugs = set(reader_grade_failures)
    runtime_catalog = runtime_catalog_entries(read_manifest(settings.source_catalog_path), settings)
    runtime_catalog_by_slug = {entry.book_slug: entry for entry in runtime_catalog}
    stale_promoted_slugs = {
        str(row["book_slug"])
        for row in quality_report["bundles"]
        if str(row.get("readiness", "")) in {
            "translation_ready",
            "manual_review_ready",
            "source_expansion_needed",
        }
    }
    source_manifest_entries = _safe_read_manifest(settings.source_manifest_path)
    approved_entries = [
        entry
        for entry in source_manifest_entries
        if entry.book_slug not in stale_promoted_slugs
        and entry.book_slug not in reader_grade_failure_slugs
    ]
    approved_slugs = {
        entry.book_slug
        for entry in approved_entries
        if entry.ocp_version == settings.ocp_version and entry.docs_language == settings.docs_language
    }
    existing_translation_entries = _safe_read_manifest(settings.translation_draft_manifest_path)
    translation_overlay = {_entry_identity(entry): entry for entry in existing_translation_entries}

    translation_ready_rows = [
        row for row in quality_report["bundles"] if row["readiness"] == "translation_ready"
    ]
    manual_review_rows = [
        row for row in quality_report["bundles"] if row["readiness"] == "manual_review_ready"
    ]

    translation_entries: list[SourceManifestEntry] = []
    translation_rows: list[dict[str, object]] = []
    for row in translation_ready_rows:
        slug = str(row["book_slug"])
        runtime_entry = runtime_catalog_by_slug.get(slug)
        if runtime_entry is None:
            continue
        base_entry = translation_overlay.get(_entry_identity(runtime_entry), runtime_entry)
        dossier = _bundle_dossier(settings, slug)
        translated_entry = _build_translation_entry(base_entry, readiness_row=row, dossier=dossier)
        translation_entries.append(translated_entry)
        translation_rows.append(
            {
                **row,
                "bundle_root": str(_bundle_root(settings, slug)),
                "translation_source_url": translated_entry.translation_source_url,
                "translation_source_language": translated_entry.translation_source_language,
            }
        )

    approved_by_key = {_entry_identity(entry): entry for entry in approved_entries}
    for entry in translation_entries:
        approved_by_key[_entry_identity(entry)] = entry
    corpus_working_entries = sorted(approved_by_key.values(), key=_entry_identity)

    manual_review_queue = [
        {
            **row,
            "bundle_root": str(_bundle_root(settings, str(row["book_slug"]))),
        }
        for row in manual_review_rows
    ]
    queued_manual_review_slugs = {
        str(item.get("book_slug", "")).strip()
        for item in manual_review_queue
        if str(item.get("book_slug", "")).strip()
    }
    for entry in source_manifest_entries:
        if entry.book_slug not in reader_grade_failure_slugs:
            continue
        if entry.book_slug in queued_manual_review_slugs:
            continue
        if entry.ocp_version != settings.ocp_version or entry.docs_language != settings.docs_language:
            continue
        failure = dict(reader_grade_failures.get(entry.book_slug, {}))
        manual_review_queue.append(
            {
                "book_slug": entry.book_slug,
                "title": entry.title,
                "readiness": "manual_review_ready",
                "recommended_action": "fix manualbook reader-grade failure and rerun approval",
                "queue_reason": "manualbook_reader_grade_failed",
                "source_lane": entry.source_lane,
                "source_type": entry.source_type,
                **failure,
            }
        )
        queued_manual_review_slugs.add(entry.book_slug)
    manual_review_queue.sort(key=lambda item: str(item.get("book_slug", "")))
    buyer_scope = dict(quality_report.get("buyer_scope", {}))
    derived_family_counts = dict(buyer_scope.get("derived_family_counts", {}))
    approved_manifest_derived_family_counts = dict(
        buyer_scope.get("approved_manifest_derived_family_counts", {})
    )
    materialized_derived_family_counts = dict(
        buyer_scope.get("materialized_derived_family_counts", {})
    )
    promotion_queue_count = (
        len(translation_entries)
        + len(manual_review_queue)
        + int(buyer_scope.get("source_expansion_needed_count", 0))
    )
    buyer_scope.update(
        {
            "promotion_queue_count": promotion_queue_count,
            "queue_scope": "buyer_playable_review",
            "translation_ready_count": len(translation_entries),
            "manual_review_ready_count": len(manual_review_queue),
            "approved_runtime_count": len(approved_entries),
            "translation_draft_playable_count": len(translation_entries),
            "manual_review_queue_count": len(manual_review_queue),
            "corpus_working_count": len(corpus_working_entries),
            "pack_scope_status": (
                "needs_queue_visibility"
                if manual_review_queue or translation_entries
                else "runtime_ready"
            ),
            "scope_verdict": (
                f"{buyer_scope.get('playable_asset_count', 0)} approved playable assets "
                f"({buyer_scope.get('approved_manual_book_count', 0)} manual books + "
                f"{buyer_scope.get('visible_derived_playbook_count', 0)} visible derived family books inside "
                f"{buyer_scope.get('playable_book_count', 0)} playable books; "
                f"approved manifest derived {buyer_scope.get('approved_manifest_derived_playbook_count', 0)} "
                f"({', '.join(f'{family} {count}' for family, count in approved_manifest_derived_family_counts.items())}); "
                f"materialized derived {buyer_scope.get('materialized_derived_playbook_count', 0)} "
                f"({', '.join(f'{family} {count}' for family, count in materialized_derived_family_counts.items())})) are visible now; "
                f"{promotion_queue_count} books remain in the buyer-visible review queue."
            ),
        }
    )

    summary = {
        "approved_runtime_count": len(approved_entries),
        "translation_ready_count": len(translation_entries),
        "manual_review_ready_count": len(manual_review_queue),
        "corpus_working_count": len(corpus_working_entries),
        "playable_book_count": int(buyer_scope.get("playable_book_count", 0)),
        "derived_playbook_count": int(buyer_scope.get("derived_playbook_count", 0)),
        "approved_manifest_derived_playbook_count": int(
            buyer_scope.get("approved_manifest_derived_playbook_count", 0)
        ),
        "materialized_derived_playbook_count": int(
            buyer_scope.get("materialized_derived_playbook_count", 0)
        ),
    }
    for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES:
        summary[f"{family}_count"] = int(buyer_scope.get(f"{family}_count", 0))

    return {
        "summary": summary,
        "approved_manifest_derived_playbook_count": int(
            buyer_scope.get("approved_manifest_derived_playbook_count", 0)
        ),
        "approved_manifest_derived_family_counts": approved_manifest_derived_family_counts,
        "materialized_derived_playbook_count": int(
            buyer_scope.get("materialized_derived_playbook_count", 0)
        ),
        "materialized_derived_family_counts": materialized_derived_family_counts,
        "visible_derived_playbook_count": int(
            buyer_scope.get("visible_derived_playbook_count", 0)
        ),
        "visible_derived_family_counts": dict(buyer_scope.get("visible_derived_family_counts", {})),
        "derived_family_counts": derived_family_counts,
        "buyer_scope": buyer_scope,
        "translation_ready": translation_rows,
        "manual_review_ready": manual_review_queue,
        "output_targets": {
            "translation_draft_manifest_path": str(settings.translation_draft_manifest_path),
            "corpus_working_manifest_path": str(settings.corpus_working_manifest_path),
            "synthesis_lane_report_path": str(synthesis_lane_report_path(settings)),
        },
        "translation_entries": translation_entries,
        "corpus_working_entries": corpus_working_entries,
    }


def synthesis_lane_report_path(settings: Settings) -> Path:
    return settings.root_dir / "reports" / "build_logs" / "synthesis_lane_report.json"


def write_synthesis_lane_outputs(
    settings: Settings,
) -> dict[str, object]:
    report = build_synthesis_lane(settings)
    translation_entries = list(report.pop("translation_entries"))
    corpus_working_entries = list(report.pop("corpus_working_entries"))
    write_manifest(settings.translation_draft_manifest_path, translation_entries)
    write_manifest(settings.corpus_working_manifest_path, corpus_working_entries)
    report_path = synthesis_lane_report_path(settings)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
