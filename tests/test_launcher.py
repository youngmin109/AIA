from pathlib import Path
import os
import subprocess
import sys
import time

import pytest
import psutil
from aia.adapters import codex as codex_module

from aia import (
    AdapterError,
    AdapterUnavailableError,
    AgentLaunchSpec,
    CodexAdapter,
    LaunchCleanupStatus,
    LaunchStatus,
    ManagedRootConflictError,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    SessionStatus,
    UserAbortTerminationResult,
)
from aia.process_identity import ProcessIdentity

from tests.test_readiness import make_barrier, readiness_inputs


class PythonTestAdapter:
    name = "python-test"

    def discover(self) -> Path:
        return Path(sys.executable)

    def build_launch(self, request, executable: Path) -> AgentLaunchSpec:
        return AgentLaunchSpec(
            adapter=self.name,
            executable=executable,
            argv=(
                str(executable),
                "-c",
                "import time; time.sleep(3)",
            ),
            stdin_bytes=b"",
        )

    def parse_runtime_metadata(self, line: str):
        return None


def make_ready_launcher(values: dict, *, popen_factory=None) -> ProtectedLauncher:
    readiness = make_barrier(values).evaluate()
    assert readiness.readiness_context is not None
    return ProtectedLauncher(
        values["session"],
        readiness.readiness_context,
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        adapter=PythonTestAdapter(),
        lease_manager=values["lease_manager"],
        popen_factory=popen_factory or subprocess.Popen,
    )


def launch_request(values: dict) -> ProtectedLaunchRequest:
    return ProtectedLaunchRequest(
        aia_session_id=values["session"].session_id,
        workspace=values["workspace"],
        agent="codex",
        prompt="Reply with a short status and do not modify files.",
    )


def cleanup_running_launcher(values: dict, launcher: ProtectedLauncher) -> None:
    sensor = launcher.process_sensor
    if sensor is not None:
        sensor.stop()
    process = launcher.process_handle
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=3)
    if values["session"].status is SessionStatus.RUNNING:
        values["session"].transition_to(SessionStatus.ABORTED)


