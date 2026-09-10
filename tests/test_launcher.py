from pathlib import Path
import subprocess
import sys
import time

import pytest
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
)

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
) -> None:
    values = readiness_inputs
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
    finally:
        cleanup_running_launcher(values, launcher)


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
    monkeypatch.setattr(codex_module.shutil, "which", lambda _: None)

    assert CodexAdapter().discover() == executable.resolve()


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
    assert "command=\"python -m aia.codex_hook_runtime\"" in config
    assert "commandWindows=\"python -m aia.codex_hook_runtime\"" in config
    assert "--dangerously-bypass-hook-trust" in spec.argv
