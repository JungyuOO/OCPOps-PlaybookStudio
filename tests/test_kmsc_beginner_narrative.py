from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.course.qdrant_course import load_ops_learning_chunks
from play_book_studio.ingestion.kmsc_beginner_narrative import (
    build_beginner_narrative,
    derive_ops_learning_chunks,
)


def _course_chunk(index: int) -> dict:
    return {
        "chunk_id": f"chunk-{index:03d}",
        "stage_id": "perf_test" if index % 2 else "integration_test",
        "title": f"Pod 상태와 서비스 검증 {index}",
        "search_text": f"OpenShift Pod Service Deployment Route 상태를 확인하는 운영 증적 {index}",
        "body_md": "테스트 결과 화면과 명령 결과를 보고 정상 상태와 실패 징후를 분리한다.",
        "image_attachments": [
            {
                "is_default_visible": True,
                "instructional_role": "command_result_evidence",
                "instructional_roles": ["console_output", "expected_state_indicator"],
                "visual_summary": "Pod Running 상태와 Service endpoint 연결 상태를 보여준다.",
                "state_signal": "Running",
            }
        ],
    }


def test_beginner_narrative_is_derived_from_chunk_content() -> None:
    narrative = build_beginner_narrative(_course_chunk(1))

    assert "Pod 상태와 서비스 검증 1" in narrative
    assert "처음 보는 사용자" in narrative
    assert "Pod" in narrative or "Service" in narrative


def test_ops_learning_chunks_auto_expand_to_minimum_count() -> None:
    course_chunks = [_course_chunk(index) for index in range(120)]
    existing = [
        {
            "learning_chunk_id": "curated-1",
            "source_chunk_ids": ["chunk-000"],
            "title": "기존 curated 항목",
        }
    ]

    derived = derive_ops_learning_chunks(course_chunks, existing_learning_chunks=existing, min_count=100, max_count=120)

    assert len(derived) >= 100
    assert derived[0]["learning_chunk_id"] == "curated-1"
    assert all(item.get("query_variants") for item in derived[1:10])
    assert all(item.get("beginner_explanation") for item in derived[1:10])


def test_load_ops_learning_chunks_derives_from_course_chunks(tmp_path: Path) -> None:
    course_dir = tmp_path / "course_pbs"
    manifests = course_dir / "manifests"
    manifests.mkdir(parents=True)
    (course_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(_course_chunk(index), ensure_ascii=False) for index in range(110)),
        encoding="utf-8",
    )
    (manifests / "ops_learning_chunks_v1.jsonl").write_text(
        json.dumps(
            {
                "learning_chunk_id": "curated-1",
                "source_chunk_ids": ["chunk-000"],
                "title": "기존 curated 항목",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    chunks = load_ops_learning_chunks(course_dir)

    assert len(chunks) >= 100
    assert chunks[0]["learning_chunk_id"] == "curated-1"
    assert any(item.get("metadata", {}).get("generated") for item in chunks[1:])
