from __future__ import annotations

from play_book_studio.course.pipeline.image_policy import apply_image_policy_to_chunk


def test_small_running_status_is_preserved_as_verification_evidence() -> None:
    chunk = {
        "title": "Pod status verification",
        "stage_id": "unit_test",
        "chunk_kind": "test_case_summary",
        "body_md": "Run oc get pods and verify the pod status.",
        "structured": {
            "method": "oc get pods -n demo",
            "expected": "The target pod is Running and Ready.",
            "verification": "Confirm the STATUS column.",
        },
        "image_attachments": [
            {
                "asset_id": "asset-running",
                "bbox_norm": [0.1, 0.1, 0.3, 0.13],
                "ocr_text": "NAME READY STATUS RESTARTS AGE api-1 1/1 Running 0 2m",
                "visual_summary": "A small pod status row shows the pod is Running.",
            }
        ],
    }

    result = apply_image_policy_to_chunk(chunk)
    attachment = result["image_attachments"][0]

    assert attachment["quality_label"] == "tiny_strip_or_icon"
    assert "expected_state_indicator" in attachment["instructional_roles"]
    assert "success_state" in attachment["instructional_roles"]
    assert attachment["state_signal"] == "Running"
    assert attachment["rank_profiles"]["procedure"] >= 0.9
    assert attachment["is_default_visible"] is True


def test_failure_state_is_ranked_for_troubleshooting() -> None:
    chunk = {
        "title": "Deployment failure check",
        "stage_id": "unit_test",
        "chunk_kind": "test_case_summary",
        "body_md": "Verify abnormal pod status after rollout.",
        "structured": {"verification": "Check Failed, Error, and CrashLoopBackOff states."},
        "image_attachments": [
            {
                "asset_id": "asset-failed",
                "bbox_norm": [0.05, 0.2, 0.85, 0.28],
                "ocr_text": "NAME READY STATUS RESTARTS AGE api-1 0/1 CrashLoopBackOff 5 10m",
            }
        ],
    }

    result = apply_image_policy_to_chunk(chunk)
    attachment = result["image_attachments"][0]

    assert attachment["instructional_role"] == "failure_state"
    assert "failure_state" in attachment["instructional_roles"]
    assert attachment["state_signal"] == "CrashLoopBackOff"
    assert attachment["rank_profiles"]["troubleshooting"] >= 0.9
    assert attachment["is_default_visible"] is True


def test_blank_attachment_is_not_default_visible() -> None:
    chunk = {
        "title": "Blank evidence",
        "stage_id": "completion",
        "chunk_kind": "chapter_summary",
        "body_md": "",
        "structured": {},
        "image_attachments": [
            {
                "asset_id": "asset-blank",
                "bbox_norm": [0.0, 0.0, 0.01, 0.01],
                "ocr_text": "",
                "visual_summary": "",
            }
        ],
    }

    result = apply_image_policy_to_chunk(chunk)
    attachment = result["image_attachments"][0]

    assert attachment["quality_label"] == "blank_or_solid"
    assert attachment["instructional_role"] == "decorative_or_empty"
    assert attachment["exclude_from_default"] is True
    assert attachment["is_default_visible"] is False


def test_empty_visual_summary_is_not_promoted_by_context() -> None:
    chunk = {
        "title": "Command verification",
        "stage_id": "integration_test",
        "chunk_kind": "test_case_summary",
        "body_md": "Run oc get pods and verify the result.",
        "structured": {"verification": "Confirm the command output."},
        "image_attachments": [
            {
                "asset_id": "asset-empty-summary",
                "bbox_norm": [0.0, 0.1, 0.9, 0.18],
                "visual_summary": "The image has a black background and no visible text.",
            }
        ],
    }

    result = apply_image_policy_to_chunk(chunk)
    attachment = result["image_attachments"][0]

    assert attachment["quality_label"] == "blank_or_solid"
    assert attachment["instructional_role"] == "decorative_or_empty"
    assert attachment["rank_profiles"]["procedure"] == 0.05
    assert attachment["is_default_visible"] is False


def test_black_terminal_log_is_preserved_as_console_evidence() -> None:
    chunk = {
        "title": "Build failure log",
        "stage_id": "integration_test",
        "chunk_kind": "test_case_summary",
        "body_md": "Check the terminal output after running the build pipeline.",
        "structured": {"verification": "Review the Failed pipeline log."},
        "image_attachments": [
            {
                "asset_id": "asset-terminal-log",
                "bbox_norm": [0.02, 0.1, 0.96, 0.72],
                "visual_summary": "A black background terminal shows Java build log text.",
                "ocr_text": "ERROR: cannot find symbol\nBUILD FAILED in 32s\nPipelineRun status Failed",
            }
        ],
    }

    result = apply_image_policy_to_chunk(chunk)
    attachment = result["image_attachments"][0]

    assert attachment["quality_label"] == "informative"
    assert attachment["instructional_role"] == "failure_state"
    assert "console_output" in attachment["instructional_roles"]
    assert attachment["state_signal"] == "Failed"
    assert attachment["exclude_from_default"] is False
    assert attachment["is_default_visible"] is True
