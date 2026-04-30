"""Persistence and validation helpers for terminal-backed learning labs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TerminalLearningContext:
    learner_id: str = ""
    learning_path_id: str = ""
    learning_step_id: str = ""
    lab_task_id: str = ""


@dataclass(frozen=True, slots=True)
class CommandCheck:
    id: str
    lab_task_id: str
    check_key: str
    command_pattern: str = ""
    expected_command: str = ""
    validation_kind: str = "command_pattern"
    validation_payload: dict[str, Any] = field(default_factory=dict)
    success_message: str = ""
    failure_hint: str = ""


@dataclass(frozen=True, slots=True)
class CommandCheckEvaluation:
    status: str
    matched: bool
    validation_result: dict[str, Any]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def evaluate_command_check(check: CommandCheck, command: str) -> CommandCheckEvaluation:
    normalized = _normalize_command(command)
    payload = dict(check.validation_payload or {})
    details: dict[str, Any] = {
        "validation_kind": check.validation_kind,
        "submitted_command": normalized,
        "expected_command": check.expected_command,
        "command_pattern": check.command_pattern,
    }
    matched = False
    error = ""
    pattern = str(payload.get("command_regex") or check.command_pattern or "").strip()
    contains = str(payload.get("command_contains") or "").strip()
    expected = _normalize_command(str(payload.get("expected_command") or check.expected_command or ""))

    if pattern:
        try:
            matched = re.search(pattern, normalized) is not None
        except re.error as exc:
            error = f"invalid command regex: {exc}"
    elif contains:
        matched = contains.casefold() in normalized.casefold()
    elif expected:
        matched = normalized.casefold() == expected.casefold()

    requires_output = any(
        key in payload
        for key in (
            "stdout_contains",
            "stderr_contains",
            "output_contains",
            "expected_exit_code",
        )
    )
    if error:
        status = "error"
    elif matched and requires_output:
        status = "pending_output"
    elif matched:
        status = "passed"
    else:
        status = "failed"
    details.update(
        {
            "matched": matched,
            "requires_output": requires_output,
            "error": error,
        }
    )
    return CommandCheckEvaluation(status=status, matched=matched, validation_result=details)


def create_terminal_session(
    connection,
    *,
    client_session_id: str,
    shell: str,
    workdir: str,
    context: TerminalLearningContext | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    context = context or TerminalLearningContext()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO terminal_sessions (
                client_session_id, learner_id, learning_path_id, learning_step_id,
                lab_task_id, shell, workdir, metadata
            )
            VALUES (
                %s, %s, NULLIF(%s, '')::uuid, NULLIF(%s, '')::uuid,
                NULLIF(%s, '')::uuid, %s, %s, %s::jsonb
            )
            ON CONFLICT (client_session_id) DO UPDATE SET
                learner_id = EXCLUDED.learner_id,
                learning_path_id = EXCLUDED.learning_path_id,
                learning_step_id = EXCLUDED.learning_step_id,
                lab_task_id = EXCLUDED.lab_task_id,
                shell = EXCLUDED.shell,
                workdir = EXCLUDED.workdir,
                status = 'started',
                started_at = now(),
                ended_at = NULL,
                exit_code = NULL,
                metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (
                client_session_id,
                context.learner_id,
                context.learning_path_id,
                context.learning_step_id,
                context.lab_task_id,
                shell,
                workdir,
                _json(metadata or {}),
            ),
        )
        return str(cursor.fetchone()[0])


def update_terminal_session_context(
    connection,
    *,
    terminal_session_id: str,
    context: TerminalLearningContext,
) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE terminal_sessions
            SET
                learner_id = COALESCE(NULLIF(%s, ''), learner_id),
                learning_path_id = COALESCE(NULLIF(%s, '')::uuid, learning_path_id),
                learning_step_id = COALESCE(NULLIF(%s, '')::uuid, learning_step_id),
                lab_task_id = COALESCE(NULLIF(%s, '')::uuid, lab_task_id)
            WHERE id = %s::uuid
            RETURNING learning_step_id
            """,
            (
                context.learner_id,
                context.learning_path_id,
                context.learning_step_id,
                context.lab_task_id,
                terminal_session_id,
            ),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        return str(row[0])


