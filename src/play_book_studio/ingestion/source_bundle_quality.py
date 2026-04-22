# bronze source bundle의 제련 준비 상태를 평가한다.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings

from .manifest import read_manifest, runtime_catalog_entries
from .topic_playbooks import (
    DERIVED_PLAYBOOK_SOURCE_TYPES,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
)

REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES = tuple(sorted(DERIVED_PLAYBOOK_SOURCE_TYPES))

APPROVED_GOLD_PROMOTION_STRATEGIES = {
    "curated_gold_manual_synthesis",
    "translated_gold_manual_synthesis",
}


def _bundle_root(settings: Settings) -> Path:
    return settings.bronze_dir / "source_bundles"


def _safe_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _approved_gold_slugs(settings: Settings) -> set[str]:
    manifest_path = getattr(settings, "source_manifest_path", None)
    if manifest_path is None:
        return set()
    path = Path(manifest_path)
    if not path.exists():
        return set()
    approved: set[str] = set()
    for entry in read_manifest(path):
        if entry.ocp_version != settings.ocp_version:
            continue
        if entry.docs_language != settings.docs_language:
            continue
        if entry.approval_status != "approved":
            continue
        if entry.content_status != "approved_ko":
            continue
        approved.add(entry.book_slug)
    return approved


def _raw_manual_count(settings: Settings, bundle_count: int) -> int:
    catalog_path = getattr(settings, "source_catalog_path", None)
    if catalog_path is None:
        return bundle_count
    path = Path(catalog_path)
    if not path.exists():
        return bundle_count
    return len(runtime_catalog_entries(read_manifest(path), settings))


def _family_status_payload(
    *,
    family: str,
    slugs: list[str],
    present_status: str,
    empty_status: str,
) -> dict[str, object]:
    return {
        "family": family,
        "count": len(slugs),
        "slugs": slugs,
        "status": present_status if slugs else empty_status,
    }


def _derived_family_counts_payload(family_slug_map: dict[str, set[str]]) -> dict[str, int]:
    return {
        family: len(sorted(slugs))
        for family, slugs in sorted(family_slug_map.items())
    }


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _approved_materialized_report_derived_rows(settings: Settings) -> list[dict[str, Any]]:
    approved_rows: list[dict[str, Any]] = []
    for row in _read_jsonl_rows(settings.playbook_documents_path):
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        if str(row.get("translation_status") or "").strip() != "approved_ko":
            continue
        if str(row.get("review_status") or "").strip() != "approved":
            continue
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        source_type = str(source_metadata.get("source_type") or "").strip()
        if source_type not in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES:
            continue
        if not (settings.playbook_books_dir / f"{slug}.json").exists():
            continue
        approved_rows.append(row)
    return approved_rows


def _playable_asset_multiplication(
    *,
    raw_manual_count: int,
    approved_manual_book_count: int,
    playable_book_count: int,
    derived_playbook_count: int,
) -> dict[str, object]:
    approved_playable_asset_count = approved_manual_book_count + playable_book_count
    ratio = 0.0
    if raw_manual_count > 0:
        ratio = round(approved_playable_asset_count / raw_manual_count, 4)
    return {
        "raw_manual_count": raw_manual_count,
        "approved_playable_asset_count": approved_playable_asset_count,
        "approved_manual_book_count": approved_manual_book_count,
        "playable_book_count": playable_book_count,
        "derived_playbook_count": derived_playbook_count,
        "delta_vs_raw_manual_count": approved_playable_asset_count - raw_manual_count,
        "ratio_vs_raw_manual_count": ratio,
    }


