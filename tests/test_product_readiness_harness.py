from __future__ import annotations

from pathlib import Path

from play_book_studio.app.data_control_room import build_data_control_room_payload


ROOT = Path(__file__).resolve().parents[1]


def _books(payload: dict, key: str) -> list[dict]:
    section = payload.get(key)
    assert isinstance(section, dict), f"{key} payload must be an object"
    books = section.get("books")
    assert isinstance(books, list), f"{key}.books must be a list"
    return books


def _official_candidate_count(payload: dict) -> int:
    candidates = (
        payload["source_of_truth_drift"]["storage_drift"]["playbooks"]["candidates"]
    )
    for candidate in candidates:
        path = str(candidate.get("path", ""))
        if "repo_wide_official_source" in path:
            return int(candidate.get("file_count", 0))
    raise AssertionError("official playbook candidate directory was not reported")


def test_runtime_catalog_contract_matches_visible_product_counts() -> None:
    payload = build_data_control_room_payload(ROOT)
    summary = payload["summary"]

    official_candidate_count = _official_candidate_count(payload)
    official_gold_visible_count = len(_books(payload, "approved_wiki_runtime_books"))
    official_hidden_count = official_candidate_count - official_gold_visible_count
    customer_runtime_count = len(_books(payload, "customer_pack_runtime_books"))
    custom_documents = payload["custom_documents"]

    assert official_candidate_count == 113
    assert official_gold_visible_count == 41
    assert official_hidden_count == 72
    assert customer_runtime_count == 85
    assert summary["customer_pack_runtime_book_count"] == 85
    assert summary["user_library_book_count"] == 15
    assert summary["derived_playbook_count"] == 70
    assert summary["topic_playbook_count"] == 14
    assert summary["operation_playbook_count"] == 14
    assert summary["troubleshooting_playbook_count"] == 14
    assert summary["policy_overlay_book_count"] == 14
    assert summary["synthesized_playbook_count"] == 14
    assert custom_documents["slot_count"] == 4
    assert custom_documents["source_count"] == 12


def test_incompatible_generated_reports_do_not_override_runtime_catalog() -> None:
    payload = build_data_control_room_payload(ROOT)

    assert payload["canonical_grade_source"]["exists"] is False
    assert payload["reports"]["source_approval"]["path"] == ""
    assert payload["reports"]["translation_lane"]["path"] == ""
    assert len(_books(payload, "approved_wiki_runtime_books")) == 41
    assert len(_books(payload, "customer_pack_runtime_books")) == 85
