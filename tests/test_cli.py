from __future__ import annotations

import json

import pytest

from aia import CodexHookInstaller
from aia.cli import (
    _extract_session_id,
    _live_hook_proof_is_valid,
    _parser,
    _print_protected_run_summary,
    _protected_run_preflight,
    _recent_run_diagnostic,
    main,
)
from aia.codex_hook_trust import summarize_aia_hooks
from aia._version import __version__
from aia_web.__main__ import run as run_console, validate_local_bind


def test_protect_without_task_selects_interactive_mode() -> None:
    args = _parser().parse_args(["protect", "C:/workspace/my-project"])

    assert args.task is None


def test_protect_with_task_keeps_one_shot_mode() -> None:
    args = _parser().parse_args(
        ["protect", "C:/workspace/my-project", "--task", "inspect"]
    )

    assert args.task == "inspect"


def test_product_proof_parser_defaults_to_disposable_block_canary() -> None:
    args = _parser().parse_args(["proof"])

    assert args.command == "proof"
    assert args.scenario == "block-canary"
    assert args.timeout == 180.0
    assert args.json is False


def test_product_proof_parser_supports_json_output() -> None:
    args = _parser().parse_args(["proof", "--json"])

    assert args.json is True


def test_product_proof_parser_supports_env_secret_block() -> None:
    args = _parser().parse_args(["proof", "--scenario", "block-env"])

    assert args.scenario == "block-env"


def test_product_proof_parser_supports_windows_delete_block() -> None:
    args = _parser().parse_args(["proof", "--scenario", "block-windows-delete"])

    assert args.scenario == "block-windows-delete"


