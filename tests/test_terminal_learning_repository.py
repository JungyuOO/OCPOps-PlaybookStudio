from __future__ import annotations

from play_book_studio.db.terminal_learning_repository import CommandCheck, evaluate_command_check


def test_evaluate_command_check_matches_regex_pattern():
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="get-pods",
        command_pattern=r"^oc\s+get\s+pods\b",
        expected_command="oc get pods",
    )

    result = evaluate_command_check(check, "  oc   get   pods -n openshift-console ")

    assert result.status == "passed"
    assert result.matched is True
    assert result.validation_result["submitted_command"] == "oc get pods -n openshift-console"


def test_evaluate_command_check_marks_output_validation_pending():
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="get-project",
        command_pattern=r"^oc\s+project$",
        validation_payload={"stdout_contains": "Using project"},
    )

    result = evaluate_command_check(check, "oc project")

    assert result.status == "pending_output"
    assert result.matched is True
    assert result.validation_result["requires_output"] is True


def test_evaluate_command_check_reports_failed_command():
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="get-project",
        expected_command="oc project",
    )

    result = evaluate_command_check(check, "oc get pods")

    assert result.status == "failed"
    assert result.matched is False
