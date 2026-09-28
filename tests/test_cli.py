from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from aia import CodexHookInstaller, ProcessIdentityStatus, SessionFinalizer
from aia.cli import (
    _extract_session_id,
    _live_hook_proof_is_valid,
    _cli_prefix,
    _self_cli_command,
    _parser,
    _print_protected_run_summary,
    _protected_run_preflight,
    _recent_run_diagnostic,
    main,
)
from aia.codex_hook_trust import summarize_aia_hooks
from aia.diagnostics import build_support_bundle
from aia._version import __version__
from aia_web.__main__ import run as run_console, validate_local_bind
from tests.test_finalization import _session


def test_cli_help_matches_existing_command_tree() -> None:
    expected = {
        "aia": "d23679860ffa7f5041663701929488a8596064de907dda95aef7feb684825050",
        "aia capabilities": "e4d1fecf21e880925884b6e73c3c0abd2e69ad9d1a97afd33dee07d56858e48e",
        "aia doctor": "e8044389ee6a0f83820c77d57d7798e69f958832e6b4ce70266a5bb7fafa2ae3",
        "aia self-test": "3bf6889c413d88aaccc4ea96a9e85c8f4009f362607c36414ef41145de5e2a07",
        "aia demo": "39939dcaa3c7e0ea53030f60eeebd358357d8fae0f75e320a1cc52aaf2ee2024",
        "aia runs": "763e498ed814d72f9704e1505bf49464589731f3085cb0688671a5033d3ba1b6",
        "aia status": "362e685b051261e95212dc4b0a5c30c429fb41d3afb52a52bb3a9ef681eaa287",
        "aia stop": "88179c5704042fe5c4e3cf94777cb8583b0ea2611b61009b2ca0af04a75a1c58",
        "aia reconcile": "40a017bafb5cb089ea0aecda0b73e474aaeb26b4915babb5852feea544558f87",
        "aia policy": "87c58e4556b0a9705f3af02c8ad43f215b35c95d204bde0441501b370c2d22e7",
        "aia policy profiles": "e28bd46c0e50f8d3ea0dee31d500e5fb522d52a8ed577dca0b6390c7f592c788",
        "aia policy init": "b491276ac50bfd74c9b73596939ef241f47c2c7121f0d1b633f4764ea2df4f58",
        "aia policy validate": "f3fb3eb5123f2e8e3b4ce6cb0ea43fc44b1a01dee0f0f997ced49f98e9a1a231",
        "aia policy evaluate": "73182a7659ff02c7cf796460c8a38372ced75e389b482a3ca97a0e9b99d06853",
        "aia hook": "2c611190a986ddd28bf573b7a6066ee18535f91f05975fab05ed2afb2cfde34f",
        "aia hook install": "fc37b8023a157db8b5bef66819898d47bab073420c1bccf38a65452a8637e0b7",
        "aia hook uninstall": "1cc7adb2a01563b9725c8963fad09e440de9393e7f2fe0fee199d61919c339f6",
        "aia hook status": "2ffcaafe1de44dfd939be58a416c251d0ff1f806c7997d75c664bb2615b0920c",
        "aia hook explain": "170e1c6dc49f3b8c8a116d114200b7fbac6fc9191382dc26018e0b8d59795ceb",
        "aia hook verify": "ea8bed358661ec632e42ff0148a868f3126eec978735f9168afd9f2c9310a007",
        "aia hook runtime": "8f3b2ffed73f188747dfaa4fa9d31c78977075aa003be311f655547e47216308",
        "aia setup": "6bf6cf6f3e3f671bc90048205a808a8c4fa4fd083927ff8826b7d006ab11f1fd",
        "aia support-bundle": "7e345a4883fc9afb9c355e61d3d4e601aabc9f1c80b74662b509ab674927d0e0",
        "aia verify-bundle": "da1af79ca66faccc845733e48b452f9ee329c0ad19bca64f60c68359bae57091",
        "aia console": "be886cbd69d101035d7d16bad003a6abd6b4d5b8f3f2a951ebcedc059b847be6",
        "aia protect": "8f0fa70197e6ba324307b3f4c0ae84a37c13ab4e231fd2e45e3c5c79d9aa0def",
        "aia start": "a9e9a0d6a879e87892b54f9014ce78716159ca848b5ab38454fff0575bd6f26d",
        "aia proof": "bfbdf74e34febaa8112d1c46b51dc0730f5249b699cba26948a7ba3444bd7d44",
    }

    def help_hashes(parser: argparse.ArgumentParser) -> dict[str, str]:
        result = {
            parser.prog: hashlib.sha256(parser.format_help().encode()).hexdigest()
        }
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    result.update(help_hashes(child))
        return result

    assert help_hashes(_parser()) == expected


