from __future__ import annotations

from types import SimpleNamespace

import play_book_studio.http.data_control_room as data_control_room
import play_book_studio.http.data_control_room_buckets as buckets
from play_book_studio.http.data_control_room_helpers import _summarize_eval
from play_book_studio.http.runtime_truth import official_runtime_grade


def _settings(root):
    return SimpleNamespace(
        active_pack=SimpleNamespace(pack_label="Unit Test Pack"),
        database_url="",
        source_manifest_path=root / "missing-source-manifest.json",
        ocp_version="4.20",
        book_url_template="https://docs.example.test/{slug}",
    )


def _db_settings(root):
    settings = _settings(root)
    settings.database_url = "postgresql://unit-test"
    return settings


def _control_room_settings(root):
    artifacts_dir = root / "artifacts"
    runtime_dir = artifacts_dir / "runtime"
    return SimpleNamespace(
        active_pack=SimpleNamespace(pack_label="Unit Test Pack"),
        app_id="play-book-studio",
        app_label="Play Book Studio",
        active_pack_id="unit-pack",
        active_pack_label="Unit Pack",
        database_url="",
        qdrant_collection="openshift_docs",
        source_manifest_path=root / "corpus" / "manifest.json",
        source_approval_report_path=root / "reports" / "source_approval.json",
        translation_lane_report_path=root / "reports" / "translation_lane.json",
        retrieval_eval_report_path=root / "reports" / "retrieval_eval.json",
        answer_eval_report_path=root / "reports" / "answer_eval.json",
        ragas_eval_report_path=root / "reports" / "ragas_eval.json",
        runtime_report_path=root / "reports" / "runtime_report.json",
        chunks_path=root / "corpus" / "chunks.jsonl",
        customer_pack_books_dir=artifacts_dir / "customer_packs" / "books",
        customer_pack_corpus_dir=artifacts_dir / "customer_packs" / "corpus",
        playbook_book_dirs=(root / "corpus" / "manualbooks",),
        runtime_dir=runtime_dir,
        normalized_docs_candidates=(root / "data" / "silver" / "normalized_docs.jsonl",),
        retrieval_normalized_docs_candidates=(
            artifacts_dir / "official_lane" / "repo_wide_official_source" / "normalized_docs.jsonl",
        ),
        ocp_version="4.20",
        docs_language="ko",
        viewer_path_prefix="/docs/ocp/4.20/ko/",
        artifacts_dir=artifacts_dir,
        book_url_template="https://docs.example.test/{slug}",
    )


class _EmptyDraftStore:
    def __init__(self, root):
        self.root = root

    def list(self):
        return []


def _viewer_smoke_pass(_root, viewer_path, *, expected_title=""):
    return {
        "viewer_smoke_status": "pass",
        "viewer_smoke_reason": "",
        "viewer_smoke_path": str(viewer_path or ""),
        "viewer_smoke_body_length": 128,
        "viewer_smoke_heading_count": 2,
        "viewer_smoke_title_present": bool(expected_title),
    }


