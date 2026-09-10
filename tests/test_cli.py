from __future__ import annotations

from aia.cli import _parser, _protected_run_preflight


def test_protect_without_task_selects_interactive_mode() -> None:
    args = _parser().parse_args(["protect", "C:/workspace/my-project"])

    assert args.task is None


def test_protect_with_task_keeps_one_shot_mode() -> None:
    args = _parser().parse_args(
        ["protect", "C:/workspace/my-project", "--task", "inspect"]
    )

    assert args.task == "inspect"


def test_doctor_parser_supports_machine_readable_preflight() -> None:
    args = _parser().parse_args(["doctor", "--json"])

    assert args.command == "doctor"
    assert args.json is True


def test_setup_parser_supports_json_and_custom_hook_path(tmp_path) -> None:
    args = _parser().parse_args(["setup", "--json", "--path", str(tmp_path / "hooks.json")])

    assert args.command == "setup"
    assert args.json is True
    assert args.path == tmp_path / "hooks.json"


def test_protected_run_preflight_requires_the_aia_hook(monkeypatch) -> None:
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: "codex.exe")
    monkeypatch.setattr("aia.cli.CodexHookInstaller.is_installed", lambda _installer: False)

    ready, failures = _protected_run_preflight()

    assert ready is False
    assert any("PreToolUse Hook" in item for item in failures)


def test_policy_validate_parser_keeps_policy_path_and_json_flag(tmp_path) -> None:
    path = tmp_path / "policy.json"
    args = _parser().parse_args(["policy", "validate", str(path), "--json"])

    assert args.command == "policy"
    assert args.policy_command == "validate"
    assert args.path == path
    assert args.json is True


def test_runs_and_status_parsers_keep_inspection_arguments() -> None:
    runs = _parser().parse_args(["runs", "--json", "--limit", "5"])
    status = _parser().parse_args(["status", "session-1", "--json"])

    assert runs.command == "runs"
    assert runs.limit == 5
    assert status.command == "status"
    assert status.session_id == "session-1"


def test_stop_parser_keeps_session_id_and_control_root() -> None:
    args = _parser().parse_args(["stop", "session-1", "--json"])

    assert args.command == "stop"
    assert args.session_id == "session-1"
    assert args.json is True
