from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from play_book_studio.course import ops_learning


@contextmanager
def _temp_root() -> Iterator[Path]:
    temp_parent = Path.cwd() / ".pytest-tmp" / "course-ops-learning"
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


def test_classify_primary_learning_anchor_requires_real_learning_content() -> None:
    chunk = {
        "chunk_id": "perf-test--4",
        "stage_id": "perf_test",
        "native_id": "4",
        "title": "성능 테스트 결과",
        "body_md": "DB SQL 응답 지연으로 전체 응답시간이 늦어진다. DB Connection Pool 대기와 worker-thread 설정을 함께 확인한다. HPA scale-out 동작과 HAProxy 자원 사용량을 보조 지표로 확인한다." * 3,
        "search_text": "성능 테스트 결과 DB SQL 응답 지연 DB Connection Pool worker-thread HPA HAProxy Prometheus 병목 개선 포인트",
        "review_status": "approved",
        "quality_score": 0.98,
        "tour_stop": {"route_role": "start_here"},
        "related_official_docs": [{"score": 0.76, "title": "Monitoring"}],
        "image_attachments": [
            {
                "instructional_role": "dashboard_metric",
                "instructional_roles": ["dashboard_metric", "command_result_evidence"],
            }
        ],
    }

    result = ops_learning.classify_learning_anchor(chunk)

    assert result["classification"] == "primary_learning_anchor"
    assert result["beginner_candidate"] is True
    assert "has_operational_image_evidence" in result["reasons"]


def test_classify_source_only_cover_even_when_quality_score_is_high() -> None:
    chunk = {
        "chunk_id": "completion--CH-01",
        "stage_id": "completion",
        "native_id": "CH-01",
        "title": "완료보고 완료본",
        "body_md": "",
        "search_text": "CH-01 완료보고 완료본. completion 단계의 chapter_summary 청크.",
        "review_status": "approved",
        "quality_score": 0.98,
        "tour_stop": {"route_role": "start_here"},
    }

    result = ops_learning.classify_learning_anchor(chunk)

    assert result["classification"] == "source_only"
    assert result["beginner_candidate"] is False
    assert "source_only_or_cover_like" in result["issues"]


def test_classify_image_context_failure_evidence_as_supporting_anchor() -> None:
    chunk = {
        "chunk_id": "integration-failure",
        "stage_id": "integration_test",
        "native_id": "3",
        "title": "실패 및 롤백 테스트",
        "body_md": "",
        "search_text": "실패 및 롤백 테스트 Failed Build failed CrashLoopBackOff 상태 확인 GitLab GitOps pipeline deployment pod log console",
        "review_status": "approved",
        "quality_score": 0.98,
        "image_attachments": [
            {"instructional_role": "failure_state", "visual_summary": "파이프라인 실행 상태가 Failed로 표시됨"},
            {"instructional_role": "console_output", "visual_summary": "Build failed 로그가 표시됨"},
            {"instructional_role": "expected_state_indicator", "visual_summary": "Pod 상태가 CrashLoopBackOff로 표시됨"},
        ],
    }

    result = ops_learning.classify_learning_anchor(chunk)

    assert result["classification"] == "supporting_evidence"
    assert "image_context_evidence_anchor" in result["reasons"]
    assert "source_only_or_cover_like" not in result["issues"]


def test_build_anchor_audit_summarizes_stage_candidates_and_weak_route_starts() -> None:
    with _temp_root() as root:
        _write_manifest(root, {"tour": {"stop_count": 2}})
        _write_chunk(
            root,
            "good",
            {
                "chunk_id": "good",
                "stage_id": "perf_test",
                "native_id": "4",
                "title": "성능 테스트 결과",
                "body_md": "DB SQL 응답 지연과 Connection Pool 대기, HPA scale-out, HAProxy 지표를 순서대로 확인한다." * 4,
                "search_text": "성능 테스트 결과 DB SQL 응답 지연 Connection Pool HPA HAProxy",
                "review_status": "approved",
                "quality_score": 0.98,
                "tour_stop": {"route_role": "start_here", "stop_order": 1},
                "image_attachments": [{"instructional_role": "dashboard_metric"}],
                "related_official_docs": [{"score": 0.8, "title": "Monitoring"}],
            },
        )
        _write_chunk(
            root,
            "cover",
            {
                "chunk_id": "cover",
                "stage_id": "completion",
                "native_id": "CH-01",
                "title": "완료보고 완료본",
                "body_md": "",
                "search_text": "CH-01 완료보고 완료본.",
                "review_status": "approved",
                "quality_score": 0.98,
                "tour_stop": {"route_role": "start_here", "stop_order": 1},
            },
        )

        payload = ops_learning.build_anchor_audit(Path("data/course_pbs"), root_dir=root)

    assert payload["canonical_model"] == "ops_learning_anchor_audit_v1"
    assert payload["source_chunk_count"] == 2
    assert payload["summary"]["beginner_candidate_count"] == 1
    assert payload["stage_summaries"]["perf_test"]["beginner_candidate_count"] == 1
    assert payload["stage_summaries"]["completion"]["weak_route_starts"][0]["chunk_id"] == "cover"


