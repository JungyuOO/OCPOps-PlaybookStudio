"""Shell-agnostic terminal session process wrapper."""

from __future__ import annotations

import os
import queue
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TerminalStream = Literal["stdout", "stderr"]


@dataclass(frozen=True, slots=True)
class TerminalSessionConfig:
    shell: str = ""
    workdir: Path = Path(".")
    ttl_seconds: int = 1800
    max_output_bytes: int = 1048576
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerminalOutputEvent:
    type: str
    data: str
    stream: TerminalStream = "stdout"


def default_terminal_shell() -> str:
    return "powershell.exe" if os.name == "nt" else "/bin/bash"


def resolve_shell_args(shell: str) -> list[str]:
    resolved = shell.strip() or default_terminal_shell()
    executable = Path(resolved).name.lower()
    if executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return [resolved, "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass"]
    if executable in {"bash", "bash.exe"} or resolved.endswith("/bash"):
        return [resolved, "-i"]
    return shlex.split(resolved)


class TerminalSession:
    def __init__(self, config: TerminalSessionConfig) -> None:
        self.config = config
        self.session_id = uuid.uuid4().hex
        self.started_at = time.monotonic()
        self._process: subprocess.Popen[str] | None = None
        self._events: queue.Queue[TerminalOutputEvent] = queue.Queue()
        self._output_bytes = 0
        self._limit_reported = False
        self._closed = threading.Event()
        self._readers: list[threading.Thread] = []

    @property
    def shell_args(self) -> list[str]:
        return resolve_shell_args(self.config.shell)

    @property
    def shell_label(self) -> str:
        return self.shell_args[0]

    def start(self) -> "TerminalSession":
        if self._process is not None:
            return self
        env = os.environ.copy()
        env.update(self.config.env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self._process = subprocess.Popen(
            self.shell_args,
            cwd=self.config.workdir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._start_reader("stdout")
        self._start_reader("stderr")
        return self

    def write(self, data: str) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return
        process.stdin.write(data)
        process.stdin.flush()

    def drain(self, *, max_events: int = 200) -> list[TerminalOutputEvent]:
        drained: list[TerminalOutputEvent] = []
        for _ in range(max_events):
            try:
                drained.append(self._events.get_nowait())
            except queue.Empty:
                break
        return drained

    def poll_exit_code(self) -> int | None:
        if self._process is None:
            return None
        return self._process.poll()

    def expired(self) -> bool:
        return (time.monotonic() - self.started_at) > self.config.ttl_seconds

    def close(self) -> None:
        self._closed.set()
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def _start_reader(self, stream: TerminalStream) -> None:
        process = self._process
        if process is None:
            return
        pipe = process.stdout if stream == "stdout" else process.stderr
        if pipe is None:
            return
        thread = threading.Thread(
            target=self._read_pipe,
            args=(stream, pipe),
            name=f"terminal-session-{self.session_id}-{stream}",
            daemon=True,
        )
        thread.start()
        self._readers.append(thread)

    def _read_pipe(self, stream: TerminalStream, pipe) -> None:
        while not self._closed.is_set():
            data = pipe.read(1)
            if not data:
                break
            self._output_bytes += len(data.encode("utf-8", errors="replace"))
            if self._output_bytes <= self.config.max_output_bytes:
                self._events.put(TerminalOutputEvent(type="output", stream=stream, data=data))
            elif not self._limit_reported:
                self._limit_reported = True
                self._events.put(
                    TerminalOutputEvent(
                        type="error",
                        stream=stream,
                        data="Terminal output limit reached; further output was truncated.",
                    )
                )


__all__ = [
    "TerminalOutputEvent",
    "TerminalSession",
    "TerminalSessionConfig",
    "default_terminal_shell",
    "resolve_shell_args",
]
