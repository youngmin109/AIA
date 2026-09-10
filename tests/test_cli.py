from __future__ import annotations

from aia.cli import _parser


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
