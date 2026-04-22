"""남은 high-value bundle을 curated gold로 일괄 승격한다."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from play_book_studio.config.settings import Settings
from play_book_studio.config.validation import read_jsonl

from .collector import collect_entry
from .curated_gold import (
    apply_curated_backup_restore_gold,
    apply_curated_etcd_gold,
    apply_curated_installing_on_any_platform_gold,
    apply_curated_logging_gold,
    apply_curated_machine_configuration_gold,
    apply_curated_monitoring_gold,
    apply_curated_operators_gold,
)
from .embedding import EmbeddingClient
from .manifest import read_manifest
from .models import ChunkRecord, SourceManifestEntry
from .qdrant_store import upsert_chunks
from .synthesis_lane import synthesis_lane_report_path, write_synthesis_lane_outputs


CURATED_GOLD_PROMOTION_STRATEGY = "curated_gold_manual_synthesis"
CURATED_GOLD_PROMOTION_NOTE = (
    "reviewed curated gold manual synthesis promoted into active gold dataset"
)

CuratedApplyFn = Callable[[Settings], dict[str, object]]


def _apply_backup_restore(settings: Settings) -> dict[str, object]:
    return apply_curated_backup_restore_gold(settings, refresh_synthesis_report=False)


def _apply_etcd(settings: Settings) -> dict[str, object]:
    return apply_curated_etcd_gold(settings, refresh_synthesis_report=False)


def _apply_installing_on_any_platform(settings: Settings) -> dict[str, object]:
    return apply_curated_installing_on_any_platform_gold(
        settings,
        refresh_synthesis_report=False,
    )


def _apply_logging(settings: Settings) -> dict[str, object]:
    return apply_curated_logging_gold(settings, refresh_synthesis_report=False)


def _apply_machine_configuration(settings: Settings) -> dict[str, object]:
    return apply_curated_machine_configuration_gold(
        settings,
        refresh_synthesis_report=False,
    )


def _apply_monitoring(settings: Settings) -> dict[str, object]:
    return apply_curated_monitoring_gold(settings, refresh_synthesis_report=False)


def _apply_operators(settings: Settings) -> dict[str, object]:
    return apply_curated_operators_gold(settings, refresh_synthesis_report=False)


CURATED_GOLD_APPLIERS: tuple[tuple[str, CuratedApplyFn], ...] = (
    ("backup_and_restore", _apply_backup_restore),
    ("etcd", _apply_etcd),
    ("installing_on_any_platform", _apply_installing_on_any_platform),
    ("logging", _apply_logging),
    ("machine_configuration", _apply_machine_configuration),
    ("monitoring", _apply_monitoring),
    ("operators", _apply_operators),
)


def _manifest_entry_by_slug(settings: Settings, slug: str) -> SourceManifestEntry:
    for entry in read_manifest(settings.source_manifest_path):
        if entry.book_slug == slug:
            return entry
    raise KeyError(f"Missing source manifest entry for curated slug: {slug}")


def promote_curated_source_bundle(
    settings: Settings,
    entry: SourceManifestEntry,
    *,
    promotion_note: str = CURATED_GOLD_PROMOTION_NOTE,
) -> dict[str, object] | None:
    dossier_path = settings.bronze_dir / "source_bundles" / entry.book_slug / "dossier.json"
    if not dossier_path.exists():
        return None

    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    current_status = dict(dossier.get("current_status", {}))
    title = str(current_status.get("title") or entry.vendor_title or entry.title)
    approved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    current_status.update(
        {
            "content_status": "approved_ko",
            "gap_lane": "approved",
            "gap_action": promotion_note,
            "fallback_detected": False,
            "hangul_chunk_ratio": 1.0,
            "title": title,
            "promotion_strategy": CURATED_GOLD_PROMOTION_STRATEGY,
            "review_status": "approved",
            "source_lane": entry.source_lane,
            "source_type": entry.source_type,
            "source_id": entry.source_id,
            "updated_at": entry.updated_at,
            "approved_at": approved_at,
        }
    )
    dossier["current_status"] = current_status
    dossier["promotion"] = {
        "strategy": CURATED_GOLD_PROMOTION_STRATEGY,
        "status": "approved_ko",
        "note": promotion_note,
        "approved_at": approved_at,
        "source_manifest_path": str(settings.source_manifest_path),
        "source_id": entry.source_id,
        "source_url": entry.source_url,
        "translation_source_url": entry.translation_source_url,
    }
    dossier_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
    return dossier


def _chunk_records_for_slug(settings: Settings, slug: str) -> list[ChunkRecord]:
    allowed = {field.name for field in fields(ChunkRecord)}
    records: list[ChunkRecord] = []
    for row in read_jsonl(settings.chunks_path):
        if str(row.get("book_slug", "")) != slug:
            continue
        payload = {key: value for key, value in row.items() if key in allowed}
        payload["section_path"] = tuple(payload.get("section_path", []))
        payload["cli_commands"] = tuple(payload.get("cli_commands", []))
        payload["error_strings"] = tuple(payload.get("error_strings", []))
        payload["k8s_objects"] = tuple(payload.get("k8s_objects", []))
        payload["operator_names"] = tuple(payload.get("operator_names", []))
        payload["verification_hints"] = tuple(payload.get("verification_hints", []))
        records.append(ChunkRecord(**payload))
    return records


def sync_curated_slug_to_qdrant(settings: Settings, slug: str) -> int:
    chunks = _chunk_records_for_slug(settings, slug)
    if not chunks:
        return 0
    client = EmbeddingClient(settings)
    vectors = client.embed_texts(chunk.text for chunk in chunks)
    return upsert_chunks(settings, chunks, vectors)


def apply_all_curated_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = True,
    sync_qdrant: bool = False,
) -> dict[str, object]:
    reports: list[dict[str, object]] = []
    total_qdrant_upserts = 0
    dossier_promoted_count = 0

    for slug, applier in CURATED_GOLD_APPLIERS:
        report = dict(applier(settings))
        entry = _manifest_entry_by_slug(settings, slug)
        collect_entry(entry, settings, force=False)
        dossier = promote_curated_source_bundle(settings, entry)
        if dossier is not None:
            dossier_promoted_count += 1
        qdrant_upserted = sync_curated_slug_to_qdrant(settings, slug) if sync_qdrant else 0
        total_qdrant_upserts += qdrant_upserted
        report["qdrant_upserted_count"] = qdrant_upserted
        report["dossier_promoted"] = dossier is not None
        reports.append(report)

    synthesis_report = None
    if refresh_synthesis_report and settings.source_catalog_path.exists():
        synthesis_report_path = synthesis_lane_report_path(settings)
        synthesis_report = write_synthesis_lane_outputs(settings)
    else:
        synthesis_report_path = None

    return {
        "summary": {
            "requested_count": len(CURATED_GOLD_APPLIERS),
            "promoted_count": len(reports),
            "dossier_promoted_count": dossier_promoted_count,
            "qdrant_upserted_count": total_qdrant_upserts,
        },
        "books": reports,
        "synthesis_report_path": None if synthesis_report_path is None else str(synthesis_report_path),
        "synthesis_summary": None if synthesis_report is None else synthesis_report.get("summary"),
    }
