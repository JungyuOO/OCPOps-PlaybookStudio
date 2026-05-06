from __future__ import annotations

from play_book_studio.http import terminal_ws
from play_book_studio.db.terminal_learning_repository import CommandCheck, TerminalLearningContext


def test_terminal_recorder_emits_command_check_result_event(monkeypatch):
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="oc-project",
        command_pattern=r"^oc project$",
        expected_command="oc project",
    )
    recorder = terminal_ws.TerminalEventRecorder(
        database_url="postgresql://unit-test",
        session=object(),
        context=TerminalLearningContext(learner_id="learner-1", lab_task_id="task-1"),
    )
    recorder.connection = object()
    recorder.terminal_session_id = "terminal-1"
    recorder.learning_step_attempt_id = "attempt-1"

    monkeypatch.setattr(terminal_ws, "record_terminal_event", lambda *args, **kwargs: "event-1")
    monkeypatch.setattr(terminal_ws, "load_command_checks_for_lab_task", lambda *args, **kwargs: (check,))
    monkeypatch.setattr(terminal_ws, "upsert_command_check_result", lambda *args, **kwargs: "result-1")

    events = recorder.record_input("oc project\r")

    assert events == [
        {
            "type": "command_check_result",
            "id": "result-1",
            "terminal_session_id": "terminal-1",
            "terminal_event_id": "event-1",
            "command_check_id": "check-1",
            "lab_task_id": "task-1",
            "learner_id": "learner-1",
            "submitted_command": "oc project",
            "status": "passed",
            "matched": True,
            "validation_result": {
                "validation_kind": "command_pattern",
                "submitted_command": "oc project",
                "expected_command": "oc project",
                "command_pattern": r"^oc project$",
                "matched": True,
                "requires_output": False,
                "error": "",
            },
        }
    ]


def test_terminal_recorder_updates_pending_output_check_from_scoped_stdout(monkeypatch):
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="oc-project-output",
        command_pattern=r"^oc project$",
        expected_command="oc project",
        validation_payload={"stdout_contains": "Using project"},
    )
    recorder = terminal_ws.TerminalEventRecorder(
        database_url="postgresql://unit-test",
        session=object(),
        context=TerminalLearningContext(learner_id="learner-1", lab_task_id="task-1"),
    )
    recorder.connection = object()
    recorder.terminal_session_id = "terminal-1"
    recorder.learning_step_attempt_id = "attempt-1"

    event_ids = iter(["command-event-1", "output-event-1"])
    result_ids = iter(["pending-result-1", "passed-result-1"])
    monkeypatch.setattr(terminal_ws, "record_terminal_event", lambda *args, **kwargs: next(event_ids))
    monkeypatch.setattr(terminal_ws, "load_command_checks_for_lab_task", lambda *args, **kwargs: (check,))
    monkeypatch.setattr(terminal_ws, "upsert_command_check_result", lambda *args, **kwargs: next(result_ids))

    pending_events = recorder.record_input("oc project\r")
    output_events = recorder.record_output(stream="stdout", data="Using project \"demo\" on server")

    assert pending_events[0]["status"] == "pending_output"
    assert pending_events[0]["matched"] is True
    assert output_events == [
        {
            "type": "command_check_result",
            "id": "passed-result-1",
            "terminal_session_id": "terminal-1",
            "terminal_event_id": "command-event-1",
            "command_check_id": "check-1",
            "lab_task_id": "task-1",
            "learner_id": "learner-1",
            "submitted_command": "oc project",
            "status": "passed",
            "matched": True,
            "validation_result": {
                "validation_kind": "command_pattern",
                "submitted_command": "oc project",
                "expected_command": "oc project",
                "command_pattern": r"^oc project$",
                "matched": True,
                "requires_output": True,
                "error": "",
                "stdout": "Using project \"demo\" on server",
                "stderr": "",
                "exit_code": None,
                "stdout_contains_matched": True,
            },
        }
    ]
    assert recorder.pending_output_checks == []