def test_documented_cli_subcommands_exist() -> None:
    parser = _parser()
    commands = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    documented: dict[str, set[str]] = {}
    for document_name in ("README.md", "docs/QUICKSTART.md", "docs/USER-GUIDE.md"):
        content = (Path(__file__).resolve().parents[1] / document_name).read_text(
            encoding="utf-8"
        )
        documented[document_name] = {
            match.group(1)
            for match in re.finditer(r"\baia\s+([A-Za-z][A-Za-z0-9_-]*)", content)
        }
        assert documented[document_name], (
            f"No documented aia commands found in {document_name}"
        )

    missing = {
        f"{document_name}: aia {command}"
        for document_name, subcommands in documented.items()
        for command in subcommands
        if command not in commands
    }
    assert not missing, "Documented CLI subcommands do not exist: " + ", ".join(
        sorted(missing)
    )


def test_protect_without_task_selects_interactive_mode() -> None:
    args = _parser().parse_args(["protect", "C:/workspace/my-project"])

    assert args.task is None


def test_start_is_the_user_facing_interactive_protected_run_entrypoint() -> None:
    args = _parser().parse_args(["start", "C:/workspace/my-project"])

    assert args.command == "start"
    assert args.workspace == Path("C:/workspace/my-project")
    assert args.task is None
    assert args.profile == "PROTECTED_DEVELOPMENT"


def test_protected_run_defaults_to_the_current_directory() -> None:
    start_args = _parser().parse_args(["start"])
    protect_args = _parser().parse_args(["protect", "--task", "inspect"])

    assert start_args.workspace == Path(".")
    assert protect_args.workspace == Path(".")


def test_capabilities_parser_supports_human_and_json_output() -> None:
    human = _parser().parse_args(["capabilities"])
    machine = _parser().parse_args(["capabilities", "--json"])

    assert human.command == "capabilities"
    assert human.json is False
    assert machine.json is True


def test_capabilities_output_explains_bounded_support(capsys) -> None:
    assert main(["capabilities"]) == 0
    output = capsys.readouterr().out

    assert "AIA 지원 범위" in output
    assert "Bash" in output
    assert "MCP" in output
    assert "Hook matcher: *" in output
    assert "UNSUPPORTED_TOOL_PATH" in output
    assert "/hooks" in output
    assert "모든 Codex 도구" in output


