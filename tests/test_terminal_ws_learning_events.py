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
