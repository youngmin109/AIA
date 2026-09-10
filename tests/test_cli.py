from __future__ import annotations

from aia.cli import _extract_session_id, _parser, _protected_run_preflight, main


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


def test_hook_uninstall_parser_supports_custom_hook_path(tmp_path) -> None:
    args = _parser().parse_args(["hook", "uninstall", "--path", str(tmp_path / "hooks.json")])

    assert args.command == "hook"
    assert args.hook_command == "uninstall"
    assert args.path == tmp_path / "hooks.json"


def test_hook_status_parser_supports_json_and_control_root(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "hook",
            "status",
            "--json",
            "--path",
            str(tmp_path / "hooks.json"),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    assert args.command == "hook"
    assert args.hook_command == "status"
    assert args.json is True
    assert args.path == tmp_path / "hooks.json"
    assert args.control_root == tmp_path / "control"


def test_hook_verify_parser_supports_live_probe_options(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "hook",
            "verify",
            "--json",
            "--path",
            str(tmp_path / "hooks.json"),
            "--control-root",
            str(tmp_path / "control"),
            "--timeout",
            "30",
        ]
    )

    assert args.command == "hook"
    assert args.hook_command == "verify"
    assert args.json is True
    assert args.timeout == 30


def test_hook_verify_extracts_protected_run_session_id() -> None:
    assert _extract_session_id("Phase: READY\nAIA Protected Run: abc-123\n") == "abc-123"
    assert _extract_session_id("Hook was not started\n") is None


def test_protected_run_preflight_requires_the_aia_hook(monkeypatch) -> None:
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: "codex.exe")
    monkeypatch.setattr("aia.cli.CodexHookInstaller.is_installed", lambda _installer: False)

    ready, failures = _protected_run_preflight()

    assert ready is False
    assert any("PreToolUse Hook" in item for item in failures)


def test_protected_run_preflight_requires_live_hook_proof_when_hook_is_installed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: "codex.exe")
    monkeypatch.setattr("aia.cli.CodexHookInstaller.is_installed", lambda _installer: True)

    ready, failures = _protected_run_preflight(tmp_path / "control")

    assert ready is False
    assert any("hook verify" in item for item in failures)

    ready, failures = _protected_run_preflight(
        tmp_path / "control",
        allow_unverified_hook=True,
    )

    assert ready is True
    assert failures == []


def test_policy_validate_parser_keeps_policy_path_and_json_flag(tmp_path) -> None:
    path = tmp_path / "policy.json"
    args = _parser().parse_args(["policy", "validate", str(path), "--json"])

    assert args.command == "policy"
    assert args.policy_command == "validate"
    assert args.path == path
    assert args.json is True


def test_policy_profiles_parser_supports_json_output() -> None:
    args = _parser().parse_args(["policy", "profiles", "--json"])

    assert args.command == "policy"
    assert args.policy_command == "profiles"
    assert args.json is True


def test_policy_init_parser_supports_profile_and_force(tmp_path) -> None:
    path = tmp_path / "policy.json"
    args = _parser().parse_args(
        [
            "policy",
            "init",
            str(path),
            "--profile",
            "CONSERVATIVE_SECURITY",
            "--force",
        ]
    )

    assert args.command == "policy"
    assert args.policy_command == "init"
    assert args.path == path
    assert args.profile == "CONSERVATIVE_SECURITY"
    assert args.force is True


def test_policy_init_creates_a_valid_editable_profile(tmp_path, capsys) -> None:
    path = tmp_path / "policy.json"

    assert (
        main(
            [
                "policy",
                "init",
                str(path),
                "--profile",
                "CONSERVATIVE_SECURITY",
            ]
        )
        == 0
    )

    assert path.is_file()
    assert "정책 파일을 생성했습니다" in capsys.readouterr().out
    assert main(["policy", "validate", str(path), "--json"]) == 0


def test_policy_init_does_not_overwrite_without_force(tmp_path, capsys) -> None:
    path = tmp_path / "policy.json"
    path.write_text("original", encoding="utf-8")

    assert main(["policy", "init", str(path)]) == 2

    assert path.read_text(encoding="utf-8") == "original"
    assert "--force" in capsys.readouterr().out


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