def test_initial_guides_keep_user_queries_free_of_internal_ids() -> None:
    with _temp_root() as root:
        _write_manifest(root, {"tour": {"stop_count": 1}})
        for guide in ops_learning.INITIAL_GUIDE_DEFINITIONS:
            for step in guide["steps"]:
                for chunk_id in step["source_chunk_ids"]:
                    _write_chunk(
                        root,
                        chunk_id,
                        {
                            "chunk_id": chunk_id,
                            "stage_id": guide["stage_id"],
                            "native_id": "DSGN-005-001",
                            "title": step["card_text"],
                            "body_md": "운영 학습 단계에 필요한 충분한 본문입니다. " * 10,
                            "search_text": "운영 학습 검색 텍스트 OpenShift GitOps HPA PVC Service Mesh",
                            "review_status": "approved",
                            "quality_score": 0.98,
                            "tour_stop": {"route_role": "standard"},
                        },
                    )

        payload = ops_learning.build_initial_guides(Path("data/course_pbs"), root_dir=root)
        cases = ops_learning.build_ops_learning_golden_cases(payload)
        accepted, rejected = ops_learning.validate_ops_learning_golden_cases(cases)

    assert payload["guide_count"] >= 7
    assert payload["step_count"] == len(cases)
    assert rejected == []
    assert accepted
    assert all(not ops_learning.INTERNAL_ID_RE.search(step["user_query"]) for guide in payload["guides"] for step in guide["steps"])
    assert all((case["source"] or {}).get("hidden_doc_anchor") is True for case in accepted)


def test_build_ops_learning_chunks_creates_second_corpus_without_fixed_answer_outline() -> None:
    with _temp_root() as root:
        chunk_id = "perf-source"
        long_sequence = (
            "HPA collects current CPU and memory metrics from metrics-server at the configured interval of about 15 seconds, "
            "compares the collected values with the target threshold, triggers scale-out action until the configured max replica "
            "count when the threshold is exceeded, and the operator should verify whether latency drops after the new pods become ready."
        )
        _write_manifest(root, {"tour": {"stop_count": 1}})
        _write_chunk(
            root,
            chunk_id,
            {
                "chunk_id": chunk_id,
                "stage_id": "perf_test",
                "native_id": "PERF-4",
                "title": "Performance result",
                "body_md": f"DB SQL response latency and DB Connection Pool waits are the first bottleneck evidence. {long_sequence}",
                "search_text": "DB SQL response latency DB Connection Pool HPA HAProxy bottleneck",
                "image_attachments": [
                    {"instructional_role": "dashboard_metric", "visual_summary": "Prometheus dashboard shows high response latency."}
                ],
            },
        )
        guides = {
            "canonical_model": "ops_learning_guide_v1",
            "guides": [
                {
                    "guide_id": "performance_bottleneck_review",
                    "stage_id": "perf_test",
                    "audience": "beginner_operator",
                    "steps": [
                        {
                            "step_id": "perf_result_bottleneck",
                            "stage_id": "perf_test",
                            "card_text": "성능 병목 확인",
                            "user_query": "성능 병목은 어디부터 보면 돼?",
                            "learning_objective": "DB 응답 지연과 Connection Pool 대기를 먼저 확인한다.",
                            "answer_outline": ["This must not be copied as a fixed answer."],
                            "expected_terms": ["DB SQL response latency", "DB Connection Pool", "HPA"],
                            "source_anchors": [{"chunk_id": chunk_id, "native_id": "PERF-4", "hidden_from_user": True}],
                            "evidence_requirements": {"image_roles": ["dashboard_metric"]},
                            "next_step_ids": [],
                        }
                    ],
                }
            ],
        }

        learning_chunks = ops_learning.build_ops_learning_chunks(Path("data/course_pbs"), guides, root_dir=root)

    assert len(learning_chunks) == 1
    learning = learning_chunks[0]
    assert learning["canonical_model"] == "ops_learning_chunk_v1"
    assert learning["chunk_type"] == "ops_learning_step"
    assert learning["source_chunk_ids"] == [chunk_id]
    assert learning["hidden_native_ids"] == ["PERF-4"]
    assert "answer_outline" not in learning
    assert "This must not be copied" not in learning["embedding_text"]
    assert any("Connection Pool" in item for item in learning["operational_sequence"])
    assert any(len(item) > 180 and "latency drops after the new pods become ready" in item for item in learning["operational_sequence"])
    assert "dashboard_metric" in learning["visual_evidence_roles"]
    assert all(not ops_learning.INTERNAL_ID_RE.search(item) for item in learning["query_variants"])


