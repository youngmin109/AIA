from __future__ import annotations

import json
from pathlib import Path

from aia import CodexHookInstaller


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
