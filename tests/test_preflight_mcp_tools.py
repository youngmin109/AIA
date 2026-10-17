import json
from pathlib import Path

import pytest

from aia_app.external_tools import (
    discover_external_tools,
    read_allowed,
    save_allowed,
    turn_off_plan,
)
from aia_app.service import RunApplicationService


def _codex_home(tmp_path: Path, monkeypatch, config: str | None) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    if config is not None:
        (home / "config.toml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home / "config.toml"


def _plugin(home: Path, marketplace: str, name: str, servers: dict, *, manifest_points_to_file: bool = True) -> None:
    version = home / "plugins" / "cache" / marketplace / name / "1.0.0"
    (version / ".codex-plugin").mkdir(parents=True)
    manifest = {"name": name, "mcpServers": "./.mcp.json"} if manifest_points_to_file else {"name": name}
    (version / ".codex-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (version / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _names(tools):
    return [(tool["name"], tool["off"]) for tool in tools]


def test_config_servers_plugin_servers_and_apps_are_found_without_starting_anything(tmp_path, monkeypatch) -> None:
    config = _codex_home(tmp_path, monkeypatch, (
        '[mcp_servers.node_repl]\ncommand = "node"\n\n'
        '[mcp_servers.docs]\nurl = "https://example.invalid/mcp"\nenabled = true\n\n'
        '[mcp_servers.off]\ncommand = "off"\nenabled = false\n\n'
        '[mcp_servers."odd.name"]\ncommand = "odd"\n\n'
        '[plugins."switched-off@market"]\nenabled = false\n'
    ))
    home = config.parent
    _plugin(home, "market", "computer", {"cua_repl": {"command": "node", "enabled": True}})
    _plugin(home, "market", "review", {"code-review": {"command": "cmd", "enabled": False}})
    _plugin(home, "market", "switched-off", {"hidden": {"command": "x"}})
    _plugin(home, "market", "default-file", {"plain": {"command": "x"}}, manifest_points_to_file=False)

    assert _names(discover_external_tools()) == [
        ("docs", "mcp_servers.docs.enabled=false"),
        ("node_repl", "mcp_servers.node_repl.enabled=false"),
        ("odd.name", None),  # Codex cannot turn this name off through -c
        ("cua_repl", "plugins.computer@market.enabled=false"),
        ("plain", "plugins.default-file@market.enabled=false"),
        ("codex_apps", "features.apps=false"),
    ]
    # Without the config's "enabled = false" the cached plugin counts again.
    config.write_text('[features]\napps = false\n', encoding="utf-8")
    assert [tool["name"] for tool in discover_external_tools()] == ["cua_repl", "plain", "hidden"]


def test_missing_config_has_only_apps_and_unreadable_config_is_unknown(tmp_path, monkeypatch) -> None:
    config = _codex_home(tmp_path, monkeypatch, None)
    assert [tool["name"] for tool in discover_external_tools()] == ["codex_apps"]
    config.write_text("[mcp_servers.node_repl\n", encoding="utf-8")
    assert discover_external_tools() is None


def test_allowed_tools_are_saved_and_a_damaged_file_allows_none(tmp_path) -> None:
    control = tmp_path / "control"
    assert read_allowed(control) == set()
    assert save_allowed(control, ["context7", "context7", "node_repl"]) == {"context7", "node_repl"}
    assert read_allowed(control) == {"context7", "node_repl"}
    (control / "external-tools.json").write_text("{not json", encoding="utf-8")
    assert read_allowed(control) == set()
    for bad in ("node_repl", [1], ["a.b"], ["x"] * 101):
        with pytest.raises(ValueError):
            save_allowed(control, bad)


def test_turn_off_plan_keeps_allowed_tools_and_turns_a_plugin_off_as_a_whole() -> None:
    tools = [
        {"name": "node_repl", "plugin": None, "off": "mcp_servers.node_repl.enabled=false"},
        {"name": "context7", "plugin": None, "off": "mcp_servers.context7.enabled=false"},
        {"name": "one", "plugin": "pair@m", "off": "plugins.pair@m.enabled=false"},
        {"name": "two", "plugin": "pair@m", "off": "plugins.pair@m.enabled=false"},
        {"name": "odd.name", "plugin": None, "off": None},
        {"name": "codex_apps", "plugin": None, "off": "features.apps=false"},
    ]
    overrides, names = turn_off_plan(tools, {"context7", "one"})
    assert overrides == [
        "mcp_servers.node_repl.enabled=false", "plugins.pair@m.enabled=false", "features.apps=false",
    ]
    assert names == ["node_repl", "one", "two", "codex_apps"]
    assert turn_off_plan(tools, {"node_repl", "context7", "one", "two", "codex_apps"}) == ([], [])


@pytest.mark.parametrize(
    "config,allowed",
    [
        ('[mcp_servers.node_repl]\ncommand = "node"\n', ["node_repl", "codex_apps"]),
        ("[mcp_servers.node_repl\n", []),
    ],
)
def test_protected_run_always_disables_notify_even_when_no_tools_are_turned_off(
    tmp_path, monkeypatch, config, allowed
) -> None:
    _codex_home(tmp_path, monkeypatch, config)
    service = RunApplicationService(tmp_path / "control")
    if allowed:
        service.set_external_tools(allowed)
    try:
        assert service._external_tool_overrides() == (["notify=[]"], [])
    finally:
        service.shutdown()


def _preflight_service(tmp_path, monkeypatch) -> RunApplicationService:
    monkeypatch.setattr("aia_app.service.CodexAdapter.discover", lambda _adapter: tmp_path / "codex.exe")
    monkeypatch.setattr("aia_app.service.CodexHookInstaller.is_installed", lambda _installer: True)
    monkeypatch.setattr("aia_app.service.CodexHookInstaller.is_posttool_installed", lambda _installer: True)
    monkeypatch.setattr(
        "aia_app.preflight.inspect_codex_hook_trust",
        lambda *args, **kwargs: type("Inspection", (), {"to_mapping": lambda self: {
            "available": True, "reason": None, "hooks": [{"event": "preToolUse", "trust_status": "TRUSTED"}],
        }})(),
    )
    return RunApplicationService(tmp_path / "control")


def test_preflight_warns_only_about_tools_kept_on_and_never_changes_the_codex_config(tmp_path, monkeypatch) -> None:
    config = _codex_home(tmp_path, monkeypatch, '[mcp_servers.node_repl]\ncommand = "node"\n')
    before = config.read_bytes()
    service = _preflight_service(tmp_path, monkeypatch)
    try:
        cleared = service.preflight()
        check = next(item for item in cleared["checks"] if item["name"] == "mcp_tools")
        assert check["ok"] is True and check["status"] == "CLEAR" and check["servers"] == []
        assert "모두 꺼 둠" in check["detail"]

        service.set_external_tools(["node_repl"])
        warned = service.preflight()
        check = next(item for item in warned["checks"] if item["name"] == "mcp_tools")
        assert check["ok"] is False and check["optional"] is True
        assert check["status"] == "ENABLED" and check["servers"] == ["node_repl"]
        assert "node_repl" in check["detail"]
        assert warned["readiness_code"] == cleared["readiness_code"]
        assert config.read_bytes() == before  # AIA only reads the Codex config
    finally:
        service.shutdown()


def test_settings_list_shows_each_tool_and_whether_protected_runs_keep_it_on(tmp_path, monkeypatch) -> None:
    _codex_home(tmp_path, monkeypatch, '[mcp_servers.node_repl]\ncommand = "node"\n\n[mcp_servers.context7]\nurl = "https://x.invalid"\n')
    service = RunApplicationService(tmp_path / "control")
    try:
        state = service.set_external_tools(["context7"])
        assert state["readable"] is True
        assert {tool["name"]: tool["on_in_protected_runs"] for tool in state["tools"]} == {
            "context7": True, "node_repl": False, "codex_apps": False,
        }
        assert service._external_tool_overrides() == (
            ["mcp_servers.node_repl.enabled=false", "features.apps=false", "notify=[]"],
            ["node_repl", "codex_apps"],
        )
        assert "notify" not in {tool["name"] for tool in state["tools"]}
    finally:
        service.shutdown()