def _approved_pack_scope(settings: Settings) -> dict[str, object]:
    empty_scope = {
        "approved_entry_count": 0,
        "approved_manual_book_count": 0,
        "approved_manifest_entry_count": 0,
        "approved_manifest_manual_book_count": 0,
        "approved_manifest_playable_book_count": 0,
        "approved_manifest_playable_family_counts": {},
        "approved_manifest_derived_family_statuses": {
            family: _family_status_payload(
                family=family,
                slugs=[],
                present_status="approved_manifest",
                empty_status="not_in_approved_manifest",
            )
            for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "approved_manifest_derived_family_counts": {
            family: 0 for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "approved_manifest_derived_playbook_count": 0,
        "approved_manifest_topic_playbook_count": 0,
        "approved_manifest_operation_playbook_count": 0,
        "approved_manifest_troubleshooting_playbook_count": 0,
        "approved_manifest_policy_overlay_book_count": 0,
        "approved_manifest_synthesized_playbook_count": 0,
        "approved_manifest_topic_playbook_slugs": [],
        "approved_manifest_operation_playbook_slugs": [],
        "approved_manifest_troubleshooting_playbook_slugs": [],
        "approved_manifest_policy_overlay_book_slugs": [],
        "approved_manifest_synthesized_playbook_slugs": [],
        "playable_book_count": 0,
        "playable_family_counts": {},
        "derived_family_statuses": {
            family: _family_status_payload(
                family=family,
                slugs=[],
                present_status="materialized",
                empty_status="not_materialized",
            )
            for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "derived_family_counts": {
            family: 0 for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "derived_playbook_count": 0,
        "topic_playbook_count": 0,
        "operation_playbook_count": 0,
        "troubleshooting_playbook_count": 0,
        "policy_overlay_book_count": 0,
        "synthesized_playbook_count": 0,
        "topic_playbook_slugs": [],
        "operation_playbook_slugs": [],
        "troubleshooting_playbook_slugs": [],
        "policy_overlay_book_slugs": [],
        "synthesized_playbook_slugs": [],
        "materialized_derived_family_statuses": {
            family: _family_status_payload(
                family=family,
                slugs=[],
                present_status="materialized",
                empty_status="not_materialized",
            )
            for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "materialized_derived_family_counts": {
            family: 0 for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "materialized_derived_playbook_count": 0,
        "materialized_topic_playbook_count": 0,
        "materialized_operation_playbook_count": 0,
        "materialized_troubleshooting_playbook_count": 0,
        "materialized_policy_overlay_book_count": 0,
        "materialized_synthesized_playbook_count": 0,
        "materialized_topic_playbook_slugs": [],
        "materialized_operation_playbook_slugs": [],
        "materialized_troubleshooting_playbook_slugs": [],
        "materialized_policy_overlay_book_slugs": [],
        "materialized_synthesized_playbook_slugs": [],
        "visible_derived_family_counts": {
            family: 0 for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
        },
        "visible_derived_playbook_count": 0,
    }
    manifest_path = getattr(settings, "source_manifest_path", None)
    if manifest_path is None:
        return dict(empty_scope)
    path = Path(manifest_path)
    if not path.exists():
        return dict(empty_scope)

    approved_manifest_playable_family_counts: dict[str, int] = {}
    approved_entry_count = 0
    approved_manual_book_count = 0
    approved_manifest_playable_book_count = 0
    family_slug_map: dict[str, set[str]] = {
        family: set() for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    materialized_family_slug_map: dict[str, set[str]] = {
        family: set() for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    visible_family_slug_map: dict[str, set[str]] = {
        family: set() for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    for entry in read_manifest(path):
        if entry.ocp_version != settings.ocp_version:
            continue
        if entry.docs_language != settings.docs_language:
            continue
        if entry.approval_status != "approved":
            continue
        if entry.content_status != "approved_ko":
            continue
        approved_entry_count += 1
        source_type = str(entry.source_type or "official_doc").strip() or "official_doc"
        source_lane = str(entry.source_lane or "").strip()
        is_playable = source_type != "official_doc" or source_lane == "applied_playbook"
        if is_playable:
            approved_manifest_playable_book_count += 1
            approved_manifest_playable_family_counts[source_type] = (
                approved_manifest_playable_family_counts.get(source_type, 0) + 1
            )
            if source_type in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES:
                family_slug_map[source_type].add(entry.book_slug)
                visible_family_slug_map[source_type].add(entry.book_slug)
        else:
            approved_manual_book_count += 1

    materialized_derived_rows = _approved_materialized_report_derived_rows(settings)
    playable_book_count = approved_manifest_playable_book_count
    playable_family_counts = dict(approved_manifest_playable_family_counts)
    for row in materialized_derived_rows:
        slug = str(row.get("book_slug") or "").strip()
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        family = str(source_metadata.get("source_type") or "").strip()
        if not slug or family not in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES:
            continue
        materialized_family_slug_map[family].add(slug)
        if slug in visible_family_slug_map[family]:
            continue
        visible_family_slug_map[family].add(slug)
        playable_book_count += 1
        playable_family_counts[family] = playable_family_counts.get(family, 0) + 1

    approved_manifest_derived_family_counts = _derived_family_counts_payload(family_slug_map)
    materialized_derived_family_counts = _derived_family_counts_payload(materialized_family_slug_map)
    visible_derived_family_counts = _derived_family_counts_payload(visible_family_slug_map)

    approved_manifest_topic_playbook_slugs = sorted(family_slug_map[TOPIC_PLAYBOOK_SOURCE_TYPE])
    approved_manifest_operation_playbook_slugs = sorted(family_slug_map[OPERATION_PLAYBOOK_SOURCE_TYPE])
    approved_manifest_troubleshooting_playbook_slugs = sorted(family_slug_map[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE])
    approved_manifest_policy_overlay_book_slugs = sorted(family_slug_map[POLICY_OVERLAY_BOOK_SOURCE_TYPE])
    approved_manifest_synthesized_playbook_slugs = sorted(family_slug_map[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE])

    topic_playbook_slugs = sorted(materialized_family_slug_map[TOPIC_PLAYBOOK_SOURCE_TYPE])
    operation_playbook_slugs = sorted(materialized_family_slug_map[OPERATION_PLAYBOOK_SOURCE_TYPE])
    troubleshooting_playbook_slugs = sorted(materialized_family_slug_map[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE])
    policy_overlay_book_slugs = sorted(materialized_family_slug_map[POLICY_OVERLAY_BOOK_SOURCE_TYPE])
    synthesized_playbook_slugs = sorted(materialized_family_slug_map[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE])

    approved_manifest_derived_playbook_count = (
        len(approved_manifest_topic_playbook_slugs)
        + len(approved_manifest_operation_playbook_slugs)
        + len(approved_manifest_troubleshooting_playbook_slugs)
        + len(approved_manifest_policy_overlay_book_slugs)
        + len(approved_manifest_synthesized_playbook_slugs)
    )
    materialized_derived_playbook_count = (
        len(topic_playbook_slugs)
        + len(operation_playbook_slugs)
        + len(troubleshooting_playbook_slugs)
        + len(policy_overlay_book_slugs)
        + len(synthesized_playbook_slugs)
    )
    visible_derived_playbook_count = sum(visible_derived_family_counts.values())
    approved_manifest_derived_family_statuses = {
        family: _family_status_payload(
            family=family,
            slugs=sorted(family_slug_map[family]),
            present_status="approved_manifest",
            empty_status="not_in_approved_manifest",
        )
        for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    materialized_derived_family_statuses = {
        family: _family_status_payload(
            family=family,
            slugs=sorted(materialized_family_slug_map[family]),
            present_status="materialized",
            empty_status="not_materialized",
        )
        for family in REPORT_DERIVED_PLAYBOOK_SOURCE_TYPES
    }

    return {
        "approved_entry_count": approved_entry_count,
        "approved_manifest_entry_count": approved_entry_count,
        "approved_manual_book_count": approved_manual_book_count,
        "approved_manifest_manual_book_count": approved_manual_book_count,
        "approved_manifest_playable_book_count": approved_manifest_playable_book_count,
        "approved_manifest_playable_family_counts": dict(sorted(approved_manifest_playable_family_counts.items())),
        "approved_manifest_derived_family_statuses": approved_manifest_derived_family_statuses,
        "approved_manifest_derived_family_counts": approved_manifest_derived_family_counts,
        "approved_manifest_derived_playbook_count": approved_manifest_derived_playbook_count,
        "approved_manifest_topic_playbook_count": len(approved_manifest_topic_playbook_slugs),
        "approved_manifest_operation_playbook_count": len(approved_manifest_operation_playbook_slugs),
        "approved_manifest_troubleshooting_playbook_count": len(approved_manifest_troubleshooting_playbook_slugs),
        "approved_manifest_policy_overlay_book_count": len(approved_manifest_policy_overlay_book_slugs),
        "approved_manifest_synthesized_playbook_count": len(approved_manifest_synthesized_playbook_slugs),
        "approved_manifest_topic_playbook_slugs": approved_manifest_topic_playbook_slugs,
        "approved_manifest_operation_playbook_slugs": approved_manifest_operation_playbook_slugs,
        "approved_manifest_troubleshooting_playbook_slugs": approved_manifest_troubleshooting_playbook_slugs,
        "approved_manifest_policy_overlay_book_slugs": approved_manifest_policy_overlay_book_slugs,
        "approved_manifest_synthesized_playbook_slugs": approved_manifest_synthesized_playbook_slugs,
        "playable_book_count": playable_book_count,
        "playable_family_counts": dict(sorted(playable_family_counts.items())),
        "derived_family_statuses": materialized_derived_family_statuses,
        "derived_family_counts": materialized_derived_family_counts,
        "derived_playbook_count": materialized_derived_playbook_count,
        TOPIC_PLAYBOOK_SOURCE_TYPE: _family_status_payload(
            family=TOPIC_PLAYBOOK_SOURCE_TYPE,
            slugs=topic_playbook_slugs,
            present_status="materialized",
            empty_status="not_materialized",
        ),
        OPERATION_PLAYBOOK_SOURCE_TYPE: _family_status_payload(
            family=OPERATION_PLAYBOOK_SOURCE_TYPE,
            slugs=operation_playbook_slugs,
            present_status="materialized",
            empty_status="not_materialized",
        ),
        TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: _family_status_payload(
            family=TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
            slugs=troubleshooting_playbook_slugs,
            present_status="materialized",
            empty_status="not_materialized",
        ),
        POLICY_OVERLAY_BOOK_SOURCE_TYPE: _family_status_payload(
            family=POLICY_OVERLAY_BOOK_SOURCE_TYPE,
            slugs=policy_overlay_book_slugs,
            present_status="materialized",
            empty_status="not_materialized",
        ),
        SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: _family_status_payload(
            family=SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
            slugs=synthesized_playbook_slugs,
            present_status="materialized",
            empty_status="not_materialized",
        ),
        "topic_playbook_count": len(topic_playbook_slugs),
        "operation_playbook_count": len(operation_playbook_slugs),
        "troubleshooting_playbook_count": len(troubleshooting_playbook_slugs),
        "policy_overlay_book_count": len(policy_overlay_book_slugs),
        "synthesized_playbook_count": len(synthesized_playbook_slugs),
        "topic_playbook_slugs": topic_playbook_slugs,
        "operation_playbook_slugs": operation_playbook_slugs,
        "troubleshooting_playbook_slugs": troubleshooting_playbook_slugs,
        "policy_overlay_book_slugs": policy_overlay_book_slugs,
        "synthesized_playbook_slugs": synthesized_playbook_slugs,
        "materialized_derived_family_statuses": materialized_derived_family_statuses,
        "materialized_derived_family_counts": materialized_derived_family_counts,
        "materialized_derived_playbook_count": materialized_derived_playbook_count,
        "materialized_topic_playbook_count": len(topic_playbook_slugs),
        "materialized_operation_playbook_count": len(operation_playbook_slugs),
        "materialized_troubleshooting_playbook_count": len(troubleshooting_playbook_slugs),
        "materialized_policy_overlay_book_count": len(policy_overlay_book_slugs),
        "materialized_synthesized_playbook_count": len(synthesized_playbook_slugs),
        "materialized_topic_playbook_slugs": topic_playbook_slugs,
        "materialized_operation_playbook_slugs": operation_playbook_slugs,
        "materialized_troubleshooting_playbook_slugs": troubleshooting_playbook_slugs,
        "materialized_policy_overlay_book_slugs": policy_overlay_book_slugs,
        "materialized_synthesized_playbook_slugs": synthesized_playbook_slugs,
        "visible_derived_family_counts": visible_derived_family_counts,
        "visible_derived_playbook_count": visible_derived_playbook_count,
    }


def _bundle_quality_row(bundle_dir: Path, *, approved_gold_slugs: set[str]) -> dict[str, object]:
    manifest = _safe_json(bundle_dir / "bundle_manifest.json")
    dossier = _safe_json(bundle_dir / "dossier.json")
    issue_candidates = _safe_json(bundle_dir / "issue_pr_candidates.json")
    repo_artifact_count = len(manifest.get("repo_artifacts", []))
    exact_issue_pr_count = len(issue_candidates.get("exact_slug", []))
    related_issue_pr_count = len(issue_candidates.get("related_terms", []))
    ko_doc = dict(manifest.get("official_docs", {})).get("ko", {})
    en_doc = dict(manifest.get("official_docs", {})).get("en", {})
    current_status = dict(dossier.get("current_status", {}))
    content_status = str(current_status.get("content_status", ""))
    gap_lane = str(current_status.get("gap_lane", ""))
    promotion_strategy = str(current_status.get("promotion_strategy", ""))
    ko_fallback_banner = bool(ko_doc.get("contains_language_fallback_banner", False))
    has_en_html = bool(en_doc.get("artifact_path")) and int(en_doc.get("content_length", 0)) > 0
    manifest_approved = bundle_dir.name in approved_gold_slugs
    # A stale approved manifest must not hide a bundle that still needs translation/review.
    if manifest_approved and content_status == "approved_ko" and (
        not ko_fallback_banner or promotion_strategy in APPROVED_GOLD_PROMOTION_STRATEGIES
    ):
        readiness = "already_promoted"
        recommended_action = "bundle already promoted into active gold corpus/manualbook"
    elif has_en_html and content_status != "approved_ko":
        readiness = "translation_ready"
        recommended_action = (
            "translate from official EN with repo sidecars and review gate"
            if gap_lane == "translation_first" or ko_fallback_banner
            else "rebuild KO manualbook from official EN translation and harvested sidecars"
        )
    elif repo_artifact_count == 0:
        readiness = "source_expansion_needed"
        recommended_action = "expand alias/title repo search before translation or synthesis"
    else:
        readiness = "manual_review_ready"
        recommended_action = "compose reviewed KO/manualbook from harvested evidence"

    return {
        "book_slug": bundle_dir.name,
        "content_status": content_status,
        "gap_lane": gap_lane,
        "promotion_strategy": promotion_strategy,
        "ko_fallback_banner": ko_fallback_banner,
        "has_en_html": has_en_html,
        "manifest_approved": manifest_approved,
        "repo_artifact_count": repo_artifact_count,
        "exact_issue_pr_count": exact_issue_pr_count,
        "related_issue_pr_count": related_issue_pr_count,
        "readiness": readiness,
        "recommended_action": recommended_action,
    }


def build_source_bundle_quality_report(settings: Settings) -> dict[str, object]:
    root = _bundle_root(settings)
    bundles = []
    approved_gold_slugs = _approved_gold_slugs(settings)
    if root.exists():
        for bundle_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            required = [
                bundle_dir / "bundle_manifest.json",
                bundle_dir / "dossier.json",
                bundle_dir / "issue_pr_candidates.json",
            ]
            if not all(path.exists() for path in required):
                continue
            bundles.append(_bundle_quality_row(bundle_dir, approved_gold_slugs=approved_gold_slugs))

    counts = {
        "translation_ready": sum(1 for item in bundles if item["readiness"] == "translation_ready"),
        "manual_review_ready": sum(1 for item in bundles if item["readiness"] == "manual_review_ready"),
        "source_expansion_needed": sum(1 for item in bundles if item["readiness"] == "source_expansion_needed"),
        "already_promoted": sum(1 for item in bundles if item["readiness"] == "already_promoted"),
    }
    raw_manual_count = _raw_manual_count(settings, len(bundles))
    approved_scope = _approved_pack_scope(settings)
    playable_asset_multiplication = _playable_asset_multiplication(
        raw_manual_count=raw_manual_count,
        approved_manual_book_count=int(approved_scope["approved_manual_book_count"]),
        playable_book_count=int(approved_scope["playable_book_count"]),
        derived_playbook_count=int(approved_scope["derived_playbook_count"]),
    )
    promotion_queue_count = (
        counts["translation_ready"]
        + counts["manual_review_ready"]
        + counts["source_expansion_needed"]
    )
    limits: list[str] = []
    materialized_derived_family_counts = dict(approved_scope["materialized_derived_family_counts"])
    if int(materialized_derived_family_counts[TOPIC_PLAYBOOK_SOURCE_TYPE]) == 0:
        limits.append("topic playbook family is not emitted yet; playable books currently reflect approved manual_synthesis only")
    if int(materialized_derived_family_counts[OPERATION_PLAYBOOK_SOURCE_TYPE]) == 0:
        limits.append("operation playbook family is not emitted yet; approved playable books still underrepresent 운영 runbook outputs")
    if int(materialized_derived_family_counts[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE]) == 0:
        limits.append("troubleshooting playbook family is not emitted yet; approved playable books still underrepresent 장애 대응 outputs")
    if int(materialized_derived_family_counts[POLICY_OVERLAY_BOOK_SOURCE_TYPE]) == 0:
        limits.append("policy overlay book family is not emitted yet; approved playable books still underrepresent customer/policy overlay outputs")
    if int(materialized_derived_family_counts[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE]) == 0:
        limits.append("synthesized playbook family is not emitted yet; approved playable books still underrepresent cross-manual synthesis outputs")
    if counts["source_expansion_needed"] > 0:
        limits.append("some raw manuals still need source expansion before they can enter translation or reviewed synthesis")
    materialized_family_breakdown = ", ".join(
        f"{family} {count}"
        for family, count in materialized_derived_family_counts.items()
    )
    approved_manifest_family_breakdown = ", ".join(
        f"{family} {count}"
        for family, count in dict(approved_scope["approved_manifest_derived_family_counts"]).items()
    )
    scope_verdict = (
        f"{playable_asset_multiplication['approved_playable_asset_count']} approved playable assets "
        f"({approved_scope['approved_manual_book_count']} manual books + "
        f"{approved_scope['visible_derived_playbook_count']} visible derived family books inside "
        f"{approved_scope['playable_book_count']} playable books; "
        f"approved manifest derived {approved_scope['approved_manifest_derived_playbook_count']} "
        f"({approved_manifest_family_breakdown}); "
        f"materialized derived {approved_scope['materialized_derived_playbook_count']} "
        f"({materialized_family_breakdown})) are visible now; "
        f"{promotion_queue_count} raw manuals remain in the bronze bundle readiness queue."
    )
    return {
        "bundle_count": len(bundles),
        "counts": counts,
        "approved_manifest_derived_playbook_count": approved_scope["approved_manifest_derived_playbook_count"],
        "approved_manifest_derived_family_counts": approved_scope["approved_manifest_derived_family_counts"],
        "materialized_derived_playbook_count": approved_scope["materialized_derived_playbook_count"],
        "materialized_derived_family_counts": approved_scope["materialized_derived_family_counts"],
        "visible_derived_playbook_count": approved_scope["visible_derived_playbook_count"],
        "visible_derived_family_counts": approved_scope["visible_derived_family_counts"],
        "derived_family_counts": approved_scope["derived_family_counts"],
        "buyer_scope": {
            "pack_id": settings.active_pack_id,
            "pack_label": settings.active_pack_label,
            "ocp_version": settings.ocp_version,
            "docs_language": settings.docs_language,
            "raw_manual_count": raw_manual_count,
            "approved_manual_book_count": approved_scope["approved_manual_book_count"],
            "approved_manifest_manual_book_count": approved_scope["approved_manifest_manual_book_count"],
            "playable_book_count": approved_scope["playable_book_count"],
            "approved_manifest_playable_book_count": approved_scope["approved_manifest_playable_book_count"],
            "approved_entry_count": approved_scope["approved_entry_count"],
            "approved_manifest_entry_count": approved_scope["approved_manifest_entry_count"],
            "topic_playbook_count": approved_scope["topic_playbook_count"],
            "operation_playbook_count": approved_scope["operation_playbook_count"],
            "troubleshooting_playbook_count": approved_scope["troubleshooting_playbook_count"],
            "policy_overlay_book_count": approved_scope["policy_overlay_book_count"],
            "synthesized_playbook_count": approved_scope["synthesized_playbook_count"],
            "derived_playbook_count": approved_scope["derived_playbook_count"],
            "derived_family_statuses": approved_scope["derived_family_statuses"],
            "derived_family_counts": approved_scope["derived_family_counts"],
            "approved_manifest_derived_family_statuses": approved_scope["approved_manifest_derived_family_statuses"],
            "approved_manifest_derived_family_counts": approved_scope["approved_manifest_derived_family_counts"],
            "approved_manifest_derived_playbook_count": approved_scope["approved_manifest_derived_playbook_count"],
            "approved_manifest_topic_playbook_count": approved_scope["approved_manifest_topic_playbook_count"],
            "approved_manifest_operation_playbook_count": approved_scope["approved_manifest_operation_playbook_count"],
            "approved_manifest_troubleshooting_playbook_count": approved_scope["approved_manifest_troubleshooting_playbook_count"],
            "approved_manifest_policy_overlay_book_count": approved_scope["approved_manifest_policy_overlay_book_count"],
            "approved_manifest_synthesized_playbook_count": approved_scope["approved_manifest_synthesized_playbook_count"],
            "materialized_derived_family_statuses": approved_scope["materialized_derived_family_statuses"],
            "materialized_derived_family_counts": approved_scope["materialized_derived_family_counts"],
            "materialized_derived_playbook_count": approved_scope["materialized_derived_playbook_count"],
            "materialized_topic_playbook_count": approved_scope["materialized_topic_playbook_count"],
            "materialized_operation_playbook_count": approved_scope["materialized_operation_playbook_count"],
            "materialized_troubleshooting_playbook_count": approved_scope["materialized_troubleshooting_playbook_count"],
            "materialized_policy_overlay_book_count": approved_scope["materialized_policy_overlay_book_count"],
            "materialized_synthesized_playbook_count": approved_scope["materialized_synthesized_playbook_count"],
            "visible_derived_family_counts": approved_scope["visible_derived_family_counts"],
            "visible_derived_playbook_count": approved_scope["visible_derived_playbook_count"],
            "topic_playbook_slugs": approved_scope["topic_playbook_slugs"],
            "operation_playbook_slugs": approved_scope["operation_playbook_slugs"],
            "troubleshooting_playbook_slugs": approved_scope["troubleshooting_playbook_slugs"],
            "policy_overlay_book_slugs": approved_scope["policy_overlay_book_slugs"],
            "synthesized_playbook_slugs": approved_scope["synthesized_playbook_slugs"],
            "approved_manifest_topic_playbook_slugs": approved_scope["approved_manifest_topic_playbook_slugs"],
            "approved_manifest_operation_playbook_slugs": approved_scope["approved_manifest_operation_playbook_slugs"],
            "approved_manifest_troubleshooting_playbook_slugs": approved_scope["approved_manifest_troubleshooting_playbook_slugs"],
            "approved_manifest_policy_overlay_book_slugs": approved_scope["approved_manifest_policy_overlay_book_slugs"],
            "approved_manifest_synthesized_playbook_slugs": approved_scope["approved_manifest_synthesized_playbook_slugs"],
            "materialized_topic_playbook_slugs": approved_scope["materialized_topic_playbook_slugs"],
            "materialized_operation_playbook_slugs": approved_scope["materialized_operation_playbook_slugs"],
            "materialized_troubleshooting_playbook_slugs": approved_scope["materialized_troubleshooting_playbook_slugs"],
            "materialized_policy_overlay_book_slugs": approved_scope["materialized_policy_overlay_book_slugs"],
            "materialized_synthesized_playbook_slugs": approved_scope["materialized_synthesized_playbook_slugs"],
            "playable_family_counts": approved_scope["playable_family_counts"],
            "approved_manifest_playable_family_counts": approved_scope["approved_manifest_playable_family_counts"],
            "playable_asset_count": playable_asset_multiplication["approved_playable_asset_count"],
            "playable_asset_multiplication": playable_asset_multiplication,
            "promotion_queue_count": promotion_queue_count,
            "queue_scope": "bronze_bundle_readiness",
            "translation_ready_count": counts["translation_ready"],
            "manual_review_ready_count": counts["manual_review_ready"],
            "source_expansion_needed_count": counts["source_expansion_needed"],
            "scope_verdict": scope_verdict,
            "limits": limits,
        },
        "bundles": bundles,
    }