def test_approved_wiki_runtime_bucket_hides_unreadable_gold_books(monkeypatch, tmp_path) -> None:
    good_viewer = tmp_path / "artifacts" / "runtime" / "served_viewers" / "docs" / "ocp" / "good_book" / "index.html"
    good_viewer.parent.mkdir(parents=True, exist_ok=True)
    good_viewer.write_text("<html><body><main>Readable content</main></body></html>", encoding="utf-8")
    other_viewer = tmp_path / "artifacts" / "runtime" / "served_viewers" / "docs" / "ocp" / "other_book" / "index.html"
    other_viewer.parent.mkdir(parents=True, exist_ok=True)
    other_viewer.write_text("<html><body><main>Other readable content</main></body></html>", encoding="utf-8")

    monkeypatch.setattr(buckets, "load_settings", _settings)
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)
    monkeypatch.setattr(
        buckets,
        "official_runtime_books",
        lambda _root: [
            {
                "book_slug": "good_book",
                "title": "Good Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/good_book",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 1.0,
                "section_count": 3,
                "chunk_count": 3,
                "viewer_path": "/docs/ocp/4.20/ko/good_book/index.html",
            },
            {
                "book_slug": "empty_book",
                "title": "Empty Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/empty_book",
                "source_lane": "official_ko",
                "section_count": 0,
                "viewer_path": "/docs/ocp/4.20/ko/empty_book/index.html",
            },
            {
                "book_slug": "missing_viewer_book",
                "title": "Missing Viewer Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/missing_viewer_book",
                "source_lane": "official_ko",
                "section_count": 2,
                "chunk_count": 2,
            },
            {
                "book_slug": "missing_artifact_book",
                "title": "Missing Artifact Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/missing_artifact_book",
                "source_lane": "official_ko",
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/docs/ocp/4.20/ko/missing_artifact_book/index.html",
            },
            {
                "book_slug": "misrouted_book",
                "title": "Misrouted Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/misrouted_book",
                "source_lane": "official_ko",
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/docs/ocp/4.20/ko/other_book/index.html",
            },
            {
                "book_slug": "unknown_route_book",
                "title": "Unknown Route Book",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/unknown_route_book",
                "source_lane": "official_ko",
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/broken/unknown_route_book/index.html",
            },
        ],
    )

    payload = buckets._build_approved_wiki_runtime_book_bucket(tmp_path, translation_lane_report={})

    assert [book["book_slug"] for book in payload["books"]] == ["good_book"]
    assert payload["books"][0]["runtime_readable"] is True
    assert payload["books"][0]["runtime_gate"] == "operational_wiki_published"
    assert payload["books"][0]["runtime_readiness"] == "route_and_artifact_passed"
    assert payload["books"][0]["gold_contract_status"] == "gold_certified"
    assert payload["books"][0]["certified_gold"] is True

    hidden_by_slug = {book["book_slug"]: book for book in payload["hidden_books"]}
    assert hidden_by_slug["empty_book"]["hidden_reason"] == "runtime_not_readable::zero_sections"
    assert hidden_by_slug["empty_book"]["grade"] == "Gold Recovery"
    assert hidden_by_slug["empty_book"]["gold_contract_status"] == "gold_recovery"
    assert hidden_by_slug["empty_book"]["gold_build_status"] == "needs_manual_repair"
    assert hidden_by_slug["empty_book"]["repair_actions"][0]["id"] == "semantic_section_rebuild"
    assert hidden_by_slug["missing_viewer_book"]["hidden_reason"] == "runtime_not_readable::missing_viewer_path"
    assert hidden_by_slug["missing_artifact_book"]["hidden_reason"] == "runtime_not_readable::missing_runtime_artifact"
    assert hidden_by_slug["misrouted_book"]["hidden_reason"] == "runtime_not_readable::viewer_slug_mismatch"
    assert hidden_by_slug["unknown_route_book"]["hidden_reason"] == "runtime_not_readable::unknown_viewer_route"
    assert payload["recovery_count"] == payload["hidden_count"]
    assert payload["recovery_books"] == payload["hidden_books"]
    assert "Gold Build Repair Queue" in payload["surface_policy"]


def test_approved_wiki_runtime_bucket_keeps_db_gold_grade(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _db_settings)
    monkeypatch.setattr(buckets, "official_runtime_books", lambda _root: [])
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[
            {
                "book_slug": "db_gold",
                "title": "DB Gold",
                "grade": "Gold",
                "section_count": 3,
                "chunk_count": 9,
                "source_url": "https://docs.example.test/db_gold",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 1.0,
                "viewer_path": "/docs/ocp/4.20/ko/db_gold/index.html",
            }
        ],
    )

    assert [
        (
            book["book_slug"],
            book["grade"],
            book["runtime_readable"],
            book["boundary_truth"],
            book["boundary_badge"],
        )
        for book in payload["books"]
    ] == [
        ("db_gold", "Gold", True, "official_gold_playbook_runtime", "Gold Playbook")
    ]


