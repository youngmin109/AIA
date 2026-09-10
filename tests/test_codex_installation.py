from __future__ import annotations

import json
from pathlib import Path

from aia import CodexHookInstaller
from aia.hook_verification import HookVerificationStore


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
    assert second["hooks"]["PreToolUse"][0]["matcher"] == (
        "Bash|apply_patch|Edit|Write|"
        "mcp__filesystem__read_file|mcp__fs__read"
    )
    assert len(second["hooks"]["PostToolUse"]) == 1
    assert second["hooks"]["PostToolUse"][0]["hooks"][0]["type"] == "command"


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
    assert updated["hooks"]["PreToolUse"][0]["matcher"] == (
        "Bash|apply_patch|Edit|Write|"
        "mcp__filesystem__read_file|mcp__fs__read"
    )
    assert updated["hooks"]["PreToolUse"][1]["matcher"] == "Bash"


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


def test_hook_verification_is_bound_to_hook_and_codex_fingerprints(tmp_path: Path) -> None:
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
    assert document["schema_version"] == "aia-hook-verification-1"
    assert document["session_id"] == "session-1"

    hook_path.write_text(hook_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert store.is_current(installer, executable) is False


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
