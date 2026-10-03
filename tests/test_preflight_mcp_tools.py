from pathlib import Path

from aia_app.preflight import _enabled_codex_mcp_servers
from aia_app.service import RunApplicationService


def _codex_home(tmp_path: Path, monkeypatch, config: str | None) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    if config is not None:
        (home / "config.toml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home / "config.toml"


def test_enabled_mcp_servers_are_listed_and_disabled_ones_are_not(tmp_path, monkeypatch) -> None:
    _codex_home(tmp_path, monkeypatch, (
        '[mcp_servers.node_repl]\ncommand = "node"\n\n'
        '[mcp_servers.docs]\nurl = "https://example.invalid/mcp"\nenabled = true\n\n'
        '[mcp_servers.off]\ncommand = "off"\nenabled = false\n'
    ))
    assert _enabled_codex_mcp_servers() == ["docs", "node_repl"]


def test_missing_config_or_no_mcp_table_means_no_servers(tmp_path, monkeypatch) -> None:
    config = _codex_home(tmp_path, monkeypatch, None)
    assert _enabled_codex_mcp_servers() == []
    config.write_text('model = "gpt-test"\n', encoding="utf-8")
    assert _enabled_codex_mcp_servers() == []


def test_unreadable_config_is_unknown_not_a_crash(tmp_path, monkeypatch) -> None:
    _codex_home(tmp_path, monkeypatch, "[mcp_servers.node_repl\n")
    assert _enabled_codex_mcp_servers() is None


def test_preflight_warns_about_mcp_tools_without_changing_readiness_or_config(tmp_path, monkeypatch) -> None:
    text = '[mcp_servers.node_repl]\ncommand = "node"\n'
    config = _codex_home(tmp_path, monkeypatch, text)
    before = config.read_bytes()
    monkeypatch.setattr("aia_app.service.CodexAdapter.discover", lambda _adapter: tmp_path / "codex.exe")
    monkeypatch.setattr("aia_app.service.CodexHookInstaller.is_installed", lambda _installer: True)
    monkeypatch.setattr("aia_app.service.CodexHookInstaller.is_posttool_installed", lambda _installer: True)
    monkeypatch.setattr(
        "aia_app.preflight.inspect_codex_hook_trust",
        lambda *args, **kwargs: type("Inspection", (), {"to_mapping": lambda self: {
            "available": True, "reason": None, "hooks": [{"event": "preToolUse", "trust_status": "TRUSTED"}],
        }})(),
    )
    service = RunApplicationService(tmp_path / "control")
    try:
        warned = service.preflight()
        assert config.read_bytes() == before  # preflight only reads the Codex config
        check = next(item for item in warned["checks"] if item["name"] == "mcp_tools")
        assert check["ok"] is False and check["optional"] is True
        assert check["status"] == "ENABLED" and check["servers"] == ["node_repl"]
        assert "node_repl" in check["detail"]
        config.write_text("", encoding="utf-8")
        clear = service.preflight()
        assert warned["readiness_code"] == clear["readiness_code"]
        assert next(item for item in clear["checks"] if item["name"] == "mcp_tools")["ok"] is True
    finally:
        service.shutdown()
