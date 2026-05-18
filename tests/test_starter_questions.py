from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import play_book_studio.http.starter_questions as starter_questions
from play_book_studio.http.starter_questions import build_studio_starter_questions

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "starter_questions_tests"


def test_starter_questions_are_loaded_from_manifests() -> None:
    shutil.rmtree(TEST_TMP, ignore_errors=True)
    eval_manifests = TEST_TMP / "corpus" / "manifests" / "eval"
    official_manifests = TEST_TMP / "corpus" / "manifests" / "official"
    course_manifests = TEST_TMP / "corpus" / "sources" / "kmsc" / "parsed-preview" / "course_pbs" / "manifests"
    eval_manifests.mkdir(parents=True, exist_ok=True)
    official_manifests.mkdir(parents=True, exist_ok=True)
    course_manifests.mkdir(parents=True, exist_ok=True)
    (eval_manifests / "pbs_chat_quality_cases.jsonl").write_text(
        json.dumps(
            {
                "query": "Operator가 Degraded일 때 CSV 상태를 어떻게 확인해?",
                "query_type": "ops_troubleshooting",
                "expected_book_slugs": ["operators"],
                "clarification_expected": False,
                "no_answer_expected": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (official_manifests / "ocp420_repo_wide_source_manifest.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "book_slug": "installing",
                        "title": "Installing a cluster",
                        "topic_path": ["Installing", "Installing a cluster"],
                        "section_family": ["Installing"],
                    },
                    {
                        "book_slug": "monitoring",
                        "title": "Monitoring overview",
                        "topic_path": ["Monitoring", "Monitoring overview"],
                        "section_family": ["Observability"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (course_manifests / "ops_learning_chunks_v1.jsonl").write_text(
        json.dumps(
            {
                "chunk_type": "ops_learning_step",
                "title": "성능 목표와 조건 먼저 보기",
                "learning_goal": "성능 목표와 테스트 환경을 먼저 확인한다",
                "source_terms": ["TPS 목표", "테스트 환경"],
                "stage_id": "perf_test",
                "course_title": "실운영 가이드",
                "query_variants": ["성능 테스트 결과에서 병목은 어디부터 보면 돼?"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_studio_starter_questions(TEST_TMP, seed="stable")
    groups = {group["key"]: group for group in payload["groups"]}

    assert groups["faq"]["questions"][0]["source"] == "official.source_manifest"
    assert groups["faq"]["questions"][0]["question"] != "Operator가 Degraded일 때 CSV 상태를 어떻게 확인해?"
    assert groups["faq"]["questions"][0]["target_book_slug"] in {"installing", "monitoring"}
    assert groups["learning"]["questions"][0]["source"] == "ocp420_repo_wide_source_manifest"
    assert groups["learning"]["questions"][0]["route_kind"] == "learning"
    assert groups["operations"]["questions"][0]["source"].endswith("ops_learning_chunks_v1.jsonl")
    assert groups["operations"]["questions"][0]["route_kind"] == "study_docs"
    assert groups["operations"]["questions"][0]["question"].endswith("?")
    assert groups["operations"]["questions"][0]["question"] != groups["operations"]["questions"][0]["title"] if "title" in groups["operations"]["questions"][0] else True
    assert "병목은 어디부터" not in groups["operations"]["questions"][0]["question"]
    assert "성능 목표와 조건 먼저 보기" in groups["operations"]["questions"][0]["question"]
    assert payload["learning_sequence"][0]["learning_index"] == 0
    assert payload["sources"]["faq"] == "official.source_manifest"


def test_operations_starter_questions_use_existing_file_copy_when_database_is_configured(monkeypatch) -> None:
    root = TEST_TMP / "db_configured"
    course_manifests = root / "corpus" / "sources" / "kmsc" / "parsed-preview" / "course_pbs" / "manifests"
    course_manifests.mkdir(parents=True, exist_ok=True)
    (course_manifests / "ops_learning_chunks_v1.jsonl").write_text(
        json.dumps(
            {
                "chunk_type": "ops_learning_step",
                "title": "File fallback guide",
                "query_variants": ["This file question should not leak"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        starter_questions,
        "load_settings",
        lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
    )

    payload = build_studio_starter_questions(root, seed="stable")
    groups = {group["key"]: group for group in payload["groups"]}

    assert groups["operations"]["questions"][0]["source"].endswith("ops_learning_chunks_v1.jsonl")
    assert groups["operations"]["questions"][0]["route_kind"] == "study_docs"
    assert groups["operations"]["questions"][0]["question"] != "This file question should not leak"


def test_starter_questions_use_postgres_official_metadata_when_database_is_configured(monkeypatch) -> None:
    root = TEST_TMP / "db_official_metadata"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        starter_questions,
        "load_settings",
        lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
    )
    monkeypatch.setattr(
        starter_questions,
        "_official_manifest_entries_from_db",
        lambda _database_url: [
            {
                "book_slug": "machine_configuration",
                "title": "Machine configuration",
                "viewer_path": "/playbooks/wiki-runtime/active/machine_configuration/index.html",
                "topic_path": ["Operations", "Machine configuration"],
                "section_family": ["operations"],
                "source_relative_path": "machine_configuration/index.html",
            }
        ],
    )

    payload = build_studio_starter_questions(root, seed="stable")
    groups = {group["key"]: group for group in payload["groups"]}

    assert groups["faq"]["questions"][0]["source"] == "postgres.official_docs"
    assert groups["faq"]["questions"][0]["target_book_slug"] == "machine_configuration"
    assert "What should" not in groups["faq"]["questions"][0]["question"]
    assert "문서를 기준으로" not in groups["faq"]["questions"][0]["question"]
    assert payload["learning_sequence"][2]["target_viewer_path"] == "/playbooks/wiki-runtime/active/machine_configuration/index.html"


def test_starter_question_preserves_target_anchor() -> None:
    question = starter_questions._starter_question(
        lane="faq",
        question="배포한 앱이 안 뜨면 어디부터 확인해야 해?",
        route_kind="chat",
        source="postgres.document_chunks",
        target_book_slug="applications",
        target_viewer_path="/playbooks/wiki-runtime/active/applications/index.html",
        target_anchor="route-service-check",
    )

    assert question["target_anchor"] == "route-service-check"


def test_postgres_official_faq_questions_are_actionable_korean(monkeypatch) -> None:
    root = TEST_TMP / "db_official_troubleshooting"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        starter_questions,
        "load_settings",
        lambda _root: SimpleNamespace(database_url="postgresql://unit-test"),
    )
    monkeypatch.setattr(
        starter_questions,
        "_official_manifest_entries_from_db",
        lambda _database_url: [
            {
                "book_slug": "validation_and_troubleshooting",
                "title": "검증 및 문제 해결",
                "viewer_path": "/playbooks/wiki-runtime/active/validation_and_troubleshooting/index.html",
                "topic_path": ["Troubleshooting", "Validation and troubleshooting"],
                "section_family": ["troubleshooting"],
                "source_relative_path": "validation_and_troubleshooting/index.html",
            }
        ],
    )

    payload = build_studio_starter_questions(root, seed="stable")
    questions = [
        item["question"]
        for group in payload["groups"]
        if group["key"] == "faq"
        for item in group["questions"]
    ]

    assert questions
    assert all("What should" not in question for question in questions)
    assert any("실패한 설치 로그 수집" in question for question in questions)
    assert all("어디부터" not in question for question in questions)


def test_operations_questions_anchor_to_kmsc_chunk_title() -> None:
    question = starter_questions._ops_chunk_question(
        {
            "title": "운영 장애 분석",
            "learning_goal": "증상과 근거를 정리한다",
            "source_terms": ["장애", "근거"],
        }
    )

    assert question == "KMSC 운영 문서에서 운영 장애 분석의 증상과 근거는 어떤 순서로 확인하나요?"


def test_learning_starter_questions_include_terminal_context_when_available(monkeypatch) -> None:
    root = TEST_TMP / "terminal_context"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        starter_questions,
        "_learning_terminal_contexts",
        lambda _root: [
            {
                "learning_path_id": "path-1",
                "learning_step_id": "step-1",
                "lab_task_id": "lab-1",
            }
        ],
    )

    payload = build_studio_starter_questions(root, seed="stable")
    first_learning = payload["learning_sequence"][0]

    assert first_learning["learning_path_id"] == "path-1"
    assert first_learning["learning_step_id"] == "step-1"
    assert first_learning["lab_task_id"] == "lab-1"
