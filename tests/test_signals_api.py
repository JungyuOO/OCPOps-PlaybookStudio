from __future__ import annotations

from play_book_studio.http.signals_api import _signal_from_command


def _row(command: str) -> dict[str, str]:
    return {
        "id": "signal-a",
        "terminal_session_id": "session-a",
        "command_text": command,
        "created_at": "2026-05-08T01:00:00+00:00",
    }


def test_signal_from_command_uses_resource_kind_and_name() -> None:
    signal = _signal_from_command(_row("oc delete pod demo-pod -n demo"))

    assert signal is not None
    assert signal["operation_type"] == "delete"
    assert signal["resource_kind"] == "pod"
    assert signal["resource_name"] == "demo-pod"
    assert signal["namespace"] == "demo"


def test_signal_from_apply_filename_does_not_treat_path_as_resource_kind() -> None:
    signal = _signal_from_command(_row("oc apply --dry-run=client -f /dev/null"))

    assert signal is not None
    assert signal["operation_type"] == "apply"
    assert signal["resource_kind"] == "manifest"
    assert signal["resource_name"] == ""
