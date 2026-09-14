from __future__ import annotations

import pytest

from scripts.actual_codex_pretool_smoke import _proof_prompt


def test_canary_proof_prompt_requires_the_shell_tool() -> None:
    prompt = _proof_prompt("canary")

    assert "AIA_BLOCK_CANARY.py" in prompt
    assert "shell tool" in prompt
    assert "Do not use another tool" in prompt


def test_proof_prompt_rejects_unknown_scenario() -> None:
    with pytest.raises(ValueError, match="unsupported proof scenario"):
        _proof_prompt("unknown")
