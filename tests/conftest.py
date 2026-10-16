"""Keep tests independent of an AIA installation on the developer's machine."""

from __future__ import annotations

import pytest

import aia.codex_installation as codex_installation


@pytest.fixture(autouse=True)
def _no_installed_hook_executable(monkeypatch) -> None:
    # A locally installed aia-hook.exe would otherwise change every computed
    # Hook command.  Tests that cover the installed forwarder patch it back in.
    monkeypatch.setattr(codex_installation, "installed_hook_executable", lambda: None)
