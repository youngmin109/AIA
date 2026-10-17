from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from aia import CodexHookInstaller
from aia.hook_verification import HookVerificationStore
import aia.hook_verification as hook_verification
import aia.codex_installation as codex_installation


def test_codex_hook_installer_preserves_existing_hooks_and_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hooks.json"
    path.write_text(
        json.dumps(
            {
                "description": "existing",
                "hooks": {
                    "SessionEnd": [{"hooks": [{"type": "command", "command": "echo end"}]}]
                },
            }
        ),
        encoding="utf-8",
    )
    installer = CodexHookInstaller(path, python_executable=tmp_path / "python.exe")

    assert not installer.is_installed()
    assert installer.install() == path
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["description"] == "existing"
    assert "SessionEnd" in first["hooks"]
    assert installer.is_installed()

    installer.install()
    second = json.loads(path.read_text(encoding="utf-8"))
    assert len(second["hooks"]["PreToolUse"]) == 1
    assert second["hooks"]["PreToolUse"][0]["hooks"][0]["type"] == "command"
    assert second["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert len(second["hooks"]["PostToolUse"]) == 1
    assert second["hooks"]["PostToolUse"][0]["hooks"][0]["type"] == "command"


def test_codex_hook_installer_uses_codex_home_when_path_is_omitted(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    installer = CodexHookInstaller()

    assert installer.path == (codex_home / "hooks.json").resolve()
    installer.install()
    assert installer.path.exists()


def test_codex_hook_installer_uses_stable_uv_launcher_from_isolated_environment(
    tmp_path: Path, monkeypatch
) -> None:
    isolated_python = (
        tmp_path
        / "uv"
        / "cache"
        / "builds-v0"
        / ".tmpExample"
        / "Scripts"
        / "python.exe"
    )
    monkeypatch.setattr(sys, "executable", str(isolated_python))
    monkeypatch.setattr(
        codex_installation.shutil,
        "which",
        lambda name: r"C:\Tools\uv.exe" if name == "uv" else None,
    )

    installer = CodexHookInstaller(tmp_path / "hooks.json")

    assert "uv.exe" in installer.command
    assert "--project" in installer.command
    assert "--isolated" in installer.command
    assert "aia.codex_hook_runtime" in installer.command
    assert installer.is_installed() is False
    installer.install()
    assert installer.is_installed() is True


def test_frozen_codex_hook_prefers_allowed_sibling_cli(tmp_path: Path, monkeypatch) -> None:
    fake_aia = tmp_path / "AIA" / "AIA.exe"
    fake_aia.parent.mkdir(parents=True)
    fake_aia.write_bytes(b"")
    fake_cli = tmp_path / "aia-cli" / "aia-cli.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(fake_aia))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    installer = CodexHookInstaller(tmp_path / "hooks.json")

    assert installer.command == subprocess.list2cmdline(
        [str(fake_cli), "hook", "runtime"]
    )


def test_frozen_desktop_installer_uses_sibling_cli_hook_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    desktop_path = tmp_path / "AIA" / "AIA.exe"
    desktop_path.parent.mkdir(parents=True)
    desktop_path.touch()
    cli_path = tmp_path / "aia-cli" / "aia-cli.exe"
    cli_path.parent.mkdir(parents=True)
    cli_path.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(desktop_path))

    installer = CodexHookInstaller(tmp_path / "hooks.json")

    assert installer.command == subprocess.list2cmdline([str(cli_path), "hook", "runtime"])
    installer.install()
    assert installer.is_installed() is True
    assert installer.has_aia_runtime() is True


def test_frozen_cli_installer_uses_itself_for_hook_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    cli_path = tmp_path / "aia-cli.exe"
    cli_path.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(cli_path))

    installer = CodexHookInstaller(tmp_path / "hooks.json")

    assert installer.command == subprocess.list2cmdline([str(cli_path), "hook", "runtime"])