def test_capabilities_json_is_machine_readable(capsys) -> None:
    assert main(["capabilities", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "aia-capabilities-v1"
    assert "Bash" in payload["support"]["pretool_matchers"]
    assert "Edit" not in payload["support"]["pretool_matchers"]
    assert "Write" not in payload["support"]["pretool_matchers"]
    assert all(
        not matcher.startswith("mcp__")
        for matcher in payload["support"]["pretool_matchers"]
    )
    assert payload["support"]["pretool_aliases"] == {
        "apply_patch": ["Edit", "Write"]
    }
    assert payload["support"]["pretool_matcher"] == "*"
    assert "UNSUPPORTED_TOOL_PATH" in payload["support"]["unsupported_tool_behavior"]
    assert payload["requires_user_action"]
    assert payload["unsupported_or_unclaimed"]


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


def test_cli_guidance_uses_module_launcher_for_source_checkout() -> None:
    command = _cli_prefix(CodexHookInstaller())

    assert "python -m aia.cli" in command
    assert "uv run --isolated" in command
    assert "uv run aia" not in command


def test_cli_guidance_prefers_sibling_cli_in_frozen_desktop_bundle(tmp_path, monkeypatch) -> None:
    fake_aia = tmp_path / "AIA" / "AIA.exe"
    fake_aia.parent.mkdir(parents=True)
    fake_aia.write_bytes(b"")
    fake_cli = tmp_path / "aia-cli" / "aia-cli.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_aia))

    assert _cli_prefix(CodexHookInstaller()) == subprocess.list2cmdline([str(fake_cli)])


def test_self_test_parser_supports_machine_readable_output() -> None:
    args = _parser().parse_args(["self-test", "--json"])

    assert args.command == "self-test"
    assert args.json is True


def test_demo_parser_defaults_to_safe_core_demo() -> None:
    args = _parser().parse_args(["demo"])

    assert args.command == "demo"
    assert args.live is False
    assert args.scenario == "block-canary"
    assert args.timeout == 180.0


def test_demo_live_parser_selects_real_codex_proof() -> None:
    args = _parser().parse_args(["demo", "--live", "--scenario", "block-env"])

    assert args.live is True
    assert args.scenario == "block-env"


def test_demo_parser_supports_presentation_scenario_roots(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "demo",
            "--scenario",
            "process-kill",
            "--workspace",
            str(tmp_path / "workspace"),
            "--control-root",
            str(tmp_path / "control"),
            "--open",
        ]
    )

    assert args.scenario == "process-kill"
    assert args.workspace == tmp_path / "workspace"
    assert args.control_root == tmp_path / "control"
    assert args.open is True


def test_demo_presentation_scenario_prints_fixture_boundary(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        "aia.demo.run_demo",
        lambda scenario, *, workspace, control_root: {
            "scenario": scenario,
            "title": "Process Sensor 관리 트리 종료",
            "session_id": "demo-process-kill",
            "workspace": str(workspace),
            "control_root": str(control_root),
            "bundle_status": "VALID",
            "next_step": "open",
        },
    )

    assert (
        main(
            [
                "demo",
                "--scenario",
                "process-kill",
                "--workspace",
                str(tmp_path / "workspace"),
                "--control-root",
                str(tmp_path / "control"),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Bundle: VALID" in output
    assert "DEMO_FIXTURE" in output


def test_demo_open_targets_the_created_session_workbench(monkeypatch, tmp_path) -> None:
    console_calls = []
    monkeypatch.setattr(
        "aia.demo.run_demo",
        lambda scenario, *, workspace, control_root: {
            "scenario": scenario,
            "title": "Hook Sensor PreToolUse 사전 차단",
            "session_id": "demo-hook-block",
            "workspace": str(workspace),
            "control_root": str(control_root),
            "bundle_status": "VALID",
            "next_step": "open",
        },
    )
    monkeypatch.setattr(
        "aia.cli._run_console",
        lambda args: console_calls.append(args) or 0,
    )

    assert (
        main(
            [
                "demo",
                "--scenario",
                "hook-block",
                "--workspace",
                str(tmp_path / "workspace"),
                "--control-root",
                str(tmp_path / "control"),
                "--open",
            ]
        )
        == 0
    )

    assert console_calls[0].open_path == "/runs/demo-hook-block/workbench"


def test_demo_runs_core_only_by_default(monkeypatch, capsys) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        "aia.cli._self_test",
        lambda args: calls.append(args.json) or 0,
    )

    assert main(["demo"]) == 0

    assert calls == [False]
    output = capsys.readouterr().out
    assert "AIA 제품 데모" in output
    assert "[1/1]" in output
    assert f"{_cli_prefix(CodexHookInstaller())} demo --live" in output


def test_demo_live_delegates_to_real_codex_proof(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("aia.cli._self_test", lambda args: 0)
    monkeypatch.setattr(
        "aia.product_e2e.main",
        lambda argv: calls.append(argv) or 7,
    )

    output_dir = tmp_path / "proof"
    assert (
        main(
            [
                "demo",
                "--live",
                "--scenario",
                "block-env",
                "--timeout",
                "12",
                "--output",
                str(output_dir),
            ]
        )
        == 7
    )

    assert calls == [
        [
            "--scenario",
            "block-env",
            "--output",
            str(output_dir),
            "--timeout",
            "12.0",
        ]
    ]


def test_support_bundle_parser_accepts_output_and_json(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "support-bundle",
            "--output",
            str(tmp_path / "support.json"),
            "--json",
        ]
    )

    assert args.command == "support-bundle"
    assert args.output == tmp_path / "support.json"
    assert args.json is True


@pytest.mark.parametrize(
    "tamper, expected_status, expected_exit",
    [(False, "VALID", 0), (True, "INVALID", 1)],
)
def test_verify_bundle_reports_status_without_modifying_files(
    tmp_path, capsys, tamper: bool, expected_status: str, expected_exit: int
) -> None:
    session, store, _ = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    result_path = final.bundle.result_directory / "result.json"
    if tamper:
        result_path.write_bytes(result_path.read_bytes() + b"tamper")
    result_directory = final.bundle.result_directory
    bundle_directory = result_directory.parent

    def file_snapshot() -> dict[str, tuple[int, int, str]]:
        return {
            str(path.relative_to(bundle_directory)): (
                path.stat().st_mtime_ns,
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in bundle_directory.rglob("*")
            if path.is_file()
        }

    before = file_snapshot()
    exit_code = main(["verify-bundle", str(result_directory), "--json"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == expected_exit
    assert output["status"] == expected_status
    assert (output["reason"] is not None) is tamper
    assert file_snapshot() == before


def test_support_bundle_excludes_full_paths_and_protected_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "aia.diagnostics.CodexAdapter.discover",
        lambda _adapter: (_ for _ in ()).throw(FileNotFoundError("no codex")),
    )
    bundle = build_support_bundle(
        control_root=tmp_path / "private-control",
        hook_path=tmp_path / "private-hooks.json",
    )

    encoded = json.dumps(bundle, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert bundle["privacy"]["raw_evidence_included"] is False
    assert bundle["privacy"]["tool_input_included"] is False
    assert bundle["codex"]["available"] is False
    assert len(bundle["hook"]["path_sha256"]) == 64


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


def test_protected_run_summary_reports_all_action_and_recovery_axes(capsys) -> None:
    _print_protected_run_summary(
        "session-3",
        {
            "session": {"status": "COMPLETED"},
            "protection": {"state": "COMPLETED_VERIFIED", "hook_events": 2},
        },
        {
            "bundle_status": "VALID",
            "recovery_status": "RESTORED",
            "integrity_status": "VERIFIED",
            "action_outcomes": [
                {
                    "policy_decision": "VIOLATION",
                    "enforcement_decision": "CONTAIN",
                    "enforcement_action": "BLOCKED",
                    "execution_result": "SUCCEEDED",
                },
                {
                    "policy_decision": "COMPLIANT",
                    "enforcement_decision": "CONTINUE",
                    "enforcement_action": "NONE",
                    "execution_result": "SUCCEEDED",
                },
            ],
        },
    )

    output = capsys.readouterr().out
    assert "Actions: 2 total / 1 compliant / 0 audit / 1 violation / 0 indeterminate" in output
    assert "Enforcement: 1 contain / 1 blocked / 0 terminated" in output
    assert "Execution: 2 succeeded / 0 failed / 0 not attempted" in output
    assert "Recovery: RESTORED" in output
    assert "Integrity: VERIFIED" in output
    assert "검증된 복구 성공" in output


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
    assert payload["ready"] is False
    assert payload["readiness_code"] == "CODEX_HOOK_TRUST_REQUIRED"
    assert "/hooks" in payload["next_steps"][0]


def test_setup_reports_trusted_codex_pretool_status_without_manual_review_flag(
    tmp_path, monkeypatch, capsys
) -> None:
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
                        {"event": "preToolUse", "trust_status": "TRUSTED"},
                    ],
                }
            },
        )(),
    )

    exit_code = main(["setup", "--json", "--path", str(hook_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["trust_status"] == "TRUSTED"
    assert payload["ready"] is False
    assert payload["readiness_code"] == "HOOK_VERIFICATION_REQUIRED"
    assert "신뢰된 상태" in payload["next_steps"][0]


def test_setup_reports_ready_only_after_current_live_hook_verification(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    control_root = tmp_path / "control"
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
                    "hooks": [{"event": "preToolUse", "trust_status": "TRUSTED"}],
                }
            },
        )(),
    )
    monkeypatch.setenv("AIA_CONTROL_ROOT", str(control_root))
    monkeypatch.setattr(
        "aia.cli.HookVerificationStore.is_current",
        lambda _store, _installer, _executable: True,
    )

    exit_code = main(["setup", "--json", "--path", str(hook_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["readiness_code"] == "READY"
    assert payload["hook_verification_current"] is True
    assert payload["control_root_writable"] is True


@pytest.mark.parametrize("trust_status", ["TRUSTED", "MANAGED"])
def test_hook_status_reports_actual_trusted_codex_status(
    tmp_path, monkeypatch, capsys, trust_status
) -> None:
    hook_path = tmp_path / "hooks.json"
    control_root = tmp_path / "control"
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
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": trust_status},
                    ],
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
            str(control_root),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["trust_status"] == trust_status
    assert payload["ready"] is False


def test_hook_status_requires_manual_review_when_codex_hook_is_untrusted(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    control_root = tmp_path / "control"
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
                    "reason": None,
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                    ],
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
            str(control_root),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["trust_status"] == "MANUAL_REVIEW_REQUIRED"


def test_console_parser_supports_explicit_bind_values() -> None:
    args = _parser().parse_args(
        ["console", "--host", "127.0.0.1", "--port", "8799", "--open"]
    )

    assert args.command == "console"
    assert args.host == "127.0.0.1"
    assert args.port == 8799
    assert args.open is True


def test_hook_runtime_subcommand_forwards_stdin_to_hook_runtime(monkeypatch) -> None:
    called = []

    monkeypatch.setattr(
        "aia.codex_hook_runtime.main",
        lambda: called.append(True) or 7,
    )

    assert main(["hook", "runtime"]) == 7
    assert called == [True]


def test_frozen_hook_verification_reenters_packaged_cli_without_module_flag(
    monkeypatch,
) -> None:
    monkeypatch.setattr("aia.cli.sys.frozen", True, raising=False)
    monkeypatch.setattr("aia.cli.sys.executable", r"C:\AIA\aia-cli.exe")

    assert _self_cli_command("protect", "workspace") == [
        r"C:\AIA\aia-cli.exe",
        "protect",
        "workspace",
    ]


def test_console_parser_supports_explicit_control_root(tmp_path) -> None:
    args = _parser().parse_args(
        ["console", "--control-root", str(tmp_path / "control")]
    )

    assert args.control_root == tmp_path / "control"
    assert args.open_path == "/"


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


def test_hook_explain_parser_supports_json_and_paths(tmp_path) -> None:
    args = _parser().parse_args(
        [
            "hook",
            "explain",
            "--json",
            "--path",
            str(tmp_path / "hooks.json"),
            "--control-root",
            str(tmp_path / "control"),
        ]
    )

    assert args.command == "hook"
    assert args.hook_command == "explain"
    assert args.json is True
    assert args.path == tmp_path / "hooks.json"
    assert args.control_root == tmp_path / "control"


def test_hook_explain_is_read_only_and_describes_manual_review(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(hook_path)
    installer.install()
    before = hook_path.read_bytes()
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
                    "hooks": [
                        {"event": "preToolUse", "trust_status": "MODIFIED"},
                        {"event": "postToolUse", "trust_status": "UNTRUSTED"},
                    ],
                }
            },
        )(),
    )

    assert (
        main(
            [
                "hook",
                "explain",
                "--path",
                str(hook_path),
                "--control-root",
                str(tmp_path / "control"),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "/hooks" in output
    assert "matcher: *" in output
    assert "preToolUse=MODIFIED" in output
    assert "hook verify" in output
    assert hook_path.read_bytes() == before


def test_hook_explain_json_contains_contract_without_raw_hook_payload(
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
                    "hooks": [{"event": "preToolUse", "trust_status": "TRUSTED"}],
                }
            },
        )(),
    )

    assert (
        main(
            [
                "hook",
                "explain",
                "--json",
                "--path",
                str(hook_path),
                "--control-root",
                str(tmp_path / "control"),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "aia-hook-explain-v1"
    assert payload["installed"]["pretool_use"] is True
    assert payload["review_target"]["matcher"] == "*"
    assert "Bash" in payload["review_target"]["semantic_tools"]
    assert payload["codex"]["trust"]["preToolUse"] == "TRUSTED"
    assert payload["verification"]["current"] is False
    assert "hooks" not in payload


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
    assert "hook verify" in output


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


def test_hook_verify_explains_stale_aia_command_before_probe(tmp_path, monkeypatch, capsys) -> None:
    hook_path = tmp_path / "hooks.json"
    old = CodexHookInstaller(hook_path, python_executable=tmp_path / "old-python.exe")
    old.install()

    monkeypatch.setattr(
        "aia.cli.CodexHookInstaller",
        lambda _path=None: CodexHookInstaller(
            hook_path, python_executable=tmp_path / "new-python.exe"
        ),
    )

    exit_code = main(
        [
            "hook",
            "verify",
            "--json",
            "--path",
            str(hook_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["reason"] == "PRETOOL_HOOK_COMMAND_MISMATCH"
    assert payload["aia_runtime_detected"] is True


def test_hook_verify_human_failure_shows_hook_path_and_expected_command(
    tmp_path, monkeypatch, capsys
) -> None:
    hook_path = tmp_path / "hooks.json"
    monkeypatch.setattr(
        "aia.cli.CodexHookInstaller",
        lambda _path=None: CodexHookInstaller(
            hook_path, python_executable=tmp_path / "new-python.exe"
        ),
    )

    exit_code = main(
        [
            "hook",
            "verify",
            "--path",
            str(hook_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert f"[확인] 읽은 Hook 설정: {hook_path}" in output
    assert "[예상] 현재 AIA Hook 명령:" in output
    assert "-m aia.codex_hook_runtime" in output


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
    assert f"{_cli_prefix(CodexHookInstaller(hook_path))} hook verify" in payload["next_step"]


def test_doctor_marks_stale_aia_hook_for_refresh(tmp_path, monkeypatch, capsys) -> None:
    hook_path = tmp_path / "hooks.json"
    hook_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python -m aia.codex_hook_runtime",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: executable)

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
    hook_check = next(item for item in payload["checks"] if item["name"] == "codex_hook")
    assert exit_code == 1
    assert hook_check["ok"] is False
    assert hook_check["stale"] is True
    assert "기존 AIA Hook 경로" in hook_check["detail"]
    assert "갱신" in payload["next_step"]


def test_protected_run_preflight_requires_the_aia_hook(monkeypatch) -> None:
    monkeypatch.setattr("aia.cli.CodexAdapter.discover", lambda _adapter: "codex.exe")
    monkeypatch.setattr("aia.cli.CodexHookInstaller.is_installed", lambda _installer: False)

    ready, failures = _protected_run_preflight()

    assert ready is False
    assert any("PreToolUse Hook" in item for item in failures)


def test_hook_verification_probe_flag_requires_internal_authorization_token(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("AIA_HOOK_VERIFICATION_PROBE_TOKEN", raising=False)

    exit_code = main(
        [
            "protect",
            str(tmp_path),
            "--task",
            "do nothing",
            "--_hook-verification-probe",
        ]
    )

    assert exit_code == 2
    assert "probe authorization is missing" in capsys.readouterr().out


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
        hook_verification_probe=True,
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


def test_reconcile_parser_keeps_session_id_and_control_root() -> None:
    args = _parser().parse_args(["reconcile", "session-1", "--json"])

    assert args.command == "reconcile"
    assert args.session_id == "session-1"
    assert args.json is True