def test_validate_ops_learning_golden_cases_checks_source_terms_and_image_roles() -> None:
    cases = [
        {
            "id": "guide-integration-failure",
            "query": "파이프라인이 실패하면 어떤 상태와 로그부터 봐야 해?",
            "expected": {
                "chunk_ids": ["failure"],
                "terms": ["Failed", "Build failed", "CrashLoopBackOff"],
                "image_roles": ["failure_state", "console_output"],
            },
        },
        {
            "id": "guide-bad-role",
            "query": "테스트 결과는 어떻게 정리해?",
            "expected": {
                "chunk_ids": ["failure"],
                "terms": ["없는근거"],
                "image_roles": ["dashboard_metric"],
            },
        },
    ]
    chunks_by_id = {
        "failure": {
            "chunk_id": "failure",
            "title": "실패 및 롤백 테스트",
            "search_text": "Failed Build failed CrashLoopBackOff",
            "image_attachments": [
                {"instructional_role": "failure_state"},
                {"instructional_role": "console_output"},
            ],
        }
    }

    accepted, rejected = ops_learning.validate_ops_learning_golden_cases(cases, chunks_by_id=chunks_by_id)

    assert [case["id"] for case in accepted] == ["guide-integration-failure"]
    assert rejected[0]["id"] == "guide-bad-role"
    assert "expected_term_not_in_source_chunk:없는근거" in rejected[0]["quality_reasons"]
    assert "expected_image_role_not_in_source_chunk:dashboard_metric" in rejected[0]["quality_reasons"]


def test_repository_ops_learning_golden_cases_are_grounded_in_source_chunks() -> None:
    course_dir = Path("data/course_pbs")
    golden_path = Path("manifests/course_ops_learning_golden_cases.jsonl")
    if not course_dir.exists() or not golden_path.exists():
        return
    cases = [json.loads(line) for line in golden_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks_by_id, _ = ops_learning._chunk_maps(course_dir)  # noqa: SLF001

    accepted, rejected = ops_learning.validate_ops_learning_golden_cases(cases, chunks_by_id=chunks_by_id)

    assert rejected == []
    assert len(accepted) == len(cases)
    assert all(not ops_learning.INTERNAL_ID_RE.search(str(case.get("query") or "")) for case in accepted)


def test_repository_ops_learning_chunks_are_grounded_and_public_queries_hide_internal_ids() -> None:
    course_dir = Path("data/course_pbs")
    learning_path = Path("data/course_pbs/manifests/ops_learning_chunks_v1.jsonl")
    if not course_dir.exists() or not learning_path.exists():
        return
    rows = [json.loads(line) for line in learning_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks_by_id, _ = ops_learning._chunk_maps(course_dir)  # noqa: SLF001

    assert len(rows) >= 18
    for row in rows:
        assert row["chunk_type"] == "ops_learning_step"
        assert row["source_chunk_ids"]
        assert all(chunk_id in chunks_by_id for chunk_id in row["source_chunk_ids"])
        assert row["hidden_native_ids"]
        assert row["embedding_text"]
        assert "answer_outline" not in row
        assert not ops_learning.INTERNAL_ID_RE.search(str(row.get("title") or ""))
        assert all(not ops_learning.INTERNAL_ID_RE.search(str(query or "")) for query in row.get("query_variants", []))
