from __future__ import annotations

from pathlib import Path

from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.http.terminal_ws import terminal_workspace_auto_create_enabled


def test_v030_lightspeed_byok_and_operator_settings_load_from_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "CHAT_PROVIDER=lightspeed",
                "OLS_BASE_URL=https://ols.apps.example.test",
                "OLS_AUTH_MODE=test-admin-secret",
                "OLS_AUTH_SECRET_NAME=pbs-ols-token",
                "OLS_AUTH_TOKEN=example-token",
                "OLS_TIMEOUT_SECONDS=12",
                "PBS_AUTO_CREATE_NAMESPACE=false",
                "PBS_NAMESPACE_MODE=disabled",
                "CONSOLE_EXECUTOR_MODE=test-admin-secret",
                "BYOK_PIPELINE_ENABLED=true",
                "BYOK_OUTPUT_MODE=dry-run",
                "BYOK_IMAGE_REPOSITORY=registry.example.test/pbs/byok",
                "BYOK_REGISTRY_SECRET_NAME=pbs-registry",
                "PBS_OPERATOR_READY_MODE=true",
                "PBS_OPERATOR_MANIFEST_PROFILE=sno",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.chat_provider == "lightspeed"
    assert settings.ols_base_url == "https://ols.apps.example.test"
    assert settings.ols_auth_mode == "test-admin-secret"
    assert settings.ols_auth_secret_name == "pbs-ols-token"
    assert settings.ols_auth_token == "example-token"
    assert settings.ols_timeout_seconds == 12
    assert settings.pbs_auto_create_namespace is False
    assert settings.pbs_namespace_mode == "disabled"
    assert settings.console_executor_mode == "test-admin-secret"
    assert settings.byok_pipeline_enabled is True
    assert settings.byok_output_mode == "dry-run"
    assert settings.byok_image_repository == "registry.example.test/pbs/byok"
    assert settings.byok_registry_secret_name == "pbs-registry"
    assert settings.pbs_operator_ready_mode is True
    assert settings.pbs_operator_manifest_profile == "sno"


def test_v030_namespace_auto_create_defaults_to_disabled(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)

    assert settings.pbs_auto_create_namespace is False
    assert settings.pbs_namespace_mode == "disabled"


def test_terminal_workspace_auto_create_requires_both_terminal_workspace_and_auto_create(tmp_path: Path) -> None:
    settings = Settings(root_dir=tmp_path, terminal_user_workspace_enabled=True, pbs_auto_create_namespace=False)
    assert terminal_workspace_auto_create_enabled(settings) is False

    settings = Settings(root_dir=tmp_path, terminal_user_workspace_enabled=False, pbs_auto_create_namespace=True)
    assert terminal_workspace_auto_create_enabled(settings) is False

    settings = Settings(root_dir=tmp_path, terminal_user_workspace_enabled=True, pbs_auto_create_namespace=True)
    assert terminal_workspace_auto_create_enabled(settings) is True
