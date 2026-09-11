from __future__ import annotations

import pytest

from scripts.actual_codex_pretool_smoke import _proof_prompt


def test_mcp_proof_prompt_requires_the_registered_tool() -> None:
    prompt = _proof_prompt("mcp-read")

    assert "mcp__filesystem__read_file" in prompt
    assert "exactly once" in prompt
    assert "Do not use Bash" in prompt
    assert "Do not use another tool" in prompt


def test_proof_prompt_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="unsupported proof scenario"):
        _proof_prompt("unknown")