def test_approved_wiki_runtime_bucket_hides_non_korean_db_gold(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _db_settings)
    monkeypatch.setattr(buckets, "official_runtime_books", lambda _root: [])
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[
            {
                "book_slug": "english_gold",
                "title": "English Gold",
                "grade": "Gold",
                "section_count": 3,
                "chunk_count": 20,
                "source_url": "https://docs.example.test/english_gold",
                "source_lane": "official_ko",
                "hangul_chunk_count": 0,
                "hangul_chunk_ratio": 0.0,
                "body_language_guess": "en_only",
                "viewer_path": "/docs/ocp/4.20/ko/english_gold/index.html",
            }
        ],
    )

    assert payload["books"] == []
    assert payload["hidden_count"] == 1
    assert payload["hidden_books"][0]["hidden_reason"] == "runtime_not_readable::non_ko_content"
    assert payload["hidden_books"][0]["language_gate_status"] == "fail"
    assert payload["hidden_books"][0]["hangul_chunk_ratio"] == 0.0
    assert payload["hidden_books"][0]["viewer_smoke_status"] == "skipped"


def test_non_gold_zero_section_recovery_prioritizes_materialization(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _db_settings)
    monkeypatch.setattr(
        buckets,
        "official_runtime_books",
        lambda _root: [
            {
                "book_slug": "zero_runtime",
                "title": "Zero Runtime",
                "grade": "Silver",
                "section_count": 0,
                "chunk_count": 0,
                "source_url": "https://docs.example.test/zero_runtime",
                "source_lane": "official_ko",
                "viewer_path": "/docs/ocp/4.20/ko/zero_runtime/index.html",
            }
        ],
    )
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[],
    )

    recovery = payload["hidden_books"][0]

    assert recovery["hidden_reason"] == "zero_sections"
    assert recovery["gold_recovery_group"] == "materialization"
    assert recovery["gold_recovery_action"] == "문서 파싱/section materialize 재실행 필요"
    assert recovery["gold_recovery_blocking_check"] == "section_count > 0, chunk_count > 0, viewer_smoke_status=pass"
    assert "source-approval-report" in recovery["gold_recovery_rerun_command"]
    assert recovery["gold_contract_blockers"][:3] == ["zero_sections", "zero_chunks", "language_gate_missing"]
    assert "not_gold_source_grade" in recovery["gold_contract_blockers"]


def test_runtime_truth_grades_approved_ko_approved_as_gold() -> None:
    assert official_runtime_grade(
        {
            "content_status": "approved_ko",
            "approval_status": "approved",
        }
    ) == "Gold"
    assert official_runtime_grade(
        {
            "content_status": "approved_ko",
            "approval_status": "needs_review",
        }
    ) == "Silver"


def test_runtime_book_uses_manifest_language_evidence(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _db_settings)
    monkeypatch.setattr(
        buckets,
        "official_runtime_books",
        lambda _root: [
            {
                "book_slug": "runtime_english",
                "title": "Runtime English",
                "content_status": "approved_ko",
                "source_url": "https://docs.example.test/runtime_english",
                "source_lane": "official_ko",
                "section_count": 3,
                "viewer_path": "/docs/ocp/4.20/ko/runtime_english/index.html",
            }
        ],
    )
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[
            {
                "book_slug": "runtime_english",
                "title": "Runtime English",
                "grade": "Gold",
                "section_count": 3,
                "chunk_count": 20,
                "source_url": "https://docs.example.test/runtime_english",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 0.0,
                "body_language_guess": "en_only",
                "viewer_path": "/docs/ocp/4.20/ko/runtime_english/index.html",
            }
        ],
    )

    assert payload["books"] == []
    assert [book["book_slug"] for book in payload["hidden_books"]] == ["runtime_english"]
    assert payload["hidden_books"][0]["hidden_reason"] == "runtime_not_readable::non_ko_content"
    assert payload["hidden_books"][0]["body_language_guess"] == "en_only"


