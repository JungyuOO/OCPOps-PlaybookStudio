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
        self._pty_master_fd: int | None = None

    @property
    def shell_args(self) -> list[str]:
        return resolve_shell_args(self.config.shell)

    @property
    def shell_label(self) -> str:
        return self.shell_args[0]

    def start(self) -> "TerminalSession":
        if self._process is not None:
            return self
        if os.name != "nt":
            return self._start_posix_pty()
        env = os.environ.copy()
        env.update(self.config.env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if not env.get("TERM"):
            env["TERM"] = "xterm-256color"
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

    def _start_posix_pty(self) -> "TerminalSession":
        import pty

        env = os.environ.copy()
        env.update(self.config.env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLUMNS", "80")
        env.setdefault("LINES", "24")
        master_fd, slave_fd = pty.openpty()
        self._pty_master_fd = master_fd
        try:
            self._process = subprocess.Popen(
                self.shell_args,
                cwd=self.config.workdir,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
        finally:
            os.close(slave_fd)
        self._start_pty_reader()
        return self

    def write(self, data: str) -> None:
        if self._pty_master_fd is not None:
            process = self._process
            if process is None or process.poll() is not None:
                return
            os.write(self._pty_master_fd, data.encode("utf-8", errors="replace"))
            return
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return
        process.stdin.write(data)
        process.stdin.flush()

    def resize(self, *, cols: int, rows: int) -> None:
        master_fd = self._pty_master_fd
        if master_fd is None:
            return
        safe_cols = max(20, min(int(cols or 80), 300))
        safe_rows = max(5, min(int(rows or 24), 120))
        try:
            import fcntl
            import struct
            import termios

            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", safe_rows, safe_cols, 0, 0))
        except Exception:  # noqa: BLE001
            return

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
            self._close_pty()
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        self._close_pty()

    def _close_pty(self) -> None:
        master_fd = self._pty_master_fd
        self._pty_master_fd = None
        if master_fd is None:
            return
        try:
            os.close(master_fd)
        except OSError:
            pass

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

    def _start_pty_reader(self) -> None:
        thread = threading.Thread(
            target=self._read_pty,
            name=f"terminal-session-{self.session_id}-pty",
            daemon=True,
        )
        thread.start()
        self._readers.append(thread)

    def _read_pty(self) -> None:
        while not self._closed.is_set():
            master_fd = self._pty_master_fd
            if master_fd is None:
                break
            try:
                raw = os.read(master_fd, 4096)
            except OSError:
                break
            if not raw:
                break
            data = raw.decode("utf-8", errors="replace")
            self._output_bytes += len(raw)
            if self._output_bytes <= self.config.max_output_bytes:
                self._events.put(TerminalOutputEvent(type="output", stream="stdout", data=data))
            elif not self._limit_reported:
                self._limit_reported = True
                self._events.put(
                    TerminalOutputEvent(
                        type="error",
                        stream="stdout",
                        data="Terminal output limit reached; further output was truncated.",
                    )
                )

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
