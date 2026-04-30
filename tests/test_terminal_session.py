from __future__ import annotations

from pathlib import Path

from play_book_studio.app.terminal_session import TerminalSessionConfig, resolve_shell_args
from play_book_studio.app.terminal_ws import build_terminal_session_config
from play_book_studio.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "tmp" / "terminal_session_tests"


def test_resolve_shell_args_adds_interactive_powershell_flags():
    assert resolve_shell_args("powershell.exe") == [
        "powershell.exe",
        "-NoLogo",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
    ]


def test_resolve_shell_args_adds_interactive_bash_flag():
    assert resolve_shell_args("/bin/bash") == ["/bin/bash", "-i"]


def test_terminal_session_config_uses_root_dir_by_default():
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    settings = Settings(root_dir=TEST_ROOT)

    config = build_terminal_session_config(settings, TEST_ROOT)

    assert isinstance(config, TerminalSessionConfig)
    assert config.workdir == TEST_ROOT


def test_terminal_session_config_resolves_relative_workdir():
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    settings = Settings(root_dir=TEST_ROOT, terminal_workdir_override="workspace")

    config = build_terminal_session_config(settings, TEST_ROOT)

    assert config.workdir == Path(TEST_ROOT, "workspace")
