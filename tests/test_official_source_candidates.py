from __future__ import annotations

import json
from types import SimpleNamespace

from play_book_studio.http import server_routes_ops
from play_book_studio.retrieval.query import has_hosted_control_plane_signal


def _write_manifest(path, entries: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_hosted_control_plane_signal_accepts_colloquial_korean() -> None:
    assert has_hosted_control_plane_signal("호스팅 컨트롤 플레인 아키텍처를 요약해줘")


def test_official_source_search_uses_retrieval_book_adjustments(monkeypatch, tmp_path) -> None:
    draft_manifest = tmp_path / "ocp_4_20_ko_translated_ko_draft_all_runtime.json"
    source_manifest = tmp_path / "approved_source.json"
    _write_manifest(
        draft_manifest,
        [
            {
                "book_slug": "hosted_control_planes",
                "title": "Hosted control planes",
                "viewer_path": "/docs/ocp/4.20/ko/hosted_control_planes/index.html",
                "source_relative_path": "hosted-control-planes/index.adoc",
                "source_repo": "https://github.com/openshift/openshift-docs",
                "source_branch": "enterprise-4.20",
                "source_kind": "source-first",
            },
            {
                "book_slug": "networking",
                "title": "Networking",
                "viewer_path": "/docs/ocp/4.20/ko/networking/index.html",
            },
        ],
    )
    _write_manifest(source_manifest, [])
    settings = SimpleNamespace(
        active_pack=SimpleNamespace(manifest_prefix="ocp_4_20_ko"),
        book_url_template="https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html/{slug}/index",
        database_url="",
        manifest_dir=tmp_path,
        ocp_version="4.20",
        source_manifest_path=source_manifest,
        translation_draft_manifest_path=draft_manifest,
        viewer_path_template="/docs/ocp/4.20/ko/{slug}/index.html",
    )
    monkeypatch.setattr(server_routes_ops, "load_settings", lambda _root_dir: settings)

    rows = server_routes_ops._search_official_source_candidates(
        tmp_path,
        query="호스팅 컨트롤 플레인 아키텍처를 요약해줘",
        limit=3,
    )

    assert rows
    assert rows[0]["book_slug"] == "hosted_control_planes"
    assert rows[0]["status_kind"] == "candidate"
    assert rows[0]["match_score"] >= 90


def test_official_source_search_prioritizes_troubleshooting_books(monkeypatch, tmp_path) -> None:
    draft_manifest = tmp_path / "ocp_4_20_ko_translated_ko_draft_all_runtime.json"
    source_manifest = tmp_path / "approved_source.json"
    _write_manifest(
        draft_manifest,
        [
            {
                "book_slug": "installing",
                "title": "설치",
                "viewer_path": "/docs/ocp/4.20/ko/installing/index.html",
                "source_relative_path": "installing/index.adoc",
            },
            {
                "book_slug": "support",
                "title": "지원",
                "viewer_path": "/docs/ocp/4.20/ko/support/index.html",
                "source_relative_path": "support/index.adoc",
            },
            {
                "book_slug": "validation_and_troubleshooting",
                "title": "검증 및 문제 해결",
                "viewer_path": "/docs/ocp/4.20/ko/validation_and_troubleshooting/index.html",
                "source_relative_path": "validation-and-troubleshooting/index.adoc",
            },
            {
                "book_slug": "images",
                "title": "이미지",
                "viewer_path": "/docs/ocp/4.20/ko/images/index.html",
                "source_relative_path": "images/index.adoc",
            },
        ],
    )
    _write_manifest(source_manifest, [])
    settings = SimpleNamespace(
        active_pack=SimpleNamespace(manifest_prefix="ocp_4_20_ko"),
        book_url_template="https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html/{slug}/index",
        database_url="",
        manifest_dir=tmp_path,
        ocp_version="4.20",
        source_manifest_path=source_manifest,
        translation_draft_manifest_path=draft_manifest,
        viewer_path_template="/docs/ocp/4.20/ko/{slug}/index.html",
    )
    monkeypatch.setattr(server_routes_ops, "load_settings", lambda _root_dir: settings)

    rows = server_routes_ops._search_official_source_candidates(
        tmp_path,
        query="OpenShift image pull error troubleshooting 원인과 해결",
        limit=4,
    )

    slugs = [row["book_slug"] for row in rows]
    assert slugs[0] == "validation_and_troubleshooting"
    assert "support" in slugs[:3]
    assert "images" in slugs[:3]


def test_repository_source_request_save_round_trips_to_queue(monkeypatch, tmp_path) -> None:
    settings = SimpleNamespace(unanswered_questions_path=tmp_path / "unanswered_questions.jsonl")
    monkeypatch.setattr(server_routes_ops, "load_settings", lambda _root_dir: settings)

    saved = server_routes_ops._save_repository_source_request(
        tmp_path,
        {
            "query": "Service 장애 원인 알려줘",
            "response_kind": "clarification",
            "failure_reason": "user_marked_answer_insufficient",
            "source_request_origin": "workspace_chat_acquisition",
            "warnings": ["citation 부족"],
        },
    )
    queue = server_routes_ops._list_unanswered_questions(tmp_path, limit=10)

    assert saved["record_kind"] == "unanswered_question"
    assert queue["count"] == 1
    assert queue["items"][0]["query"] == "Service 장애 원인 알려줘"
    assert queue["items"][0]["response_kind"] == "clarification"
    assert queue["items"][0]["failure_reason"] == "user_marked_answer_insufficient"
    assert queue["items"][0]["source_request_origin"] == "workspace_chat_acquisition"


def test_unanswered_queue_preserves_enriched_source_request_metadata(monkeypatch, tmp_path) -> None:
    target = tmp_path / "unanswered_questions.jsonl"
    settings = SimpleNamespace(unanswered_questions_path=target)
    monkeypatch.setattr(server_routes_ops, "load_settings", lambda _root_dir: settings)

    server_routes_ops._save_repository_source_request(
        tmp_path,
        {
            "query": "OpenShift 4.21 호스팅 컨트롤 플레인 아키텍처",
            "response_kind": "no_answer",
            "failure_reason": "user_marked_answer_insufficient",
            "source_request_origin": "workspace_chat_acquisition",
            "warnings": ["사용자가 채팅 답변에서 자료 보강 요청을 눌렀습니다."],
        },
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "record_kind": "unanswered_question",
                    "query": "OpenShift 4.21 호스팅 컨트롤 플레인 아키텍처",
                    "response_kind": "no_answer",
                    "warnings": [],
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    queue = server_routes_ops._list_unanswered_questions(tmp_path, limit=10)

    assert queue["count"] == 1
    assert queue["items"][0]["source_request_origin"] == "workspace_chat_acquisition"
    assert queue["items"][0]["failure_reason"] == "user_marked_answer_insufficient"
    assert "자료 보강 요청" in queue["items"][0]["warnings"][0]