def create_learning_step_attempt(
    connection,
    *,
    terminal_session_id: str,
    context: TerminalLearningContext,
) -> str | None:
    if not context.learning_step_id:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO learning_step_attempts (
                learner_id, learning_path_id, learning_step_id, terminal_session_id, metadata
            )
            VALUES (%s, NULLIF(%s, '')::uuid, %s::uuid, %s::uuid, '{}'::jsonb)
            RETURNING id
            """,
            (
                context.learner_id,
                context.learning_path_id,
                context.learning_step_id,
                terminal_session_id,
            ),
        )
        return str(cursor.fetchone()[0])


def record_terminal_event(
    connection,
    *,
    terminal_session_id: str,
    event_ordinal: int,
    event_type: str,
    stream: str = "",
    data: str = "",
    command_text: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO terminal_events (
                terminal_session_id, event_ordinal, event_type, stream, data, command_text, metadata
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                terminal_session_id,
                int(event_ordinal),
                event_type,
                stream,
                data,
                command_text,
                _json(metadata or {}),
            ),
        )
        return str(cursor.fetchone()[0])


def finish_terminal_session(
    connection,
    *,
    terminal_session_id: str,
    status: str,
    exit_code: int | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE terminal_sessions
            SET status = %s, exit_code = %s, ended_at = now()
            WHERE id = %s::uuid
            """,
            (status, exit_code, terminal_session_id),
        )


def load_command_checks_for_lab_task(connection, *, lab_task_id: str) -> tuple[CommandCheck, ...]:
    if not lab_task_id:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id, lab_task_id, check_key, command_pattern, expected_command,
                validation_kind, validation_payload, success_message, failure_hint
            FROM command_checks
            WHERE lab_task_id = %s::uuid
            ORDER BY ordinal ASC
            """,
            (lab_task_id,),
        )
        return tuple(
            CommandCheck(
                id=str(row[0]),
                lab_task_id=str(row[1]),
                check_key=str(row[2] or ""),
                command_pattern=str(row[3] or ""),
                expected_command=str(row[4] or ""),
                validation_kind=str(row[5] or ""),
                validation_payload=_json_value(row[6], {}),
                success_message=str(row[7] or ""),
                failure_hint=str(row[8] or ""),
            )
            for row in cursor.fetchall()
        )


def upsert_command_check_result(
    connection,
    *,
    terminal_session_id: str,
    terminal_event_id: str,
    command_check: CommandCheck,
    learning_step_attempt_id: str | None,
    learner_id: str,
    submitted_command: str,
    evaluation: CommandCheckEvaluation,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO command_check_results (
                learning_step_attempt_id, terminal_session_id, terminal_event_id,
                command_check_id, lab_task_id, learner_id, submitted_command,
                status, matched, validation_result, updated_at
            )
            VALUES (
                NULLIF(%s, '')::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                %s, %s, %s, %s, %s::jsonb, now()
            )
            ON CONFLICT (terminal_session_id, command_check_id) DO UPDATE SET
                learning_step_attempt_id = EXCLUDED.learning_step_attempt_id,
                terminal_event_id = EXCLUDED.terminal_event_id,
                learner_id = EXCLUDED.learner_id,
                submitted_command = EXCLUDED.submitted_command,
                status = EXCLUDED.status,
                matched = EXCLUDED.matched,
                validation_result = EXCLUDED.validation_result,
                updated_at = now()
            RETURNING id
            """,
            (
                learning_step_attempt_id or "",
                terminal_session_id,
                terminal_event_id,
                command_check.id,
                command_check.lab_task_id,
                learner_id,
                submitted_command,
                evaluation.status,
                evaluation.matched,
                _json(evaluation.validation_result),
            ),
        )
        return str(cursor.fetchone()[0])


__all__ = [
    "CommandCheck",
    "CommandCheckEvaluation",
    "TerminalLearningContext",
    "create_learning_step_attempt",
    "create_terminal_session",
    "evaluate_command_check",
    "finish_terminal_session",
    "load_command_checks_for_lab_task",
    "record_terminal_event",
    "update_terminal_session_context",
    "upsert_command_check_result",
]
