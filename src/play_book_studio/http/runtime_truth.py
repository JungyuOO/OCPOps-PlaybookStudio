from __future__ import annotations

from typing import Any

from play_book_studio.config.settings import Settings


def _normalized(value: object) -> str:
    return str(value or "").strip()


def _is_source_first_candidate(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    promotion_strategy = _normalized(entry.get("promotion_strategy")).lower()
    if promotion_strategy == "full_rebuild_source_repo_binding":
        return True
    source_lane = _normalized(entry.get("source_lane")).lower()
    boundary_truth = _normalized(entry.get("boundary_truth")).lower()
    return source_lane == "official_source_first_candidate" or boundary_truth == "official_candidate_runtime"


def _is_approved_ko(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    for key in ("content_status", "translation_status", "translation_stage"):
        if _normalized(entry.get(key)).lower() == "approved_ko":
            return True
    return False


def official_runtime_grade(entry: dict[str, Any]) -> str:
    if _is_approved_ko(entry):
        return "Gold"
    source_type = _normalized(entry.get("source_type"))
    if source_type in {
        "topic_playbook",
        "operation_playbook",
        "troubleshooting_playbook",
        "policy_overlay_book",
        "synthesized_playbook",
    }:
        return "Bronze"
    return "Silver"


def official_runtime_truth_payload(*, settings: Settings, manifest_entry: dict[str, Any]) -> dict[str, str]:
    pack_label = _normalized(manifest_entry.get("pack_label")) or _normalized(settings.active_pack.pack_label)
    approval_state = _normalized(manifest_entry.get("approval_state") or manifest_entry.get("approval_status"))
    publication_state = _normalized(manifest_entry.get("publication_state"))
    parser_backend = _normalized(manifest_entry.get("parser_backend"))
    source_lane = _normalized(manifest_entry.get("source_lane"))
    if _is_approved_ko(manifest_entry):
        runtime_truth_label = f"{pack_label} Gold Playbook" if pack_label else "Gold Playbook"
        return {
            "source_lane": source_lane,
            "approval_state": approval_state or "approved",
            "publication_state": publication_state or "active",
            "parser_backend": parser_backend,
            "boundary_truth": "official_gold_playbook_runtime",
            "runtime_truth_label": runtime_truth_label,
            "boundary_badge": "Gold Playbook",
        }
    if _is_source_first_candidate(manifest_entry):
        runtime_truth_label = f"{pack_label} Source-First Candidate" if pack_label else "Source-First Candidate"
        return {
            "source_lane": "official_source_first_candidate",
            "approval_state": "",
            "publication_state": publication_state or "active",
            "parser_backend": parser_backend,
            "boundary_truth": "official_candidate_runtime",
            "runtime_truth_label": runtime_truth_label,
            "boundary_badge": "Source-First Candidate",
        }
    runtime_truth_label = f"{pack_label} Source-First Candidate" if pack_label else "Source-First Candidate"
    return {
        "source_lane": source_lane,
        "approval_state": approval_state,
        "publication_state": publication_state or "active",
        "parser_backend": parser_backend,
        "boundary_truth": "official_candidate_runtime",
        "runtime_truth_label": runtime_truth_label,
        "boundary_badge": "Source-First Candidate",
    }


__all__ = ["official_runtime_grade", "official_runtime_truth_payload"]
