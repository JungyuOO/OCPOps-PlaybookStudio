import json

from play_book_studio.app.data_control_room import build_data_control_room_payload
from play_book_studio.app.data_control_room_helpers import _select_report_candidate


def test_select_report_candidate_rejects_count_mismatches(tmp_path):
    report_path = tmp_path / "source_approval_report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "book_count": 145,
                    "approved_ko_count": 80,
                },
                "books": [{"book_slug": "overview"}],
            }
        ),
        encoding="utf-8",
    )

    selected_path, payload = _select_report_candidate(
        report_path,
        summary_key="approved_ko_count",
        rows_key="books",
        expected_count=34,
    )

    assert selected_path is None
    assert payload == {}


def test_select_report_candidate_accepts_matching_count(tmp_path):
    report_path = tmp_path / "source_approval_report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "book_count": 34,
                    "approved_ko_count": 34,
                },
                "books": [{"book_slug": "overview"}],
            }
        ),
        encoding="utf-8",
    )

    selected_path, payload = _select_report_candidate(
        report_path,
        summary_key="approved_ko_count",
        rows_key="books",
        expected_count=34,
    )

    assert selected_path == report_path
    assert payload["summary"]["approved_ko_count"] == 34


def test_data_control_room_ignores_orphan_translation_lane_when_source_report_mismatches(tmp_path, monkeypatch):
    root = tmp_path
    corpus_dir = root / "artifacts" / "corpus"
    corpus_dir.mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / "data" / "wiki_runtime_books").mkdir(parents=True)
    (root / "data" / "gold_corpus_ko").mkdir(parents=True)
    (root / "data" / "customer_packs" / "books").mkdir(parents=True)
    (root / "data" / "customer_packs" / "drafts").mkdir(parents=True)
    (root / "artifacts" / "official_lane" / "repo_wide_official_source" / "playbooks").mkdir(parents=True)

    (root / "manifests" / "ocp_ko_4_20_approved_ko.json").write_text(
        json.dumps({"entries": [{"book_slug": "overview", "title": "Overview"}]}),
        encoding="utf-8",
    )
    (root / "data" / "wiki_runtime_books" / "active_manifest.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "book_slug": "overview",
                        "title": "Overview",
                        "content_status": "approved_ko",
                        "translation_stage": "approved_ko",
                        "viewer_path": "/docs/ocp/4.20/ko/overview/index.html",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (corpus_dir / "source_approval_report.json").write_text(
        json.dumps({"summary": {"book_count": 2, "approved_ko_count": 2}, "books": []}),
        encoding="utf-8",
    )
    (corpus_dir / "translation_lane_report.json").write_text(
        json.dumps(
            {
                "summary": {"book_count": 2, "active_queue_count": 1},
                "active_queue": [{"book_slug": "overview"}],
            }
        ),
        encoding="utf-8",
    )

    payload = build_data_control_room_payload(root)

    assert payload["canonical_grade_source"]["exists"] is False
    assert payload["reports"]["translation_lane"]["path"] == ""
