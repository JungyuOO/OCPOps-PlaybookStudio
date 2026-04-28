from __future__ import annotations

from play_book_studio.course.qdrant_course import (
    course_embedding_text,
    course_point_payload,
    ops_learning_embedding_text,
    ops_learning_point_payload,
)


def test_course_embedding_text_includes_image_evidence_fields() -> None:
    chunk = {
        "chunk_id": "chunk-image",
        "stage_id": "integration_test",
        "title": "Failure verification",
        "search_text": "Check pipeline failure.",
        "image_attachments": [
            {
                "instructional_role": "failure_state",
                "instructional_roles": ["failure_state", "console_output"],
                "state_signal": "CrashLoopBackOff",
                "quality_label": "informative",
                "visual_summary": "Pod status row shows CrashLoopBackOff.",
                "ocr_text": "NAME READY STATUS api-1 0/1 CrashLoopBackOff",
            }
        ],
    }

    text = course_embedding_text(chunk)
    payload = course_point_payload(chunk)

    assert "CrashLoopBackOff" in text
    assert "failure_state" in text
    assert "console_output" in text
    assert "CrashLoopBackOff" in payload["image_text"]
    assert "CrashLoopBackOff" in payload["text"]


def test_course_point_payload_keeps_image_text_separate() -> None:
    chunk = {
        "chunk_id": "chunk-running",
        "stage_id": "integration_test",
        "title": "Running verification",
        "image_attachments": [
            {
                "instructional_role": "expected_state_indicator",
                "state_signal": "Running",
                "visual_summary": "A small status strip shows Running.",
            }
        ],
    }

    payload = course_point_payload(chunk)

    assert payload["image_text"]
    assert "Running" in payload["image_text"]


def test_ops_learning_point_payload_preserves_step_source_and_suggestions() -> None:
    learning_chunk = {
        "learning_chunk_id": "cicd::flow",
        "chunk_type": "ops_learning_step",
        "guide_id": "cicd",
        "step_id": "flow",
        "stage_id": "architecture",
        "title": "CI/CD flow",
        "learning_goal": "Understand GitOps, Tekton, and ArgoCD in the release path.",
        "operational_sequence": ["Check merge approval.", "Check pipeline result."],
        "what_to_look_for": ["MR approval", "Pipeline Succeeded"],
        "normal_state": ["Succeeded", "Synced"],
        "failure_state": ["Failed", "OutOfSync"],
        "visual_evidence_roles": ["success_state", "failure_state"],
        "source_chunk_ids": ["source-a", "source-b"],
        "hidden_native_ids": ["DSGN-005-402"],
        "next_step_ids": ["validate"],
        "query_variants": ["How should I read the CI/CD flow?"],
    }

    text = ops_learning_embedding_text(learning_chunk)
    payload = ops_learning_point_payload(learning_chunk)

    assert "GitOps" in text
    assert "Pipeline Succeeded" in text
    assert payload["chunk_type"] == "ops_learning_step"
    assert payload["source_collection"] == "course_ops_learning"
    assert payload["source_chunk_ids"] == ["source-a", "source-b"]
    assert payload["hidden_native_ids"] == ["DSGN-005-402"]
    assert payload["query_variants"] == ["How should I read the CI/CD flow?"]
