"""WebSocket transport for Terminal Session runtime."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings

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


async def _handle_terminal_connection(websocket, *args: object, config: TerminalSessionConfig) -> None:
    session = TerminalSession(config).start()
    await websocket.send(
        _json_event(
            {
                "type": "ready",
                "session_id": session.session_id,
                "shell": session.shell_label,
                "workdir": str(config.workdir),
            }
        )
    )

    async def pump_output() -> None:
        exit_sent = False
        while True:
            for event in session.drain():
                payload = {
                    "type": event.type,
                    "stream": event.stream,
                    "data": event.data,
                }
                await websocket.send(_json_event(payload))
            exit_code = session.poll_exit_code()
            if exit_code is not None and not exit_sent:
                exit_sent = True
                await websocket.send(_json_event({"type": "exit", "exit_code": exit_code}))
                return
            if session.expired():
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
                session.write(str(message.get("data", "")))
            elif message_type == "resize":
                continue
            elif message_type == "close":
                break
    finally:
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

    async def run_server() -> None:
        async def handler(websocket, *args: object) -> None:
            await _handle_terminal_connection(websocket, *args, config=config)

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
