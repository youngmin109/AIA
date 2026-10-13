"""Codex external tools (MCP servers) that protected runs turn off.

MCP tools can run without the PreToolUse Hook (the Codex app's node_repl, for
example), so AIA can neither block nor record what they do.  AIA reads the
Codex setup without changing it and turns the tools off only for its own
protected runs, through ``-c`` overrides on that run's app-server.  A tool
stays off unless the user allows it in Settings; a tool AIA has not seen yet
is off too.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tomllib
from typing import Any

from aia.hook_verification import HookVerificationStore

SETTINGS_FILE = "external-tools.json"
APPS_TOOL = "codex_apps"
MAX_ALLOWED = 100
# Names Codex accepts in a ``-c`` key path; anything else cannot be turned off.
_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}")
_PLUGIN = re.compile(r"[A-Za-z0-9_-]{1,100}@[A-Za-z0-9_-]{1,100}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _plugin_servers(version_dir: Path) -> list[str]:
    """MCP servers a cached plugin version turns on (its own ``enabled`` flag)."""

    manifest = _read_json(version_dir / ".codex-plugin" / "plugin.json")
    declared = manifest.get("mcpServers") if isinstance(manifest, dict) else None
    if isinstance(declared, dict):
        servers: Any = declared
    else:
        source = (version_dir / (declared if isinstance(declared, str) else ".mcp.json")).resolve(strict=False)
        if not source.is_relative_to(version_dir.resolve(strict=False)):
            return []
        document = _read_json(source)
        servers = document.get("mcpServers") if isinstance(document, dict) else None
    if not isinstance(servers, dict):
        return []
    return sorted(
        str(name) for name, spec in servers.items()
        if isinstance(spec, dict) and spec.get("enabled", True) is not False
    )


def _newest_version(plugin_dir: Path) -> Path | None:
    try:
        versions = [path for path in plugin_dir.iterdir() if path.is_dir()]
        return max(versions, key=lambda path: path.stat().st_mtime, default=None)
    except OSError:
        return None


def _subdirectories(path: Path) -> list[Path]:
    try:
        return sorted(child for child in path.iterdir() if child.is_dir())
    except OSError:
        return []


def discover_external_tools(config_path: Path | None = None) -> list[dict[str, Any]] | None:
    """External tools the Codex setup turns on, read from files only; None if the config is unreadable.

    Three sources, the same names Codex reports for a conversation:
    ``[mcp_servers]`` in config.toml, MCP servers of cached plugins (unless the
    config turns the plugin off), and ChatGPT apps (``codex_apps``).
    """

    path = config_path or HookVerificationStore._codex_config_path()
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None

    tools: list[dict[str, Any]] = []
    servers = config.get("mcp_servers")
    for name, spec in sorted(servers.items()) if isinstance(servers, dict) else ():
        if isinstance(spec, dict) and spec.get("enabled", True) is not False:
            tools.append({
                "name": str(name), "source": "config", "plugin": None,
                "off": f"mcp_servers.{name}.enabled=false" if _NAME.fullmatch(str(name)) else None,
            })

    plugin_settings = config.get("plugins") if isinstance(config.get("plugins"), dict) else {}
    for marketplace in _subdirectories(path.parent / "plugins" / "cache"):
        for plugin_dir in _subdirectories(marketplace):
            plugin = f"{plugin_dir.name}@{marketplace.name}"
            settings = plugin_settings.get(plugin)
            if isinstance(settings, dict) and settings.get("enabled") is False:
                continue
            version = _newest_version(plugin_dir)
            for name in _plugin_servers(version) if version is not None else ():
                tools.append({
                    "name": name, "source": "plugin", "plugin": plugin,
                    "off": f"plugins.{plugin}.enabled=false" if _PLUGIN.fullmatch(plugin) else None,
                })

    features = config.get("features") if isinstance(config.get("features"), dict) else {}
    if features.get("apps", True) is not False:
        tools.append({"name": APPS_TOOL, "source": "apps", "plugin": None, "off": "features.apps=false"})
    return tools


def read_allowed(control_root: Path) -> set[str]:
    """Tools the user keeps on in protected runs; a missing or damaged file allows none."""

    document = _read_json(control_root / SETTINGS_FILE)
    allowed = document.get("allowed") if isinstance(document, dict) else None
    if not isinstance(allowed, list):
        return set()
    return {name for name in allowed if isinstance(name, str) and _NAME.fullmatch(name)}


def save_allowed(control_root: Path, names: Any) -> set[str]:
    if not isinstance(names, list) or len(names) > MAX_ALLOWED:
        raise ValueError(f"allowed must be a list of at most {MAX_ALLOWED} tool names")
    if not all(isinstance(name, str) and _NAME.fullmatch(name) for name in names):
        raise ValueError("allowed must contain tool names")
    allowed = sorted(set(names))
    control_root.mkdir(parents=True, exist_ok=True)
    path = control_root / SETTINGS_FILE
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": 1, "allowed": allowed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return set(allowed)


def turn_off_plan(tools: list[dict[str, Any]], allowed: set[str]) -> tuple[list[str], list[str]]:
    """``-c`` overrides for a protected run and the tool names they turn off.

    A plugin is turned off as a whole, so it stays on only when every server
    it brings is allowed.
    """

    blocked_plugins = {tool["plugin"] for tool in tools if tool["plugin"] and tool["name"] not in allowed}
    overrides: list[str] = []
    names: list[str] = []
    for tool in tools:
        off = tool["off"] and (tool["name"] not in allowed or tool["plugin"] in blocked_plugins)
        if not off:
            continue
        names.append(tool["name"])
        if tool["off"] not in overrides:
            overrides.append(tool["off"])
    return overrides, names


class ExternalToolsMixin:
    def external_tools(self) -> dict[str, Any]:
        """The Settings list: each tool, whether protected runs keep it on, and whether AIA can turn it off."""

        tools = discover_external_tools()
        allowed = read_allowed(self.control_root)
        _overrides, off = turn_off_plan(tools or [], allowed)
        return {
            "readable": tools is not None,
            "tools": [
                {
                    "name": tool["name"], "source": tool["source"], "plugin": tool["plugin"],
                    "on_in_protected_runs": tool["name"] not in off,
                    "allowed": tool["name"] in allowed,
                    "can_turn_off": tool["off"] is not None,
                }
                for tool in tools or []
            ],
        }

    def set_external_tools(self, allowed: Any) -> dict[str, Any]:
        save_allowed(self.control_root, allowed)
        return self.external_tools()

    def _external_tool_overrides(self) -> tuple[list[str], list[str]]:
        tools = discover_external_tools()
        return turn_off_plan(tools or [], read_allowed(self.control_root))