def test_cli_version_uses_package_version(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        _parser().parse_args(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == f"AIA {__version__}"


def test_doctor_parser_supports_machine_readable_preflight() -> None:
    args = _parser().parse_args(["doctor", "--json"])

    assert args.command == "doctor"
    assert args.json is True


def test_self_test_parser_supports_machine_readable_output() -> None:
    args = _parser().parse_args(["self-test", "--json"])

    assert args.command == "self-test"
    assert args.json is True


def test_self_test_exercises_core_contracts_without_codex(capsys) -> None:
    exit_code = main(["self-test", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["codex_live_proof"] == "NOT_RUN"
    assert {item["name"] for item in payload["checks"]} >= {
        "policy_profile_resolution",
        "protected_default_policy",
        "active_policy_freeze",
        "workspace_lease",
        "safe_checkpoint",
        "raw_evidence_seal",
        "lifecycle_cleanup",
    }


def test_protected_run_summary_explains_verified_completion(capsys) -> None:
    _print_protected_run_summary(
        "session-1",
        {
            "session": {"status": "COMPLETED"},
            "protection": {"state": "COMPLETED_VERIFIED", "hook_events": 3},
            "result_path": "C:/control/sessions/session-1/result/result.json",
        },
        {"bundle_status": "VALID", "incidents": [{"action_id": "a-1"}]},
    )

    output = capsys.readouterr().out
    assert "AIA 보호 실행 결과" in output
    assert "Protection: COMPLETED_VERIFIED" in output
    assert "Hook Events: 3" in output
    assert "Result Bundle: VALID" in output
    assert "실제 Hook과 센서 종료 상태가 확인된 보호 실행" in output


def test_protected_run_summary_marks_degraded_completion(capsys) -> None:
    _print_protected_run_summary(
        "session-2",
        {
            "session": {"status": "COMPLETED"},
            "protection": {"state": "COMPLETED_DEGRADED", "hook_events": 0},
            "incident_count": 0,
        },
        {"bundle_status": "VALID", "incidents": []},
    )

    output = capsys.readouterr().out
    assert "보호 경계가 완전히 검증되지 않았습니다" in output
    assert "다시 실행하세요" in output


def test_setup_parser_supports_json_and_custom_hook_path(tmp_path) -> None:
    args = _parser().parse_args(["setup", "--json", "--path", str(tmp_path / "hooks.json")])

    assert args.command == "setup"
    assert args.json is True
    assert args.path == tmp_path / "hooks.json"


def test_setup_reports_current_codex_pretool_trust(tmp_path, monkeypatch, capsys) -> None:
    hook_path = tmp_path / "hooks.json"
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

    exit_code = main(["setup", "--json", "--path", str(hook_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["configured"] is True
    assert payload["codex_pretool_trust_status"] == "MODIFIED"
    assert payload["codex_hook_trust"]["hooks"][0]["trust_status"] == "MODIFIED"
    assert "/hooks" in payload["next_steps"][0]


def test_console_parser_supports_explicit_bind_values() -> None:
    args = _parser().parse_args(
        ["console", "--host", "127.0.0.1", "--port", "8799", "--open"]
    )

    assert args.command == "console"
    assert args.host == "127.0.0.1"
    assert args.port == 8799
    assert args.open is True


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


def test_hook_status_human_output_explains_trust_and_verification_steps(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    CodexHookInstaller(hook_path).install()
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
                    "hooks": [{"event": "preToolUse", "trust_status": "MODIFIED"}],
                }
            },
        )(),
    )

    exit_code = main(
        [
            "hook",
            "status",
            "--path",
            str(hook_path),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "/hooks" in output
    assert "aia hook verify" in output


def test_hook_status_does_not_report_ready_when_current_fingerprint_is_untrusted(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(hook_path)
    installer.install()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: executable)
    monkeypatch.setattr(
        "aia.cli.HookVerificationStore.is_current",
        lambda _store, _installer, _executable: True,
    )
    monkeypatch.setattr(
        "aia.cli.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "hooks": [{"event": "preToolUse", "trust_status": "MODIFIED"}],
                }
            },
        )(),
    )

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
    assert payload["verification_status"] == "CURRENT_BUT_UNTRUSTED"
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


def test_hook_verify_fails_before_probe_when_codex_hook_is_untrusted(
    tmp_path, monkeypatch, capsys
) -> None:
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
                        {"event": "preToolUse", "trust_status": "MODIFIED"}
                    ],
                }
            },
        )(),
    )

    def fail_if_probe_starts(*args, **kwargs):
        raise AssertionError("untrusted Hook must not start a live probe")

    monkeypatch.setattr("aia.cli.subprocess.run", fail_if_probe_starts)

    exit_code = main(
        [
            "hook",
            "verify",
            "--json",
            "--path",
            str(hook_path),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["verified"] is False
    assert payload["reason"] == "CODEX_HOOK_TRUST_REQUIRED"
    assert payload["trust_status"] == "MODIFIED"
    assert payload["probe_started"] is False


def test_hook_verify_fails_before_probe_when_codex_does_not_show_aia_pretool(
    tmp_path, monkeypatch, capsys
) -> None:
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
                    "hooks": [],
                }
            },
        )(),
    )
    monkeypatch.setattr(
        "aia.cli.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("missing PreToolUse must not start a live probe")
        ),
    )

    exit_code = main(
        [
            "hook",
            "verify",
            "--json",
            "--path",
            str(hook_path),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["reason"] == "CODEX_PRETOOL_HOOK_NOT_VISIBLE"
    assert payload["trust_status"] == "NOT_VISIBLE"
    assert payload["probe_started"] is False


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
    assert payload["readiness_code"] == "CODEX_HOOK_TRUST_REQUIRED"
    assert "aia hook verify" in payload["next_step"]


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


def test_protected_run_preflight_explains_untrusted_codex_hook(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: tmp_path / "codex.exe")
    monkeypatch.setattr("aia.cli.CodexHookInstaller.is_installed", lambda _installer: True)
    monkeypatch.setattr(
        "aia.cli.inspect_codex_hook_trust",
        lambda *args, **kwargs: type(
            "Inspection",
            (),
            {
                "to_mapping": lambda self: {
                    "available": True,
                    "hooks": [{"event": "preToolUse", "trust_status": "MODIFIED"}],
                }
            },
        )(),
    )

    ready, failures = _protected_run_preflight(tmp_path / "control")

    assert ready is False
    assert any("PreToolUse Hook Trust=MODIFIED" in item for item in failures)


def test_policy_validate_parser_keeps_policy_path_and_json_flag(tmp_path) -> None:
    path = tmp_path / "policy.json"
    args = _parser().parse_args(["policy", "validate", str(path), "--json"])

    assert args.command == "policy"
    assert args.policy_command == "validate"
    assert args.path == path
    assert args.json is True


def test_policy_evaluate_parser_supports_path_and_operation() -> None:
    args = _parser().parse_args(
        [
            "policy",
            "evaluate",
            "--operation",
            "READ",
            "--path",
            ".env",
            "--json",
        ]
    )

    assert args.policy_command == "evaluate"
    assert args.operation == "READ"
    assert args.target_path == ".env"
    assert args.json is True


def test_product_commands_default_to_protected_development_profile() -> None:
    evaluate_args = _parser().parse_args(
        ["policy", "evaluate", "--operation", "READ", "--path", ".env"]
    )
    init_args = _parser().parse_args(["policy", "init", "policy.json"])
    protect_args = _parser().parse_args(["protect", "."])

    assert evaluate_args.profile == "PROTECTED_DEVELOPMENT"
    assert init_args.profile == "PROTECTED_DEVELOPMENT"
    assert protect_args.profile == "PROTECTED_DEVELOPMENT"


def test_policy_evaluate_uses_resolved_profile_without_running_target(capsys) -> None:
    exit_code = main(
        [
            "policy",
            "evaluate",
            "--profile",
            "BASIC_DEVELOPMENT",
            "--operation",
            "DELETE",
            "--path",
            ".env",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy_decision"] == "VIOLATION"
    assert payload["operation_effect"] == "DENY"
    assert payload["matched_rule_ids"]


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