def test_approved_wiki_runtime_bucket_marks_mixed_korean_gold_for_review(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _db_settings)
    monkeypatch.setattr(buckets, "official_runtime_books", lambda _root: [])
    monkeypatch.setattr(buckets, "_viewer_document_smoke", _viewer_smoke_pass)

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[
            {
                "book_slug": "mixed_gold",
                "title": "Mixed Gold",
                "grade": "Gold",
                "section_count": 3,
                "chunk_count": 20,
                "source_url": "https://docs.example.test/mixed_gold",
                "source_lane": "official_ko",
                "hangul_chunk_count": 12,
                "hangul_chunk_ratio": 0.6,
                "body_language_guess": "mixed",
                "viewer_path": "/docs/ocp/4.20/ko/mixed_gold/index.html",
            }
        ],
    )

    assert payload["books"] == []
    assert [book["book_slug"] for book in payload["hidden_books"]] == ["mixed_gold"]
    assert payload["hidden_books"][0]["language_gate_status"] == "warning"
    assert payload["hidden_books"][0]["language_gate_reason"] == "mixed_ko_content"
    assert payload["hidden_books"][0]["gold_contract_status"] == "gold_recovery"
    assert payload["hidden_books"][0]["hangul_chunk_ratio"] == 0.6


def test_approved_wiki_runtime_bucket_hides_viewer_smoke_failures(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _settings)
    monkeypatch.setattr(buckets, "_local_runtime_artifact_exists", lambda _root, _viewer_path, _slug: True)
    monkeypatch.setattr(
        buckets,
        "official_runtime_books",
        lambda _root: [
            {
                "book_slug": "smoke_ok",
                "title": "Smoke OK",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/smoke_ok",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 1.0,
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/docs/ocp/4.20/ko/smoke_ok/index.html",
            },
            {
                "book_slug": "smoke_bad",
                "title": "Smoke Bad",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/smoke_bad",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 1.0,
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/docs/ocp/4.20/ko/smoke_bad/index.html",
            },
        ],
    )

    def smoke(_root, viewer_path, *, expected_title=""):
        if "smoke_bad" in viewer_path:
            return {
                "viewer_smoke_status": "fail",
                "viewer_smoke_reason": "viewer_404",
                "viewer_smoke_path": viewer_path,
                "viewer_smoke_body_length": 0,
                "viewer_smoke_heading_count": 0,
                "viewer_smoke_title_present": False,
            }
        return _viewer_smoke_pass(_root, viewer_path, expected_title=expected_title)

    monkeypatch.setattr(buckets, "_viewer_document_smoke", smoke)

    payload = buckets._build_approved_wiki_runtime_book_bucket(tmp_path, translation_lane_report={})

    assert [book["book_slug"] for book in payload["books"]] == ["smoke_ok"]
    assert payload["books"][0]["viewer_smoke_status"] == "pass"
    hidden_by_slug = {book["book_slug"]: book for book in payload["hidden_books"]}
    assert hidden_by_slug["smoke_bad"]["hidden_reason"] == "runtime_not_readable::viewer_404"
    assert hidden_by_slug["smoke_bad"]["viewer_smoke_reason"] == "viewer_404"