def test_codex_hook_installer_distinguishes_stale_aia_runtime_from_missing_hook(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hooks.json"
    old = CodexHookInstaller(path, python_executable=tmp_path / "old-python.exe")
    old.install()

    current = CodexHookInstaller(path, python_executable=tmp_path / "new-python.exe")

    assert current.has_aia_runtime() is True
    assert current.is_installed() is False
    assert current.has_aia_runtime("PostToolUse") is True


def test_codex_hook_install_migrates_only_the_existing_aia_entry(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    python_executable = tmp_path / "python.exe"
    installer = CodexHookInstaller(path, python_executable=python_executable)
    installer.install()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook"}]}
    )
    document["hooks"]["PreToolUse"][0]["matcher"] = "Bash|apply_patch"
    path.write_text(json.dumps(document), encoding="utf-8")

    installer.install()

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert updated["hooks"]["PreToolUse"][1]["matcher"] == "Bash"


def test_codex_hook_install_replaces_stale_aia_command_but_preserves_user_hooks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hooks.json"
    old = CodexHookInstaller(path, python_executable=tmp_path / "old-python.exe")
    old.install()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook"}]}
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    current = CodexHookInstaller(path, python_executable=tmp_path / "new-python.exe")
    current.install()

    updated = json.loads(path.read_text(encoding="utf-8"))
    handlers = [
        handler
        for entry in updated["hooks"]["PreToolUse"]
        for handler in entry.get("hooks", [])
    ]
    aia_handlers = [
        handler
        for handler in handlers
        if "aia.codex_hook_runtime" in str(handler.get("command", ""))
    ]
    assert len(aia_handlers) == 1
    assert "new-python.exe" in aia_handlers[0]["command"]
    assert {handler.get("command") for handler in handlers} >= {
        "user-hook",
        aia_handlers[0]["command"],
    }
    assert current.is_installed() is True


def test_codex_hook_install_does_not_migrate_user_command_with_similar_argument(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hooks.json"
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "powershell -Command \"Write-Host '-m aia.codex_hook_runtime'\"",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    installer = CodexHookInstaller(path, python_executable=tmp_path / "python.exe")

    installer.install()

    updated = json.loads(path.read_text(encoding="utf-8"))
    commands = [
        handler.get("command")
        for entry in updated["hooks"]["PreToolUse"]
        for handler in entry.get("hooks", [])
    ]
    assert any(isinstance(command, str) and command.startswith("powershell") for command in commands)
    assert sum("aia.codex_hook_runtime" in str(command) for command in commands) == 2


def test_stale_aia_matcher_is_not_reported_as_installed(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(
        path,
        python_executable=tmp_path / "python.exe",
    )
    installer.install()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["hooks"]["PreToolUse"][0]["matcher"] = "Bash|apply_patch|Edit|Write"
    document["hooks"]["PostToolUse"][0]["matcher"] = "Bash|apply_patch|Edit|Write"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert installer.is_installed() is False
    assert installer.is_posttool_installed() is False


def test_codex_hook_uninstall_removes_only_aia_handlers(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    python_executable = tmp_path / "python.exe"
    installer = CodexHookInstaller(path, python_executable=python_executable)
    installer.install()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook"}]}
    )
    path.write_text(json.dumps(document), encoding="utf-8")

    installer.uninstall()

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert installer.is_installed() is False
    assert installer.is_posttool_installed() is False
    assert updated["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook"}]}
    ]
    assert updated["hooks"]["PostToolUse"] == []


