from __future__ import annotations

from scripts.actual_codex_hook_lifecycle_smoke import _replace_inline_hook_configs


_BASE_ARGV = (
    "codex.exe",
    "exec",
    "-c",
    "features.hooks=true",
    "-c",
    "hooks.PreToolUse=old-pre",
    "-c",
    "hooks.PostToolUse=old-post",
    "--dangerously-bypass-hook-trust",
    "-",
)


def test_diagnostic_hook_override_preserves_non_hook_options_and_argument_order() -> None:
    argv = _replace_inline_hook_configs(
        _BASE_ARGV,
        mode="aia-matcher",
        command="python hook.py",
    )

    assert argv.count("features.hooks=true") == 1
    assert "old-pre" not in argv
    assert "old-post" not in argv
    pre_index = next(i for i, value in enumerate(argv) if value.startswith("hooks.PreToolUse="))
    post_index = next(i for i, value in enumerate(argv) if value.startswith("hooks.PostToolUse="))
    bypass_index = argv.index("--dangerously-bypass-hook-trust")
    prompt_index = argv.index("-")
    assert pre_index < bypass_index < prompt_index
    assert post_index < bypass_index < prompt_index


def test_diagnostic_post_only_mode_removes_pretool_override() -> None:
    argv = _replace_inline_hook_configs(
        _BASE_ARGV,
        mode="post-only",
        command="python hook.py",
    )

    assert not any(value.startswith("hooks.PreToolUse=") for value in argv)
    assert any(value.startswith("hooks.PostToolUse=") for value in argv)


def test_diagnostic_wildcard_mode_uses_a_wildcard_matcher() -> None:
    argv = _replace_inline_hook_configs(
        _BASE_ARGV,
        mode="wildcard",
        command="python hook.py",
    )

    pre = next(value for value in argv if value.startswith("hooks.PreToolUse="))
    post = next(value for value in argv if value.startswith("hooks.PostToolUse="))
    assert 'matcher=".*"' in pre
    assert 'matcher=".*"' in post