def test_runtime_hidden_slug_is_not_reintroduced_from_manifest(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(buckets, "load_settings", _settings)
    monkeypatch.setattr(buckets, "_local_runtime_artifact_exists", lambda _root, _viewer_path, _slug: True)
    monkeypatch.setattr(
        buckets,
        "official_runtime_books",
        lambda _root: [
            {
                "book_slug": "same_slug",
                "title": "Runtime Broken",
                "content_status": "approved_ko",
                "grade": "Gold",
                "source_url": "https://docs.example.test/same_slug",
                "source_lane": "official_ko",
                "section_count": 2,
                "chunk_count": 2,
                "viewer_path": "/docs/ocp/4.20/ko/same_slug/index.html",
            }
        ],
    )
    monkeypatch.setattr(
        buckets,
        "_viewer_document_smoke",
        lambda _root, viewer_path, *, expected_title="": {
            "viewer_smoke_status": "fail",
            "viewer_smoke_reason": "viewer_404",
            "viewer_smoke_path": viewer_path,
            "viewer_smoke_body_length": 0,
            "viewer_smoke_heading_count": 0,
            "viewer_smoke_title_present": False,
        },
    )

    payload = buckets._build_approved_wiki_runtime_book_bucket(
        tmp_path,
        translation_lane_report={},
        approved_manifest_entries=[
            {
                "book_slug": "same_slug",
                "title": "Manifest Would Pass",
                "grade": "Gold",
                "section_count": 3,
                "chunk_count": 3,
                "source_url": "https://docs.example.test/same_slug",
                "source_lane": "official_ko",
                "hangul_chunk_ratio": 1.0,
                "viewer_path": "/docs/ocp/4.20/ko/same_slug/index.html",
            }
        ],
    )

    assert payload["books"] == []
    assert [book["book_slug"] for book in payload["hidden_books"]] == ["same_slug"]
    assert payload["hidden_books"][0]["hidden_reason"] == "runtime_not_readable::viewer_404"


def test_viewer_document_smoke_warns_when_title_not_exactly_rendered(tmp_path) -> None:
    viewer = tmp_path / "artifacts" / "runtime" / "served_viewers" / "docs" / "ocp" / "smoke_title" / "index.html"
    viewer.parent.mkdir(parents=True, exist_ok=True)
    viewer.write_text(
        "<html><body><main><h1>다른 제목</h1><h2>본문</h2><p>읽을 수 있는 운영 위키 본문입니다.</p></main></body></html>",
        encoding="utf-8",
    )

    smoke = buckets._viewer_document_smoke(
        tmp_path,
        "/docs/ocp/4.20/ko/smoke_title/index.html",
        expected_title="정확히 일치하지 않는 제목",
    )

    assert smoke["viewer_smoke_status"] == "pass"
    assert smoke["viewer_smoke_warning"] == "viewer_title_not_matched"
    assert smoke["viewer_smoke_heading_count"] == 2


def test_directory_fingerprint_changes_when_runtime_artifact_changes(tmp_path) -> None:
    served_viewers = tmp_path / "artifacts" / "runtime" / "served_viewers"
    served_viewers.mkdir(parents=True)

    before = data_control_room._path_fingerprint(served_viewers)
    artifact = served_viewers / "docs" / "ocp" / "4.20" / "ko" / "networking" / "index.html"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("<main>networking</main>", encoding="utf-8")
    after = data_control_room._path_fingerprint(served_viewers)

    assert before != after


def test_data_control_room_top_level_gold_books_use_gated_runtime_bucket(monkeypatch, tmp_path) -> None:
    source_only_gold = {
        "book_slug": "source_only_gold",
        "title": "Source Only Gold",
        "content_status": "approved_ko",
        "source_url": "https://docs.example.test/source_only_gold",
        "source_lane": "official_ko",
        "approval_status": "approved",
        "section_count": 1,
        "viewer_path": "/docs/ocp/4.20/ko/source_only_gold/index.html",
    }
    gated_gold = {
        "book_slug": "gated_gold",
        "title": "Gated Gold",
        "grade": "Gold",
        "review_status": "active_runtime",
        "source_type": "official_doc",
        "source_lane": "official_ko",
        "section_count": 2,
        "code_block_count": 0,
        "viewer_path": "/docs/ocp/4.20/ko/gated_gold/index.html",
        "source_url": "",
        "updated_at": "",
        "runtime_readable": True,
        "runtime_gate": "operational_wiki_published",
        "runtime_readiness": "route_and_artifact_passed",
    }

    monkeypatch.setattr(data_control_room, "load_settings", _control_room_settings)
    monkeypatch.setattr(data_control_room, "CustomerPackDraftStore", _EmptyDraftStore)
    monkeypatch.setattr(data_control_room, "_approved_manifest_entries", lambda _settings: [source_only_gold])
    monkeypatch.setattr(data_control_room, "_build_approved_wiki_runtime_book_bucket", lambda *_args, **_kwargs: {"books": [gated_gold], "hidden_books": []})
    monkeypatch.setattr(
        data_control_room,
        "build_corpus_status",
        lambda **_kwargs: {
            "database": "postgres",
            "collection": "openshift_docs",
            "source_counts": {"official_docs": 29, "study_docs": 9},
            "chunk_counts": {"official_docs": 27907, "study_docs": 523},
            "total_sources": 38,
            "total_chunks": 28430,
            "qdrant_index_entries": 28430,
            "missing_qdrant_index_entries": 0,
            "qdrant_index_parity": True,
            "ready_scopes": ["official_docs", "study_docs"],
            "ready": True,
        },
    )

    def select_report(_candidate_path, settings_path, *, summary_key, rows_key, expected_count):
        del summary_key, expected_count
        if rows_key == "books":
            return settings_path, {
                "summary": {"book_count": 1, "approved_ko_count": 1, "blocked_count": 0},
                "books": [source_only_gold],
            }
        return settings_path, {"summary": {"active_queue_count": 0}, "active_queue": []}

    monkeypatch.setattr(data_control_room, "_select_report_candidate", select_report)

    payload = data_control_room._build_data_control_room_payload_uncached(tmp_path)

    assert [book["book_slug"] for book in payload["gold_books"]] == ["gated_gold"]
    assert payload["summary"]["gold_book_count"] == 1
    assert payload["grading"]["source_approved_gold_books"][0]["book_slug"] == "source_only_gold"
    assert payload["summary"]["certification_status"] == "not_certifiable"
    assert payload["summary"]["release_blocking"] is True
    assert "missing_morning_gate_report" in payload["certification"]["blockers"]
    assert payload["summary"]["db_total_document_count"] == 38
    assert payload["summary"]["db_official_document_count"] == 29
    assert payload["summary"]["db_customer_document_count"] == 9
    assert payload["summary"]["official_corpus_chunk_count"] == 27907
    assert payload["summary"]["customer_corpus_chunk_count"] == 523
    assert payload["summary"]["total_repository_chunk_count"] == 28430
    assert payload["summary"]["qdrant_index_entry_count"] == 28430
    assert payload["summary"]["qdrant_index_parity"] is True
    assert payload["runtime_db_corpus"]["ready_scopes"] == ["official_docs", "study_docs"]


def test_data_control_room_cache_fingerprint_watches_runtime_surface_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(data_control_room, "load_settings", _control_room_settings)

    fingerprint = data_control_room._data_control_room_cache_fingerprint(tmp_path)
    paths = {item[0].replace("\\", "/") for item in fingerprint}

    expected_markers = [
        "data/wiki_runtime_books",
        "data/wiki_relations",
        "data/gold_candidate_books/full_rebuild_manifest.json",
        "PRODUCT_GATE_SCORECARD.yaml",
        "reports/build_logs/product_rehearsal_report.json",
        "reports/build_logs/buyer_packet_bundle_index.json",
        "reports/build_logs/release_candidate_freeze_packet.json",
        "artifacts/runtime/served_viewers",
        "artifacts/runtime/wiki_overlays",
    ]
    for marker in expected_markers:
        assert any(marker in path for path in paths), marker


def test_eval_summary_accepts_expected_hit_aliases_and_ragas_summary() -> None:
    retrieval_summary = _summarize_eval({"overall": {"case_count": 20, "expected_hit_at_1": 0.8, "expected_hit_at_3": 0.9}})
    ragas_summary = _summarize_eval({"summary": {"case_count": 20, "faithfulness": 0.82, "answer_relevancy": 0.91}})

    assert retrieval_summary["book_hit_at_1"] == 0.8
    assert retrieval_summary["book_hit_at_3"] == 0.9
    assert ragas_summary["faithfulness"] == 0.82
    assert ragas_summary["answer_relevancy"] == 0.91


def test_certification_contract_blocks_low_quality_reports() -> None:
    snapshots = {
        "morning_gate": {"exists": True, "path": "gate.json"},
        "source_approval": {"exists": True, "path": "source.json"},
        "retrieval_eval": {"exists": True, "path": "retrieval.json"},
        "answer_eval": {"exists": True, "path": "answer.json"},
        "ragas_eval": {"exists": True, "path": "ragas.json"},
        "runtime_report": {"exists": True, "path": "runtime.json"},
    }

    contract = data_control_room._build_certification_contract(
        report_snapshots=snapshots,
        approved_wiki_runtime_books={"books": [{"certified_gold": True}], "hidden_books": []},
        canonical_grade_source={"exists": True},
        runtime_report={"runtime": {"db_corpus": {"qdrant_index_parity": True}}},
        retrieval_report={"overall": {"case_count": 18, "expected_hit_at_3": 0.83}},
        answer_report={"overall": {"case_count": 18, "pass_rate": 0.83, "avg_citation_precision": 0.44}},
        ragas_report={"summary": {"case_count": 4, "faithfulness": 0.7}},
    )

    assert contract["status"] == "not_certifiable"
    assert "retrieval_eval_case_count_below_minimum" in contract["blockers"]
    assert "retrieval_hit_at_3_below_threshold" in contract["blockers"]
    assert "answer_eval_case_count_below_minimum" in contract["blockers"]
    assert "answer_pass_rate_below_threshold" in contract["blockers"]
    assert "citation_precision_below_threshold" in contract["blockers"]
    assert "ragas_eval_case_count_below_minimum" in contract["blockers"]
    assert "ragas_faithfulness_below_threshold" in contract["blockers"]
    details_by_blocker = {item["blocker"]: item for item in contract["blocker_details"]}
    assert details_by_blocker["citation_precision_below_threshold"]["owner"] == "answer-quality"
    assert "play_book_studio.cli eval" in details_by_blocker["answer_eval_case_count_below_minimum"]["verification_command"]


def test_certification_uses_emitted_citation_precision_when_available() -> None:
    snapshots = {
        "morning_gate": {"exists": True, "path": "gate.json"},
        "source_approval": {"exists": True, "path": "source.json"},
        "retrieval_eval": {"exists": True, "path": "retrieval.json"},
        "answer_eval": {"exists": True, "path": "answer.json"},
        "ragas_eval": {"exists": True, "path": "ragas.json"},
        "runtime_report": {"exists": True, "path": "runtime.json"},
    }

    contract = data_control_room._build_certification_contract(
        report_snapshots=snapshots,
        approved_wiki_runtime_books={"books": [{"certified_gold": True}], "hidden_books": []},
        canonical_grade_source={"exists": True},
        runtime_report={"runtime": {"db_corpus": {"qdrant_index_parity": True}}},
        retrieval_report={"overall": {"case_count": 20, "expected_hit_at_3": 0.95}},
        answer_report={
            "overall": {
                "case_count": 20,
                "pass_rate": 1.0,
                "avg_citation_precision": 0.65,
                "strict_expected_only_rate": 1.0,
            }
        },
        ragas_report={"summary": {"case_count": 20, "faithfulness": 0.82}},
    )

    assert "citation_precision_below_threshold" not in contract["blockers"]
    assert contract["quality_gates"]["citation_precision"]["metric"] == 1.0
