from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.app.starter_questions import build_studio_starter_questions

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "starter_questions_tests"


def test_starter_questions_are_loaded_from_manifests() -> None:
    manifests = TEST_TMP / "manifests"
    course_manifests = TEST_TMP / "data" / "course_pbs" / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    course_manifests.mkdir(parents=True)
    (manifests / "pbs_chat_quality_cases.jsonl").write_text(
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
    (manifests / "ocp420_repo_wide_source_manifest.json").write_text(
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
    (course_manifests / "ops_learning_guides_v1.json").write_text(
        json.dumps(
            {
                "guides": [
                    {
                        "stage_id": "perf_test",
                        "title": "성능 테스트",
                        "steps": [
                            {
                                "user_query": "성능 테스트 결과에서 병목은 어디부터 보면 돼?",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_studio_starter_questions(TEST_TMP, seed="stable")
    groups = {group["key"]: group for group in payload["groups"]}

    assert groups["faq"]["questions"][0]["question"] == "Operator가 Degraded일 때 CSV 상태를 어떻게 확인해?"
    assert groups["learning"]["questions"][0]["source"] == "ocp420_repo_wide_source_manifest"
    assert groups["operations"]["questions"][0]["question"] == "성능 테스트 결과에서 병목은 어디부터 보면 돼?"
    assert payload["learning_sequence"][0]["learning_index"] == 0
