from __future__ import annotations

import json
import shutil
import sys
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

    assert groups["faq"]["questions"][0]["question"] == "Operator가 Degraded일 때 CSV 상태를 어떻게 확인해?"
    assert groups["learning"]["questions"][0]["source"] == "ocp420_repo_wide_source_manifest"
    assert groups["operations"]["questions"][0]["source"].endswith("ops_learning_chunks_v1.jsonl")
    assert groups["operations"]["questions"][0]["question"] == "성능 테스트 결과를 받으면 목표와 조건은 어떻게 먼저 확인해?"
    assert "병목은 어디부터" not in groups["operations"]["questions"][0]["question"]
    assert payload["learning_sequence"][0]["learning_index"] == 0


def test_starter_questions_do_not_fall_back_to_files_when_database_is_configured(monkeypatch) -> None:
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
    monkeypatch.setitem(sys.modules, "psycopg", None)

    payload = build_studio_starter_questions(root, seed="stable")
    groups = {group["key"]: group for group in payload["groups"]}

    assert groups["operations"]["questions"] == []


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
    assert any(question.endswith("확인하면 돼?") for question in questions)


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
