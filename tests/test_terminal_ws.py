from pathlib import Path

from play_book_studio.config.settings import Settings
from play_book_studio.http.terminal_ws import terminal_workspace_auto_create_enabled


def test_terminal_workspace_auto_create_requires_explicit_pbs_namespace_flag(tmp_path: Path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        terminal_user_workspace_enabled=True,
        pbs_auto_create_namespace=False,
        pbs_namespace_mode="disabled",
    )

    assert terminal_workspace_auto_create_enabled(settings) is False


def test_terminal_workspace_auto_create_can_be_enabled_for_sandbox_mode(tmp_path: Path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        terminal_user_workspace_enabled=True,
        pbs_auto_create_namespace=True,
        pbs_namespace_mode="per-user",
    )

    assert terminal_workspace_auto_create_enabled(settings) is True
