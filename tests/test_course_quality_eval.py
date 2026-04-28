from __future__ import annotations

import json
import argparse
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from play_book_studio.course import quality_eval


@contextmanager
def _temp_root() -> Iterator[Path]:
    temp_parent = Path.cwd() / ".pytest-tmp" / "course-quality"
    temp_parent.mkdir(parents=True, exist_ok=True)
    root = temp_parent / f"case-{uuid.uuid4().hex}"
    root.mkdir(parents=True)
    yield root


def _write_chunk(root: Path, chunk_id: str, payload: dict) -> None:
    chunks_dir = root / "data" / "course_pbs" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    (chunks_dir / f"{chunk_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_manifest(root: Path, payload: dict) -> None:
    manifests_dir = root / "data" / "course_pbs" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "course_v1.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_asset(root: Path, asset_path: str) -> None:
    path = root / asset_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")


def _source_chunk(asset_path: str = "data/course_pbs/assets/running.png") -> dict:
    return {
        "chunk_id": "unit-test--running",
        "stage_id": "unit_test",
        "native_id": "TEST-UN-OCP-99-01",
        "title": "Pod Running 확인",
        "body_md": "oc get pods 결과에서 Running 상태를 확인한다.",
        "search_text": "TEST-UN-OCP-99-01 Running Ready 상태 확인",
        "related_official_docs": [
            {
                "score": 0.8,
                "title": "OpenShift Docs",
                "section_title": "Viewing pods",
                "match_reason": "pod status keyword match",
            }
        ],
        "image_attachments": [
            {
                "asset_id": "asset-running",
                "asset_path": asset_path,
                "instructional_role": "expected_state_indicator",
                "instructional_roles": ["expected_state_indicator", "success_state"],
                "state_signal": "Running",
                "visual_summary": "Pod status row shows Running.",
                "ocr_text": "NAME READY STATUS api-1 1/1 Running",
                "is_default_visible": True,
            }
        ],
    }


def test_validate_cases_rejects_untraceable_test_data() -> None:
    with _temp_root() as root:
        asset_path = "data/course_pbs/assets/running.png"
        _write_asset(root, asset_path)
        running_chunk = {
            **_source_chunk(asset_path),
            "tour_stop": {
                "next_chunk_id": "unit-test--next",
                "stop_order": 1,
                "total_stops": 2,
                "route_role": "standard",
            },
        }
        next_chunk = {
            **_source_chunk(asset_path),
            "chunk_id": "unit-test--next",
            "native_id": "TEST-UN-OCP-99-02",
            "title": "Pod Ready 확인",
            "search_text": "Ready 상태 확인",
            "tour_stop": {
                "next_chunk_id": "",
                "stop_order": 2,
                "total_stops": 2,
                "route_role": "standard",
            },
        }
        _write_chunk(root, "unit-test--running", running_chunk)
        _write_chunk(root, "unit-test--next", next_chunk)

        valid = quality_eval._case(
            case_id="valid-running",
            category="image_state_evidence",
            query="Running 상태는 어떻게 확인해?",
            stage_id="unit_test",
            expected_chunk_ids=["unit-test--running"],
            expected_artifact_kinds=["course_chunk", "course_image_evidence"],
            expected_image_roles=["expected_state_indicator"],
            expected_state_signals=["Running"],
            source={"chunk_id": "unit-test--running", "asset_id": "asset-running", "asset_path": asset_path},
        )
        invalid = {
            **valid,
            "id": "invalid-running",
            "schema": "wrong_schema",
            "expected_image_roles": ["dashboard_metric"],
            "expected_state_signals": ["CrashLoopBackOff"],
            "source": {"chunk_id": "unit-test--running", "asset_id": "missing-asset", "asset_path": "data/course_pbs/assets/missing.png"},
        }

        accepted, rejected = quality_eval.validate_cases([valid, invalid], root / "data" / "course_pbs", root_dir=root)

    assert [case["id"] for case in accepted] == ["valid-running"]
    assert rejected[0]["id"] == "invalid-running"
    assert "invalid_schema" in rejected[0]["quality_reasons"]
    assert "asset_path_missing" in rejected[0]["quality_reasons"]
    assert "asset_id_not_in_expected_chunk" in rejected[0]["quality_reasons"]
    assert "expected_role_not_in_source_chunk:dashboard_metric" in rejected[0]["quality_reasons"]
    assert "expected_state_not_in_source_chunk:CrashLoopBackOff" in rejected[0]["quality_reasons"]


def test_generate_cases_creates_diverse_source_backed_cases() -> None:
    with _temp_root() as root:
        asset_path = "data/course_pbs/assets/running.png"
        _write_asset(root, asset_path)
        running_chunk = {
            **_source_chunk(asset_path),
            "tour_stop": {
                "next_chunk_id": "unit-test--next",
                "stop_order": 1,
                "total_stops": 2,
                "route_role": "standard",
            },
        }
        next_chunk = {
            **_source_chunk(asset_path),
            "chunk_id": "unit-test--next",
            "native_id": "TEST-UN-OCP-99-02",
            "title": "Pod Ready 확인",
            "search_text": "Ready 상태 확인",
            "tour_stop": {
                "next_chunk_id": "",
                "stop_order": 2,
                "total_stops": 2,
                "route_role": "standard",
            },
        }
        _write_chunk(root, "unit-test--running", running_chunk)
        _write_chunk(root, "unit-test--next", next_chunk)
        _write_manifest(
            root,
            {
                "stages": [
                    {
                        "stage_id": "unit_test",
                        "title": "단위 테스트",
                        "learning_route": {"start_here": ["unit-test--running"], "then_open": ["unit-test--next"]},
                    }
                ]
            },
        )

        cases = quality_eval.generate_cases(root / "data" / "course_pbs", target_count=20)
        accepted, rejected = quality_eval.validate_cases(cases, root / "data" / "course_pbs", root_dir=root)

    categories = {case["category"] for case in cases}
    assert {
        "exact_anchor",
        "guided_stage_route",
        "guided_route_sequence",
        "guided_route_step",
        "official_mapping",
        "official_mapping_broad",
        "image_state_evidence",
        "image_role_evidence",
        "beginner_guided_step",
        "beginner_concept",
    } <= categories
    beginner_cases = [case for case in cases if str(case.get("category") or "").startswith("beginner_")]
    assert beginner_cases
    assert all("TEST-UN-OCP" not in str(case.get("query") or "") for case in beginner_cases)
    assert all((case.get("source") or {}).get("hidden_doc_anchor") is True for case in beginner_cases)
    assert len(accepted) == len(cases)
    assert rejected == []


def test_run_cases_fails_when_expected_image_state_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    case = quality_eval._case(
        case_id="state-running",
        category="image_state_evidence",
        query="Running 상태는 어떻게 확인해?",
        expected_chunk_ids=["unit-test--running"],
        expected_artifact_kinds=["course_chunk", "course_image_evidence"],
        expected_image_roles=["expected_state_indicator"],
        expected_state_signals=["Running"],
    )

    monkeypatch.setattr(
        quality_eval,
        "_course_chat_payload",
        lambda root_dir, payload: {
            "sources": [{"chunk_id": "unit-test--running"}],
            "artifacts": [
                {"kind": "course_chunk", "items": []},
                {
                    "kind": "course_image_evidence",
                    "items": [{"asset_id": "asset-failed", "instructional_role": "failure_state", "state_signal": "Failed"}],
                },
            ],
        },
    )

    report = quality_eval.run_cases([case], root_dir=Path("."))

    assert report["failed"] == 1
    assert "expected_state_not_in_image_evidence" in report["failures"][0]["failures"]
    assert "expected_role_not_in_image_evidence" in report["failures"][0]["failures"]
    assert "answer_too_short" in report["failures"][0]["failures"]


def test_run_cases_validates_answer_contains_meaningful_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    case = quality_eval._case(
        case_id="answer-running",
        category="image_state_evidence",
        query="Running 상태는 어떻게 확인해?",
        expected_chunk_ids=["unit-test--running"],
        expected_artifact_kinds=["course_chunk", "course_image_evidence"],
        expected_image_roles=["expected_state_indicator"],
        expected_state_signals=["Running"],
        expected_terms=["Running"],
    )

    monkeypatch.setattr(
        quality_eval,
        "_course_chat_payload",
        lambda root_dir, payload: {
            "answer": "\n".join(
                [
                    "실운영 Study-docs 기준",
                    "질문과 직접 연결된 사내 산출물을 먼저 봅니다. 아래 항목은 PPT/PDF에서 추출된 청크와 원본 slide ref를 기준으로 한 근거입니다.",
                    "- [TEST-UN-OCP-99-01] Pod Running 확인: oc get pods 결과에서 Running 상태와 Ready 컬럼을 함께 확인합니다.",
                    "",
                    "이미지 증적",
                    "- TEST-UN-OCP-99-01 slide 3: expected_state_indicator / Running - Pod status row shows Running.",
                ]
            ),
            "sources": [
                {
                    "source_kind": "project_artifact",
                    "chunk_id": "unit-test--running",
                    "title": "Pod Running 확인",
                }
            ],
            "artifacts": [
                {"kind": "course_chunk", "items": []},
                {
                    "kind": "course_image_evidence",
                    "items": [
                        {
                            "asset_id": "asset-running",
                            "chunk_id": "unit-test--running",
                            "instructional_role": "expected_state_indicator",
                            "state_signal": "Running",
                        }
                    ],
                },
            ],
        },
    )

    report = quality_eval.run_cases([case], root_dir=Path("."))

    assert report["passed"] == 1
    assert report["results"][0]["answer_quality_passed"] is True
    assert report["results"][0]["semantic_context_passed"] is True
    assert report["results"][0]["answer_char_count"] >= 120


def test_run_cases_flags_official_question_without_official_context(monkeypatch: pytest.MonkeyPatch) -> None:
    case = quality_eval._case(
        case_id="official-context",
        category="official_mapping",
        query="TEST-UN-OCP-99-01 Study-docs and official docs",
        expected_chunk_ids=["unit-test--running"],
        expected_artifact_kinds=["course_chunk", "official_check"],
        expected_terms=["TEST-UN-OCP-99-01"],
    )

    monkeypatch.setattr(
        quality_eval,
        "_course_chat_payload",
        lambda root_dir, payload: {
            "answer": "x" * 180,
            "sources": [
                {
                    "source_kind": "project_artifact",
                    "chunk_id": "unit-test--running",
                    "title": "Pod Running",
                }
            ],
            "artifacts": [
                {"kind": "course_chunk", "items": []},
                {"kind": "official_check", "items": []},
            ],
        },
    )

    report = quality_eval.run_cases([case], root_dir=Path("."))

    assert report["failed"] == 1
    failures = report["failures"][0]["failures"]
    assert "semantic_missing_official_context" in failures
    assert "semantic_missing_official_card_items" in failures
    assert report["failures"][0]["semantic_context_passed"] is False


def test_run_cases_flags_guided_step_without_real_next_card(monkeypatch: pytest.MonkeyPatch) -> None:
    case = quality_eval._case(
        case_id="route-step",
        category="guided_route_step",
        query="TEST-UN-OCP-99-01 next step",
        expected_chunk_ids=["unit-test--running"],
        expected_artifact_kinds=["course_chunk", "course_guided_tour"],
    )

    monkeypatch.setattr(
        quality_eval,
        "_course_chat_payload",
        lambda root_dir, payload: {
            "answer": "x" * 180,
            "sources": [
                {
                    "source_kind": "project_artifact",
                    "chunk_id": "unit-test--running",
                    "title": "Pod Running",
                }
            ],
            "artifacts": [
                {"kind": "course_chunk", "items": []},
                {
                    "kind": "course_guided_tour",
                    "items": [
                        {
                            "role": "current",
                            "chunk_id": "unit-test--running",
                            "title": "Pod Running",
                        }
                    ],
                },
            ],
        },
    )

    report = quality_eval.run_cases([case], root_dir=Path("."))

    assert report["failed"] == 1
    assert "semantic_route_step_missing_next_chunk" in report["failures"][0]["failures"]
    assert report["failures"][0]["semantic_context_passed"] is False


def test_run_quality_eval_fails_when_quality_gate_has_rejected_cases() -> None:
    with _temp_root() as root:
        _write_chunk(root, "unit-test--running", _source_chunk())
        args = argparse.Namespace(
            root_dir=root,
            course_dir=Path("data/course_pbs"),
            cases_path=Path("manifests/course_qa_cases.jsonl"),
            accepted_path=Path("manifests/course_qa_cases.accepted.jsonl"),
            rejected_path=Path("manifests/course_qa_cases.rejected.jsonl"),
            report_path=Path("data/course_pbs/manifests/course_qa_report.json"),
            target_count=1,
            min_accepted=1,
            allow_rejected=False,
            verbose_results=False,
            generate=False,
            run=False,
        )
        cases_path = root / "manifests" / "course_qa_cases.jsonl"
        bad_case = {
            **quality_eval._case(
                case_id="bad-case",
                category="image_state_evidence",
                query="Running 상태는 어떻게 확인해?",
                stage_id="unit_test",
                expected_chunk_ids=["unit-test--running"],
                expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                expected_image_roles=["missing_role"],
                expected_state_signals=["Running"],
            ),
            "source": {"chunk_id": "unit-test--running", "asset_id": "asset-running", "asset_path": "data/course_pbs/assets/missing.png"},
        }
        quality_eval.write_jsonl(cases_path, [bad_case])

        exit_code = quality_eval.run_quality_eval(args)
        report = json.loads((root / "data/course_pbs/manifests/course_qa_report.json").read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["accepted_count"] == 0
    assert report["rejected_count"] == 1
    assert report["quality_gate"]["passed"] is False
    assert "accepted_below_min:0<1" in report["quality_gate"]["failures"]
    assert "rejected_cases_present:1" in report["quality_gate"]["failures"]