def test_hook_verification_is_bound_to_hook_and_codex_fingerprints(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config_path = codex_home / "config.toml"
    config_path.write_text("approval_policy = 'on-request'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")

    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    assert store.is_current(installer, executable) is True
    document = store.read()
    assert document is not None
    assert document["schema_version"] == "aia-hook-verification-6"
    assert document["codex_config_sha256"]
    assert document["aia_hook_runtime_sha256"]
    assert document["session_id"] == "session-1"

    hook_path.write_text(hook_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert store.is_current(installer, executable) is False


def test_frozen_hook_verification_uses_stable_runtime_identity(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        "approval_policy = 'on-request'\n", encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    runtime_a = tmp_path / "aia-a" / "codex_hook_runtime.py"
    runtime_b = tmp_path / "aia-b" / "codex_hook_runtime.py"
    runtime_a.parent.mkdir()
    runtime_b.parent.mkdir()
    runtime_a.write_bytes(b"same-packaged-runtime")
    runtime_b.write_bytes(runtime_a.read_bytes())
    monkeypatch.setattr(hook_verification.sys, "frozen", True, raising=False)
    monkeypatch.setattr(hook_verification, "_RUNTIME_PATH", runtime_a)
    store = HookVerificationStore(tmp_path / "control")

    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    document = store.read()
    assert document is not None
    assert document["aia_hook_runtime"] == "packaged:aia.codex_hook_runtime"
    monkeypatch.setattr(hook_verification, "_RUNTIME_PATH", runtime_b)
    assert store.is_current(installer, executable) is True


def test_hook_verification_is_invalid_after_codex_config_changes(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config_path = codex_home / "config.toml"
    config_path.write_text("approval_policy = 'on-request'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    config_path.write_text("approval_policy = 'never'\n", encoding="utf-8")

    assert store.is_current(installer, executable) is False


def test_hook_verification_stale_reasons_name_changed_table_without_values(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config_path = codex_home / "config.toml"
    config_path.write_text(
        '[desktop]\ntheme = "private-setting-before"\n'
        '[tui]\nfont_size = 14\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        "aia.adapters.codex.CodexAdapter.executable_version",
        lambda _executable: "0.162.1",
    )
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    proof = store.read()
    assert proof is not None
    assert proof["codex_version"] == "0.162.1"
    assert proof["codex_config_tables_sha256"].keys() == {"desktop", "tui"}
    fingerprint = store._fingerprint(installer, executable)
    assert fingerprint is not None
    assert "codex_version" not in fingerprint
    assert "codex_config_tables_sha256" not in fingerprint

    proof["codex_version"] = "0.900.0"
    proof["codex_config_tables_sha256"]["desktop"] = "metadata-only-change"
    store.path.write_text(json.dumps(proof), encoding="utf-8")
    assert store.is_current(installer, executable) is True

    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )
    config_path.write_text(
        '[desktop]\ntheme = "private-setting-after"\n'
        '[tui]\nfont_size = 14\n',
        encoding="utf-8",
    )

    reasons = store.stale_reasons(installer, executable)

    assert store.is_current(installer, executable) is False
    assert reasons == ["Codex 설정 파일이 바뀌었어요: [desktop] 표"]
    assert "private-setting-before" not in " ".join(reasons)
    assert "private-setting-after" not in " ".join(reasons)
    assert str(config_path) not in " ".join(reasons)


def test_hook_verification_stale_reasons_show_codex_version_transition(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "aia.adapters.codex.CodexAdapter.executable_version",
        lambda _executable: "0.162.1",
    )
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    executable.write_bytes(b"codex-test-build-2")
    monkeypatch.setattr(
        "aia.adapters.codex.CodexAdapter.executable_version",
        lambda _executable: "0.163.0",
    )

    reasons = store.stale_reasons(installer, executable)

    assert store.is_current(installer, executable) is False
    assert reasons == ["Codex 실행 파일이 바뀌었어요 (0.162.1 → 0.163.0)"]


def test_hook_verification_stale_reasons_handle_old_proof_without_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config_path = codex_home / "config.toml"
    config_path.write_text('[tui]\nfont_size = 14\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        "aia.adapters.codex.CodexAdapter.executable_version",
        lambda _executable: "0.162.1",
    )
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )
    proof = store.read()
    assert proof is not None
    proof.pop("codex_version")
    proof.pop("codex_config_tables_sha256")
    store.path.write_text(json.dumps(proof), encoding="utf-8")
    config_path.write_text('[tui]\nfont_size = 15\n', encoding="utf-8")

    reasons = store.stale_reasons(installer, executable)

    assert store.is_current(installer, executable) is False
    assert reasons == [
        "Codex 설정 파일이 바뀌었어요(어느 표인지는 다음 검증부터 보여요)"
    ]


def test_hook_verification_survives_codex_workspace_trust_bookkeeping(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    config_path = codex_home / "config.toml"
    config_path.write_text(
        "approval_policy = 'on-request'\n"
        "\n"
        "[projects.'C:\\\\workspace\\\\demo']\n"
        "trust_level = 'trusted'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    config_path.write_text(
        "approval_policy = 'on-request'\n"
        "\n"
        "[projects.'C:\\\\workspace\\\\demo']\n"
        "trust_level = 'untrusted'\n"
        "\n"
        "[projects.'C:\\\\workspace\\\\new-demo']\n"
        "trust_level = 'trusted'\n",
        encoding="utf-8",
    )

    assert store.is_current(installer, executable) is True


def test_hook_verification_is_invalid_after_codex_executable_changes(tmp_path: Path) -> None:
    hook_path = tmp_path / "hooks.json"
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(hook_path, python_executable=tmp_path / "python.exe")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    executable.write_bytes(b"codex-test-build-2")

    assert store.is_current(installer, executable) is False


def _hook_forwarder(tmp_path: Path, content: bytes = b"forwarder-1") -> Path:
    forwarder = tmp_path / "Programs" / "AIA" / "aia-hook" / "aia-hook.exe"
    forwarder.parent.mkdir(parents=True, exist_ok=True)
    forwarder.write_bytes(content)
    return forwarder


def test_installed_hook_forwarder_is_the_hook_command_for_every_build(
    tmp_path: Path, monkeypatch
) -> None:
    forwarder = _hook_forwarder(tmp_path)
    monkeypatch.setattr(codex_installation, "installed_hook_executable", lambda: forwarder)
    source_installer = CodexHookInstaller(tmp_path / "hooks.json")

    dist_desktop = tmp_path / "dist" / "windows" / "AIA" / "AIA.exe"
    dist_desktop.parent.mkdir(parents=True)
    dist_desktop.touch()
    dist_cli = tmp_path / "dist" / "windows" / "aia-cli" / "aia-cli.exe"
    dist_cli.parent.mkdir(parents=True)
    dist_cli.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(dist_desktop))
    dist_installer = CodexHookInstaller(tmp_path / "hooks.json")

    expected = subprocess.list2cmdline([str(forwarder)])
    assert source_installer.command == expected
    assert dist_installer.command == expected
    assert dist_installer.hook_executable == forwarder


def test_explicit_python_hook_keeps_the_module_runtime(tmp_path: Path, monkeypatch) -> None:
    forwarder = _hook_forwarder(tmp_path)
    monkeypatch.setattr(codex_installation, "installed_hook_executable", lambda: forwarder)
    python_executable = tmp_path / "python.exe"

    installer = CodexHookInstaller(tmp_path / "hooks.json", python_executable=python_executable)

    assert installer.command == subprocess.list2cmdline(
        [str(python_executable.resolve(strict=False)), "-m", "aia.codex_hook_runtime"]
    )


def test_packaged_app_outside_the_default_folder_uses_its_own_forwarder(
    tmp_path: Path, monkeypatch
) -> None:
    desktop = tmp_path / "Custom AIA" / "AIA.exe"
    desktop.parent.mkdir(parents=True)
    desktop.touch()
    forwarder = tmp_path / "Custom AIA" / "aia-hook" / "aia-hook.exe"
    forwarder.parent.mkdir(parents=True)
    forwarder.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(desktop))

    installer = CodexHookInstaller(tmp_path / "hooks.json")

    assert installer.command == subprocess.list2cmdline([str(forwarder)])


def test_setup_replaces_an_earlier_aia_hook_command_with_the_forwarder(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "hooks.json"
    old_cli = tmp_path / "dist" / "windows" / "aia-cli" / "aia-cli.exe"
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": subprocess.list2cmdline([str(old_cli), "hook", "runtime"]),
                                }
                            ],
                        },
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook"}]},
                    ]
                    for event in ("PreToolUse", "PostToolUse")
                }
            }
        ),
        encoding="utf-8",
    )
    forwarder = _hook_forwarder(tmp_path)
    monkeypatch.setattr(codex_installation, "installed_hook_executable", lambda: forwarder)
    installer = CodexHookInstaller(path)

    assert installer.is_installed() is False
    assert installer.has_aia_runtime() is True
    installer.install()

    document = json.loads(path.read_text(encoding="utf-8"))
    for event in ("PreToolUse", "PostToolUse"):
        commands = [
            handler["command"]
            for entry in document["hooks"][event]
            for handler in entry["hooks"]
        ]
        # The stale AIA entry is dropped and the forwarder entry appended;
        # Codex runs every matching Hook, so only the set matters.
        assert sorted(commands) == sorted([installer.command, "user-hook"])
    assert installer.is_fully_installed() is True

    installer.uninstall()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert [
        handler["command"]
        for entry in document["hooks"]["PreToolUse"]
        for handler in entry["hooks"]
    ] == ["user-hook"]


def test_hook_verification_is_invalid_after_the_hook_forwarder_changes(
    tmp_path: Path, monkeypatch
) -> None:
    forwarder = _hook_forwarder(tmp_path)
    monkeypatch.setattr(codex_installation, "installed_hook_executable", lambda: forwarder)
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test-build-1")
    installer = CodexHookInstaller(tmp_path / "hooks.json")
    installer.install()
    store = HookVerificationStore(tmp_path / "control")
    store.write_verified(
        installer=installer,
        executable=executable,
        session_id="session-1",
        hook_event_count=1,
    )

    assert store.is_current(installer, executable) is True
    assert store.read()["hook_executable_sha256"]

    forwarder.write_bytes(b"forwarder-2")

    assert store.is_current(installer, executable) is False
