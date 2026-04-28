from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.source_authority import source_authority_payload


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _official_candidates(root_dir: Path, *, query: str, limit: int) -> list[dict[str, Any]]:
    try:
        from play_book_studio.app.server_routes_ops import _search_official_source_candidates

        rows = _search_official_source_candidates(root_dir, query=query, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        authority = source_authority_payload(
            {
                **row,
                "current_source_basis": _clean(row.get("current_source_basis")) or "official_candidate",
                "source_collection": "core",
            }
        )
        normalized.append(
            {
                **row,
                **authority,
                "candidate_kind": "official_source_candidate",
                "materialize_endpoint": "/api/repositories/official-materialize",
                "accepted_source_basis": ["official_homepage", "official_repo"],
            }
        )
    return normalized


def build_gap_repair_plan(root_dir: Path, *, query: str, limit: int = 5) -> dict[str, Any]:
    normalized_query = _clean(query)
    official_candidates = _official_candidates(root_dir, query=normalized_query, limit=limit)
    state = "ready_to_materialize_official" if official_candidates else "needs_community_source_selection"
    return {
        "state": state,
        "query": normalized_query,
        "source_policy": {
            "priority_order": ["official", "customer_private", "community"],
            "community_rule": "Allowed when useful, but must be labeled Community Source and review-required.",
            "private_rule": "Customer material stays inside the approved private project boundary.",
        },
        "official_candidates": official_candidates,
        "community_search": {
            "endpoint": "/api/repositories/search",
            "query": normalized_query,
            "authority_after_selection": source_authority_payload({"source_authority": "community"}),
            "materialization_status": "selection_required",
            "note": "GitHub/community results are candidates; they are not official until explicitly reviewed.",
        },
        "materialization_routes": [
            {
                "authority": "official",
                "endpoint": "/api/repositories/official-materialize",
                "method": "POST",
                "required_fields": ["book_slug", "source_basis"],
                "postcondition": "draft generation, Gold promotion, Qdrant sync, viewer/source-meta smoke pass",
            },
            {
                "authority": "community",
                "endpoint": "/api/customer-packs/ingest",
                "method": "POST",
                "required_fields": ["title", "source_type", "uri"],
                "accepted_aliases": {"uri": ["source_url"]},
                "postcondition": "captured/normalized private or community-labeled draft enters retrieval with review required",
            },
        ],
        "closed_loop_acceptance": [
            "no_answer_recorded",
            "source_candidates_found",
            "selected_source_materialized_to_library",
            "same_chat_query_rerun",
            "rerun_response_kind_not_no_answer",
            "rerun_has_at_least_one_landing_citation",
        ],
    }
