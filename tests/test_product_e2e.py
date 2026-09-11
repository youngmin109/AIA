from __future__ import annotations

import json
from pathlib import Path

from aia.product_e2e import (
    _block_confirmation,
    _copy_current_hook_verification,
    _output_metadata,
    _proof_passed,
    _safe_hook_verification,
    _write_report,
)
from aia import BundleVerificationStatus, CodexHookInstaller
from aia.hook_verification import HookVerificationStore


def _common_kwargs() -> dict[str, object]:
    return {
        "cli_exit_code": 0,
        "session_status": "COMPLETED",
        "bundle_status": BundleVerificationStatus.VALID.value,
        "hook_event_count": 1,
        "workspace_unchanged": True,
    }


def test_block_proof_requires_confirmed_codex_block() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=0,
    ) is False


def test_block_proof_passes_only_with_gate_and_execution_confirmation() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
    ) is True


def test_block_proof_fails_when_canary_side_effect_is_present() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=True,
        gate_block_count=1,
        confirmed_block_count=1,
    ) is False


def test_normal_proof_does_not_require_a_block_confirmation() -> None:
    assert _proof_passed(
        scenario="normal",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=0,
        confirmed_block_count=0,
    ) is True


def test_env_block_proof_requires_secret_marker_to_remain_unseen() -> None:
    common = _common_kwargs()
    assert _proof_passed(
        scenario="block-env",
        **common,
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
        secret_leaked=False,
    ) is True
    assert _proof_passed(
        scenario="block-env",
        **common,
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
        secret_leaked=True,
    ) is False


def test_env_block_confirmation_names_secret_non_disclosure() -> None:
    assert _block_confirmation(
        scenario="block-env",
        canary_executed=False,
        secret_leaked=False,
        gate_block_count=1,
        confirmed_block_count=1,
    ) == "SECRET_NOT_LEAKED"
    assert _block_confirmation(
        scenario="block-env",
        canary_executed=False,
        secret_leaked=True,
        gate_block_count=1,
        confirmed_block_count=1,
    ) == "SECRET_LEAKED"


def test_windows_delete_block_uses_the_same_no_side_effect_confirmation() -> None:
    assert _block_confirmation(
        scenario="block-windows-delete",
        canary_executed=False,
        secret_leaked=False,
        gate_block_count=1,
        confirmed_block_count=1,
    ) == "CANARY_NO_SIDE_EFFECT"


def test_human_proof_summary_does_not_print_captured_codex_output(tmp_path, capsys) -> None:
    report = {
        "scenario": "block-env",
        "proof_passed": True,
        "session_id": "session-1",
        "hook_event_count": 1,
        "gate_block_count": 1,
        "confirmed_block_count": 1,
        "secret_leaked": False,
        "block_confirmation": "SECRET_NOT_LEAKED",
        "bundle_status": "VALID",
        "cli_stdout": "AIA_SECRET_CANARY=do-not-leak",
        "report_path": None,
    }

    assert _write_report(tmp_path, report, 0) == 0
    output = capsys.readouterr().out

    assert "PASS" in output
    assert "SECRET_NOT_LEAKED" in output
    assert "AIA_SECRET_CANARY=do-not-leak" not in output


def test_output_metadata_keeps_only_size_and_digest() -> None:
    metadata = _output_metadata("AIA_SECRET_CANARY=do-not-leak")

    assert set(metadata) == {"bytes", "sha256"}
    assert metadata["bytes"] > 0
    assert "AIA_SECRET_CANARY" not in str(metadata)


def test_hook_verification_keeps_actionable_status_without_raw_output() -> None:
    result = _safe_hook_verification(
        stdout=json.dumps(
            {
                "verified": False,
                "protection_claim": "PROTECTION_NOT_PROVEN",
                "reason": "CODEX_HOOK_TRUST_REQUIRED",
                "trust_status": "MODIFIED",
                "next_step": "Codex /hooks에서 AIA Hook을 검토·신뢰하세요.",
                "codex_executable": "C:/secret/codex.exe",
                "raw_output": "AIA_SECRET_CANARY=do-not-leak",
            }
        ),
        stderr="diagnostic secret AIA_SECRET_CANARY=do-not-leak",
        exit_code=2,
    )

    assert result["verified"] is False
    assert result["reason"] == "CODEX_HOOK_TRUST_REQUIRED"
    assert result["trust_status"] == "MODIFIED"
    assert "next_step" in result
    assert "codex_executable" not in result
    assert "raw_output" not in result
    assert "AIA_SECRET_CANARY" not in str(result)
    assert result["stdout"]["bytes"] > 0
    assert result["stderr"]["bytes"] > 0


def test_hook_verification_reports_invalid_json_without_retaining_output() -> None:
    result = _safe_hook_verification(
        stdout="not json AIA_SECRET_CANARY=do-not-leak",
        stderr="error AIA_SECRET_CANARY=do-not-leak",
        exit_code=1,
    )

    assert result["parse_error"] == "INVALID_JSON"
    assert "AIA_SECRET_CANARY" not in str(result)


def test_current_hook_verification_can_be_reused_for_isolated_proof_root(tmp_path: Path) -> None:
    hook_path = tmp_path / "hooks.json"
    installer = CodexHookInstaller(hook_path)
    installer.install()
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex-test")
    source_root = tmp_path / "source-control"
    target_root = tmp_path / "target-control"
    HookVerificationStore(source_root).write_verified(
        installer=installer,
        executable=executable,
        session_id="verified-session",
        hook_event_count=1,
    )

    assert _copy_current_hook_verification(
        source_control_root=source_root,
        target_control_root=target_root,
        installer=installer,
        executable=executable,
    ) is True
    assert HookVerificationStore(target_root).is_current(installer, executable) is True
