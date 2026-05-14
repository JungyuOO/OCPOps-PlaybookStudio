from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from play_book_studio.cluster.workspace_models import WorkspaceHandle
from play_book_studio.config.settings import Settings
from play_book_studio.db.terminal_learning_repository import CommandCheck, evaluate_command_check_output
from play_book_studio.http.terminal_session import TerminalSessionConfig, resolve_shell_args
from play_book_studio.http.terminal_ws import (
    build_terminal_session_config,
    build_workspace_terminal_session_config,
)

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


def test_workspace_terminal_session_config_routes_to_sandbox_entrypoint():
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    settings = Settings(root_dir=TEST_ROOT, terminal_sandbox_shell="/bin/bash")
    workspace = WorkspaceHandle(namespace="pbs-user-a3f9c1d2", pod_name="sandbox-abc", ready=True)

    config = build_workspace_terminal_session_config(settings, TEST_ROOT, workspace)

    assert config.shell == "/app/scripts/sandbox-exec-entrypoint.sh"
    assert config.workdir == TEST_ROOT
    assert config.env["PBS_SANDBOX_NAMESPACE"] == "pbs-user-a3f9c1d2"
    assert config.env["PBS_SANDBOX_POD"] == "sandbox-abc"
    assert config.env["PBS_SANDBOX_SHELL"] == "/bin/bash"


def test_evaluate_command_check_output_requires_scoped_stdout_match():
    check = CommandCheck(
        id="check-1",
        lab_task_id="task-1",
        check_key="project-output",
        command_pattern=r"^oc project$",
        expected_command="oc project",
        validation_payload={"stdout_contains": "Using project"},
    )

    pending = evaluate_command_check_output(check, "oc project", stdout="No project selected")
    passed = evaluate_command_check_output(check, "oc project", stdout='Using project "demo"')

    assert pending.status == "pending_output"
    assert pending.matched is False
    assert passed.status == "passed"
    assert passed.matched is True


def test_terminal_entrypoint_does_not_fallback_to_local_shell_without_cluster_config():
    bash_path = shutil.which("bash")
    if bash_path is None:
        pytest.skip("bash is not available in this environment")
    if "system32" in bash_path.lower().replace("/", "\\"):
        pytest.skip("Windows WSL shim bash cannot read native workspace paths")
    script_path = REPO_ROOT / "deploy" / "scripts" / "terminal-entrypoint.sh"
    env = os.environ.copy()
    env.pop("OCP_API_BASE_URL", None)
    env.pop("OCP_API_TOKEN", None)

    result = subprocess.run(
        [bash_path, str(script_path)],
        input="echo SHOULD_NOT_RUN\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Local shell fallback is disabled" in output
    assert "Refresh the OpenShift API URL and token" in output
    assert "SHOULD_NOT_RUN" not in output
