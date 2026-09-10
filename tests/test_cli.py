from __future__ import annotations

import json

import pytest

from aia import CodexHookInstaller
from aia.cli import (
    _extract_session_id,
    _live_hook_proof_is_valid,
    _parser,
    _protected_run_preflight,
    _recent_run_diagnostic,
    main,
)
from aia.codex_hook_trust import summarize_aia_hooks
from aia_web.__main__ import run as run_console, validate_local_bind


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


def test_console_parser_supports_explicit_bind_values() -> None:
    args = _parser().parse_args(["console", "--host", "127.0.0.1", "--port", "8799"])

    assert args.command == "console"
    assert args.host == "127.0.0.1"
    assert args.port == 8799


def test_console_rejects_non_loopback_host() -> None:
    with pytest.raises(ValueError, match="local-only"):
        run_console(host="0.0.0.0", port=8799)


def test_console_bind_validation_rejects_invalid_port() -> None:
    with pytest.raises(ValueError, match="port"):
        validate_local_bind("127.0.0.1", 65_536)


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


def test_hook_status_is_not_ready_when_only_the_definition_is_installed(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(hook_path)
    installer.install()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: executable)

    exit_code = main(
        [
            "hook",
            "status",
            "--json",
            "--path",
            str(hook_path),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["pretool_installed"] is True
    assert payload["verification_status"] == "MISSING_OR_STALE"
    assert payload["ready"] is False


def test_recent_run_diagnostic_explains_downgraded_codex_execution(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "aia.cli.ResultBundleReader.list_completed",
        lambda _reader: [
            {
                "session_id": "session-1",
                "ended_at": "2026-09-10T12:00:00Z",
                "protection_state": "COMPLETED_DEGRADED",
                "bundle_status": "VALID",
                "hook_event_count": 0,
            }
        ],
    )
    monkeypatch.setattr(
        "aia.cli.ResultBundleReader.read_result",
        lambda _reader, _session_id: {
            "limitations": [
                "CODEX_SANDBOX_DOWNGRADED",
                "CODEX_APPROVAL_POLICY_DOWNGRADED",
            ],
            "agent_execution": {
                "output_observation": {
                    "effective_sandbox": "read-only",
                    "effective_approval_policy": "never",
                }
            },
        },
    )

    diagnostic = _recent_run_diagnostic(tmp_path / "control")

    assert diagnostic is not None
    assert diagnostic["protection_state"] == "COMPLETED_DEGRADED"
    assert diagnostic["effective_sandbox"] == "read-only"
    assert diagnostic["effective_approval_policy"] == "never"
    assert "실행 정책보다 약한" in diagnostic["next_step"]


def test_recent_run_diagnostic_is_empty_without_committed_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("aia.cli.ResultBundleReader.list_completed", lambda _reader: [])

    assert _recent_run_diagnostic(tmp_path / "control") is None


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


def test_live_hook_proof_requires_session_event_and_verified_bundle() -> None:
    assert _live_hook_proof_is_valid(
        hook_event_count=1,
        protection_state="COMPLETED_VERIFIED",
        bundle_status="VALID",
    ) is True
    assert _live_hook_proof_is_valid(
        hook_event_count=0,
        protection_state="COMPLETED_DEGRADED",
        bundle_status="VALID",
    ) is False


def test_codex_hook_trust_summary_exposes_modified_and_untrusted_entries(tmp_path) -> None:
    path = tmp_path / "hooks.json"
    inspection = summarize_aia_hooks(
        {
            "result": {
                "data": [
                    {
                        "cwd": str(tmp_path),
                        "hooks": [
                            {
                                "sourcePath": str(path),
                                "eventName": "preToolUse",
                                "enabled": True,
                                "trustStatus": "modified",
                                "matcher": "Bash",
                                "command": "python -m aia.codex_hook_runtime",
                                "key": "hook:pre",
                            },
                            {
                                "sourcePath": str(path),
                                "eventName": "postToolUse",
                                "enabled": True,
                                "trustStatus": "untrusted",
                                "matcher": "Bash",
                                "command": "python -m aia.codex_hook_runtime",
                                "key": "hook:post",
                            },
                        ],
                    }
                ]
            }
        },
        hook_path=path,
    )

    assert inspection.available is True
    assert [item["trust_status"] for item in inspection.hooks] == ["MODIFIED", "UNTRUSTED"]
    assert _live_hook_proof_is_valid(
        hook_event_count=1,
        protection_state="COMPLETED_VERIFIED",
        bundle_status="INVALID",
    ) is False


def test_doctor_reports_actual_codex_hook_trust_state(tmp_path, monkeypatch, capsys) -> None:
    hook_path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(hook_path)
    installer.install()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: executable)
    monkeypatch.setattr(
        "aia.cli.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                        {"event": "postToolUse", "trust_status": "UNTRUSTED"},
                    ],
                }
            },
        )(),
    )

    exit_code = main(
        [
            "doctor",
            "--json",
            "--hook-path",
            str(hook_path),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    trust_check = next(item for item in payload["checks"] if item["name"] == "codex_hook_trust")
    assert trust_check["ok"] is False
    assert "PreToolUse=MODIFIED" in trust_check["value"]
    assert payload["codex_hook_trust"]["hooks"][0]["trust_status"] == "MODIFIED"


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
