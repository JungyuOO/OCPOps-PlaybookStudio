from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_ALLOWED_LAUNCHERS = ("codex_python.ps1",)


def require_execution_contract(
    script_path: str,
    *,
    allowed_launchers: Iterable[str] | None = None,
    launcher_hint: str | None = None,
) -> None:
    script_name = Path(script_path).name
    launchers = tuple(allowed_launchers or DEFAULT_ALLOWED_LAUNCHERS)
    launcher = os.environ.get("PLAY_BOOK_LAUNCHER", "").strip()
    if launcher not in launchers:
        hint = launcher_hint or ", ".join(launchers)
        raise SystemExit(f"Direct execution is blocked. Use {hint}.")

    write_scope = os.environ.get("PLAY_BOOK_WRITE_SCOPE", "").strip()
    if not write_scope:
        raise SystemExit(f"Missing required PLAY_BOOK_WRITE_SCOPE for {script_name}.")

    verify_cmd = os.environ.get("PLAY_BOOK_VERIFY_CMD", "").strip()
    if not verify_cmd:
        raise SystemExit(f"Missing required PLAY_BOOK_VERIFY_CMD for {script_name}.")


def run_guarded_script(
    main_func: Callable[[], int],
    script_path: str,
    *,
    allowed_launchers: Iterable[str] | None = None,
    launcher_hint: str | None = None,
) -> int:
    require_execution_contract(
        script_path,
        allowed_launchers=allowed_launchers,
        launcher_hint=launcher_hint,
    )
    return int(main_func())
