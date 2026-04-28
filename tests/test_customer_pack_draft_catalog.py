from __future__ import annotations

from play_book_studio.app.source_books_customer_pack import (
    deduplicate_customer_pack_draft_summaries,
)


def test_customer_pack_draft_catalog_deduplicates_repeated_uploaded_files() -> None:
    stale = {
        "draft_id": "dtb-stale",
        "source_type": "pptx",
        "title": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL",
        "book_slug": "kmsc-cocp-recr-005-아키텍처설계서-cicd-20251208-final",
        "uploaded_file_name": "KMSC-COCP-RECR-005_아키텍처설계서_CICD_20251208_FINAL.pptx",
        "status": "normalized",
        "updated_at": "2026-04-23T12:43:35Z",
        "created_at": "2026-04-23T06:09:37Z",
        "read_ready": True,
        "publish_ready": True,
        "quality_status": "ready",
        "shared_grade": "gold",
        "playable_asset_count": 1,
    }
    current = {
        **stale,
        "draft_id": "dtb-current",
        "updated_at": "2026-04-23T13:53:28Z",
        "created_at": "2026-04-23T08:00:23Z",
        "playable_asset_count": 6,
    }
    unrelated = {
        **stale,
        "draft_id": "dtb-unrelated",
        "title": "KOMSCO 지급결제플랫폼 OCP 운영 플레이북",
        "book_slug": "customer-master-kmsc-ocp-operations-playbook",
        "uploaded_file_name": "",
        "source_type": "md",
    }

    deduped = deduplicate_customer_pack_draft_summaries([stale, unrelated, current])

    assert [draft["draft_id"] for draft in deduped] == ["dtb-current", "dtb-unrelated"]


def test_customer_pack_draft_catalog_keeps_named_test_runs_with_same_fingerprint() -> None:
    base = {
        "source_type": "pptx",
        "source_fingerprint": "same-upload",
        "book_slug": "test-1-surya",
        "status": "normalized",
        "updated_at": "2026-04-23T13:53:28Z",
        "created_at": "2026-04-23T08:00:23Z",
        "read_ready": True,
        "publish_ready": True,
        "quality_status": "ready",
        "shared_grade": "gold",
        "playable_asset_count": 6,
    }
    test_one = {
        **base,
        "draft_id": "dtb-test-one",
        "title": "Test 1 - Surya",
    }
    test_two = {
        **base,
        "draft_id": "dtb-test-two",
        "book_slug": "test-2-qwen",
        "title": "Test 2 - Qwen",
    }

    deduped = deduplicate_customer_pack_draft_summaries([test_one, test_two])

    assert [draft["draft_id"] for draft in deduped] == ["dtb-test-one", "dtb-test-two"]
