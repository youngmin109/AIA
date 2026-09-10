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
    assert len(second["hooks"]["PostToolUse"]) == 1
    assert second["hooks"]["PostToolUse"][0]["hooks"][0]["type"] == "command"
