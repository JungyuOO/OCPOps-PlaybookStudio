from __future__ import annotations

import json

from play_book_studio.evals.validation_real_loop import (
    build_validation_report,
    load_blind_question_cases,
    load_gold_answer_cases,
    write_real_loop,
)


def test_load_blind_question_cases_excludes_gold_answers(tmp_path):
    target = tmp_path / "validation" / "ocp_cases.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            [
                {
                    "Question": "PVC가 Pending이면 무엇을 확인해?",
                    "answer": "정답은 서비스 호출 전에 읽으면 안 됩니다.",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = load_blind_question_cases(tmp_path, "validation/ocp_*.json")

    assert len(cases) == 1
    assert cases[0].question == "PVC가 Pending이면 무엇을 확인해?"
    assert not hasattr(cases[0], "answer")


def test_gold_answers_load_only_for_compare_phase(tmp_path):
    target = tmp_path / "validation" / "ocp_cases.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            [
                {
                    "Question": "Pod 목록 확인은?",
                    "answer": "Pod 목록은 `oc get pods`로 확인합니다.",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    gold = load_gold_answer_cases(tmp_path, "validation/ocp_*.json")
    report = build_validation_report(
        [
            {
                "case_id": "ocp_cases:0001",
                "source_file": "validation/ocp_cases.json",
                "source_index": 0,
                "question_sha256_16": "hash",
                "status": "ok",
                "response_kind": "rag",
                "answer": "Pod 목록은 `oc get pods` 명령으로 조회합니다.",
            }
        ],
        gold,
    )

    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    assert "answer" not in report["results"][0]


def test_write_real_loop_shape_can_skip_service(tmp_path):
    target = tmp_path / "validation" / "ocp_cases.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps([{"Question": "Route는?", "answer": "Route 설명"}], ensure_ascii=False),
        encoding="utf-8",
    )

    payload = write_real_loop(
        tmp_path,
        pattern="validation/ocp_*.json",
        output_path=tmp_path / "validation" / "real_loop.json",
        base_url="http://127.0.0.1:8765",
        timeout_seconds=1,
        limit=0,
        skip_service=True,
    )

    assert payload["service_payload_contract"]["gold_answer_loaded_during_service_loop"] is False
    assert payload["summary"]["question_count"] == 1
    assert (tmp_path / "validation" / "real_loop.json").is_file()


def test_write_real_loop_resume_keeps_existing_service_results(tmp_path):
    target = tmp_path / "validation" / "ocp_cases.json"
    output = tmp_path / "validation" / "real_loop.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            [
                {"Question": "Pod 목록은?", "answer": "Pod 목록 답변"},
                {"Question": "Route 확인은?", "answer": "Route 확인 답변"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output.write_text(
        json.dumps(
            {
                "service_results": [
                    {
                        "case_id": "ocp_cases:0001",
                        "answer": "이미 받은 답변",
                        "status": "ok",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = write_real_loop(
        tmp_path,
        pattern="validation/ocp_*.json",
        output_path=output,
        base_url="http://localhost:8765",
        timeout_seconds=1,
        limit=0,
        skip_service=True,
        resume=True,
    )

    assert payload["summary"]["service_result_count"] == 1
    assert payload["summary"]["pending_count"] == 1
    assert payload["service_results"][0]["answer"] == "이미 받은 답변"
def test_write_real_loop_can_replace_only_selected_range(tmp_path):
    target = tmp_path / "validation" / "ocp_cases.json"
    output = tmp_path / "validation" / "real_loop.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            [
                {"Question": "Q1", "answer": "A1"},
                {"Question": "Q2", "answer": "A2"},
                {"Question": "Q3", "answer": "A3"},
                {"Question": "Q4", "answer": "A4"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output.write_text(
        json.dumps(
            {
                "service_results": [
                    {"case_id": "ocp_cases:0001", "answer": "old1", "status": "ok"},
                    {"case_id": "ocp_cases:0002", "answer": "old2", "status": "ok"},
                    {"case_id": "ocp_cases:0003", "answer": "old3", "status": "ok"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = write_real_loop(
        tmp_path,
        pattern="validation/ocp_*.json",
        output_path=output,
        base_url="http://localhost:8765",
        timeout_seconds=1,
        limit=2,
        start_index=2,
        replace_selected=True,
        skip_service=True,
        resume=True,
    )

    assert payload["summary"]["question_count"] == 4
    assert payload["summary"]["service_result_count"] == 1
    assert payload["summary"]["pending_count"] == 3
    assert payload["selected_range"]["start_index"] == 2
    assert payload["selected_range"]["selected_count"] == 2
    assert [row["case_id"] for row in payload["service_results"]] == ["ocp_cases:0001"]