def test_deterministic_python_protected_launch_reaches_running(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    launcher = make_ready_launcher(values)
    result = launcher.launch(launch_request(values))

    try:
        assert result.status is LaunchStatus.RUNNING
        assert values["session"].status is SessionStatus.RUNNING
        assert result.context is not None
        assert result.context.launch_provenance == "AIA_SPAWNED_ROOT"
        assert result.context.root_registration.registration_source == (
            "PROTECTED_LAUNCHER"
        )
        assert result.context.prompt_sha256 == launch_request(values).prompt_sha256
        assert result.context.spawn_to_identity_ms >= 0
        assert result.context.spawn_to_process_sensor_healthy_ms >= 0
        assert "Reply with" not in repr(result.context)
        assert launcher.process_sensor is not None
    finally:
        cleanup_running_launcher(values, launcher)


def test_user_abort_terminates_only_the_verified_launched_root(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    launcher = make_ready_launcher(values)
    result = launcher.launch(launch_request(values))

    try:
        assert result.status is LaunchStatus.RUNNING
        assert launcher.request_user_abort() is True
        assert launcher.process_handle is not None
        assert launcher.process_handle.poll() is not None
        assert values["session"].status is SessionStatus.RUNNING
    finally:
        cleanup_running_launcher(values, launcher)


def test_user_abort_result_is_separate_and_verified(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    launcher = make_ready_launcher(values)
    result = launcher.launch(launch_request(values))

    try:
        assert result.status is LaunchStatus.RUNNING
        abort = launcher.request_user_abort_result()
        assert isinstance(abort, UserAbortTerminationResult)
        assert abort.status == "SUCCEEDED"
        assert abort.outcome == "TERMINATED"
        assert abort.verified_tree_gone is True
        assert abort.succeeded is True
        assert abort.to_mapping()["termination_id"] == abort.termination_id
    finally:
        cleanup_running_launcher(values, launcher)


def test_user_abort_during_starting_uses_verified_startup_identity(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    launcher = make_ready_launcher(values)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        launcher._status = LaunchStatus.STARTING
        launcher._startup_identity = ProcessIdentity(
            process.pid,
            psutil.Process(process.pid).create_time(),
        )
        result = launcher.request_user_abort_result()
        assert result is not None
        assert result.status == "SUCCEEDED"
        assert result.outcome == "TERMINATED"
        assert result.verified_tree_gone is True
        assert result.reason is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        cleanup_running_launcher(values, launcher)


def test_prompt_is_dispatched_only_after_running_and_hook_bridge_ready(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    observations: list[tuple[SessionStatus, bool]] = []
    launcher: ProtectedLauncher

    def recording_popen(argv, **kwargs):
        process = subprocess.Popen(argv, **kwargs)
        stream = process.stdin
        assert stream is not None

        class ObservedStdin:
            def write(self, value: bytes):
                observations.append((values["session"].status, launcher.hook_bridge.ready))
                return stream.write(value)

            def close(self):
                return stream.close()

        process.stdin = ObservedStdin()
        return process

    launcher = make_ready_launcher(values, popen_factory=recording_popen)
    result = launcher.launch(launch_request(values))
    try:
        assert result.status is LaunchStatus.RUNNING
        assert observations == [(SessionStatus.RUNNING, True)]
        assert result.context is not None
        assert result.context.hook_bridge_ready
    finally:
        cleanup_running_launcher(values, launcher)


def test_launcher_uses_shell_false_and_canonical_workspace(
    readiness_inputs: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = readiness_inputs
    monkeypatch.setenv("CODEX_SESSION_ID", "outer-session")
    captured: dict = {}

    def recording_popen(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.Popen(argv, **kwargs)

    launcher = make_ready_launcher(values, popen_factory=recording_popen)
    result = launcher.launch(launch_request(values))
    try:
        assert result.status is LaunchStatus.RUNNING
        assert captured["shell"] is False
        assert captured["cwd"] == str(values["session"].workspace)
        assert captured["stdout"] is subprocess.DEVNULL
        assert captured["stderr"] is subprocess.DEVNULL
        assert "CODEX_SESSION_ID" not in captured["env"]
    finally:
        cleanup_running_launcher(values, launcher)


def test_protected_codex_child_does_not_inherit_outer_session_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", "C:\\Users\\tester\\.codex")
    monkeypatch.setenv("CODEX_SESSION_ID", "outer-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "outer-thread")
    monkeypatch.setenv("CODEX_PERMISSION_PROFILE", ":danger-full-access")
    monkeypatch.setenv("CODEX_CI", "1")

    child = ProtectedLauncher._child_environment(
        {"AIA_SESSION_ID": "aia-session", "AIA_LAUNCH_ID": "launch-1"}
    )

    assert child["CODEX_HOME"] == "C:\\Users\\tester\\.codex"
    assert "CODEX_SESSION_ID" not in child
    assert "CODEX_THREAD_ID" not in child
    assert "CODEX_PERMISSION_PROFILE" not in child
    assert "CODEX_CI" not in child
    assert child["AIA_SESSION_ID"] == "aia-session"


def test_launch_requires_ready_session(readiness_inputs: dict) -> None:
    values = readiness_inputs
    launcher = ProtectedLauncher(
        values["session"],
        object(),
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        adapter=PythonTestAdapter(),
        lease_manager=values["lease_manager"],
    )

    result = launcher.launch(launch_request(values))

    assert result.status is LaunchStatus.FAILED
    assert result.failure_code == "SESSION_NOT_READY"
    assert result.cleanup_status is LaunchCleanupStatus.NOT_ATTEMPTED
    assert values["session"].status is SessionStatus.PREPARING


def test_workspace_change_after_ready_refuses_spawn(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs
    launcher = make_ready_launcher(values)
    (values["workspace"] / "changed-after-ready.txt").write_text(
        "changed", encoding="utf-8"
    )

    result = launcher.launch(launch_request(values))

    assert result.status is LaunchStatus.FAILED
    assert result.failure_code == "LAUNCH_REFUSED"
    assert launcher.process_handle is None
    assert values["session"].status is SessionStatus.FAILED


def test_adapter_failure_keeps_ready_for_retry(readiness_inputs: dict) -> None:
    values = readiness_inputs
    readiness = make_barrier(values).evaluate()
    assert readiness.readiness_context is not None

    class MissingAdapter(PythonTestAdapter):
        def discover(self) -> Path:
            raise AdapterUnavailableError("missing")

    launcher = ProtectedLauncher(
        values["session"],
        readiness.readiness_context,
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        adapter=MissingAdapter(),
        lease_manager=values["lease_manager"],
    )
    result = launcher.launch(launch_request(values))

    assert result.status is LaunchStatus.FAILED
    assert result.failure_code == "ADAPTER_UNAVAILABLE"
    assert values["session"].status is SessionStatus.READY
    assert launcher.process_handle is None


def test_hook_failure_refuses_launch_without_spawn(readiness_inputs: dict) -> None:
    values = readiness_inputs
    readiness = make_barrier(values).evaluate()
    assert readiness.readiness_context is not None
    values["hook"].stop()
    launcher = ProtectedLauncher(
        values["session"],
        readiness.readiness_context,
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        adapter=PythonTestAdapter(),
        lease_manager=values["lease_manager"],
    )

    result = launcher.launch(launch_request(values))

    assert result.status is LaunchStatus.FAILED
    assert result.failure_code == "LAUNCH_REFUSED"
    assert launcher.process_handle is None
    assert values["session"].status is SessionStatus.FAILED


def test_managed_registry_failure_cleans_up_before_running(
    readiness_inputs: dict,
) -> None:
    values = readiness_inputs

    class FailingRegistry:
        def register(self, managed_process):
            raise ManagedRootConflictError("test registry failure")

    readiness = make_barrier(values).evaluate()
    assert readiness.readiness_context is not None
    launcher = ProtectedLauncher(
        values["session"],
        readiness.readiness_context,
        values["context"],
        values["checkpoint"],
        values["filesystem"],
        values["hook"],
        adapter=PythonTestAdapter(),
        lease_manager=values["lease_manager"],
        managed_process_registry=FailingRegistry(),
    )

    result = launcher.launch(launch_request(values))

    assert result.status is LaunchStatus.FAILED
    assert result.failure_code == "MANAGED_ROOT_CONFLICT"
    assert result.cleanup_status is LaunchCleanupStatus.SUCCEEDED
    assert values["session"].status is SessionStatus.FAILED
    assert launcher.process_handle is not None
    assert launcher.process_handle.poll() is not None


def test_codex_adapter_uses_verified_cli_contract_without_prompt_in_argv(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="secret prompt",
        model="gpt-5.5",
        adapter_options={"json": True, "skip_git_repo_check": True},
    )
    executable = Path(sys.executable)
    spec = adapter.build_launch(request, executable)

    assert spec.argv[0] == str(executable)
    assert spec.argv[1:3] == ("exec", "-C")
    assert "secret prompt" not in spec.argv
    assert spec.stdin_bytes == b"secret prompt"
    assert "--dangerously-bypass-approvals-and-sandbox" not in spec.argv


def test_codex_adapter_builds_interactive_terminal_launch_without_prompt(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        adapter_options={"interactive": True, "sandbox": "workspace-write"},
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    assert spec.interactive is True
    assert spec.argv[0] == str(sys.executable)
    assert spec.argv[1] == "-C"
    assert "exec" not in spec.argv
    assert "--color" not in spec.argv
    assert "-" not in spec.argv
    assert spec.stdin_bytes == b""


def test_codex_adapter_uses_inline_submit_binding_for_workbench_terminal(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        adapter_options={
            "interactive": True,
            "sandbox": "workspace-write",
            "workbench_terminal": True,
        },
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    assert spec.argv.count("--no-alt-screen") == 1
    assert 'tui.keymap.composer.submit="ctrl-x"' in spec.argv


def test_codex_adapter_rejects_workbench_terminal_for_exec_mode(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="safe",
        adapter_options={"workbench_terminal": True},
    )

    with pytest.raises(AdapterError, match="interactive mode"):
        adapter.build_launch(request, Path(sys.executable))


def test_codex_adapter_rejects_permission_bypass_option(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="safe",
        adapter_options={"dangerously_bypass_approvals_and_sandbox": True},
    )

    with pytest.raises(AdapterError):
        adapter.build_launch(request, Path(sys.executable))


def test_codex_adapter_missing_executable_is_explicit() -> None:
    with pytest.raises(AdapterUnavailableError):
        CodexAdapter(executable_name="aia-command-that-does-not-exist").discover()


def test_codex_adapter_finds_windows_install_outside_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "OpenAI" / "Codex" / "bin" / "version-1"
    executable = install / "codex.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(codex_module.shutil, "which", lambda _: None)

    assert CodexAdapter().discover() == executable.resolve()


def test_codex_adapter_prefers_path_selection_over_side_by_side_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_executable = tmp_path / "path" / "codex.exe"
    side_by_side = tmp_path / "OpenAI" / "Codex" / "bin" / "version-1" / "codex.exe"
    path_executable.parent.mkdir(parents=True)
    side_by_side.parent.mkdir(parents=True)
    path_executable.write_bytes(b"path")
    side_by_side.write_bytes(b"installed")
    monkeypatch.delenv("CODEX_CLI_PATH", raising=False)
    monkeypatch.setattr(codex_module.shutil, "which", lambda _name: str(path_executable))
    monkeypatch.setattr(
        CodexAdapter,
        "_windows_install_candidates",
        lambda _adapter: (side_by_side,),
    )

    assert CodexAdapter().discover() == path_executable.resolve()


def test_codex_adapter_honors_explicit_cli_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "configured" / "codex.exe"
    configured.parent.mkdir(parents=True)
    configured.write_bytes(b"configured")
    monkeypatch.setenv("CODEX_CLI_PATH", str(configured))
    monkeypatch.setattr(codex_module.shutil, "which", lambda _name: None)

    assert CodexAdapter().discover() == configured.resolve()


def test_codex_adapter_prefers_newer_codex_install_when_multiple_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = tmp_path / "old" / "codex.exe"
    new = tmp_path / "new" / "codex.exe"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    monkeypatch.setattr(codex_module.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        CodexAdapter,
        "_windows_install_candidates",
        lambda _adapter: (old, new),
    )
    old_time = old.stat().st_mtime
    os.utime(new, (old_time + 10, old_time + 10))

    assert CodexAdapter().discover() == new.resolve()


def test_codex_adapter_prefers_newer_reported_version_over_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older_version = tmp_path / "older-version" / "codex.exe"
    newer_version = tmp_path / "newer-version" / "codex.exe"
    older_version.parent.mkdir(parents=True)
    newer_version.parent.mkdir(parents=True)
    older_version.write_bytes(b"older")
    newer_version.write_bytes(b"newer")
    newer_mtime = older_version.stat().st_mtime + 10
    os.utime(older_version, (newer_mtime, newer_mtime))
    monkeypatch.setattr(codex_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        CodexAdapter,
        "_windows_install_candidates",
        lambda _adapter: (older_version, newer_version),
    )
    versions = {
        older_version.resolve(): (0, 154, 0),
        newer_version.resolve(): (0, 155, 0),
    }
    monkeypatch.setattr(
        CodexAdapter,
        "_executable_version",
        staticmethod(lambda path: versions.get(Path(path).resolve())),
    )

    assert CodexAdapter().discover() == newer_version.resolve()


def test_codex_adapter_reports_selected_executable_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")
    monkeypatch.setattr(
        CodexAdapter,
        "_executable_version",
        staticmethod(lambda _path: (0, 154, 0)),
    )

    assert CodexAdapter.executable_version(executable) == "0.154.0"


def test_codex_adapter_embeds_current_hook_handler_schema(tmp_path: Path) -> None:
    adapter = CodexAdapter(
        hook_command="python -m aia.codex_hook_runtime",
        allow_hook_trust_bypass=True,
    )
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run the task",
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    config = next(argument for argument in spec.argv if argument.startswith("hooks.PreToolUse"))
    assert 'matcher="*"' in config
    assert "command=\"python -m aia.codex_hook_runtime\"" in config
    assert "commandWindows=\"python -m aia.codex_hook_runtime\"" in config
    assert any(argument.startswith("hooks.PostToolUse") for argument in spec.argv)
    assert "--dangerously-bypass-hook-trust" in spec.argv


def test_codex_product_adapter_enables_installed_hooks_without_trust_bypass(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter(enable_hooks=True)
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run the task",
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    assert "features.hooks=true" in spec.argv
    assert "--dangerously-bypass-hook-trust" not in spec.argv


def test_codex_adapter_rejects_mcp_server_option_outside_product_scope(
    tmp_path: Path,
) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="read",
        adapter_options={"mcp_server": {"name": "filesystem"}},
    )

    with pytest.raises(AdapterError, match="unsupported Codex adapter option"):
        adapter.build_launch(request, Path(sys.executable))


def test_codex_adapter_can_pin_a_safe_approval_policy(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run",
        adapter_options={"approval_policy": "on-request"},
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    assert 'approval_policy="on-request"' in spec.argv


def test_codex_adapter_uses_codex_safe_exec_approval_mode(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run",
        adapter_options={"approve_for_me": True},
    )

    spec = adapter.build_launch(request, Path(sys.executable))

    assert "--approve-for-me" in spec.argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in spec.argv


def test_codex_adapter_rejects_safe_exec_mode_with_explicit_sandbox(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run",
        adapter_options={"approve_for_me": True, "sandbox": "workspace-write"},
    )

    with pytest.raises(AdapterError, match="cannot be combined"):
        adapter.build_launch(request, Path(sys.executable))


def test_codex_adapter_rejects_never_approval_policy(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    request = ProtectedLaunchRequest(
        aia_session_id="session-1",
        workspace=tmp_path,
        agent="codex",
        prompt="run",
        adapter_options={"approval_policy": "never"},
    )

    with pytest.raises(AdapterError):
        adapter.build_launch(request, Path(sys.executable))


def test_codex_adapter_classifies_native_block_confirmation_without_raw_output() -> None:
    observation = CodexAdapter.classify_execution_output(
        b"The command was blocked by the PreToolUse hook. It did not run.\n",
        b"",
        posttool_observed=False,
    )

    assert observation.block_confirmation_available is True
    assert observation.reason == "CODEX_BLOCK_AND_NO_RUN_MESSAGE"
    assert observation.output_bytes > 0
    assert "blocked" not in repr(observation)


def test_codex_adapter_does_not_confirm_when_posttool_was_observed() -> None:
    observation = CodexAdapter.classify_execution_output(
        b"The command was blocked by the PreToolUse hook. It did not run.\n",
        b"",
        posttool_observed=True,
    )

    assert observation.block_confirmation_available is False
    assert observation.reason == "POSTTOOL_OBSERVED"


def test_codex_adapter_records_effective_sandbox_from_native_startup_output() -> None:
    observation = CodexAdapter.classify_execution_output(
        b"",
        b"approval: never\nsandbox: read-only\n",
        posttool_observed=False,
    )

    assert observation.effective_approval_policy == "never"
    assert observation.effective_sandbox == "read-only"
    assert observation.to_mapping()["effective_sandbox"] == "read-only"


def test_codex_adapter_accepts_native_hook_block_event_without_raw_tool_output() -> None:
    observation = CodexAdapter.classify_execution_output(
        b"hook: PreToolUse Blocked\n",
        b"",
        posttool_observed=False,
    )

    assert observation.block_confirmation_available is True
    assert observation.reason == "CODEX_HOOK_BLOCKED_EVENT"
