"""WebSocket transport for Terminal Session runtime."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from play_book_studio.config.settings import Settings
from play_book_studio.db.terminal_learning_repository import (
    TerminalLearningContext,
    create_learning_step_attempt,
    create_terminal_session,
    evaluate_command_check,
    finish_terminal_session,
    load_command_checks_for_lab_task,
    record_terminal_event,
    update_terminal_session_context,
    upsert_command_check_result,
)

from .terminal_session import TerminalSession, TerminalSessionConfig

def _json_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False)


def _terminal_workdir(settings: Settings, root_dir: Path) -> Path:
    if not settings.terminal_workdir_override:
        return root_dir
    path = Path(settings.terminal_workdir_override)
    if path.is_absolute():
        return path
    return root_dir / path


def build_terminal_session_config(settings: Settings, root_dir: Path) -> TerminalSessionConfig:
    return TerminalSessionConfig(
        shell=settings.terminal_shell,
        workdir=_terminal_workdir(settings, root_dir),
        ttl_seconds=settings.terminal_session_ttl_seconds,
        max_output_bytes=settings.terminal_max_output_bytes,
    )


def _context_from_message(message: dict[str, Any]) -> TerminalLearningContext:
    return TerminalLearningContext(
        learner_id=str(message.get("learner_id") or message.get("learnerId") or ""),
        learning_path_id=str(message.get("learning_path_id") or message.get("learningPathId") or ""),
        learning_step_id=str(message.get("learning_step_id") or message.get("learningStepId") or ""),
        lab_task_id=str(message.get("lab_task_id") or message.get("labTaskId") or ""),
    )


def _context_from_path(path: str) -> TerminalLearningContext:
    query = path.split("?", 1)[1] if "?" in path else ""
    params = parse_qs(query)
    return TerminalLearningContext(
        learner_id=(params.get("learner_id") or params.get("learnerId") or [""])[0],
        learning_path_id=(params.get("learning_path_id") or params.get("learningPathId") or [""])[0],
        learning_step_id=(params.get("learning_step_id") or params.get("learningStepId") or [""])[0],
        lab_task_id=(params.get("lab_task_id") or params.get("labTaskId") or [""])[0],
    )


def _websocket_path(websocket, args: tuple[object, ...]) -> str:
    if args and isinstance(args[0], str):
        return args[0]
    request = getattr(websocket, "request", None)
    return str(getattr(request, "path", "") or "")


class TerminalEventRecorder:
    def __init__(self, *, database_url: str, session: TerminalSession, context: TerminalLearningContext) -> None:
        self.database_url = database_url
        self.session = session
        self.context = context
        self.terminal_session_id = ""
        self.learning_step_attempt_id: str | None = None
        self.event_ordinal = 0
        self.input_buffer = ""
        self.connection = None

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            import psycopg

            self.connection = psycopg.connect(self.database_url, autocommit=True)
            self.terminal_session_id = create_terminal_session(
                self.connection,
                client_session_id=self.session.session_id,
                shell=self.session.shell_label,
                workdir=str(self.session.config.workdir),
                context=self.context,
                metadata={"transport": "websocket"},
            )
            self.learning_step_attempt_id = create_learning_step_attempt(
                self.connection,
                terminal_session_id=self.terminal_session_id,
                context=self.context,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[server] terminal persistence disabled for session {self.session.session_id}: {exc}")
            self.close()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def update_context(self, context: TerminalLearningContext) -> None:
        self.context = TerminalLearningContext(
            learner_id=context.learner_id or self.context.learner_id,
            learning_path_id=context.learning_path_id or self.context.learning_path_id,
            learning_step_id=context.learning_step_id or self.context.learning_step_id,
            lab_task_id=context.lab_task_id or self.context.lab_task_id,
        )
        if not self.connection or not self.terminal_session_id:
            return
        update_terminal_session_context(
            self.connection,
            terminal_session_id=self.terminal_session_id,
            context=self.context,
        )
        if self.learning_step_attempt_id is None:
            self.learning_step_attempt_id = create_learning_step_attempt(
                self.connection,
                terminal_session_id=self.terminal_session_id,
                context=self.context,
            )

    def record_output(self, *, stream: str, data: str) -> None:
        if not self.connection or not self.terminal_session_id or not data:
            return
        self.event_ordinal += 1
        record_terminal_event(
            self.connection,
            terminal_session_id=self.terminal_session_id,
            event_ordinal=self.event_ordinal,
            event_type="output",
            stream=stream,
            data=data,
        )

    def record_error(self, message: str) -> None:
        if not self.connection or not self.terminal_session_id:
            return
        self.event_ordinal += 1
        record_terminal_event(
            self.connection,
            terminal_session_id=self.terminal_session_id,
            event_ordinal=self.event_ordinal,
            event_type="error",
            data=message,
        )

    def record_input(self, data: str) -> None:
        if not data:
            return
        self.input_buffer += data.replace("\r", "\n")
        while "\n" in self.input_buffer:
            command, self.input_buffer = self.input_buffer.split("\n", 1)
            command = command.strip()
            if command:
                self.record_command(command)

    def record_command(self, command: str) -> None:
        if not self.connection or not self.terminal_session_id:
            return
        self.event_ordinal += 1
        event_id = record_terminal_event(
            self.connection,
            terminal_session_id=self.terminal_session_id,
            event_ordinal=self.event_ordinal,
            event_type="command",
            command_text=command,
            data=command,
        )
        if not self.context.lab_task_id:
            return
        for check in load_command_checks_for_lab_task(self.connection, lab_task_id=self.context.lab_task_id):
            evaluation = evaluate_command_check(check, command)
            if evaluation.matched or evaluation.status == "error":
                upsert_command_check_result(
                    self.connection,
                    terminal_session_id=self.terminal_session_id,
                    terminal_event_id=event_id,
                    command_check=check,
                    learning_step_attempt_id=self.learning_step_attempt_id,
                    learner_id=self.context.learner_id,
                    submitted_command=command,
                    evaluation=evaluation,
                )

    def finish(self, *, status: str, exit_code: int | None = None) -> None:
        if not self.connection or not self.terminal_session_id:
            return
        finish_terminal_session(
            self.connection,
            terminal_session_id=self.terminal_session_id,
            status=status,
            exit_code=exit_code,
        )


async def _handle_terminal_connection(
    websocket,
    *args: object,
    config: TerminalSessionConfig,
    database_url: str = "",
) -> None:
    session = TerminalSession(config).start()
    recorder = TerminalEventRecorder(
        database_url=database_url,
        session=session,
        context=_context_from_path(_websocket_path(websocket, args)),
    )
    recorder.start()
    await websocket.send(
        _json_event(
            {
                "type": "ready",
                "session_id": session.session_id,
                "persisted_session_id": recorder.terminal_session_id,
                "shell": session.shell_label,
                "workdir": str(config.workdir),
            }
        )
    )

    async def pump_output() -> None:
        exit_sent = False
        while True:
            output_chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}
            for event in session.drain():
                if event.type == "output":
                    output_chunks.setdefault(event.stream, []).append(event.data)
                elif event.type == "error":
                    recorder.record_error(event.data)
                payload = {
                    "type": event.type,
                    "stream": event.stream,
                    "data": event.data,
                }
                await websocket.send(_json_event(payload))
            for stream, chunks in output_chunks.items():
                if chunks:
                    recorder.record_output(stream=stream, data="".join(chunks))
            exit_code = session.poll_exit_code()
            if exit_code is not None and not exit_sent:
                exit_sent = True
                recorder.finish(status="exited", exit_code=exit_code)
                await websocket.send(_json_event({"type": "exit", "exit_code": exit_code}))
                return
            if session.expired():
                recorder.record_error("Terminal session TTL expired.")
                recorder.finish(status="expired")
                await websocket.send(
                    _json_event(
                        {
                            "type": "error",
                            "data": "Terminal session TTL expired.",
                        }
                    )
                )
                return
            await asyncio.sleep(0.03)

    pump_task = asyncio.create_task(pump_output())
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                message = {"type": "input", "data": str(raw_message)}
            message_type = message.get("type")
            if message_type == "input":
                data = str(message.get("data", ""))
                recorder.record_input(data)
                session.write(data)
            elif message_type == "context":
                recorder.update_context(_context_from_message(message))
                await websocket.send(
                    _json_event(
                        {
                            "type": "context",
                            "persisted_session_id": recorder.terminal_session_id,
                            "learning_step_id": recorder.context.learning_step_id,
                            "lab_task_id": recorder.context.lab_task_id,
                        }
                    )
                )
            elif message_type == "resize":
                continue
            elif message_type == "close":
                break
    finally:
        recorder.finish(status="closed", exit_code=session.poll_exit_code())
        recorder.close()
        session.close()
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass


def start_terminal_websocket_server(*, settings: Settings, root_dir: Path) -> threading.Thread:
    try:  # websockets 15+
        from websockets.asyncio.server import serve as websocket_serve
    except ImportError:  # pragma: no cover - compatibility with older websockets
        from websockets import serve as websocket_serve

    config = build_terminal_session_config(settings, root_dir)
    host = settings.terminal_host
    port = settings.terminal_ws_port
    database_url = settings.database_url

    async def run_server() -> None:
        async def handler(websocket, *args: object) -> None:
            await _handle_terminal_connection(websocket, *args, config=config, database_url=database_url)

        async with websocket_serve(handler, host, port):
            await asyncio.Future()

    def run_loop() -> None:
        asyncio.run(run_server())

    thread = threading.Thread(
        target=run_loop,
        name="pbs-terminal-websocket",
        daemon=True,
    )
    thread.start()
    print(f"[server] terminal session websocket running at ws://{host}:{port}")
    return thread


__all__ = [
    "build_terminal_session_config",
    "start_terminal_websocket_server",
]
